#!/usr/bin/env python3
"""Extract 25 manual grid observations with a separate baseline pair per row.

No model is trained here. Grid validation sessions keep their held-out role.
Flagged rows remain in the report, but are ineligible for fitting.
"""
import argparse
import json
import math
import re
from pathlib import Path

import analyze_session as a
from build_edge_model import summarize_trial


def extract(path):
    manifest, rows = a.read_session(path)
    if manifest['status'] != 'completed':
        raise ValueError('완료된 격자 세션이 필요합니다.')
    trials = [t for t in manifest['trials'] if t['status'] == 'completed']
    scenarios = {t['spec'].get('scenarioID') for t in trials}
    if scenarios not in ({'gridMapTrain'}, {'gridMapTest'}):
        raise ValueError('11 또는 12 격자 세션만 읽을 수 있습니다.')
    purpose = 'grid_map_train' if scenarios == {'gridMapTrain'} else 'grid_map_test'
    movement = [float(m[1]) for w in manifest.get('warnings', [])
                if (m := re.search(r'iPad movement at uptime ([0-9.]+)', w))]
    points, groups = [], []
    for row in range(1, 6):
        group = [t for t in trials if t['spec'].get('calibrationGroup') == f'row{row}']
        baselines = [t for t in group if t['spec']['kind'] == 'mapBaseline']
        holds = [t for t in group if t['spec']['kind'] == 'mapHold']
        if len(group) != 7 or len(baselines) != 2 or len(holds) != 5:
            raise ValueError(f'{row}행의 배경 2개와 정지점 5개가 필요합니다.')
        if {t['spec'].get('edgeAction') for t in baselines} != {'before', 'after'}:
            raise ValueError(f'{row}행의 배경 역할 오류')
        base = {t['spec']['edgeAction']: summarize_trial(t, rows, 'baseline') for t in baselines}
        before, after = base['before'], base['after']
        if before['time'] >= after['time']:
            raise ValueError('배경 시간 순서 오류')
        warnings = []
        if max(before['noiseUT'], after['noiseUT']) >= 3:
            warnings.append('unstable_baseline')
        if any(before['startTime'] <= t <= after['endTime'] for t in movement):
            warnings.append('ipad_movement_after_baseline')
        if {t['spec'].get('gridColumn') for t in holds} != set(range(1, 6)):
            raise ValueError(f'{row}행의 열이 빠지거나 중복됐습니다.')
        for trial in holds:
            spec = trial['spec']; col = spec['gridColumn']
            expected = {'x': (col-1)/4, 'y': (row-1)/4}
            if spec.get('gridRow') != row or spec.get('point') != expected or spec.get('purpose') != purpose:
                raise ValueError('격자 좌표 또는 학습/검증 역할 오류')
            data = [r for r in rows if r['trial_id'] == spec['id'] and r['phase'] == 'hold']
            if any(r['label_source'] != 'manual_static_target' for r in data):
                raise ValueError('정지점에 수동 표식 좌표 라벨이 필요합니다.')
            obs = summarize_trial(trial, rows, 'hold')
            if not before['time'] < obs['time'] < after['time']:
                raise ValueError('해당 줄의 배경 측정 범위 밖에 있는 점입니다.')
            f = (obs['time']-before['time'])/(after['time']-before['time'])
            baseline = [b+f*(e-b) for b, e in zip(before['raw'], after['raw'])]
            points.append(dict(trial=spec['id'], row=row, column=col, xy=[expected['x'],expected['y']],
                               purpose=purpose, calibrationGroup=f'row{row}', **obs,
                               deltaUT=[b-v for b,v in zip(obs['raw'],baseline)],
                               deltaUsingRowStartUT=[b-v for b,v in zip(obs['raw'],before['raw'])],
                               eligible=not warnings))
        groups.append(dict(row=row, before=before, after=after, driftUT=math.dist(before['raw'],after['raw']),
                           warnings=warnings, eligible=not warnings))
    return dict(session=manifest['id'], scenario=next(iter(scenarios)), purpose=purpose,
                eligibleForInitialMap=purpose == 'grid_map_train' and all(p['eligible'] for p in points),
                points=points, calibrationGroups=groups,
                limits=['Manual marked positions, not instrumented ground truth; normalized coordinates are not millimeters.',
                        'Interpolated row backgrounds are offline estimates; compare with row-start-only correction.',
                        '12 repeats the same positions in a new order; it does not measure unseen-position accuracy.',
                        'A single training pass does not establish repeatability; no model was fitted by this extraction.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = extract(args.session)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'grid_observations.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    print(f"25개 점 추출 · 역할 {result['purpose']} · 사용 가능한 줄 {sum(g['eligible'] for g in result['calibrationGroups'])}/5")
