#!/usr/bin/env python3
"""Fit a provisional 2D magnetic surface from eligible stationary grid rows.

No temporal guide labels or validation sessions enter the fit. Movement rows
are excluded by default; a documented, explicit row override may include them.
Bilinear forward interpolation is inverted over a 101x101 spatial
search grid; the displayed guide line never constrains that search.
"""
import argparse
import csv
import hashlib
import json
import math
import statistics as st
from collections import deque
from pathlib import Path

import analyze_session as a
import extract_grid_map as g


def build(observations, aspect, *, include_movement_rows=(), inclusion_note=None):
    if observations['purpose'] != 'grid_map_train':
        raise ValueError('Held-out grid sessions must not train the model')
    included = set(include_movement_rows)
    groups = {r['row']: r for r in observations['calibrationGroups']}
    if included and (not inclusion_note or not inclusion_note.strip()):
        raise ValueError('A reason is required when including movement-flagged rows')
    for row in included:
        if row not in groups or groups[row].get('warnings') != ['ipad_movement_after_baseline']:
            raise ValueError('Only an explicitly named row flagged solely for movement can be included')
    points = [p for p in observations['points'] if p['eligible'] or p['row'] in included]
    xs = sorted({p['xy'][0] for p in points})
    ys = sorted({p['xy'][1] for p in points})
    if len(xs) < 3 or len(ys) < 3 or xs[0] != 0 or xs[-1] != 1 or ys[0] != 0 or ys[-1] != 1:
        raise ValueError('Insufficient eligible grid coverage; collect missing boundary rows')
    lookup = {tuple(p['xy']): p for p in points}
    if len(lookup) != len(points) or any((x,y) not in lookup for y in ys for x in xs):
        raise ValueError('A complete rectangular subset of eligible points is required')
    return dict(version=1, method='bilinear_forward_surface_grid_inverse', aspect=aspect,
                xKnots=xs, yKnots=ys, fieldsUT=[[lookup[x,y]['deltaUT'] for x in xs] for y in ys],
                searchSteps=100, residualLimitUT=max(3, 5*max(p['noiseUT'] for p in points)),
                ambiguityDistance=0.2, ambiguityMarginUT=0.75,
                sourceSession=observations['session'], trainingTrialIDs=[p['trial'] for p in points],
                excludedRows=[r['row'] for r in observations['calibrationGroups'] if not r['eligible'] and r['row'] not in included],
                movementIncludedRows=sorted(included), inclusionNote=inclusion_note if included else None,
                scope='Provisional fixed-pose desk-contact 2D map; no independent validation yet. '
                      'Movement warnings are retained; see explicit inclusion metadata. '
                      'Intermediate positions are interpolated, not measured.')


def field(model, x, y):
    xs, ys = model['xKnots'], model['yKnots']
    i = next((i for i in range(len(xs)-1) if x <= xs[i+1]),len(xs)-2)
    j = next((j for j in range(len(ys)-1) if y <= ys[j+1]),len(ys)-2)
    u = max(0,min(1,(x-xs[i])/(xs[i+1]-xs[i])))
    v = max(0,min(1,(y-ys[j])/(ys[j+1]-ys[j])))
    f = model['fieldsUT']
    return [(1-v)*((1-u)*f[j][i][k]+u*f[j][i+1][k])+
            v*((1-u)*f[j+1][i][k]+u*f[j+1][i+1][k]) for k in range(3)]


class Projector:
    def __init__(self, model):
        self.model = model
        n = model['searchSteps']
        self.candidates = [(i/n,j/n,field(model,i/n,j/n)) for j in range(n+1) for i in range(n+1)]
        self.minimum = max(3,0.2*min(math.hypot(*c[2]) for c in self.candidates))

    def project(self, b):
        if len(b) != 3 or not all(map(math.isfinite,b)):
            raise ValueError('Finite 3-axis field required')
        ds = [math.dist(c[2],b) for c in self.candidates]
        i = min(range(len(ds)),key=ds.__getitem__)
        x,y,_ = self.candidates[i]; residual=ds[i]
        other = min((d for (xx,yy,_),d in zip(self.candidates,ds)
                     if math.hypot(xx-x,yy-y) >= self.model['ambiguityDistance']), default=math.inf)
        ambiguous = other <= residual+self.model['ambiguityMarginUT']
        signal = math.hypot(*b)
        return dict(xy=[x,y],residualUT=residual,otherLocationResidualUT=other,
                    signalUT=signal,shown=signal>=self.minimum,ambiguous=ambiguous,
                    accepted=signal>=self.minimum and residual<=self.model['residualLimitUT'] and not ambiguous)


