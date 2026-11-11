#!/usr/bin/env python3
"""Evaluate a held-out edge session against a frozen deployed model.

Replay uses only the initial pen-away baseline and past 0.12-second samples.
This reconstructs display policy, not callback timing or a filmed trajectory.
The separate static diagnostic interpolates before/after backgrounds offline.
"""
import argparse
import csv
import hashlib
import json
import math
import statistics as st
from collections import Counter, deque
from pathlib import Path

import analyze_session as a
import build_edge_model as e


def evaluate(session_path, model_path, output, *, diagnostic_with_movement=False):
    model_bytes = model_path.read_bytes()
    model = json.loads(model_bytes)
    manifest, rows = a.read_session(session_path)
    session = e.extract(session_path, diagnostic_with_movement=diagnostic_with_movement)
    assert all(h['purpose'] == 'edge_test' for h in session['holds']), 'Validation only'
    assert all(c['sourceSession'] != session['id'] for c in model['curves']), 'Training leakage'
    rows.sort(key=lambda r: float(r['timestamp_s']))
    trials = {t['spec']['id']: t for t in manifest['trials'] if t['status'] == 'completed'}
    before_trial = next(t for t in trials.values() if t['spec'].get('edgeAction') == 'before')
    after_trial = next(t for t in trials.values() if t['spec'].get('edgeAction') == 'after')
    before = e.summarize_trial(before_trial, rows, 'baseline')
    after = e.summarize_trial(after_trial, rows, 'baseline')

    # Same ordered grid, weak-signal gate, and competing-location policy as Swift.
    candidates = [(c['edge'], i/400, e.xy(c['edge'], i/400), e.field(c, i/400), c['residualLimitUT'])
                  for c in model['curves'] for i in range(401)]
    minimum = max(3, .2*min(math.hypot(*c[3]) for c in candidates))

    def project(field):
        distances = [math.dist(c[3], field) for c in candidates]
        i = min(range(len(distances)), key=distances.__getitem__)
        edge, parameter, point, _, limit = candidates[i]
        residual = distances[i]
        ambiguous = any(math.dist(c[2], point) >= .2 and d <= residual+.75
                        for c, d in zip(candidates, distances))
        signal = math.hypot(*field)
        return dict(edge=edge, parameter=parameter, xy=point, residualUT=residual,
                    signalUT=signal, shown=signal >= minimum, ambiguous=ambiguous,
                    accepted=signal >= minimum and residual <= limit and not ambiguous)

    static = []
    for h in session['holds']:
        pred = project(h['delta'])
        target = e.xy(h['edge'], h['parameter'])
        dx, dy = pred['xy'][0]-target[0], pred['xy'][1]-target[1]
        static.append(dict(trial=h['trial'], targetEdge=h['edge'], targetParameter=h['parameter'],
                           targetXY=target, **pred, errorFractionOfHeight=math.hypot(dx*model['aspect'], dy),
                           edgeCorrect=pred['edge'] == h['edge'] if 0 < h['parameter'] < 1 else None))

    frames, recent, last_display = [], deque(), -math.inf
    for row in rows:
        t = float(row['timestamp_s'])
        if t < before_trial['endUptime']:
            continue
        recent.append((t, a.vector(row)))
        while recent and t-recent[0][0] > .12:
            recent.popleft()
        if t-last_display < .09 or len(recent) < 3:
            continue
        last_display = t
        trial = trials.get(row['trial_id'])
        if not trial or row['phase'] not in ('hold', 'move'):
            continue
        # Exclude initial settling/edge transitions from the stationary evaluation.
        if row['phase'] == 'hold' and not (trial['startUptime']+trial['settleSeconds']+.4 <= t < trial['endUptime']-.2):
            continue
        raw = a.median_vector([b for _, b in recent])
        delta = [v-b for v, b in zip(raw, before['raw'])]
        pred = project(delta)
        frames.append(dict(timestamp=t, trial=row['trial_id'], phase=row['phase'], filteredDeltaUT=delta, **pred))

    replay_trials = []
    for trial_id, trial in trials.items():
        selected = [f for f in frames if f['trial'] == trial_id]
        if not selected:
            continue
        spec = trial['spec']
        counts = Counter(f['edge'] for f in selected)
        # Projection onto the other edge near a shared corner is not a known error.
        others = [f for f in selected if f['edge'] != spec['edge']]
        endpoints = [e.xy(spec['edge'], s) for s in (0, 1)]
        distances = [min(math.dist(f['xy'], p) for p in endpoints) for f in others]
        item = dict(trial=trial_id, action=spec['edgeAction'], phase=selected[0]['phase'],
                    frames=len(selected), hidden=sum(not f['shown'] for f in selected),
                    accepted=sum(f['accepted'] for f in selected), ambiguous=sum(f['ambiguous'] for f in selected),
                    predictedEdges=dict(counts), minSignalUT=min(f['signalUT'] for f in selected),
                    maxOtherEdgeDistanceFromSharedCornerNormalized=max(distances, default=None),
                    otherEdgeCandidatesBeyond20Percent=sum(d >= .2 for d in distances))
        if 'point' in spec:
            target = [spec['point']['x'], spec['point']['y']]
            errors = [math.hypot((f['xy'][0]-target[0])*model['aspect'], f['xy'][1]-target[1]) for f in selected]
            item.update(targetXY=target, medianErrorFractionOfHeight=st.median(errors),
                        maxErrorFractionOfHeight=max(errors))
        replay_trials.append(item)

    inventory = []
    for path in sorted(session_path.iterdir()):
        if not path.is_file():
            continue
        item = dict(file=path.name, bytes=path.stat().st_size,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if path.suffix == '.csv':
            with path.open() as handle:
                records = list(csv.DictReader(handle))
            expected = manifest['sensorCounts'].get(path.stem, 0)
            assert len(records) == expected, f'Incomplete copy: {path.name}'
            times = [float(r['timestamp_s']) for r in records]
            item.update(rows=len(records), manifestRows=expected,
                        maxTimestampGapSeconds=max((t1-t0 for t0, t1 in zip(times, times[1:])), default=None))
        inventory.append(item)
    errors = [s['errorFractionOfHeight'] for s in static]
    summary = dict(session=session['id'], modelSHA256=hashlib.sha256(model_bytes).hexdigest(), modelUnchanged=True,
                   diagnosticOnly=session['diagnosticOnly'], movementWarningTimes=session['movementWarningTimes'],
                   completedTrials=len(trials), magnetometerSamples=len(rows), warnings=manifest.get('warnings', []),
                   baselineDriftUT=session['baselineDriftUT'], baselineNoiseUT={'before': before['noiseUT'], 'after': after['noiseUT']},
                   stationaryPointTests=static, medianStationaryErrorFractionOfHeight=st.median(errors),
                   maxStationaryErrorFractionOfHeight=max(errors),
                   replay={'baseline': 'fixed initial baseline median; no future baseline', 'baselineUT': before['raw'],
                           'filter': 'causal 0.12-second component median; display spacing >= 0.09 seconds',
                           'minimumSignalUT': minimum, 'trials': replay_trials},
                   limits=(['Movement occurred after initial baseline: results are diagnostic, not a clean fixed-setup validation.'] if session['diagnosticOnly'] else []) +
                          ['Manual approximate anchors; independent session at previously trained positions.',
                           'Static diagnostic uses offline before/after interpolation, unlike fixed-baseline replay.',
                           'Replay reconstructs inference policy from recorded sensor times, not actual UI callback timing.',
                           'No measured moving coordinates: accepted frames are model coverage, not trajectory accuracy.',
                           'A different edge near a shared corner is not necessarily a position error.',
                           'Error is normalized by rectangle height, with width scaled by the stated aspect ratio.'])
    assert model_path.read_bytes() == model_bytes
    output.mkdir(parents=True, exist_ok=True)
    for name, value in [('validation_summary.json', summary), ('causal_replay.json', frames), ('source_inventory.json', inventory)]:
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--diagnostic-with-movement', action='store_true',
                        help='Inspect a flagged session without training or claiming fixed-setup validation; warnings remain in output.')
    args = parser.parse_args()
    evaluate(args.session, args.model, args.out, diagnostic_with_movement=args.diagnostic_with_movement)
