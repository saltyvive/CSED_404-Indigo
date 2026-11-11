#!/usr/bin/env python3
"""Fit edge-only PCHIP magnetic maps; never use sweep time as position.

Whole edge_test sessions stay held out. Input sessions must have matching setup,
completed before/after baselines, and repeated stationary training anchors.
Python standard library only; coordinates are normalized, not millimeters.
"""
import argparse
import json
import math
import re
import statistics as st
from pathlib import Path
import analyze_session as a

EDGES = ('top', 'bottom', 'left', 'right')
KNOTS = [0, .25, .5, .75, 1]


def slopes(x, y):
    h = [b-a for a, b in zip(x, x[1:])]
    d = [(b-a)/step for a, b, step in zip(y, y[1:], h)]
    if len(x) == 2:
        return [d[0], d[0]]
    def endpoint(h0, h1, d0, d1):
        v = ((2*h0+h1)*d0-h0*d1)/(h0+h1)
        if v*d0 <= 0:
            return 0.0
        return math.copysign(min(abs(v), 3*abs(d0)), v) if d0*d1 < 0 else v
    m = [endpoint(h[0], h[1], d[0], d[1])]
    for i in range(1, len(x)-1):
        if d[i-1]*d[i] <= 0:
            m.append(0.0)
        else:
            w1, w2 = 2*h[i]+h[i-1], h[i]+2*h[i-1]
            m.append((w1+w2)/(w1/d[i-1]+w2/d[i]))
    m.append(endpoint(h[-1], h[-2], d[-1], d[-2]))
    return m


def field(curve, s):
    x, y, m = curve['knots'], curve['fieldsUT'], curve['slopesUT']
    i = min(len(x)-2, max(0, next((j-1 for j in range(1, len(x)) if s <= x[j]), len(x)-2)))
    h = x[i+1]-x[i]
    t = max(0, min(1, (s-x[i])/h))
    return [(2*t**3-3*t*t+1)*y[i][k] + (t**3-2*t*t+t)*h*m[i][k] +
            (-2*t**3+3*t*t)*y[i+1][k] + (t**3-t*t)*h*m[i+1][k] for k in range(3)]


def xy(edge, s):
    return {'top': [s, 0], 'bottom': [s, 1], 'left': [0, s], 'right': [1, s]}[edge]


def project(model, b):
    candidates = []
    for curve in model['curves']:
        residual, s = min((a.dist(field(curve, i/400), b), i/400) for i in range(401))
        candidates.append((residual, curve['edge'], s, curve['residualLimitUT']))
    residual, edge, s, limit = min(candidates)
    return dict(edge=edge, parameter=s, xy=xy(edge, s), residualUT=residual,
                accepted=residual <= limit,
                otherEdgeResidualUT=min((c[0] for c in candidates if c[1] != edge), default=None))


def summarize_trial(trial, rows, phase):
    start = trial['startUptime'] + trial.get('settleSeconds', 3)
    end = trial.get('endUptime', start)
    data = sorted((float(r['timestamp_s']), a.vector(r)) for r in rows
                  if r['trial_id'] == trial['spec']['id'] and r['phase'] == phase
                  and start+.4 <= float(r['timestamp_s']) < end-.2)
    data = [(t, b) for t, b in data if all(math.isfinite(v) for v in b)]
    if len(data) < 75 or data[-1][0]-data[0][0] < 1.8:
        raise ValueError(f"센서 샘플 부족: {trial['spec']['id']}")
    if max(t1-t0 for (t0, _), (t1, _) in zip(data, data[1:])) > .15:
        raise ValueError(f"센서 공백: {trial['spec']['id']}")
    center = a.median_vector([b for _, b in data])
    noise = math.sqrt(st.mean(a.dist(b, center)**2 for _, b in data))
    return dict(time=st.median(t for t, _ in data), startTime=data[0][0], endTime=data[-1][0],
                raw=center, noiseUT=noise, samples=len(data))


