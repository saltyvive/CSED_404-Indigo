#!/usr/bin/env python3
"""Validate a new gridMapTest session against a frozen model, without fitting.

Report all points, preserving movement flags. Primary replay fixes each row's
starting background and uses a causal median. A separate posthoc diagnostic
uses both row backgrounds; it is not the online algorithm. Replay tests the
projection/display policy, not the live app's movement invalidation lifecycle.
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
import extract_grid_map as extract


def errors(prediction, target, aspect):
    x,y=prediction['xy']; tx,ty=target
    return dict(errorFractionOfHeight=math.hypot((x-tx)*aspect,y-ty),
                absoluteXFractionOfWidth=abs(x-tx),absoluteYFractionOfHeight=abs(y-ty),
                nearestMarkedPointCorrect=round(x*4)==round(tx*4) and round(y*4)==round(ty*4))


def aggregate(items):
    if not items:return None
    return dict(count=len(items),accepted=sum(p['accepted'] for p in items),
                hidden=sum(not p['shown'] for p in items),ambiguous=sum(p['ambiguous'] for p in items),
                nearestMarkedPointCorrect=sum(p['nearestMarkedPointCorrect'] for p in items),
                medianErrorFractionOfHeight=st.median(p['errorFractionOfHeight'] for p in items),
                p95ErrorFractionOfHeight=a.quantile([p['errorFractionOfHeight'] for p in items],.95),
                maximumErrorFractionOfHeight=max(p['errorFractionOfHeight'] for p in items))


def evaluate(session_path, model_path, output):
    model_bytes=model_path.read_bytes();model=json.loads(model_bytes)
    obs=extract.extract(session_path)
    if obs['purpose']!='grid_map_test':raise ValueError('Only held-out 12 sessions may be validated here')
    if obs['session']==model['sourceSession']:raise ValueError('Training-session leakage')
    if set(p['trial'] for p in obs['points']) & set(model['trainingTrialIDs']):
        raise ValueError('Training trial IDs overlap validation trials')
    manifest,rows=a.read_session(session_path)
    if not math.isclose(manifest['setup']['aspect'],model['aspect']):raise ValueError('Rectangle aspect mismatch')
    rows.sort(key=lambda r:float(r['timestamp_s']))
    projector=g.Projector(model)
    movement=[float(match[1]) for w in manifest.get('warnings',[])
              if (match:=re.search(r'iPad movement at uptime ([0-9.]+)',w))]
    static={name:[] for name in ('rowStart','posthoc')}
    for p in obs['points']:
        for name,field in [('rowStart',p['deltaUsingRowStartUT']),('posthoc',p['deltaUT'])]:
            pred=projector.project(field)
            static[name].append(dict(trial=p['trial'],row=p['row'],column=p['column'],targetXY=p['xy'],
                                     qualityEligible=p['eligible'],**pred,**errors(pred,p['xy'],model['aspect'])))
    frames=[]
    for group in obs['calibrationGroups']:
        points={p['trial']:p for p in obs['points'] if p['row']==group['row']}
        recent=deque();last=-math.inf
        for r in rows:
            t=float(r['timestamp_s'])
            if not group['before']['endTime']<t<group['after']['startTime']:continue
            recent.append((t,a.vector(r)))
            while recent and t-recent[0][0]>.12:recent.popleft()
            if t-last<.09 or len(recent)<3:continue
            last=t;p=points.get(r['trial_id'])
            if not p or not p['startTime']<=t<=p['endTime']:continue
            delta=[v-b for v,b in zip(a.median_vector([v for _,v in recent]),group['before']['raw'])]
            pred=projector.project(delta)
            after_warning=any(group['before']['startTime']<=w<=t for w in movement)
            frames.append(dict(timestamp=t,trial=p['trial'],row=p['row'],column=p['column'],targetXY=p['xy'],
                               qualityEligible=p['eligible'],afterMovementWarning=after_warning,
                               filteredDeltaUT=delta,**pred,**errors(pred,p['xy'],model['aspect'])))
    def grouped(items):
        return dict(all=aggregate(items),unflaggedRows=aggregate([p for p in items if p['qualityEligible']]),
                    interior=aggregate([p for p in items if 0<p['targetXY'][0]<1 and 0<p['targetXY'][1]<1]),
                    rows=[dict(row=row,**aggregate([p for p in items if p['row']==row])) for row in range(1,6)])
    summary=dict(session=obs['session'],modelSource=model['sourceSession'],modelSHA256=hashlib.sha256(model_bytes).hexdigest(),
                 modelFitted=False,sourceWarnings=manifest['warnings'],
                 flaggedRows=[r['row'] for r in obs['calibrationGroups'] if not r['eligible']],
                 rowBackgroundDriftUT=[r['driftUT'] for r in obs['calibrationGroups']],
                 rowStartStatic=grouped(static['rowStart']),posthocStatic=grouped(static['posthoc']),
                 causalReplay=grouped(frames),framesAfterMovementWarning=sum(f['afterMovementWarning'] for f in frames),
                 limits=['New session at the same manually marked positions, not unseen-position or handwriting accuracy.',
                         '2D distance is normalized by rectangle height, with x multiplied by aspect 1.5; not millimeters.',
                         'Nearest marked point identification is coarser than coordinate accuracy.',
                         'Movement-flagged rows are retained and reported separately; physical setup constancy is not proved.',
                         'Replay tests causal filtering/projection; the live app would invalidate on detected motion.',
                         'Posthoc interpolated backgrounds use future observations and are not online performance.',
                         'No model parameters or thresholds were fitted or tuned using this test session.'])
    inventory=[]
    for file in sorted(session_path.iterdir()):
        if not file.is_file():continue
        item=dict(file=file.name,bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
        if file.suffix=='.csv':
            with file.open() as stream:item['rows']=sum(1 for _ in csv.DictReader(stream))
            if item['rows']!=manifest['sensorCounts'].get(file.stem,0):raise ValueError(f'Sensor row count mismatch: {file.name}')
        inventory.append(item)
    if model_path.read_bytes()!=model_bytes:raise RuntimeError('Model changed during evaluation')
    output.mkdir(parents=True,exist_ok=True)
    for name,result in [('validation_summary.json',summary),('static_predictions.json',static),
                        ('causal_replay.json',frames),('grid_observations.json',obs),('source_inventory.json',inventory)]:
        (output/name).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    (output/'grid_model.json').write_bytes(model_bytes)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path);parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();result=evaluate(args.session,args.model,args.out)
    print(json.dumps({k:result[k] for k in ['flaggedRows','rowStartStatic','posthocStatic','causalReplay']},indent=2))
