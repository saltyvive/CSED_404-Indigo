#!/usr/bin/env python3
"""Replay self-paced line tests 13–15 against a frozen, unconstrained 2D map.

Only the instructed line is known, not position or speed at any timestamp.
Cross-line distance assumes the operator followed that line; it is NOT full
trajectory error. A single out-and-back does not establish repeatability.
"""
import argparse
import csv
import hashlib
import json
import math
import re
import statistics as st
from collections import deque
from pathlib import Path

import analyze_session as a
import build_grid_model as g
from build_edge_model import summarize_trial


def endpoints(guide):
    if guide in [f'row{i}' for i in range(1,6)]:
        y=(int(guide[-1])-1)/4;return [[0,y],[1,y]]
    if guide in [f'col{i}' for i in range(1,6)]:
        x=(int(guide[-1])-1)/4;return [[x,0],[x,1]]
    if guide=='diagonalDown':return [[0,0],[1,1]]
    if guide=='diagonalUp':return [[1,0],[0,1]]
    raise ValueError('Unknown instructed path')


def line_metrics(point, guide, aspect):
    first,last=endpoints(guide)
    ax,ay=first[0]*aspect,first[1];dx,dy=(last[0]-first[0])*aspect,last[1]-first[1]
    px,py=point[0]*aspect-ax,point[1]-ay
    length=math.hypot(dx,dy);along=(px*dx+py*dy)/(length*length)
    signed=(dx*py-dy*px)/length
    distance=math.hypot(px-max(0,min(1,along))*dx,py-max(0,min(1,along))*dy)
    return dict(lineDistanceFractionOfHeight=distance,signedLineOffsetFractionOfHeight=signed,alongFraction=along)


def extract(session_path):
    manifest,rows=a.read_session(session_path)
    if manifest['status']!='completed':raise ValueError('Completed path session required')
    trials=[t for t in manifest['trials'] if t['status']=='completed']
    scenarios={t['spec'].get('scenarioID') for t in trials}
    expected={'gridHorizontal':[f'row{i}' for i in range(1,6)],
              'gridVertical':[f'col{i}' for i in range(1,6)],
              'gridDiagonal':['diagonalDown','diagonalUp']}
    if len(scenarios)!=1 or next(iter(scenarios)) not in expected:raise ValueError('Only path-test scenarios 13–15 are supported')
    scenario=next(iter(scenarios));groups=[]
    if len(trials)!=3*len(expected[scenario]):raise ValueError('Unexpected completed trial count')
    movement=[float(m[1]) for w in manifest.get('warnings',[]) if (m:=re.search(r'iPad movement at uptime ([0-9.]+)',w))]
    for guide in expected[scenario]:
        group=[t for t in trials if t['spec'].get('calibrationGroup')==guide]
        if len(group)!=3 or {t['spec'].get('edgeAction') for t in group}!={'before','sweep','after'}:
            raise ValueError('Each path needs exactly one before/sweep/after triple')
        if any(t['spec'].get('guidePathID')!=guide or t['spec'].get('point') is not None for t in group):
            raise ValueError('Path ID mismatch or point coordinate injected')
        actions={t['spec']['edgeAction']:t for t in group};sweep=actions['sweep']
        if sweep['spec']['kind']!='mapSweep' or sweep['spec'].get('purpose')!='grid_path_test':
            raise ValueError('Path sweep must remain test-only')
        for action in ['before','after']:
            if actions[action]['spec']['kind']!='mapBaseline' or actions[action]['spec'].get('purpose')!='grid_path_baseline':
                raise ValueError('Path baseline kind/role mismatch')
        before=summarize_trial(actions['before'],rows,'baseline');after=summarize_trial(actions['after'],rows,'baseline')
        start=sweep['startUptime']+sweep.get('settleSeconds',3);end=sweep['endUptime']
        if not before['endTime']<start<end<after['startTime'] or not 4<=end-start<=180:
            raise ValueError('Path times or duration invalid')
        data=sorted((r for r in rows if r['trial_id']==sweep['spec']['id'] and r['phase']=='move'),key=lambda r:float(r['timestamp_s']))
        if any(r['label_source']!='known_path_only' or r.get('target_x') or r.get('target_y') for r in data):
            raise ValueError('Self-paced path must not contain timestamped target coordinates')
        if len(data)<100 or any(not all(map(math.isfinite,a.vector(r))) for r in data):raise ValueError('Missing or non-finite path samples')
        times=[float(r['timestamp_s']) for r in data]
        gaps=[b-a for a,b in zip(times,times[1:])]
        warnings=[]
        if max(before['noiseUT'],after['noiseUT'])>=3:warnings.append('unstable_baseline')
        if max(gaps,default=0)>.15:warnings.append('sensor_gap')
        if any(before['startTime']<=t<=after['endTime'] for t in movement):warnings.append('ipad_movement_after_baseline')
        groups.append(dict(guide=guide,trial=sweep['spec']['id'],start=start,end=end,duration=end-start,
                           samples=len(data),maximumSampleGap=max(gaps,default=0),
                           before=before,after=after,driftUT=math.dist(before['raw'],after['raw']),warnings=warnings))
    return manifest,rows,groups,movement