def extract(path, *, diagnostic_with_movement=False):
    manifest, rows = a.read_session(path)
    if manifest['status'] != 'completed':
        raise ValueError(f"완료되지 않은 세션: {manifest['id']}")
    trials = [t for t in manifest['trials'] if t['status'] == 'completed' and t['spec'].get('scenarioID')]
    if len(set(t['spec']['scenarioID'] for t in trials)) != 1:
        raise ValueError('한 세션에 하나의 변 측정 묶음이 필요합니다.')
    if trials[0]['spec']['scenarioID'] in ('gridMapTrain', 'gridMapTest'):
        raise ValueError('격자 자료는 extract_grid_map.py로 줄별 배경을 적용하세요.')
    baselines = {}
    for trial in trials:
        if trial['spec']['kind'] == 'edgeBaseline':
            if trial['spec']['edgeAction'] in baselines:
                raise ValueError('복수 배경 측정은 구간을 나눠 검증해야 합니다.')
            baselines[trial['spec']['edgeAction']] = summarize_trial(trial, rows, 'baseline')
    if set(baselines) != {'before', 'after'}:
        raise ValueError('시작·종료 배경 측정이 모두 필요합니다.')
    before, after = baselines['before'], baselines['after']
    if after['time'] <= before['time'] or max(before['noiseUT'], after['noiseUT']) >= 3:
        raise ValueError('배경 순서 또는 배경 안정성을 확인하세요.')
    movement = []
    for warning in manifest.get('warnings', []):
        match = re.search(r'iPad movement at uptime ([0-9.]+)', warning)
        if match and before['startTime'] <= float(match[1]) <= after['endTime']:
            movement.append(float(match[1]))
    if movement and not diagnostic_with_movement:
        # Even movement between trials can change the geometry. Never silently
        # treat a rotated device as a simple additive baseline shift.
        raise ValueError('이 세션에 iPad 움직임 경고가 있습니다. 배치 변화 여부를 먼저 검토하세요.')
    holds, sweeps, probes = [], [], []
    def baseline(t):
        f = max(0, min(1, (t-before['time'])/(after['time']-before['time'])))
        return [b+f*(e-b) for b, e in zip(before['raw'], after['raw'])]
    for trial in trials:
        spec = trial['spec']
        if spec['kind'] == 'edgeHold':
            if spec.get('edge') not in EDGES or spec.get('purpose') not in ('edge_train', 'edge_test'):
                raise ValueError('기준점의 변 또는 학습/검증 구분이 올바르지 않습니다.')
            if any(r['label_source'] != 'manual_static_target' for r in rows
                   if r['trial_id'] == spec['id'] and r['phase'] == 'hold'):
                raise ValueError('기준점에는 정지 위치 라벨만 사용할 수 있습니다.')
            obs = summarize_trial(trial, rows, 'hold')
            if not before['time'] < obs['time'] < after['time']:
                raise ValueError('배경 측정 밖의 기준점이 있습니다.')
            p = spec['point']
            obs.update(edge=spec['edge'], parameter=p['x'] if spec['edge'] in ('top', 'bottom') else p['y'],
                       purpose=spec['purpose'], repetition=spec['repetition'], trial=spec['id'], session=manifest['id'],
                       delta=[v-b for v, b in zip(obs['raw'], baseline(obs['time']))])
            holds.append(obs)
        elif spec['kind'] == 'edgeSweep':
            selected = [r for r in rows if r['trial_id'] == spec['id'] and r['phase'] == 'move']
            if any(r.get('target_x') or r.get('target_y') for r in selected):
                raise ValueError('자유 왕복에 시간 기반 좌표가 섞였습니다.')
            # Deliberate 5 Hz diagnostic replay only, not coordinate accuracy.
            samples, last = [], -math.inf
            for r in selected:
                t = float(r['timestamp_s'])
                if t-last >= .2:
                    samples.append([v-b for v, b in zip(a.vector(r), baseline(t))]); last = t
            sweeps.append(dict(trial=spec['id'], edge=spec['edge'], purpose=spec['purpose'], samples=samples))
        elif spec['kind'] == 'edgePose':
            phases = {}
            for phase in ('pose_reference', 'pose_change', 'pose_return'):
                selected = [(float(r['timestamp_s']), a.vector(r)) for r in rows
                            if r['trial_id'] == spec['id'] and r['phase'] == phase]
                if selected:
                    lo, hi = min(t for t, _ in selected), max(t for t, _ in selected)
                    stable = [b for t, b in selected if lo+.5 <= t <= hi-.3]
                    if len(stable) >= 50:
                        phases[phase] = a.median_vector(stable)
            probes.append(dict(trial=spec['id'], action=spec['edgeAction'], point=spec['point'],
                               measuredAngle=None, phaseFieldsUT=phases,
                               changeUT=a.dist(phases['pose_reference'], phases['pose_change']) if len(phases) == 3 else None,
                               returnDriftUT=a.dist(phases['pose_reference'], phases['pose_return']) if len(phases) == 3 else None))
    return dict(id=manifest['id'], startedAt=manifest['startedAt'], setup=manifest['setup'], holds=holds,
                baselineDriftUT=a.dist(before['raw'], after['raw']), sweeps=sweeps, probes=probes,
                diagnosticOnly=bool(movement), movementWarningTimes=movement)


