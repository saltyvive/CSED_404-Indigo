"""Verify and bundle the frozen C weights; never silently overwrite a frozen model."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def bundle(report):
    raw=(report/'joint_mlp.json').read_bytes();model=json.loads(raw)
    summary=json.loads((report/'summary.json').read_bytes())
    digest=hashlib.sha256(raw).hexdigest()
    assert summary['modelSHA256']==digest and summary['independentAirRepeatValidation'] is False
    assert model['planSHA256']==hashlib.sha256((ROOT/'evaluation/joint_mlp_plan.json').read_bytes()).hexdigest()
    resources=ROOT/'MagAir/Resources'
    a=json.loads((resources/'model_A_13.json').read_bytes())
    b=json.loads((resources/'model_A_hover3_1.json').read_bytes())
    assert set(model['trainingTrialIDs'])==set(a['trainingTrialIDs']+b['trainingTrialIDs'])
    assert set(model['sourceSessions'])==set(a['sourceSessions']+b['sourceSessions'])
    assert [c['passes'] for c in model['conditions']]==[[1,3],[1]]
    assert len(model['supportFieldsUT'])==3276
    frozen=ROOT/'evaluation/frozen/joint_mlp_contact13_air1.json'
    if frozen.exists():
        assert frozen.read_bytes()==raw, 'Use a new version for different weights'
    else:
        frozen.write_bytes(raw)
    (resources/'joint_mlp_contact13_air1.json').write_bytes(raw)
    catalog=dict(version=1,resource='joint_mlp_contact13_air1',sha256=digest,planSHA256=model['planSHA256'])
    (resources/'joint_mlp_catalog.json').write_text(json.dumps(catalog,indent=2)+'\n')
    print('Frozen C bundle verified:',digest)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    bundle(p.parse_args().report)
