"""Infer experimental D from a background-subtracted 3-axis magnetic vector."""
import argparse
import json
from pathlib import Path
from experiment_model_d import ROOT, predict


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',type=Path,default=ROOT/'evaluation/experimental/model_D_contact13_air12.json')
    p.add_argument('--field',type=float,nargs=3,required=True,metavar=('BX_UT','BY_UT','BZ_UT'))
    args=p.parse_args();model=json.loads(args.model.read_bytes());raw,state=predict(model,[args.field])
    print(json.dumps(dict(state={-1:'air_3mm',0:'uncertain',1:'contact_0mm'}[int(state[0])],
        xyMM=(raw['xy'][0]*[50,30]).tolist(),svmScore=float(raw['score'][0]),
        supportUT=float(raw['support'][0]),scope=model['scope']),ensure_ascii=False,indent=2))
