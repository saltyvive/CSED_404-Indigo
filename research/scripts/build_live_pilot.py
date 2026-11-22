#!/usr/bin/env python3
"""Build an explicitly provisional four-corner field interpolation model.

Only stationary corner holds label position. Moving guide timestamps are never
training targets. Height trials train a separate, manually selected air mode.
"""
import argparse
import json
import math
from pathlib import Path
import statistics as st
import analyze_session as a

ORDER = [(0, 0), (1, 0), (1, 1), (0, 1)]


def baseline_points(manifest, rows):
    points = []
    for trial in manifest['trials']:
        if trial['status'] != 'completed' or trial['spec']['kind'] not in ('baselineBefore', 'baselineAfter'):
            continue
        selected = [r for r in rows if r['trial_id'] == trial['spec']['id'] and r['phase'] == 'baseline']
        if selected:
            points.append((st.median(float(r['timestamp_s']) for r in selected), a.median_vector([a.vector(r) for r in selected])))
    if not points:
        raise ValueError('완료된 배경 자기장 측정이 필요합니다.')
    return sorted(points)


def baseline_at(points, time):
    if time <= points[0][0]:
        return points[0][1]
    for (t0, b0), (t1, b1) in zip(points, points[1:]):
        if time <= t1:
            f = (time - t0) / (t1 - t0)
            return tuple(x + f*(y-x) for x, y in zip(b0, b1))
    return points[-1][1]


def observations(manifest, rows):
    baselines = baseline_points(manifest, rows)
    trials = {t['spec']['id']: t for t in manifest['trials']}
    holds, _ = a.collect_holds(manifest, rows)
    surface, air = [], []
    for h in holds:
        if h['kind'] == 'corners':
            t = trials[h['trial']]
            b = baseline_at(baselines, t['startUptime'] + t.get('settleSeconds', 3) + 1.5)
            surface.append(dict(h, b=tuple(x-y for x, y in zip(h['b'], b))))
    for pair in a.check_height_pairs(manifest, rows)['pairs']:
        t = trials[pair['trial']]
        b = baseline_at(baselines, t['startUptime'] + t.get('settleSeconds', 3) + 6.5)
        h = pair['holds']['air_hold']
        air.append({'trial': pair['trial'], 'repetition': pair['repetition'],
                    'xy': [t['spec']['point']['x'], t['spec']['point']['y']],
                    'b': tuple(x-y for x, y in zip(h['median_uT'], b)), 'noise_rms_uT': h['noise_rms_uT']})
    return {'surface': surface, 'air': air}, baselines


def centers(holds):
    result = []
    for xy in ORDER:
        fields = [h['b'] for h in holds if tuple(h['xy']) == xy]
        if not fields:
            raise ValueError('모든 모서리에 유효한 정지 측정이 필요합니다.')
        result.append(a.median_vector(fields))
    return result


def field_at(anchors, x, y):
    w = ((1-x)*(1-y), x*(1-y), x*y, (1-x)*y)
    return tuple(sum(w[j]*anchors[j][i] for j in range(4)) for i in range(3))


def project(anchors, field):
    best = (float('inf'), 0, 0)
    for iy in range(27):
        for ix in range(27):
            x, y = -0.15 + ix*0.05, -0.15 + iy*0.05
            best = min(best, (a.dist(field_at(anchors, x, y), field), x, y))
    _, cx, cy = best
    for iy in range(-5, 6):
        for ix in range(-5, 6):
            x, y = cx + ix*0.005, cy + iy*0.005
            best = min(best, (a.dist(field_at(anchors, x, y), field), x, y))
    return {'residual_uT': best[0], 'xy': [best[1], best[2]]}


def build(manifest, rows):
    datasets, baselines = observations(manifest, rows)
    modes, validation = [], {}
    for mode, holds in datasets.items():
        anchors = centers(holds)
        # Gate set from training-repeat scatter, not a calibrated confidence score.
        spread = [a.dist(h['b'], anchors[ORDER.index(tuple(h['xy']))]) for h in holds]
        threshold = max(3.0, 3*a.quantile(spread, 0.95))
        minimum_signal = max(3.0, min(a.dist(b, (0, 0, 0)) for b in anchors)*0.2)
        modes.append({'id': mode, 'title': '책상 접촉' if mode == 'surface' else '약 1cm 공중',
                      'anchors': anchors, 'residualLimitUT': threshold, 'minimumSignalUT': minimum_signal,
                      'trainingTrialIDs': [h['trial'] for h in holds]})
        train = [h for h in holds if h['repetition'] <= 2]
        test = [h for h in holds if h['repetition'] == 3]
        assert not {h['trial'] for h in train} & {h['trial'] for h in test}
        fit = centers(train)
        predictions = []
        for h in test:
            estimate = project(fit, h['b'])
            nearest = min(range(4), key=lambda i: a.dist(fit[i], h['b']))
            predictions.append(dict(estimate, trial=h['trial'], target=h['xy'],
                                    corner_correct=list(ORDER[nearest]) == h['xy'],
                                    corner_projection_error=a.dist(estimate['xy'], h['xy'])))
        validation[mode] = {'train_trials': len(train), 'test_trials': len(test),
                            'correct_corners': sum(p['corner_correct'] for p in predictions),
                            'predictions': predictions,
                            'scope': 'Held-out stationary corners only; interior and moving accuracy are unknown.'}
    return {'version': 1, 'sourceSession': manifest['id'], 'aspect': manifest['setup']['aspect'],
            'method': 'inverse bilinear interpolation of four median magnetic-field anchors',
            'baselineReferenceUT': baselines[-1][1], 'modes': modes,
            'limitation': 'Four-corner pilot. Interior position, handwriting, and physical pen contact are unvalidated.'}, validation, baselines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session')
    parser.add_argument('--out', default='reports/first-real')
    parser.add_argument('--model', default='MagAir/Resources/live_model.json')
    args = parser.parse_args()
    m, rows = a.read_session(args.session)
    model, validation, baselines = build(m, rows)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    path = Path(args.model); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, ensure_ascii=False, indent=2))
    notes = {'user_observations': ['Motion speed did not reliably follow guide speed.',
                                 'Air height was approximate and hand shake was present.'],
             'baseline': baselines, 'validation': validation,
             'dynamic_labels_used': False, 'interior_accuracy_measured': False,
             'air_height_measured': False, 'baseline_note': 'The ending baseline preceded height trials. Later drift is not measured.'}
    (out/'live_validation.json').write_text(json.dumps(notes, ensure_ascii=False, indent=2))
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
