#!/usr/bin/env python3
"""MagAir schema-1 quality report + conservative, trial-held-out kNN baseline.

Python 3.9+, standard library only. No sample-wise random split and no use of
moving guide targets as ground truth. Fits/evaluates one fixed-setup session.
"""
import argparse
import csv
import html
import io
import json
import math
from pathlib import Path
import statistics as st
import zipfile


def read_session(path):
    path = Path(path)
    if path.is_dir():
        manifest = json.loads((path / 'manifest.json').read_text())
        with (path / 'magnetometer.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
    else:
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith('/manifest.json') or n == 'manifest.json']
            if len(names) != 1:
                raise ValueError('ZIP에는 세션이 정확히 하나 있어야 합니다.')
            manifest = json.loads(z.read(names[0]))
            prefix = names[0][:-len('manifest.json')]
            rows = list(csv.DictReader(io.StringIO(z.read(prefix + 'magnetometer.csv').decode('utf-8'))))
    if manifest.get('schemaVersion') != 1:
        raise ValueError('지원하지 않는 schemaVersion입니다.')
    required = {'timestamp_s', 'trial_id', 'phase', 'bx_uT', 'by_uT', 'bz_uT', 'label_source'}
    if rows and not required.issubset(rows[0]):
        raise ValueError('magnetometer.csv의 필수 열이 없습니다.')
    return manifest, rows


def vector(row):
    return tuple(float(row[k]) for k in ('bx_uT', 'by_uT', 'bz_uT'))


def median_vector(vectors):
    return tuple(st.median(v[i] for v in vectors) for i in range(3))


