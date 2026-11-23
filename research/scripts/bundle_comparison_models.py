"""Bundle the completed comparison's 14 models, hashes and concise evaluation ledger."""
import argparse
import hashlib
import json
from pathlib import Path
from compare_pass_combinations import ROOT, save
from build_printed_grid_model import require


def bundle(report):
    summary=json.loads((report/'summary.json').read_text())
    lookup={(m['family'],m['combination']):m for m in summary['models']}
    entries=[];resources=ROOT/'MagAir/Resources'
    for combo in ('1','2','3','12','23','13','123'):
        a,b=(lookup[f,combo] for f in ('A','B'))
        entry=dict(id=combo,passes=a['trainingPasses'],evaluations=[])
        for family,model in [('A',a),('B',b)]:
            raw=(report/'models'/model['modelFile']).read_bytes()
            require(hashlib.sha256(raw).hexdigest()==model['modelSHA256'],'Model hash mismatch')
            name='model_'+family+'_'+combo
            (resources/(name+'.json')).write_bytes(raw)
            entry['resource'+family]=name;entry['sha256'+family]=model['modelSHA256']
        for ea,eb in zip(a['evaluations'],b['evaluations']):
            require(ea['testPass']==eb['testPass'] and ea['role']==eb['role'],'Evaluation pairing mismatch')
            entry['evaluations'].append(dict(testPass=ea['testPass'],role=ea['role'],primaryA=ea['primary'],primaryB=eb['primary']))
        entries.append(entry)
    save(resources/'model_catalog.json',dict(version=1,defaultCombination='123',entries=entries))
    # Keep portable default aliases and immutable final snapshots.
    for family,alias,snapshot in [('A','grid_model.json','pass1_2_3.json'),('B','knn_model.json','knn_pass1_2_3.json')]:
        raw=(resources/f'model_{family}_123.json').read_bytes()
        (resources/alias).write_bytes(raw)
        target=ROOT/'evaluation/frozen'/snapshot
        require(not target.exists() or target.read_bytes()==raw,'Do not overwrite a frozen model')
        target.write_bytes(raw)
    print('Bundled 7 A/B pairs; default 123, held-out and training replay kept separate.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    bundle(p.parse_args().report)
