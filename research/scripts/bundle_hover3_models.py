"""Bundle frozen 3mm A/B models and their explicitly non-independent replay metrics."""
import argparse
import hashlib
import json
from pathlib import Path

from build_printed_grid_model import require
from compare_pass_combinations import ROOT, save


def bundle(report):
    summary_bytes=(report/'summary.json').read_bytes()
    summary=json.loads(summary_bytes)
    require(summary['independentAirRepeatValidation'] is False, 'Unexpected evaluation scope')
    entry=dict(id='hover3_1',passes=[1],evaluations=[])
    models=[]; resources=ROOT/'MagAir/Resources'
    for family in 'AB':
        source=ROOT/'evaluation/frozen'/f'hover3_pass1_{family}.json'
        raw=source.read_bytes()
        require(raw==(report/'models'/source.name).read_bytes(), 'Frozen model differs from analyzed model')
        model=json.loads(raw); context=model['printedGridContext']; pose=context['pose']
        require(context['passes']==[1] and pose['tipHeightMM']==3 and not pose['tipContact'] and
                pose['phiDegrees']==0 and pose['thetaDegrees']==90 and pose['alphaDegrees']==0, 'Wrong model condition')
        models.append(model)
        name=f'model_{family}_hover3_1'
        (resources/(name+'.json')).write_bytes(raw)
        entry['resource'+family]=name
        entry['sha256'+family]=hashlib.sha256(raw).hexdigest()
    require(models[0]['printedGridContext']==models[1]['printedGridContext'] and
            set(models[0]['trainingTrialIDs'])==set(models[1]['trainingTrialIDs']), 'A/B source mismatch')
    metrics=[summary['positionReplay']['air_'+family+'_before'] for family in 'AB']
    require(all(m['role']=='training_replay' and m['count']==273 for m in metrics), 'Not training replay')
    entry['evaluations']=[dict(testPass=1,role='training_replay',primaryA=metrics[0],primaryB=metrics[1])]
    save(resources/'hover3_model_catalog.json',dict(version=1,defaultCombination='hover3_1',entries=[entry],
        analysisSummarySHA256=hashlib.sha256(summary_bytes).hexdigest(),
        scope='Fixed 3mm position mapping only; no automatic height/contact classification; one training pass, no independent repeat.'))
    cases=[]
    batches=json.loads((report/'hover_observations.json').read_bytes())
    for family in 'AB':
        for mode in ('before','linear'):
            for p in json.loads((report/f'air_{family}_{mode}-position-predictions.json').read_bytes()):
                batch=next(b for b in batches if b['session']==p['session'])
                point=next(q for q in batch['points'] if q['trial']==p['trial'])
                field=point['deltaUT'] if mode=='linear' else [v-b for v,b in zip(point['raw'],batch['before']['raw'])]
                cases.append(dict(combination='hover3_1',family=family,filteredDeltaUT=field,
                    **{key:p[key] for key in ('xy','residualUT','otherLocationResidualUT','shown','ambiguous','accepted')}))
    target=ROOT/'build/tests/hover3-model-parity.json';target.parent.mkdir(parents=True,exist_ok=True)
    save(target,cases)
    print('Bundled frozen 3mm A/B; original 14 contact models unchanged.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    bundle(parser.parse_args().report)
