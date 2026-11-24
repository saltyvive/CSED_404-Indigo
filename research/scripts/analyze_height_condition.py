"""Post-hoc 0/3 mm feasibility; row holdout is not an independent height-repeat test.

No sensor frames from a withheld row enter either class's training prototypes.
No target coordinate, fixture pose or height enters the classifier query.
The existing contact models and their rejection thresholds remain unchanged.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics as st

from build_printed_grid_model import extract, build as build_a, require
from build_knn_model import build as build_b, Projector as ProjectorB
from build_grid_model import Projector as ProjectorA
from compare_pass_combinations import save, summarize
from evaluate_printed_pass import percentile

ROOT = Path(__file__).resolve().parents[1]


def distribution(values):
    values = list(values)
    return dict(count=len(values), minimum=min(values), median=st.median(values),
                p95=percentile(values, .95), maximum=max(values))


def feature(point, batch, mode):
    if mode == 'linear':
        return list(point['deltaUT'])
    require(mode == 'before', 'Unknown background mode')
    return [v-b for v,b in zip(point['raw'], batch['before']['raw'])]


def prototypes(contact, hover, passes, excluded_row=None):
    """One representative per XY per class, with identical row exclusion for both."""
    groups = {}
    for state, batches in [('contact', contact), ('air', hover)]:
        for batch in batches:
            if batch['row'] == excluded_row or (state == 'contact' and batch['repetition'] not in passes):
                continue
            for p in batch['points']:
                groups.setdefault((state, p['row'], p['column']), []).append(p)
    return [dict(state=state, row=row, column=col, xy=ps[0]['xy'],
                 field=[st.median(p['deltaUT'][a] for p in ps) for a in range(3)],
                 trainingTrials=[p['session']+'/'+p['trial'] for p in ps])
            for (state,row,col),ps in sorted(groups.items())]


def classify(field, train):
    distances = {state: min(math.dist(field,p['field']) for p in train if p['state']==state)
                 for state in ('contact', 'air')}
    gap = abs(distances['air']-distances['contact'])
    # Do not give either class a tie-breaking advantage.
    predicted = 'tie' if gap < 1e-12 else min(distances, key=distances.get)
    return dict(predicted=predicted, distanceUT=distances, gapUT=gap)


def classification_summary(rows):
    result = {}
    for state in ('contact','air'):
        samples = [r for r in rows if r['truth']==state]
        result[state] = dict(count=len(samples), correct=sum(r['predicted']==state for r in samples),
                             recall=sum(r['predicted']==state for r in samples)/len(samples),
                             predicted={label:sum(r['predicted']==label for r in samples) for label in ('contact','air','tie')})
    result['balancedAccuracy'] = st.mean(result[s]['recall'] for s in ('contact','air'))
    return result


def grouped_rows(contact, hover, passes, mode):
    predictions = []
    for held in range(1,14):
        train = prototypes(contact,hover,passes,excluded_row=held)
        require(len(train)==2*12*21, 'Unbalanced or incomplete training prototypes')
        training_ids = {t for p in train for t in p['trainingTrials']}
        for state,batches in [('contact',contact),('air',hover)]:
            for batch in batches:
                if batch['row'] != held or (state=='contact' and batch['repetition'] not in passes):
                    continue
                for p in batch['points']:
                    require(p['session']+'/'+p['trial'] not in training_ids, 'Held-out trial leakage')
                    predictions.append(dict(truth=state,passID=batch['repetition'],row=held,column=p['column'],
                        session=batch['session'],trial=p['trial'],**classify(feature(p,batch,mode),train)))
    summary = classification_summary(predictions)
    summary['perRow'] = {str(row): classification_summary([p for p in predictions if p['row']==row]) for row in range(1,14)}
    return summary,predictions


def position_predictions(projector, batches, mode):
    rows = []
    for batch in batches:
        for p in batch['points']:
            pred = projector.project(feature(p,batch,mode))
            rows.append(dict(session=batch['session'],trial=p['trial'],row=p['row'],column=p['column'],
                targetXY=p['xy'],errorMM=math.hypot(50*(pred['xy'][0]-p['xy'][0]),30*(pred['xy'][1]-p['xy'][1])),**pred))
    return summarize(rows),rows


def separation(contact, hover, passes, mode):
    # This paired comparison uses known XY for diagnosis, not inference.
    lookup = {}
    for batch in contact:
        if batch['repetition'] not in passes: continue
        for p in batch['points']:
            lookup.setdefault((p['row'],p['column']),[]).append(feature(p,batch,mode))
    references = {key:[st.median(v[a] for v in vs) for a in range(3)] for key,vs in lookup.items()}
    pairs = []
    for batch in hover:
        for p in batch['points']:
            key = p['row'],p['column']; value = feature(p,batch,mode)
            other = min(references,key=lambda k: math.dist(value,references[k]))
            pairs.append(dict(row=key[0],column=key[1],sameXYDistanceUT=math.dist(value,references[key]),
                              nearestContactRow=other[0],nearestContactColumn=other[1],
                              nearestContactDistanceUT=math.dist(value,references[other]),
                              nearestContactXYSeparationMM=2.5*math.dist(key,other)))
    return dict(sameXY=distribution(p['sameXYDistanceUT'] for p in pairs),
                nearestOtherHeight=distribution(p['nearestContactDistanceUT'] for p in pairs),
                nearestOtherHeightBelow1UT=sum(p['nearestContactDistanceUT']<1 for p in pairs),
                nearestOtherHeightBelow2UT=sum(p['nearestContactDistanceUT']<2 for p in pairs),
                perRow={str(row):distribution(p['sameXYDistanceUT'] for p in pairs if p['row']==row) for row in range(1,14)},
                closestExamples=sorted(pairs,key=lambda p:p['nearestContactDistanceUT'])[:10]),pairs


def run(sources_file, out):
    require(not out.exists(), 'Use a fresh output directory')
    sources = json.loads(sources_file.read_bytes())
    selected = json.loads((ROOT/sources['contactSourcesFile']).read_bytes())
    contact=[]; hover=[]; inventory=[]
    for group, paths in [(p,selected[p]) for p in ('1','2','3')]+[('air',sources['hoverSessions'])]:
        for name in paths:
            path = ROOT/name
            raw = (path/'manifest.json').read_bytes()
            review = sources['motionReviews'].get(path.name) if group=='air' else None
            if review: require(hashlib.sha256(raw).hexdigest()==review['manifestSHA256'], 'Motion review source changed')
            b=extract(path,allow_transient_motion=bool(review) or group=='1',
                review_note=review['note'] if review else 'Previously reviewed contact pass-1 transient non-measurement motion.')
            if group=='air':
                require(b['campaignID']==sources['hoverCampaignID'] and b['pose']['tipHeightMM']==3 and
                        not b['pose']['tipContact'] and b['repetition']==1, 'Wrong air condition')
            else:
                require(b['pose']['tipHeightMM']==0 and b['pose']['tipContact'] and b['repetition']==int(group), 'Wrong contact condition')
            require(b['pose']['phiDegrees']==0 and b['pose']['thetaDegrees']==90 and b['pose']['alphaDegrees']==0, 'Wrong angles')
            (hover if group=='air' else contact).append(b)
            manifest=json.loads(raw)
            for f in sorted(path.iterdir()):
                if not f.is_file(): continue
                item=dict(group=group,session=path.name,file=f.name,bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest())
                if f.suffix=='.csv':
                    with f.open() as stream: item['rows']=sum(1 for _ in csv.DictReader(stream))
                    require(item['rows']==manifest['sensorCounts'].get(f.stem,0),'Sensor count mismatch')
                inventory.append(item)
    require(len(hover)==13 and {b['row'] for b in hover}==set(range(1,14)), 'Incomplete air pass')
    out.mkdir(parents=True); (out/'models').mkdir()
    save(out/'source_inventory.json',inventory);save(out/'contact_observations.json',contact);save(out/'hover_observations.json',hover)
    (out/'sources.json').write_bytes(sources_file.read_bytes())
    result=dict(independentAirRepeatValidation=False,quality=dict(
        positions=sum(len(b['points']) for b in hover),excludedAttempts=sum(len(b['excludedAttempts']) for b in hover),
        pointNoiseUT=distribution(p['noiseUT'] for b in hover for p in b['points']),
        samplesPerTrimmedHold=distribution(p['samples'] for b in hover for p in b['points']),
        backgroundDriftUT=distribution(b['driftUT'] for b in hover),
        motionRows=[b['row'] for b in hover if b['motionEvents']],
        perRow=[dict(row=b['row'],driftUT=b['driftUT'],backgroundNoiseUT=[b['before']['noiseUT'],b['after']['noiseUT']],
                     motionEvents=b['motionEvents'],inclinationRange=b['inclinationRange'],excludedAttempts=b['excludedAttempts']) for b in hover]),
        separation={},rowHoldout={},positionReplay={},limits=[
            'One air pass only; all classification is exploratory row holdout, not independent air-repeat accuracy.',
            'Row holdout excludes all positions and frames from the whole test row in both height classes.',
            'Equal prototypes per height; queries use only three magnetic components, never target XY, pose, height, time or row.',
            'Before mode uses only the preceding row baseline at test; linear mode uses the future end baseline and is an offline diagnostic.',
            'Height and collection day/campaign are confounded. Similar tilt cannot rule out translation or yaw.',
            'Source class labels distinguish operator-set 0mm and 3mm only; no general contact sensor or other heights were validated.',
            'Air position replay reuses training placements and cannot estimate independent position accuracy.'])
    for combo in ('1','2','3','13','123'):
        passes=list(map(int,combo))
        for mode in ('before','linear'):
            key=combo+'_'+mode
            result['separation'][key],pairs=separation(contact,hover,passes,mode)
            save(out/(key+'-separation.json'),pairs)
            result['rowHoldout'][key],pred=grouped_rows(contact,hover,passes,mode)
            save(out/(key+'-height-predictions.json'),pred)
        print('Height diagnostic contact '+combo+' completed',flush=True)
    c={p:{(q['row'],q['column']):q['deltaUT'] for b in contact if b['repetition']==p for q in b['points']} for p in (1,3)}
    result['contact1vs3SameXYDistanceUT']=distribution(math.dist(c[1][k],c[3][k]) for k in c[1])
    for family,builder,projector_cls in [('A',build_a,ProjectorA),('B',build_b,ProjectorB)]:
        model=builder(hover,[1]);save(out/'models'/('hover3_pass1_'+family+'.json'),model)
        projector=projector_cls(model)
        for mode in ('before','linear'):
            key='air_'+family+'_'+mode
            summary,pred=position_predictions(projector,hover,mode)
            result['positionReplay'][key]=dict(role='training_replay',**summary)
            save(out/(key+'-position-predictions.json'),pred)
        for combo in ('13','123'):
            raw=(ROOT/'MagAir/Resources'/f'model_{family}_{combo}.json').read_bytes()
            old=projector_cls(json.loads(raw))
            key='contact_'+family+combo+'_on_air_before'
            summary,pred=position_predictions(old,hover,'before')
            result['positionReplay'][key]=dict(role='wrong_height_stress_test_not_contact_detection',modelSHA256=hashlib.sha256(raw).hexdigest(),**summary)
            save(out/(key+'-position-predictions.json'),pred)
        print('Position diagnostics '+family+' completed',flush=True)
    save(out/'summary.json',result)
    print('Saved '+str(out/'summary.json'),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,default=ROOT/'evaluation/hover3_sources.json')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.sources,args.out)