def build(sessions):
    if not sessions:
        raise ValueError('세션이 필요합니다.')
    if any(s.get('diagnosticOnly') for s in sessions):
        raise ValueError('움직임 경고가 있는 진단 자료는 모델 학습에 사용할 수 없습니다.')
    signature = lambda s: tuple(s['setup'].get(k) for k in ('aspect', 'widthMM', 'heightMM', 'standAngle', 'environment', 'pencil', 'plane', 'heightNote'))
    if len({signature(s) for s in sessions}) != 1:
        raise ValueError('실험 조건이 다른 세션입니다. 같은 배치의 자료만 함께 사용하세요.')
    curves, observations = [], []
    for edge in EDGES:
        eligible = [s for s in sessions if any(h['edge'] == edge and h['purpose'] == 'edge_train' for h in s['holds'])]
        if not eligible:
            continue
        source = max(eligible, key=lambda s: s['startedAt'])
        holds = [h for h in source['holds'] if h['edge'] == edge and h['purpose'] == 'edge_train']
        centers = []
        for knot in KNOTS:
            group = [h for h in holds if abs(h['parameter']-knot) < 1e-8]
            if len({h['repetition'] for h in group}) < 2:
                raise ValueError(f'{edge}의 {knot*100:g}% 지점에 서로 다른 2회 학습이 필요합니다.')
            centers.append(a.median_vector([h['delta'] for h in group]))
        derivatives = list(zip(*(slopes(KNOTS, [v[axis] for v in centers]) for axis in range(3))))
        scatter = [a.dist(h['delta'], centers[KNOTS.index(h['parameter'])]) for h in holds]
        limit = max(3.0, 3*a.quantile(scatter, .95), 3*st.median(h['noiseUT'] for h in holds))
        curves.append(dict(edge=edge, knots=KNOTS, fieldsUT=centers, slopesUT=derivatives,
                           residualLimitUT=limit, sourceSession=source['id'], trainingTrialIDs=[h['trial'] for h in holds]))
        observations.extend(holds)
    if not curves:
        raise ValueError('edge_train 기준점 학습 세션이 필요합니다. 검증·왕복·자세 자료만으로 학습하지 않습니다.')
    model = dict(version=1, method='per-edge shape-preserving cubic magnetic-field interpolation',
                 aspect=sessions[0]['setup']['aspect'], curves=curves,
                 scope='Edge-only. No interior map, measured pencil IMU, contact detection, or measured dynamic ground truth.')
    known = {c['edge'] for c in curves}
    tests = []
    for session in sessions:
        for h in session['holds']:
            if h['purpose'] != 'edge_test' or h['edge'] not in known:
                continue
            pred = project(model, h['delta'])  # Deliberately no target edge input.
            target = xy(h['edge'], h['parameter'])
            tests.append(dict(trial=h['trial'], session=session['id'], targetEdge=h['edge'], targetXY=target,
                              **pred, edgeCorrect=pred['edge'] == h['edge'] if 0 < h['parameter'] < 1 and len(known) > 1 else None,
                              normalizedXYError=a.dist(target, pred['xy']),
                              alongEdgeError=abs(pred['parameter']-h['parameter']) if pred['edge'] == h['edge'] else None))
    replay = []
    for session in sessions:
        for sweep in session['sweeps']:
            if sweep['edge'] not in known:
                continue
            estimates = [project(model, b) for b in sweep['samples']]
            replay.append(dict(trial=sweep['trial'], assignedEdge=sweep['edge'], samples=len(estimates),
                               accepted=sum(p['accepted'] for p in estimates),
                               note='Display coverage only. Sweeps have no measured along-edge coordinates; no trajectory accuracy.',
                               estimates=estimates))
    confusion = [p for p in tests if p['edgeCorrect'] is not None]
    report = dict(sourceSessions=[s['id'] for s in sessions], trainedEdges=sorted(known),
                  baselineDriftUT={s['id']: s['baselineDriftUT'] for s in sessions},
                  heldOutPointTests=tests, edgeClassificationCount=len(confusion),
                  edgeCorrect=sum(p['edgeCorrect'] for p in confusion),
                  medianNormalizedXYError=st.median(p['normalizedXYError'] for p in tests) if tests else None,
                  poseProbes=[p for s in sessions for p in s['probes']], sweepReplay=replay,
                  warnings=['Manual approximate anchors, not instrumented ground truth.',
                            'Matching setup text does not prove physical placement is unchanged.',
                            'No held-out spatial interpolation accuracy until unseen positions are collected.',
                            'No temporal tracking filter in this offline curve baseline.',
                            'Corner edge identity is ambiguous; excluded from edge classification.'])
    return model, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions', nargs='+', help='Completed edge-study directories or ZIP files')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    model, report = build([extract(path) for path in args.sessions])
    args.out.mkdir(parents=True, exist_ok=True)
    for filename, data in [('edge_model.json', model), ('edge_report.json', report)]:
        (args.out/filename).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    print(f"학습한 변: {', '.join(report['trainedEdges'])}; 별도 정지 검증: {len(report['heldOutPointTests'])}개")
    print('실시간 앱 모델 반영 전 결과와 배경 변화·자세 영향을 검토하세요.')


if __name__ == '__main__':
    main()
