#!/usr/bin/env python3
"""Build a fixed-condition 21x13 map from explicitly selected complete passes.

One pass is an explicitly provisional personal-test model, not validation.
No historical, other-campaign, other-pose, or incomplete rows are pooled.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics as st

import analyze_session as a
from build_edge_model import summarize_trial
from build_grid_model import Projector
from fixture_pose import resolve_pose

PROTOCOL = 'sweetspot_21x13_v1'
GEOMETRY = dict(columns=21, rows=13, widthMM=50, heightMM=30, pitchMM=2.5,
                paperWidthMM=297, paperHeightMM=210, paperLowerLeftOffsetMM=dict(x=115, y=55))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def vector(row, keys):
    values = [float(row[k]) for k in keys]
    require(all(map(math.isfinite, values)), 'Non-finite sensor data')
    return values


def extract(path, *, allow_transient_motion=False, review_note=None):
    m, samples = a.read_session(path)
    meta = m.get('printedGrid', {})
    require(m['status'] == 'completed' and meta.get('protocolID') == PROTOCOL, 'Complete printed-grid session required')
    require(all(meta.get(k) == v for k, v in GEOMETRY.items()), 'Printed geometry mismatch')
    require(m['setup']['widthMM'] == '50' and m['setup']['heightMM'] == '30' and
            abs(m['setup']['aspect']-5/3) < 1e-9, 'Setup geometry mismatch')
    row, repetition = meta['batch']['row'], meta['batch']['pass']
    require(row in range(1, 14) and repetition in (1, 2, 3) and meta.get('campaignID'), 'Invalid batch/campaign')
    raw_pose = meta['pose']
    pose, pose_annotation = resolve_pose(m, (path/'manifest.json').read_bytes())
    require(0 <= pose['phiDegrees'] < 360 and 0 <= pose['thetaDegrees'] <= 90 and
            math.isfinite(pose['tipHeightMM']) and (pose['tipHeightMM'] == 0 if pose['tipContact'] else pose['tipHeightMM'] > 0)
            and pose['source'] == 'operator_set_fixture_unmeasured', 'Invalid fixture labels')
    require(pose['thetaDegrees'] == 90 or pose.get('tiltDirectionAtPhiZero'), 'Tilt reference missing')
    trials = [t for t in m['trials'] if t['status'] == 'completed']
    require(len(trials) == 23 and len({t['spec']['id'] for t in trials}) == 23, 'Expected 21 unique holds + two backgrounds')
    columns = list(range(1, 22)) if (row+repetition) % 2 == 0 else list(range(21, 0, -1))
    order = [('before', None)] + [('hold', c) for c in columns] + [('after', None)]
    for trial, (action, col) in zip(trials, order):
        spec = trial['spec']; is_hold = col is not None
        xy = dict(x=(col-1)/20, y=(row-1)/12) if is_hold else None
        require(spec.get('scenarioID') == f'{PROTOCOL}_p{repetition}_r{row}' and
                spec.get('gridColumns') == 21 and spec.get('gridRows') == 13 and spec.get('gridSize') is None and
                spec.get('gridRow') == row and spec.get('gridColumn') == col and spec.get('repetition') == repetition and
                spec.get('calibrationGroup') == f'pass{repetition}-row{row}' and spec.get('edgeAction') == action and
                spec['kind'] == ('mapHold' if is_hold else 'mapBaseline') and
                spec.get('purpose') == ('printed_grid_train' if is_hold else 'printed_grid_baseline') and
                spec.get('pointID') == (f'r{row}c{col}' if is_hold else f'pass{repetition}-row{row}-{action}') and
                spec.get('point') == xy and spec.get('nominalPointMM') == (dict(x=(col-1)*2.5, y=(row-1)*2.5) if is_hold else None) and
                spec.get('fixturePose') == (raw_pose if is_hold else None), 'Trial target/pose/order mismatch')
        expected_end = trial['startUptime']+3+(3 if is_hold else 10)
        require(trial.get('settleSeconds') == 3 and math.isfinite(expected_end) and
                abs(trial.get('endUptime', 0)-expected_end) < 1e-3, 'Incomplete timing')
    require(all(t['endUptime'] <= u['startUptime'] for t, u in zip(trials, trials[1:])), 'Overlapping trials')
    ids = {t['spec']['id'] for t in trials}
    for sample in samples:
        if sample['trial_id'] not in ids or sample['phase'] != 'hold':
            continue
        spec = next(t['spec'] for t in trials if t['spec']['id'] == sample['trial_id'])
        require(sample['label_source'] == 'manual_static_target' and sample['dataset'] == 'printed_grid_train' and
                abs(float(sample['target_x'])-spec['point']['x']) < 1e-8 and
                abs(float(sample['target_y'])-spec['point']['y']) < 1e-8 and
                float(sample['fixture_phi_deg']) == pose['phiDegrees'] and
                float(sample['fixture_theta_deg']) == pose['thetaDegrees'] and
                float(sample['instructed_tip_height_mm']) == pose['tipHeightMM'] and
                sample['fixture_tip_state'] == ('contact' if pose['tipContact'] else 'air') and
                sample['fixture_pose_source'] == pose['source'], 'CSV target/pose labels mismatch')
        if pose_annotation:
            require(sample.get('fixture_alpha_deg', '') == '' and sample.get('fixture_alpha_source', '') == '',
                    'Legacy alpha annotation conflicts with CSV labels')
        else:
            require(sample.get('fixture_alpha_deg', '') != '' and
                    float(sample['fixture_alpha_deg']) == pose['alphaDegrees'] and
                    sample.get('fixture_alpha_source') == pose['alphaLabelSource'], 'CSV alpha labels mismatch')
    before = summarize_trial(trials[0], samples, 'baseline')
    after = summarize_trial(trials[-1], samples, 'baseline')
    require(max(before['noiseUT'], after['noiseUT']) < 3, 'Unstable background; recollect row')

    # Inspect continuous IMU as well as warnings: the app only warns while a trial is active.
    with (path/'device_motion.csv').open() as stream:
        motion = list(csv.DictReader(stream))
    kept = [r for r in motion if before['startTime'] <= float(r['timestamp_s']) <= after['endTime']]
    require(kept, 'Missing iPad motion data')
    events, inclinations = [], []
    for sample in kept:
        timestamp = float(sample['timestamp_s'])
        acceleration = math.hypot(*vector(sample, ('user_ax_g', 'user_ay_g', 'user_az_g')))
        rotation = math.hypot(*vector(sample, ('rx_rad_s', 'ry_rad_s', 'rz_rad_s')))
        g = vector(sample, ('gravity_x_g', 'gravity_y_g', 'gravity_z_g'))
        require(math.hypot(*g) > .1, 'Invalid gravity vector')
        inclinations.append(math.degrees(math.acos(min(1, abs(g[2])/math.hypot(*g)))))
        if acceleration > .03 or rotation > .05:
            steady = any(t['startUptime']+3 <= timestamp < t['endUptime'] for t in trials)
            events.append(dict(timestamp=timestamp, phase=sample['phase'], trial=sample['trial_id'],
                               accelerationG=acceleration, rotationRadS=rotation, overlapsCompletedSteadyInterval=steady))
    require(not any(e['overlapsCompletedSteadyInterval'] for e in events), 'iPad motion during completed measurement; recollect row')
    if events:
        require(allow_transient_motion and review_note and review_note.strip(), 'Review non-measurement iPad motion explicitly')
    points = []
    for trial in trials[1:-1]:
        spec = trial['spec']; obs = summarize_trial(trial, samples, 'hold')
        require(obs['noiseUT'] < 3, 'Unstable hold; recollect point/row')
        require(before['endTime'] < obs['startTime'] < obs['endTime'] < after['startTime'], 'Unbracketed point')
        fraction = (obs['time']-before['time'])/(after['time']-before['time'])
        background = [b+fraction*(e-b) for b, e in zip(before['raw'], after['raw'])]
        # Three causal filtered observations per hold for same-data replay diagnostics only.
        frames = []
        for target_time in [obs['startTime']+.2, obs['time'], obs['endTime']-.1]:
            window = [r for r in samples if r['trial_id'] == spec['id'] and r['phase'] == 'hold' and
                      target_time-.12 <= float(r['timestamp_s']) <= target_time]
            require(len(window) >= 3, 'Sparse causal replay window')
            filtered = a.median_vector([a.vector(r) for r in window])
            frames.append(dict(time=target_time, filteredDeltaUT=[v-b for v, b in zip(filtered, before['raw'])]))
        points.append(dict(session=m['id'], trial=spec['id'], row=row, column=spec['gridColumn'], repetition=repetition,
                           xy=[spec['point']['x'], spec['point']['y']], **obs,
                           deltaUT=[v-b for v, b in zip(obs['raw'], background)], causalFrames=frames))
    return dict(session=m['id'], campaignID=meta['campaignID'], row=row, repetition=repetition, device=m['device'],
                setup=m['setup'], pose=pose, poseAnnotation=pose_annotation, points=points, before=before, after=after,
                driftUT=math.dist(before['raw'], after['raw']), motionEvents=events,
                motionReviewNote=review_note if events else None, sourceWarnings=m.get('warnings', []),
                inclinationRange=[min(inclinations), max(inclinations)],
                excludedAttempts=[dict(trial=t['spec']['id'], status=t['status'], reason=t.get('reason'))
                                  for t in m['trials'] if t['status'] != 'completed'])


def build(batches, passes):
    require(passes and len(set(passes)) == len(passes) and all(p in (1, 2, 3) for p in passes), 'Select distinct passes 1..3')
    require(len(batches) == 13*len(passes) and {(b['repetition'], b['row']) for b in batches} ==
            {(p, r) for p in passes for r in range(1, 14)}, 'Exactly one complete session per selected pass/row required')
    require(len({b['session'] for b in batches}) == len(batches), 'Duplicate sessions')
    reference = batches[0]
    for b in batches:
        require(all(b[k] == reference[k] for k in ('campaignID', 'device', 'setup', 'pose')), 'Campaign/setup/fixture pose mismatch')
    xs, ys = [i/20 for i in range(21)], [j/12 for j in range(13)]
    points = [p for b in batches for p in b['points']]
    lookup = {}
    for y in ys:
        for x in xs:
            group = [p for p in points if p['xy'] == [x, y]]
            require(sorted(p['repetition'] for p in group) == sorted(passes), 'Missing/duplicate independent placement')
            lookup[x, y] = a.median_vector([p['deltaUT'] for p in group])
    sessions = sorted(b['session'] for b in batches)
    return dict(version=1, method='bilinear_forward_surface_grid_inverse', aspect=5/3,
                xKnots=xs, yKnots=ys, fieldsUT=[[lookup[x,y] for x in xs] for y in ys],
                searchSteps=180, residualLimitUT=max(3, 5*max(p['noiseUT'] for p in points)),
                ambiguityDistance=.2, ambiguityMarginUT=.75,
                sourceSession='printed-grid-'+hashlib.sha256('|'.join(sessions).encode()).hexdigest()[:12],
                sourceSessions=sessions, trainingTrialIDs=[p['session']+'/'+p['trial'] for p in points], excludedRows=[],
                movementIncludedRows=sorted({b['row'] for b in batches if b['motionEvents']}),
                inclusionNote='Reviewed transient motion outside completed steady measurements; physical translation/yaw cannot be ruled out. Provisional test only.' if any(b['motionEvents'] for b in batches) else None,
                printedGridContext=dict(campaignID=reference['campaignID'], passes=sorted(passes), widthMM=50, heightMM=30,
                                        pose=reference['pose'], poseAnnotationIDs=sorted({b['poseAnnotation'] for b in batches if b['poseAnnotation']}), trainingPositions=273,
                                        ipadInclinationRange=[min(b['inclinationRange'][0] for b in batches), max(b['inclinationRange'][1] for b in batches)]),
                aggregation='Equal weight per placement; componentwise median after per-row linear background correction',
                scope='Provisional fixed-condition personal test, no independent validation. ' +
                      ('Only one placement per position; repeatability is unknown. ' if len(passes)==1 else '') +
                      'Bilinear interpolation between 273 printed targets; no Pencil IMU, pose, contact, guide or time-derived position is an inference input.')


def run(paths, out, passes, *, allow_transient_motion=False, review_note=None):
    require(not out.exists(), 'Use a fresh report directory to preserve previous runs')
    batches = [extract(p, allow_transient_motion=allow_transient_motion, review_note=review_note) for p in paths]
    model = build(batches, passes)
    inventory = []
    for path in paths:
        manifest = json.loads((path/'manifest.json').read_text())
        for file in sorted(path.iterdir()):
            if not file.is_file():
                continue
            item = dict(session=manifest['id'], file=file.name, bytes=file.stat().st_size,
                        sha256=hashlib.sha256(file.read_bytes()).hexdigest())
            if file.suffix == '.csv':
                with file.open() as f:
                    item['rows'] = sum(1 for _ in csv.DictReader(f))
                require(item['rows'] == manifest['sensorCounts'].get(file.stem, 0), 'Sensor count mismatch: '+str(file))
            inventory.append(item)
    projector = Projector(model)
    static, replay = [], []
    for b in batches:
        for point in b['points']:
            def result(field):
                pred = projector.project(field)
                return dict(**pred, targetXY=point['xy'], row=point['row'], column=point['column'],
                            trial=point['session']+'/'+point['trial'],
                            errorMM=math.hypot(50*(pred['xy'][0]-point['xy'][0]), 30*(pred['xy'][1]-point['xy'][1])))
            static.append(result(point['deltaUT']))
            for frame in point['causalFrames']:
                replay.append(dict(**frame, **result(frame['filteredDeltaUT'])))
    report = dict(status='provisional_personal_test', positions=273, passes=sorted(passes), placements=len(static),
                  independentValidation=False, repeatabilityMeasured=len(passes)>1,
                  trainingAnchorFit=dict(shown=sum(p['shown'] for p in static), accepted=sum(p['accepted'] for p in static),
                                         medianErrorMM=st.median(p['errorMM'] for p in static)),
                  sameTrainingDataCausalReplay=dict(frames=len(replay), accepted=sum(p['accepted'] for p in replay),
                                                   medianErrorMM=st.median(p['errorMM'] for p in replay)),
                  limits=['Fit and replay reuse training data and are NOT independent accuracy estimates.',
                          'End backgrounds correct training data offline; replay/live use only a preceding baseline.',
                          'Review retained movement and background-drift flags; no compensation proves unchanged physical geometry.',
                          'A single pass cannot measure replacement repeatability or select a broadly generalizable model.'])
    out.mkdir(parents=True)
    for name, value in [('grid_model.json', model), ('analysis.json', report), ('observations.json', batches),
                        ('source_inventory.json', inventory), ('anchor_fit.json', static), ('causal_replay.json', replay)]:
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--passes', nargs='+', type=int, required=True)
    parser.add_argument('--allow-reviewed-transient-motion', action='store_true')
    parser.add_argument('--review-note')
    args = parser.parse_args()
    run(args.sessions, args.out, args.passes, allow_transient_motion=args.allow_reviewed_transient_motion, review_note=args.review_note)
