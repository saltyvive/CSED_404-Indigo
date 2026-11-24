"""Reproducible air pass-2 extraction, frozen-evaluation ledger and 1/2/12 comparison.

Run prepare, replay OLD estimators, freeze-summary, build, train C, replay all,
then summarize and bundle. New weights never replace old frozen model files.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from build_printed_grid_model import extract, build as build_a, require
from build_knn_model import build as build_b, Projector as ProjectorB
from build_grid_model import Projector as ProjectorA
from compare_pass_combinations import ROOT, save, summarize
from train_joint_mlp import load_records, evaluate, summarize as neural_summary

OLD = ROOT/'reports/hover3-20261125-pass1'
OLD_C = ROOT/'reports/joint-mlp-20261125-v1'
NEW_C = ROOT/'reports/joint-mlp-20261125-air12'
SECOND_C = ROOT/'reports/joint-mlp-20261125-air2'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_preserving(path, value):
    value = json.loads(json.dumps(value, allow_nan=False))
    if path.exists():
        require(json.loads(path.read_bytes()) == value, 'Existing result differs: '+str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        save(path, value)


def queries(contact, air):
    rows = []
    for state, batches in [('contact', contact), ('air', air)]:
        for b in batches:
            if state == 'contact' and b['repetition'] not in (1,3):
                continue
            for p in b['points']:
                fields = [('primary', [v-s for v,s in zip(p['raw'], b['before']['raw'])]), ('offline', p['deltaUT'])]
                fields += [('causal', f['filteredDeltaUT']) for f in p['causalFrames']]
                for mode, field in fields:
                    rows.append(dict(truth=state, passID=b['repetition'], row=p['row'], column=p['column'],
                        session=p['session'], trial=p['trial'], xy=p['xy'], field=field, mode=mode))
    return rows


def prepare(out):
    sources = json.loads((ROOT/'evaluation/hover3_pass2_sources.json').read_bytes())
    plan = json.loads((ROOT/'evaluation/hover3_pass2_plan.json').read_bytes())
    rows = []; inventory = []
    for name in sources['sessions']:
        path = ROOT/name; m = json.loads((path/'manifest.json').read_bytes()); meta = m['printedGrid']
        review = sources['motionReviews'].get(path.name)
        if review:
            require(digest(path/'manifest.json') == review['manifestSHA256'], 'Motion review source changed')
        b = extract(path, allow_transient_motion=bool(review), review_note=review['note'] if review else None)
        require(b['repetition'] == 2 and b['campaignID'] == plan['campaignID'], 'Wrong pass/campaign')
        require([b['pose'][k] for k in ('phiDegrees','thetaDegrees','alphaDegrees','tipHeightMM','tipContact')] == [0,90,0,3,False], 'Wrong pose/height')
        require(meta['evaluationJointModelSHA256'] == plan['frozenModels'] and meta['evaluationTrainingPasses'] == [1], 'Frozen model provenance mismatch')
        require(meta['evaluationModelSHA256'] == plan['frozenModels']['A_air1'] and meta['evaluationKNNModelSHA256'] == plan['frozenModels']['B_air1'], 'Wrong standalone evaluation model')
        require(meta['scheduledRowOrder'] == list(range(1,14)) and meta['rowOrderRevision'] == 'hover3_pass2_ascending_20261125_v1', 'Wrong row order')
        rows.append(b)
        for f in sorted(path.iterdir()):
            if not f.is_file(): continue
            item = dict(session=path.name, file=f.name, bytes=f.stat().st_size, sha256=digest(f))
            if f.suffix == '.csv':
                with f.open() as stream: item['rows'] = sum(1 for _ in csv.DictReader(stream))
                require(item['rows'] == m['sensorCounts'].get(f.stem,0), 'Sensor count mismatch')
            inventory.append(item)
    require(len(rows) == 13 and {b['row'] for b in rows} == set(range(1,14)), 'Incomplete pass2')
    air1 = json.loads((OLD/'hover_observations.json').read_bytes())
    contact = json.loads((OLD/'contact_observations.json').read_bytes())
    write_preserving(out/'source_inventory.json', inventory)
    write_preserving(out/'hover_observations.json', air1+rows)
    write_preserving(out/'contact_observations.json', contact)
    write_preserving(out/'all-queries.json', queries(contact, air1+rows))
    write_preserving(out/'frozen-queries.json', queries([], rows))


def joint_metrics(items, family):
    ps = [r[family] for r in items]
    m = summarize(ps)
    if family in ('A','B','C'):
        m.update(correct=sum(r[family]['predicted']==r['truth'] for r in items),
            wrong=sum(r[family]['accepted'] and r[family]['predicted']!=r['truth'] for r in items),
            abstain=sum(not p['accepted'] for p in ps),
            correctHeightAndXYWithin2p5MM=sum(r[family]['predicted']==r['truth'] and r[family]['errorMM']<=2.5 for r in items),
            correctHeightAndXYWithin5MM=sum(r[family]['predicted']==r['truth'] and r[family]['errorMM']<=5 for r in items))
        reasons = dict(weakSignal=0, heightAmbiguous=0, otherPosition=0, support=0, xyBounds=0)
        for p in ps:
            if p['accepted']: continue
            key = 'weakSignal' if not p['shown'] else (
                ('support' if not p['inSupport'] else 'xyBounds' if not p['inBounds'] else 'heightAmbiguous') if family=='C'
                else 'heightAmbiguous' if p['heightAmbiguous'] else 'otherPosition')
            reasons[key] += 1
        require(sum(reasons.values()) == m['abstain'], 'Reason counts mismatch')
        m['rejectionReasons'] = reasons
    return m


def freeze_summary(out):
    report = json.loads((out/'frozen-before-training.json').read_bytes())
    expected = json.loads((ROOT/'evaluation/hover3_pass2_plan.json').read_bytes())['frozenModels']
    require(report['models'] == {k.replace('_air1','_air').replace('C_joint','C'):v for k,v in expected.items()}, 'Frozen models changed')
    data = report['predictions']; require(len(data)==1365, 'Wrong frozen evaluation count')
    result = {}
    for mode in ('primary','causal','offline'):
        selected = [r for r in data if r['mode']==mode]
        require(len(selected)==(819 if mode=='causal' else 273) and all(r['truth']=='air' and r['passID']==2 for r in selected), 'Wrong evaluation samples')
        result[mode] = {}
        for family in ('A','B','C','singleA','singleB'):
            m = summarize([r[family] for r in selected])
            if family in ('A','B','C'):
                m.update(correctAir=sum(r[family]['predicted']=='air' for r in selected),wrongContact=sum(r[family]['predicted']=='contact' for r in selected),abstain=sum(not r[family]['accepted'] for r in selected),
                    correctHeightAndXYWithin2p5MM=sum(r[family]['predicted']=='air' and r[family]['errorMM']<=2.5 for r in selected),
                    correctHeightAndXYWithin5MM=sum(r[family]['predicted']=='air' and r[family]['errorMM']<=5 for r in selected))
            result[mode][family] = m
    summary = dict(role='held_out_air_pass_evaluated_before_training',models=report['models'],queriesSHA256=report['queriesSHA256'],predictionSHA256=digest(out/'frozen-before-training.json'),metrics=result)
    write_preserving(out/'frozen-evaluation-summary.json', summary)


def build(out):
    plan = json.loads((ROOT/'evaluation/joint_mlp_air12_plan.json').read_bytes())
    require(digest(out/'frozen-evaluation-summary.json') == plan['frozenPreTrainingSummarySHA256'], 'Frozen evaluation must precede training')
    air = json.loads((out/'hover_observations.json').read_bytes())
    for combo in ('2','12'):
        passes = list(map(int,combo)); selected = [b for b in air if b['repetition'] in passes]
        for family, builder in [('A',build_a),('B',build_b)]:
            name = f'model_{family}_hover3_{combo}.json'; model = builder(selected,passes)
            for folder in (out/'models',ROOT/'evaluation/frozen',ROOT/'MagAir/Resources'):
                write_preserving(folder/name,model)


def summarize_all(out):
    files = {'1':out/'old-all.json','2':out/'air2-joint-all.json','12':out/'new-all.json'}
    reports = {k:json.loads(p.read_bytes()) for k,p in files.items()}
    resources = ROOT/'MagAir/Resources'
    for combo,report in reports.items():
        expected = {key:digest(resources/(name+'.json')) for key,name in {
            'A_contact13':'model_A_13', 'B_contact13':'model_B_13',
            'A_air':f'model_A_hover3_{combo}', 'B_air':f'model_B_hover3_{combo}',
            'C':f'joint_mlp_contact13_air{combo}'}.items()}
        require(report['models']==expected, 'Replay used the wrong model combination: '+combo)
    qhash = digest(out/'all-queries.json')
    require(all(r['queriesSHA256']==qhash for r in reports.values()), 'Different comparison inputs')
    require(all(len(r['predictions'])==5460 for r in reports.values()), 'Incomplete comparison')
    frozen = json.loads((out/'frozen-before-training.json').read_bytes())
    old2 = [r for r in reports['1']['predictions'] if r['truth']=='air' and r['passID']==2]
    require(old2 == frozen['predictions'], 'Original frozen results changed after fitting')
    joint = {}; single = {}
    for combo,report in reports.items():
        data = report['predictions']; single[combo] = {}; joint[combo] = {}
        for mode in ('primary','causal','offline'):
            s = [r for r in data if r['mode']==mode]
            single[combo][mode] = {}
            for pass_id in (1,2):
                air = [r for r in s if r['truth']=='air' and r['passID']==pass_id]
                single[combo][mode][str(pass_id)] = dict(role='training_replay' if str(pass_id) in combo else 'held_out_pass',
                    A=joint_metrics(air,'singleA'), B=joint_metrics(air,'singleB'))
            joint[combo][mode] = {}
            for state,passes in [('contact',(1,3)),('air',(1,2))]:
                for pass_id in passes:
                    selected = [r for r in s if r['truth']==state and r['passID']==pass_id]
                    role = 'held_out_pass' if state=='air' and str(pass_id) not in combo else 'training_replay'
                    joint[combo][mode][f'{state}{pass_id}'] = dict(role=role, **{f:joint_metrics(selected,f) for f in 'ABC'})
            joint[combo][mode]['air2_without_row11'] = {f:joint_metrics([r for r in s if r['truth']=='air' and r['passID']==2 and r['row']!=11],f) for f in 'ABC'}
    batches = json.loads((out/'hover_observations.json').read_bytes())
    def stats(v):
        return dict(median=float(np.median(v)),p95=float(np.percentile(v,95)),maximum=max(v))
    quality = {}
    for pass_id in (1,2):
        bs = [b for b in batches if b['repetition']==pass_id]
        quality[str(pass_id)] = dict(backgroundDriftUT=stats([b['driftUT'] for b in bs]),
            pointNoiseUT=stats([p['noiseUT'] for b in bs for p in b['points']]),
            rows=[dict(row=b['row'],driftUT=b['driftUT'],motionEvents=b['motionEvents'],excludedAttempts=b['excludedAttempts']) for b in bs])
    # Matched spatial test of extra air data, not an independent pass comparison.
    records,_ = load_records(out,(1,2)); held = {}
    for label,trained in [('1',OLD_C),('2',SECOND_C),('12',NEW_C)]:
        pred = []
        for fold in range(5):
            model = json.loads((trained/f'fold{fold+1}_model.json').read_bytes())
            test = [r for r in records if r['state']=='air' and r['passID']==2 and (r['row']-1)%5==fold]
            require(set(model['trainingTrialIDs']).isdisjoint(r['session']+'/'+r['trial'] for r in test),'Fold leakage')
            pred.extend(evaluate(model,test,'primary'))
        require(len(pred)==273, 'Incomplete fold evaluation')
        # Summarize expects both states; select only air after adding no fabricated samples.
        values = [p['positionErrorMM'] for p in pred]
        held[label] = dict(count=273,correct=sum(p['predicted']=='air' for p in pred),wrong=sum(p['predicted']=='contact' for p in pred),abstain=sum(not p['accepted'] for p in pred),
            medianXYErrorMM=float(np.median(values)),p95XYErrorMM=float(np.percentile(values,95)))
        write_preserving(out/f'C{label}-matched-row-holdout-air2.json',pred)
    result = dict(quality=quality,joint=joint,singleHeight=single,matchedCSpatialHoldoutAir2=held,
        comparisonFileSHA256={k:digest(p) for k,p in files.items()},
        limitations=['Final air12 models train on both air passes: no held-out air pass remains.',
            'Old->new scores on pass2 compare held-out evaluation against training replay; not independent improvement.',
            'Matched C row holdout withholds the same whole rows in both heights/passes; same-campaign spatial diagnostic only.',
            'New pass has only air labels; fresh contact precision/specificity/balanced accuracy cannot be measured.',
            'Offline mode uses future end background and is not a real-time algorithm.'])
    write_preserving(out/'summary-all-subsets.json',result)
    print(json.dumps(dict(quality=quality,matchedC=held,jointAir2={k:v['primary']['air2'] for k,v in joint.items()}),indent=2))


def bundle(out):
    summary = json.loads((out/'summary-all-subsets.json').read_bytes()); resources = ROOT/'MagAir/Resources'
    entries = []; parity = []
    for combo in ('1','2','12'):
        entry = dict(id='hover3_'+combo,passes=list(map(int,combo)),evaluations=[])
        predictions = json.loads((out/({'1':'old-all','2':'air2-joint-all','12':'new-all'}[combo]+'.json')).read_bytes())['predictions']
        for family,projector_class in [('A',ProjectorA),('B',ProjectorB)]:
            name=f'model_{family}_hover3_{combo}'; path=resources/(name+'.json'); model=json.loads(path.read_bytes())
            frozen=ROOT/'evaluation/frozen'/(f'hover3_pass1_{family}.json' if combo=='1' else name+'.json')
            require(path.read_bytes()==frozen.read_bytes(),'Model changed from frozen copy')
            entry['resource'+family]=name;entry['sha256'+family]=digest(path)
            projector=projector_class(model)
            # Independent Python parity, sampled uniformly across both passes and grid rows.
            cases=[r for r in predictions if r['truth']=='air' and r['mode']=='primary'][::7]
            for r in cases:
                p=projector.project(r['field']);swift=r['single'+family]
                require(math.dist(p['xy'],swift['xy'])<1e-8 and abs(p['residualUT']-swift['residualUT'])<1e-8 and p['accepted']==swift['accepted'], 'Swift/Python mismatch')
                parity.append(dict(combination=entry['id'],family=family,filteredDeltaUT=r['field'],**p))
        for test in (1,2):
            metrics=summary['singleHeight'][combo]['primary'][str(test)]
            entry['evaluations'].append(dict(testPass=test,role=metrics['role'],primaryA=metrics['A'],primaryB=metrics['B']))
        entries.append(entry)
    save(resources/'hover3_model_catalog.json',dict(version=1,defaultCombination='hover3_12',entries=entries,
        analysisSummarySHA256=digest(out/'summary-all-subsets.json'),scope='3mm position-only 1/2/12; cross-pass scores separated from training replay; final 12 has no independent pass.'))
    write_preserving(ROOT/'build/tests/hover3-repeat-parity.json',parity)
    export_neural(out)
    print('Bundled 3mm and joint 1/2/12, retaining all old weights;',len(parity),'Python parity cases')


def export_neural(out):
    resources = ROOT/'MagAir/Resources'
    for combo,trained in [('2',SECOND_C),('12',NEW_C)]:
        raw=(trained/'joint_mlp.json').read_bytes(); model=json.loads(raw)
        require(model['planSHA256']==digest(ROOT/f'evaluation/joint_mlp_air{combo}_plan.json'),'Wrong C plan')
        for key in ('trainingTrialIDs','sourceSessions'):
            expected=set(json.loads((resources/'model_A_13.json').read_bytes())[key]+json.loads((resources/f'model_A_hover3_{combo}.json').read_bytes())[key])
            require(set(model[key])==expected,'C source mismatch')
        for folder in (ROOT/'evaluation/frozen',resources):
            path=folder/f'joint_mlp_contact13_air{combo}.json'
            if path.exists():require(path.read_bytes()==raw,'Frozen C changed')
            else:path.write_bytes(raw)
        save(resources/f'joint_mlp_air{combo}_catalog.json',dict(version=1,resource=f'joint_mlp_contact13_air{combo}',sha256=hashlib.sha256(raw).hexdigest(),planSHA256=model['planSHA256']))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','freeze-summary','build','summarize','bundle','neural'])
    parser.add_argument('--out',type=Path,default=ROOT/'reports/hover3-20261125-pass2')
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    {'prepare':prepare,'freeze-summary':freeze_summary,'build':build,'summarize':summarize_all,'bundle':bundle,'neural':export_neural}[args.stage](args.out)
