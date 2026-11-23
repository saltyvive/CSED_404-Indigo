"""Retain repeated magnetic prototypes and regress continuous desk coordinates."""
import hashlib
import json
import math
from pathlib import Path

from build_printed_grid_model import build as build_grid

PLAN = Path(__file__).resolve().parents[1]/'evaluation/knn_plan.json'


def build(batches, passes):
    grid = build_grid(batches, passes)  # Enforce complete, disjoint, same-condition rows.
    plan_bytes = PLAN.read_bytes(); plan = json.loads(plan_bytes)
    locations = []
    for row in range(13):
        for column in range(21):
            xy = [column/20, row/12]; fields = []; placements = []
            for batch in sorted(batches, key=lambda b: (b['repetition'], b['row'])):
                for point in batch['points']:
                    if point['xy'] != xy: continue
                    placements.append(point['session']+'/'+point['trial'])
                    fields.append(list(point['deltaUT']))
                    for frame in point['causalFrames']:
                        fraction = (frame['time']-batch['before']['time'])/(batch['after']['time']-batch['before']['time'])
                        fields.append([v-fraction*(e-b) for v,b,e in
                                       zip(frame['filteredDeltaUT'],batch['before']['raw'],batch['after']['raw'])])
            assert len(placements) == len(passes) and len(fields) == 4*len(passes)
            locations.append(dict(xy=xy, fieldsUT=fields, placementIDs=placements))
    return dict(version=1, method=plan['method'], planSHA256=hashlib.sha256(plan_bytes).hexdigest(),
                k=plan['neighbors'], weightPower=plan['weightPower'], distanceFloorUT=plan['distanceFloorUT'],
                localRadiusMM=plan['localRadiusMM'], ambiguityDistance=plan['ambiguityDistance'],
                ambiguityMarginUT=plan['ambiguityMarginUT'], residualLimitUT=grid['residualLimitUT'],
                minimumSignalUT=max(3,.2*min(math.hypot(*f) for p in locations for f in p['fieldsUT'])),
                locations=locations, sourceSessions=grid['sourceSessions'], trainingTrialIDs=grid['trainingTrialIDs'],
                printedGridContext=grid['printedGridContext'],
                scope='Fixed-pose provisional multiprototype local k-NN. Four correlated representatives per placement; not independent examples. No pose/guide/tip coordinates are inference inputs. No independent evaluation of the combined model yet.')


class Projector:
    def __init__(self, model):
        self.model = model

    def project(self, field):
        if len(field) != 3 or not all(map(math.isfinite,field)):
            raise ValueError('Finite 3-axis field required')
        m=self.model; locations=m['locations']
        distances=[min(math.dist(field,f) for f in p['fieldsUT']) for p in locations]
        best=min(range(len(locations)), key=lambda i:(distances[i],i))
        anchor=locations[best]['xy']; residual=distances[best]
        other=min((d for p,d in zip(locations,distances) if math.dist(p['xy'],anchor)>=m['ambiguityDistance']),default=1e300)
        context=m['printedGridContext']; width=context['widthMM']; height=context['heightMM']
        nearby=[i for i,p in enumerate(locations) if math.hypot(width*(p['xy'][0]-anchor[0]),height*(p['xy'][1]-anchor[1])) <= m['localRadiusMM']+1e-9]
        nearby.sort(key=lambda i:(distances[i],i)); chosen=nearby[:m['k']]
        exact=[i for i in chosen if distances[i]<=m['distanceFloorUT']]
        if exact: chosen=exact; weights=[1.0]*len(chosen)
        else: weights=[1/max(distances[i],m['distanceFloorUT'])**m['weightPower'] for i in chosen]
        total=sum(weights)
        xy=[sum(w*locations[i]['xy'][a] for i,w in zip(chosen,weights))/total for a in range(2)]
        signal=math.hypot(*field); ambiguous=other<=residual+m['ambiguityMarginUT']
        return dict(xy=xy,residualUT=residual,otherLocationResidualUT=other,signalUT=signal,shown=signal>=m['minimumSignalUT'],
                    ambiguous=ambiguous,accepted=signal>=m['minimumSignalUT'] and residual<=m['residualLimitUT'] and not ambiguous)