def dist(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    index = (len(values)-1)*q
    lo = int(index)
    return values[lo] + (values[min(lo+1, len(values)-1)]-values[lo])*(index-lo)


def collect_holds(manifest, rows):
    trials = {t['spec']['id']: t for t in manifest['trials'] if t['status'] == 'completed'}
    buckets = {}
    for row in rows:
        trial = trials.get(row.get('trial_id'))
        if not trial or row.get('phase') != 'hold' or row.get('label_source') != 'manual_static_target':
            continue
        if trial['spec']['kind'] not in ('gridTrain', 'gridTest', 'corners'):
            continue
        try:
            timestamp, field = float(row['timestamp_s']), vector(row)
        except (ValueError, KeyError):
            continue
        start = trial['startUptime'] + trial.get('settleSeconds', 3)
        end = trial.get('endUptime', start+3)
        # A little guard time after/before cues reduces human reaction contamination.
        if not (start + 0.4 <= timestamp < end - 0.2) or not all(map(math.isfinite, field)):
            continue
        buckets.setdefault(row['trial_id'], []).append((timestamp, field))
    holds, excluded = [], []
    for trial_id, trial in trials.items():
        spec = trial['spec']
        if spec['kind'] not in ('gridTrain', 'gridTest', 'corners'):
            continue
        samples = sorted(buckets.get(trial_id, []))
        duration = samples[-1][0]-samples[0][0] if len(samples) > 1 else 0
        gaps = [b[0]-a[0] for a, b in zip(samples, samples[1:])]
        if len(samples) < 10 or duration < 1.5 or max(gaps, default=0) > 0.5:
            excluded.append({'trial': trial_id, 'reason': 'insufficient_or_gapped_data', 'samples': len(samples)})
            continue
        fields = [s[1] for s in samples]
        center = median_vector(fields)
        point = spec['point']
        holds.append({'trial': trial_id, 'kind': spec['kind'], 'repetition': spec['repetition'],
                      'point_id': spec['pointID'], 'xy': [point['x'], point['y']], 'b': center,
                      'noise_rms_uT': math.sqrt(st.mean(dist(b, center)**2 for b in fields)),
                      'samples': len(fields), 'duration_s': duration})
    return holds, excluded


def fit(holds):
    if len({tuple(h['xy']) for h in holds}) < 4:
        return None
    scale = [max(st.pstdev(h['b'][i] for h in holds), 1e-6) for i in range(3)]
    return {'method': 'inverse-distance kNN, k=4 distinct coordinate prototypes', 'scale': scale,
            'prototypes': prototypes(holds), 'training_trial_ids': [h['trial'] for h in holds]}


def prototypes(holds):
    buckets = {}
    for h in holds:
        buckets.setdefault(tuple(h['xy']), []).append(h['b'])
    return [{'xy': list(xy), 'b': median_vector(fields)} for xy, fields in sorted(buckets.items())]


def predict(model, b):
    candidates = sorted((dist([b[i]/model['scale'][i] for i in range(3)],
                              [p['b'][i]/model['scale'][i] for i in range(3)]), i, p)
                         for i, p in enumerate(model['prototypes']))[:4]
    if candidates[0][0] < 1e-10:
        return list(candidates[0][2]['xy'])
    weights = [1/(d*d+1e-12) for d, _, _ in candidates]
    return [sum(w*p['xy'][axis] for w, (_, _, p) in zip(weights, candidates))/sum(weights) for axis in range(2)]


def evaluate(train, test, dimensions=None):
    model = fit(train)
    if not model or not test:
        return {'available': False, 'reason': '학습 4개 이상 서로 다른 위치와 별도 검증 측정이 필요합니다.'}
    assert not ({h['trial'] for h in train} & {h['trial'] for h in test}), 'Train/test trial leakage'
    results = []
    for h in test:
        p = predict(model, h['b'])
        dx, dy = p[0]-h['xy'][0], p[1]-h['xy'][1]
        result = {'trial': h['trial'], 'target': h['xy'], 'prediction': p,
                  'error_normalized': math.hypot(dx, dy), 'error_x': abs(dx), 'error_y': abs(dy)}
        if dimensions:
            result['error_mm'] = math.hypot(dx*dimensions[0], dy*dimensions[1])
        results.append(result)
    errors = [r['error_normalized'] for r in results]
    report = {'available': True, 'train_trials': len(train), 'test_trials': len(test),
              'train_unique_positions': len({tuple(h['xy']) for h in train}),
              'test_unique_positions': len({tuple(h['xy']) for h in test}),
              'median_normalized_error': st.median(errors), 'p95_normalized_error': quantile(errors, 0.95),
              'median_x_fraction': st.median(r['error_x'] for r in results),
              'median_y_fraction': st.median(r['error_y'] for r in results), 'predictions': results}
    if dimensions:
        report['median_error_mm'] = st.median(r['error_mm'] for r in results)
    return report


def check_corners(holds):
    """Classify held-out corner trials; never extrapolate interior coordinates."""
    corners = [h for h in holds if h['kind'] == 'corners']
    train = [h for h in corners if h['repetition'] <= 2]
    test = [h for h in corners if h['repetition'] == 3]
    if len({tuple(h['xy']) for h in train}) != 4 or not test:
        return {'available': False, 'trials_collected': len(corners),
                'reason': '네 모서리의 1·2회차와 별도의 3회차가 필요합니다.'}
    centers = prototypes(train)
    predictions = []
    for h in test:
        winner = min(centers, key=lambda p: dist(p['b'], h['b']))
        predictions.append({'trial': h['trial'], 'target': h['xy'], 'predicted_corner': winner['xy'],
                            'correct': list(h['xy']) == winner['xy']})
    return {'available': True, 'train_trials': len(train), 'test_trials': len(test),
            'correct': sum(p['correct'] for p in predictions), 'predictions': predictions,
            'minimum_corner_separation_uT': min(dist(a['b'], b['b']) for i, a in enumerate(centers) for b in centers[i+1:]),
            'median_within_hold_noise_uT': st.median(h['noise_rms_uT'] for h in corners),
            'limitation': '소수의 정지 구간 중앙값을 비교한 네 모서리 구별 검사입니다. 내부 좌표·글씨·다른 날의 성능은 평가하지 않습니다.'}


def check_height_pairs(manifest, rows):
    """Compare three steady holds in each completed surface/air/surface trial.

    Height and contact are operator instructions, not instrumented truth.
    Transitions and timing margins are never included in the comparison.
    """
    trials = {t['spec']['id']: t for t in manifest['trials']
              if t['spec']['kind'] == 'cornersHeight' and t['status'] == 'completed'}
    windows = {'surface_hold': (0, 3), 'air_hold': (5, 8), 'surface_return': (10, 13)}
    buckets = {}
    for row in rows:
        trial = trials.get(row.get('trial_id'))
        phase = row.get('phase')
        if not trial or phase not in windows or row.get('label_source') != 'manual_height_instruction':
            continue
        try:
            timestamp, field = float(row['timestamp_s']), vector(row)
        except (ValueError, KeyError):
            continue
        start = trial['startUptime'] + trial.get('settleSeconds', 3)
        lo, hi = windows[phase]
        end = min(start + hi, trial.get('endUptime', start + 13))
        if start + lo + 0.4 <= timestamp < end - 0.2 and all(map(math.isfinite, field)):
            buckets.setdefault((row['trial_id'], phase), []).append((timestamp, field))
    pairs, excluded = [], []
    for trial_id, trial in trials.items():
        holds = {}
        for phase in windows:
            samples = sorted(buckets.get((trial_id, phase), []))
            duration = samples[-1][0] - samples[0][0] if len(samples) > 1 else 0
            gaps = [b[0] - a[0] for a, b in zip(samples, samples[1:])]
            if len(samples) < 10 or duration < 1.5 or max(gaps, default=0) > 0.5:
                excluded.append({'trial': trial_id, 'phase': phase, 'reason': 'insufficient_or_gapped_data'})
                continue
            fields = [s[1] for s in samples]
            center = median_vector(fields)
            holds[phase] = {'median_uT': center, 'samples': len(samples),
                            'noise_rms_uT': math.sqrt(st.mean(dist(b, center)**2 for b in fields))}
        if len(holds) != 3:
            continue
        before, air, after = [holds[p]['median_uT'] for p in windows]
        contact = tuple((b + a)/2 for b, a in zip(before, after))
        spec = trial['spec']
        pairs.append({'trial': trial_id, 'point_id': spec['pointID'], 'repetition': spec['repetition'],
                      'nominal_lift_mm': spec.get('nominalLiftMM'),
                      'air_minus_surface_vector_uT': tuple(a - b for a, b in zip(air, contact)),
                      'air_surface_distance_uT': dist(air, contact),
                      'surface_return_distance_uT': dist(before, after), 'holds': holds})
    report = {'available': bool(pairs), 'completed_trials': len(trials), 'valid_pairs': len(pairs),
              'pairs': pairs, 'excluded_phases': excluded,
              'limitation': '약 1cm는 눈대중으로 맞춘 안내 높이입니다. 차이에는 높이 외에 손 떨림·기울기·위치 오차도 포함될 수 있습니다. 접촉 감지 정확도나 높이 추정 오차가 아닙니다.'}
    if pairs:
        report['median_air_surface_distance_uT'] = st.median(p['air_surface_distance_uT'] for p in pairs)
        report['median_surface_return_distance_uT'] = st.median(p['surface_return_distance_uT'] for p in pairs)
    return report


def analyze(manifest, rows):
    warnings = list(manifest.get('warnings', []))
    if manifest['status'] != 'completed':
        warnings.append('세션이 정상 종료되지 않았습니다. 완료된 trial만 분석합니다.')
    valid = []
    for row in rows:
        try:
            t, b = float(row['timestamp_s']), vector(row)
            if math.isfinite(t) and all(map(math.isfinite, b)):
                valid.append((t, b, row))
        except (ValueError, KeyError):
            pass
    deltas = [b[0]-a[0] for a, b in zip(valid, valid[1:])]
    positive = [d for d in deltas if d > 0]
    if any(d <= 0 for d in deltas):
        warnings.append('중복 또는 역순 센서 타임스탬프가 있습니다.')
    holds, excluded = collect_holds(manifest, rows)
    train = [h for h in holds if h['kind'] == 'gridTrain']
    test = [h for h in holds if h['kind'] == 'gridTest']
    corners = [h for h in holds if h['kind'] == 'corners']
    requested_grid = any(t['spec']['kind'] in ('gridTrain', 'gridTest') for t in manifest['trials'])
    expectations = [('학습', train, 75), ('검증', test, 32)] if requested_grid else []
    for name, subset, expected in expectations:
        if len(subset) < expected:
            warnings.append(f'{name} 유효 고정점 측정 {len(subset)}개 / 권장 {expected}개. 일부 결과만 계산될 수 있습니다.')
    dims = None
    try:
        w, h = float(manifest['setup']['widthMM']), float(manifest['setup']['heightMM'])
        if w > 0 and h > 0 and math.isfinite(w) and math.isfinite(h):
            dims = (w, h)
    except (ValueError, KeyError):
        pass
    completed = {t['spec']['id'] for t in manifest['trials'] if t['status'] == 'completed'}
    baseline = {}
    for name in ('baselineBefore', 'baselineAfter'):
        fields = [b for _, b, r in valid if r.get('protocol') == name and r.get('phase') == 'baseline' and r.get('trial_id') in completed]
        if fields:
            baseline[name] = {'median_uT': median_vector(fields), 'samples': len(fields)}
        else:
            warnings.append(f'{name} 데이터 없음: 배경 자기장 변화 확인이 제한됩니다.')
    if len(baseline) == 2:
        baseline['drift_uT'] = dist(baseline['baselineBefore']['median_uT'], baseline['baselineAfter']['median_uT'])
    repeat = evaluate([h for h in train if h['repetition'] <= 2], [h for h in train if h['repetition'] == 3], dims)
    spatial = evaluate(train, test, dims)
    model = fit(train)
    # A rough ambiguity diagnostic: pairs with small field separation relative to within-hold noise.
    ambiguous = []
    for i, a in enumerate(train):
        for b in train[i+1:]:
            if dist(a['xy'], b['xy']) >= 0.25:
                separation = dist(a['b'], b['b'])
                noise = math.hypot(a['noise_rms_uT'], b['noise_rms_uT'])
                if separation < 3*max(noise, 1e-6):
                    ambiguous.append({'a': a['trial'], 'b': b['trial'], 'field_distance_uT': separation})
    report = {'session': manifest['id'], 'sensor_rows': len(rows), 'valid_numeric_rows': len(valid),
              'median_sample_rate_hz': 1/st.median(positive) if positive else None,
              'max_gap_s': max(positive) if positive else None,
              'gaps_over_100ms': sum(d > 0.1 for d in positive), 'baseline': baseline,
              'valid_static_trials': len(holds), 'excluded_static_trials': excluded,
              'corner_check': check_corners(holds),
              'height_check': check_height_pairs(manifest, rows),
              'repeat_holdout': repeat, 'spatial_holdout': spatial,
              'potentially_ambiguous_pairs': ambiguous[:50], 'warnings': warnings,
              'limitations': ['수동으로 맞춘 지점이므로 정답 위치에도 오차가 있습니다.',
                              '동적 안내 좌표는 정답이 아니므로 궤적 정확도를 평가하지 않습니다.',
                              '같은 배치 한 세션의 결과입니다. 다른 날·높이·회전·사용자 일반화는 별도 실험입니다.',
                              '정지 구간 중앙값 기준 오차이며 순간 샘플의 실시간 추적 성능은 아닙니다.',
                              'kNN은 가능성을 살펴보는 기준 모델입니다. 필기 복원 성공을 뜻하지 않습니다.']}
    return report, model


def plot_svg(result):
    if not result.get('available'):
        return '<p>데이터가 충분하지 않습니다.</p>'
    parts = ['<svg viewBox="0 0 460 460" role="img" aria-label="목표점과 예측점 오차"><rect x="30" y="30" width="400" height="400" fill="#f4f8f7" stroke="#a5b7b3"/>']
    for r in result['predictions']:
        x, y = [30+400*v for v in r['target']]
        px, py = [30+400*v for v in r['prediction']]
        parts.append(f'<path d="M{x},{y} L{px},{py}" stroke="#d47457" opacity=".65"/><circle cx="{x}" cy="{y}" r="4" fill="#1c3552"/><circle cx="{px}" cy="{py}" r="4" fill="#16a08c"/>')
    parts.append('</svg><p>남색: 수동 목표점 · 초록: 예측 · 선: 오차 (x, y 각각 0~1)</p>')
    return ''.join(parts)


def write_report(report, model, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if model:
        (output/'model.json').write_text(json.dumps(model, ensure_ascii=False, indent=2))
    else:
        (output/'model.json').unlink(missing_ok=True)
    body = '<h1>MagAir · 첫 좌표 매핑 검사</h1><p>'+html.escape(report['session'])+'</p>'
    body += '<p>실제 센서 수신률 중앙값: '+str(report['median_sample_rate_hz'])+' Hz</p>'
    corner = report['corner_check']
    if corner.get('trials_collected', 0) or corner.get('available'):
        body += '<section><h2>자가 없는 첫 실험 · 네 모서리</h2>'
        if corner.get('available'):
            body += f'<p>1·2회차로 기준을 만들고 3회차 {corner["test_trials"]}번 중 {corner["correct"]}번을 맞혔습니다.</p>'
            body += f'<p>모서리 간 최소 자기장 거리: {corner["minimum_corner_separation_uT"]:.2f} µT · 정지 중 잡음 중앙값: {corner["median_within_hold_noise_uT"]:.2f} µT</p>'
            body += '<p>'+html.escape(corner['limitation'])+'</p>'
        else:
            body += '<p>'+html.escape(corner['reason'])+'</p>'
        body += '</section>'
    height = report['height_check']
    if height['completed_trials']:
        body += '<section><h2>접촉 ↔ 약 1cm 공중 비교</h2>'
        body += f'<p>완료 {height["completed_trials"]}회 중 세 정지 구간이 모두 유효한 비교 {height["valid_pairs"]}회.</p>'
        if height['available']:
            body += f'<p>공중–접촉 자기장 거리 중앙값: {height["median_air_surface_distance_uT"]:.2f} µT · 다시 접촉했을 때 원래 값과의 거리: {height["median_surface_return_distance_uT"]:.2f} µT.</p>'
            body += '<p>들기 전·내린 후 접촉 값의 평균과 공중 값을 비교합니다. 전환 시간과 각 정지 구간의 처음 0.4초·끝 0.2초는 제외했습니다.</p>'
        body += '<p>'+html.escape(height['limitation'])+'</p></section>'
    for key, title in [('repeat_holdout', '같은 좌표, 새로운 반복'), ('spatial_holdout', '학습하지 않은 칸 중심')]:
        result = report[key]
        body += '<section><h2>'+title+'</h2>'
        if result.get('available'):
            body += f'<p>중앙 오차: x={result["median_x_fraction"]*100:.1f}% 가로, y={result["median_y_fraction"]*100:.1f}% 세로. 검증 {result["test_trials"]}회.</p>'
            if 'median_error_mm' in result:
                body += f'<p>입력한 실측 치수 기준 중앙 오차: {result["median_error_mm"]:.2f} mm</p>'
        body += plot_svg(result)+'</section>'
    body += '<h2>확인할 사항</h2><ul>'+''.join('<li>'+html.escape(s)+'</li>' for s in report['warnings']+report['limitations'])+'</ul>'
    document = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>MagAir 분석</title><style>body{font:16px/1.7 system-ui;color:#193047;background:#f5f7f9;max-width:900px;margin:40px auto;padding:24px}section{background:white;border-radius:18px;padding:24px;margin:24px 0}svg{max-width:460px;width:100%}h1,h2{line-height:1.3}</style>'+body+'</html>'
    (output/'report.html').write_text(document)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', help='앱에서 받은 ZIP 또는 압축 해제한 세션 폴더')
    parser.add_argument('--out', default='reports/latest')
    args = parser.parse_args()
    try:
        manifest, rows = read_session(args.session)
        report, model = analyze(manifest, rows)
        write_report(report, model, args.out)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f'분석 실패: {error}\n')
    print(f'보고서: {Path(args.out).resolve() / "report.html"}')
    print(f'유효 고정점 측정: {report["valid_static_trials"]}개')
    for warning in report['warnings']:
        print('참고:', warning)


if __name__ == '__main__':
    main()