def evaluate(session, output, *, include_movement_rows=(), inclusion_note=None):
    observations = g.extract(session)
    manifest, rows = a.read_session(session)
    model = build(observations,manifest['setup']['aspect'],include_movement_rows=include_movement_rows,
                  inclusion_note=inclusion_note)
    fitted = set(model['trainingTrialIDs'])
    projector = Projector(model)
    output.mkdir(parents=True,exist_ok=True)
    def save(name,obj):
        (output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False))
    save('grid_model.json',model)
    save('grid_observations.json',observations)
    static = []
    for p in observations['points']:
        pred = projector.project(p['deltaUT'])
        error = math.hypot((pred['xy'][0]-p['xy'][0])*model['aspect'],pred['xy'][1]-p['xy'][1])
        static.append(dict(trial=p['trial'],row=p['row'],column=p['column'],targetXY=p['xy'],
                           fitted=p['trial'] in fitted,sourceEligibleWithoutOverride=p['eligible'],
                           errorFractionOfHeight=error,**pred))
    frames=[]
    # Replay each row with only its starting background, never its future end.
    # Flagged row 4 is a counterfactual diagnostic after its movement event.
    for group in observations['calibrationGroups']:
        points={p['trial']:p for p in observations['points'] if p['row']==group['row']}
        recent=deque(); last=-math.inf
        for r in rows:
            t=float(r['timestamp_s'])
            if not group['before']['endTime'] < t < group['after']['startTime']: continue
            recent.append((t,a.vector(r)))
            while recent and t-recent[0][0]>.12:recent.popleft()
            if t-last<.09 or len(recent)<3:continue
            last=t
            p=points.get(r['trial_id'])
            if not p or not p['startTime']<=t<=p['endTime']:continue
            b=[v-base for v,base in zip(a.median_vector([v for _,v in recent]),group['before']['raw'])]
            pred=projector.project(b)
            error=math.hypot((pred['xy'][0]-p['xy'][0])*model['aspect'],pred['xy'][1]-p['xy'][1])
            frames.append(dict(timestamp=t,trial=p['trial'],row=p['row'],targetXY=p['xy'],
                               fitted=p['trial'] in fitted,sourceEligibleWithoutOverride=p['eligible'],
                               filteredDeltaUT=b,errorFractionOfHeight=error,**pred))
    inventory=[]
    for file in sorted(session.iterdir()):
        if not file.is_file():continue
        item=dict(file=file.name,bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest())
        if file.suffix=='.csv':
            with file.open() as stream:item['rows']=sum(1 for _ in csv.DictReader(stream))
            expected=manifest['sensorCounts'].get(file.stem,0)
            if item['rows']!=expected:raise ValueError(f'Sensor row count mismatch: {file}')
        inventory.append(item)
    summary=dict(session=manifest['id'],sourceWarnings=manifest['warnings'],trainingPoints=len(model['trainingTrialIDs']),
                 excludedRows=model['excludedRows'],rowDriftUT=[r['driftUT'] for r in observations['calibrationGroups']],
                 movementIncludedRows=model['movementIncludedRows'],inclusionNote=model['inclusionNote'],
                 static=static,replayRows=[],limits=[
                     'Training anchors reconstruct the fit and are not independent accuracy measurements.',
                     'Movement-flagged rows retain their warnings even when explicitly included in fitting.',
                     'Row-start replay uses causal filtering, but live testing would invalidate on iPad movement.',
                     'No recorded moving paths or Pencil IMU exist in session 11. Test 12 must remain held out.',
                     'A small gravity-angle change cannot rule out physical translation or yaw.'])
    for row in range(1,6):
        fs=[f for f in frames if f['row']==row]
        summary['replayRows'].append(dict(row=row,frames=len(fs),accepted=sum(f['accepted'] for f in fs),
                                          ambiguous=sum(f['ambiguous'] for f in fs),
                                          medianErrorFractionOfHeight=st.median(f['errorFractionOfHeight'] for f in fs),
                                          maxErrorFractionOfHeight=max(f['errorFractionOfHeight'] for f in fs)))
    save('analysis.json',summary);save('causal_replay.json',frames);save('source_inventory.json',inventory)
    print(json.dumps({k:summary[k] for k in ('trainingPoints','excludedRows','rowDriftUT','replayRows')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session',type=Path);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--include-movement-row',type=int,action='append',default=[])
    parser.add_argument('--inclusion-note')
    args=parser.parse_args();evaluate(args.session,args.out,include_movement_rows=args.include_movement_row,
                                     inclusion_note=args.inclusion_note)