def aggregate(frames):
    if not frames:return None
    def measures(fs):
        if not fs:return None
        return dict(medianLineDistanceFractionOfHeight=st.median(f['lineDistanceFractionOfHeight'] for f in fs),
                    p95LineDistanceFractionOfHeight=a.quantile([f['lineDistanceFractionOfHeight'] for f in fs],.95),
                    maxLineDistanceFractionOfHeight=max(f['lineDistanceFractionOfHeight'] for f in fs),
                    medianSignedOffsetFractionOfHeight=st.median(f['signedLineOffsetFractionOfHeight'] for f in fs),
                    estimatedAlongRange=[min(f['alongFraction'] for f in fs),max(f['alongFraction'] for f in fs)])
    run_start=None;longest=0
    for f in frames:
        if not f['accepted']:
            if run_start is None:run_start=f['timestamp']
            longest=max(longest,f['timestamp']-run_start+.1)
        else:run_start=None
    return dict(frames=len(frames),accepted=sum(f['accepted'] for f in frames),
                hidden=sum(not f['shown'] for f in frames),ambiguous=sum(f['ambiguous'] for f in frames),
                framesAfterMovementWarning=sum(f['afterMovementWarning'] for f in frames),
                longestRejectedRunApproxSeconds=longest,allCandidates=measures(frames),
                acceptedCandidates=measures([f for f in frames if f['accepted']]),
                startAlongMedian=st.median(f['alongFraction'] for f in frames if f['timestamp']<=frames[0]['timestamp']+1),
                endAlongMedian=st.median(f['alongFraction'] for f in frames if f['timestamp']>=frames[-1]['timestamp']-1))


def evaluate(session_path,model_path,output):
    model_bytes=model_path.read_bytes();model=json.loads(model_bytes)
    manifest,rows,groups,movement=extract(session_path)
    if manifest['id']==model['sourceSession']:raise ValueError('Training-session leakage')
    if {g['trial'] for g in groups}&set(model['trainingTrialIDs']):raise ValueError('Training trial leakage')
    if not math.isclose(manifest['setup']['aspect'],model['aspect']):raise ValueError('Rectangle aspect mismatch')
    rows.sort(key=lambda r:float(r['timestamp_s']))
    projector=g.Projector(model);frames=[];posthoc=[]
    for group in groups:
        recent=deque();last=-math.inf
        for row in rows:
            t=float(row['timestamp_s'])
            if not group['before']['endTime']<t<group['after']['startTime']:continue
            recent.append((t,a.vector(row)))
            while recent and t-recent[0][0]>.12:recent.popleft()
            if t-last<.09 or len(recent)<3:continue
            last=t
            if row['trial_id']!=group['trial'] or row['phase']!='move' or not group['start']<=t<group['end']:continue
            raw=a.median_vector([v for _,v in recent])
            f=(t-group['before']['time'])/(group['after']['time']-group['before']['time'])
            interpolated=[b+f*(e-b) for b,e in zip(group['before']['raw'],group['after']['raw'])]
            for dest,baseline in [(frames,group['before']['raw']),(posthoc,interpolated)]:
                delta=[v-b for v,b in zip(raw,baseline)];pred=projector.project(delta)
                dest.append(dict(timestamp=t,trial=group['trial'],guide=group['guide'],
                                 qualityEligible=not group['warnings'],afterMovementWarning=any(group['before']['startTime']<=w<=t for w in movement),
                                 filteredDeltaUT=delta,**pred,**line_metrics(pred['xy'],group['guide'],model['aspect'])))
    summary=dict(session=manifest['id'],modelSource=model['sourceSession'],modelSHA256=hashlib.sha256(model_bytes).hexdigest(),
                 modelFitted=False,sourceWarnings=manifest['warnings'],paths=[],
                 limits=['One self-paced out-and-back per line is exploratory, not a repeatability or speed-invariance study.',
                         'The path is an instruction, not observed ground truth. Cross-line distance assumes adherence.',
                         'Along-line position and speed are unknown; no full trajectory error or inferred constant-speed labels.',
                         'Display acceptance is not position accuracy; report rejected and accepted estimates separately.',
                         'Frame summaries are time-weighted and affected by dwell and speed; frames are not independent repetitions.',
                         'Replay tests filtering/projection and does not enforce live motion invalidation. Flagged segments are diagnostic.',
                         'Posthoc correction uses future end backgrounds; it is not online performance.'])
    for group in groups:
        summary['paths'].append(dict(**group,causal=aggregate([f for f in frames if f['guide']==group['guide']]),
                                     posthoc=aggregate([f for f in posthoc if f['guide']==group['guide']])))
    inventory=[]
    for file in sorted(session_path.iterdir()):
        if not file.is_file():continue
        item=dict(file=file.name,bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
        if file.suffix=='.csv':
            with file.open() as stream:item['rows']=sum(1 for _ in csv.DictReader(stream))
            if item['rows']!=manifest['sensorCounts'].get(file.stem,0):raise ValueError('Source sensor count mismatch')
        inventory.append(item)
    if model_path.read_bytes()!=model_bytes:raise RuntimeError('Model changed during evaluation')
    output.mkdir(parents=True,exist_ok=True)
    for name,data in [('validation_summary.json',summary),('causal_replay.json',frames),('posthoc_replay.json',posthoc),('source_inventory.json',inventory)]:
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
    (output/'grid_model.json').write_bytes(model_bytes)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path);parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result=evaluate(args.session,args.model,args.out)
    print(json.dumps([dict(guide=p['guide'],driftUT=p['driftUT'],warnings=p['warnings'],causal=p['causal'],posthoc=p['posthoc']) for p in result['paths']],indent=2))
