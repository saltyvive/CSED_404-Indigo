#!/usr/bin/env python3
"""Pool explicit 9x9 training batches, keeping each placement/pass independent.

All three passes train the final map. Leave-one-pass-out is an internal
diagnostic at known marked positions, not the subsequent independent test.
No old 5x5 sessions, moving guides, or validation sessions are accepted.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import statistics as st
from pathlib import Path

import analyze_session as a
from build_edge_model import summarize_trial
from build_grid_model import Projector


def batch_spec(scenario):
    match = re.fullmatch(r'grid9Train([123])([ABC])', scenario or '')
    if not match:
        raise ValueError('Only explicit grid9Train1A...grid9Train3C training batches are accepted')
    repetition, batch = int(match[1]), ord(match[2])-ord('A')
    order = list(range(1, 10)) if repetition == 1 else (
        list(range(9, 0, -1)) if repetition == 2 else [5, 1, 9, 3, 7, 2, 8, 4, 6])
    return repetition, order[batch*3:batch*3+3]


def extract(path):
    manifest, samples = a.read_session(path)
    if manifest['status'] != 'completed':
        raise ValueError(f"Incomplete batch: {manifest['id']}")
    trials = [t for t in manifest['trials'] if t['status'] == 'completed']
    scenarios = {t['spec'].get('scenarioID') for t in trials}
    if len(scenarios) != 1 or len(trials) != 33:
        raise ValueError('A complete batch must have 27 holds and six backgrounds')
    scenario = scenarios.pop()
    repetition, expected_rows = batch_spec(scenario)
    if len({t['spec']['id'] for t in trials}) != len(trials):
        raise ValueError('Duplicate trial IDs')
    if {t['spec'].get('gridRow') for t in trials} != set(expected_rows):
        raise ValueError('Unexpected rows for this batch')
    movement = [float(m[1]) for w in manifest.get('warnings', [])
                if (m := re.search(r'iPad movement at uptime ([0-9.]+)', w))]
    groups, points = [], []
    for row in expected_rows:
        group_id = f'pass{repetition}-row{row}'
        group = [t for t in trials if t['spec'].get('gridRow') == row]
        for trial in group:
            spec = trial['spec']
            if (spec.get('gridSize') != 9 or spec.get('repetition') != repetition or
                    spec.get('calibrationGroup') != group_id):
                raise ValueError('Incorrect grid size, pass, or background group')
        holds = [t for t in group if t['spec']['kind'] == 'mapHold']
        baselines = [t for t in group if t['spec']['kind'] == 'mapBaseline']
        if len(group) != 11 or len(holds) != 9 or len(baselines) != 2:
            raise ValueError('Each row needs nine holds and two backgrounds')
        if {t['spec'].get('gridColumn') for t in holds} != set(range(1, 10)):
            raise ValueError('Missing or duplicate grid column')
        if {t['spec'].get('edgeAction') for t in baselines} != {'before', 'after'}:
            raise ValueError('Missing before/after background')
        for t in baselines:
            if t['spec'].get('purpose') != 'grid9_baseline' or t['spec'].get('point') is not None:
                raise ValueError('Invalid background labels')
        base = {t['spec']['edgeAction']: summarize_trial(t, samples, 'baseline') for t in baselines}
        before, after = base['before'], base['after']
        if before['endTime'] >= after['startTime']:
            raise ValueError('Invalid background chronology')
        warnings = []
        if max(before['noiseUT'], after['noiseUT']) >= 3:
            warnings.append('unstable_baseline')
        if any(before['startTime'] <= t <= after['endTime'] for t in movement):
            warnings.append('ipad_movement_after_baseline')
        for trial in holds:
            spec = trial['spec']; col = spec['gridColumn']
            xy = [(col-1)/8, (row-1)/8]
            if (spec.get('purpose') != 'grid9_train' or spec.get('edgeAction') != 'hold' or
                    spec.get('point') != dict(zip(('x', 'y'), xy))):
                raise ValueError('Incorrect training role or 9x9 coordinates')
            rows = [r for r in samples if r['trial_id'] == spec['id'] and r['phase'] == 'hold']
            coordinates = [(float(r['target_x']), float(r['target_y'])) for r in rows]
            if (any(r['label_source'] != 'manual_static_target' for r in rows) or
                any(not all(map(math.isfinite, q)) or math.dist(q, xy) > 1e-8 for q in coordinates)):
                raise ValueError('CSV target labels must match the manually marked position')
            obs = summarize_trial(trial, samples, 'hold')
            if not before['endTime'] < obs['startTime'] < obs['endTime'] < after['startTime']:
                raise ValueError('Hold lies outside its background pair')
            fraction = (obs['time']-before['time'])/(after['time']-before['time'])
            bg = [b+fraction*(e-b) for b, e in zip(before['raw'], after['raw'])]
            reasons = warnings + (['unstable_hold'] if obs['noiseUT'] >= 3 else [])
            points.append(dict(session=manifest['id'], trial=spec['id'], repetition=repetition,
                               row=row, column=col, xy=xy, **obs,
                               deltaUT=[v-b for v, b in zip(obs['raw'], bg)],
                               deltaUsingRowStartUT=[v-b for v, b in zip(obs['raw'], before['raw'])],
                               eligible=not reasons, warnings=reasons))
        groups.append(dict(row=row, repetition=repetition, before=before, after=after,
                           driftUT=math.dist(before['raw'], after['raw']), warnings=warnings))
    return dict(session=manifest['id'], scenario=scenario, device=manifest['device'], setup=manifest['setup'],
                sourceWarnings=manifest.get('warnings', []), calibrationGroups=groups, points=points)


def combine(batches):
    expected = {f'grid9Train{p}{b}' for p in range(1, 4) for b in 'ABC'}
    if len(batches) != 9 or {b['scenario'] for b in batches} != expected:
        raise ValueError('Supply exactly one completed session for each of the nine training batches')
    if len({b['session'] for b in batches}) != 9:
        raise ValueError('Duplicate session input')
    keys = ('pencil', 'plane', 'aspect', 'widthMM', 'heightMM', 'heightNote', 'standAngle', 'environment')
    reference = batches[0]
    for batch in batches:
        if batch['device'] != reference['device'] or any(batch['setup'].get(k) != reference['setup'].get(k) for k in keys):
            raise ValueError('Setup metadata differs; review geometry before pooling')
    aspect = reference['setup']['aspect']
    if not math.isfinite(aspect) or aspect <= 0:
        raise ValueError('Invalid aspect ratio')
    points = [p for b in batches for p in b['points']]
    counts = {}
    for p in points:
        counts.setdefault(tuple(p['xy']), []).append(p['repetition'])
    if len(counts) != 81 or any(sorted(passes) != [1, 2, 3] for passes in counts.values()):
        raise ValueError('Every position must have exactly three distinct placements/passes')
    return points, aspect


def build(points, aspect, *, minimum_repeats=2):
    eligible = [p for p in points if p['eligible']]
    knots = [i/8 for i in range(9)]
    lookup, variability = {}, []
    for row, y in enumerate(knots, 1):
        for col, x in enumerate(knots, 1):
            group = [p for p in eligible if p['xy'] == [x, y]]
            if len({p['repetition'] for p in group}) < minimum_repeats:
                raise ValueError(f'{row}행 {col}열: usable independent repeats below {minimum_repeats}; inspect exclusions and recollect')
            values = [p['deltaUT'] for p in group]
            center = a.median_vector(values)
            lookup[x, y] = center
            variability.append(dict(row=row, column=col, xy=[x, y], repeats=len(group),
                                    passes=[p['repetition'] for p in group], medianUT=center,
                                    maxPairwiseDistanceUT=max((math.dist(u, v) for u in values for v in values), default=0),
                                    rmsAroundMedianUT=math.sqrt(st.mean(math.dist(v, center)**2 for v in values))))
    sessions = sorted({p['session'] for p in eligible})
    model = dict(version=1, method='bilinear_forward_surface_grid_inverse', aspect=aspect,
                 xKnots=knots, yKnots=knots, fieldsUT=[[lookup[x, y] for x in knots] for y in knots],
                 searchSteps=160, residualLimitUT=max(3, 5*max(p['noiseUT'] for p in eligible)),
                 ambiguityDistance=0.2, ambiguityMarginUT=0.75,
                 sourceSession='grid9-pooled-'+hashlib.sha256('|'.join(sessions).encode()).hexdigest()[:12],
                 sourceSessions=sessions, trainingTrialIDs=[p['session']+'/'+p['trial'] for p in eligible],
                 excludedRows=[], movementIncludedRows=[], inclusionNote=None,
                 trainingGridSize=9, aggregation='Equal weight per independent placement; componentwise median after per-row background correction',
                 minimumRepeats=minimum_repeats, pointRepeatCounts=[[v['repeats'] for v in variability[i:i+9]] for i in range(0, 81, 9)],
                 scope='All supplied eligible training passes pooled. Fixed pose desk contact. '
                       'Intermediate positions remain bilinearly interpolated. No independent validation of this model yet.')
    return model, variability


def internal_diagnostics(points, aspect):
    """Whole-pass exclusion; the final model subsequently uses all three passes."""
    result = []
    for repetition in (1, 2, 3):
        train = [p for p in points if p['repetition'] != repetition]
        try:
            model, _ = build(train, aspect, minimum_repeats=1)
        except ValueError as error:
            result.append(dict(heldOutPass=repetition, skipped=str(error)))
            continue
        projector = Projector(model)
        frames = []
        for p in points:
            if p['repetition'] != repetition or not p['eligible']:
                continue
            pred = projector.project(p['deltaUsingRowStartUT'])
            error = math.hypot(aspect*(p['xy'][0]-pred['xy'][0]), p['xy'][1]-pred['xy'][1])
            frames.append(dict(trial=p['session']+'/'+p['trial'], targetXY=p['xy'], errorFractionOfHeight=error, **pred))
        result.append(dict(heldOutPass=repetition, trainingObservations=len(model['trainingTrialIDs']),
                           count=len(frames), accepted=sum(f['accepted'] for f in frames),
                           medianErrorFractionOfHeight=st.median(f['errorFractionOfHeight'] for f in frames) if frames else None,
                           frames=frames))
    return result


def run(paths, out):
    # A failed rerun must not leave a stale model looking like a successful result.
    if (out/'grid_model.json').exists():
        raise ValueError('Choose a fresh output directory; an existing model is never silently replaced')
    batches = [extract(path) for path in paths]
    points, aspect = combine(batches)
    out.mkdir(parents=True, exist_ok=True)
    def save(name, obj):
        (out/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False))
    inventory = []
    for path in paths:
        manifest = json.loads((path/'manifest.json').read_text())
        for file in sorted(path.iterdir()):
            if not file.is_file():
                continue
            item = dict(session=manifest['id'], file=file.name, bytes=file.stat().st_size,
                        sha256=hashlib.sha256(file.read_bytes()).hexdigest())
            if file.suffix == '.csv':
                with file.open() as stream:
                    item['rows'] = sum(1 for _ in csv.DictReader(stream))
                if item['rows'] != manifest['sensorCounts'].get(file.stem, 0):
                    raise ValueError(f'Sensor row count mismatch: {file}')
            inventory.append(item)
    save('source_inventory.json', inventory)
    save('observations.json', batches)
    report = dict(status='pending', observations=len(points), uniquePositions=81,
                  excluded=[p for p in points if not p['eligible']],
                  limits=['All three passes train the final model; internal pass exclusion is not a final independent test.',
                          'New physical placement/session, not adjacent sensor frames, defines a repeat.',
                          'Metadata equality does not establish unchanged physical geometry; review raw motion warnings.',
                          'Row background interpolation is offline; held-out diagnostic inputs use starting backgrounds only.',
                          'No moving path or Pencil IMU is used; no millimeter or handwriting accuracy is established.'])
    try:
        model, variability = build(points, aspect)
    except ValueError as error:
        report.update(status='needs_review_or_recollection', reason=str(error))
        save('analysis.json', report)
        raise
    diagnostics = internal_diagnostics(points, aspect)
    report.update(status='model_ready_for_personal_test', trainingObservations=len(model['trainingTrialIDs']),
                  pointVariability=variability, internalLeaveOnePassOut=diagnostics)
    save('analysis.json', report)
    save('grid_model.json', model)
    print(f"81 positions, {len(model['trainingTrialIDs'])} retained training placements; independent validation still pending")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions', type=Path, nargs='+')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.sessions, args.out)
