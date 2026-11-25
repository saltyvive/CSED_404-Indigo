"""Exact uniform anchor subsampling of contact pass1, test all three 273-point passes."""
import argparse
import copy
import hashlib
import html
import json
import math
from pathlib import Path
import numpy as np
from build_grid_model import field, Projector
from train_joint_mlp import ROOT, save
from evaluate_printed_pass import metrics as legacy_metrics


def indices(total, count):
    if count<3 or (total-1)%(count-1):
        raise ValueError('Require exact uniform measured coordinates including both boundaries')
    return list(range(1,total+1,(total-1)//(count-1)))


def build(reference, batches, rows, columns):
    rr,cc=indices(13,rows),indices(21,columns)
    points=[p for b in batches if b['repetition']==1 for p in b['points'] if p['row'] in rr and p['column'] in cc]
    lookup={(p['row'],p['column']):p for p in points}
    assert len(lookup)==rows*columns
    model=copy.deepcopy(reference)
    model.update(xKnots=[(c-1)/20 for c in cc],yKnots=[(r-1)/12 for r in rr],
        fieldsUT=[[lookup[r,c]['deltaUT'] for c in cc] for r in rr],
        trainingTrialIDs=sorted(p['session']+'/'+p['trial'] for p in points),sourceSessions=sorted({p['session'] for p in points}),
        sourceSession=f'contact-pass1-density-{rows}x{columns}',
        scope='Offline exact uniform anchor-count ablation. Same A1 parameters, selected pass1 fields only; pass1 evaluation is not independent.')
    # Do not claim compatibility with the app's hard-coded 21x13 context schema.
    model.pop('printedGridContext',None)
    model['densityContext']=dict(trainingPass=1,rows=rows,columns=columns,positions=len(points),selectedRows=rr,selectedColumns=cc,
        widthMM=50,heightMM=30,spacingXMM=50/(columns-1),spacingYMM=30/(rows-1))
    return model


class FastProjector:
    """Vectorized exact same search, tie order and ambiguity test as existing A."""
    def __init__(self,model):
        self.model=model;n=model['searchSteps']
        self.xy=np.array([(i/n,j/n) for j in range(n+1) for i in range(n+1)])
        self.fields=np.array([field(model,x,y) for x,y in self.xy])
        self.minimum=max(3,.2*min(math.hypot(*f) for f in self.fields))

    def project_many(self,values):
        q=np.array(values,dtype=float)
        if q.ndim!=2 or q.shape[1]!=3 or not np.isfinite(q).all():raise ValueError('Finite N x 3 magnetic inputs required')
        result=[]
        for start in range(0,len(q),48):
            x=q[start:start+48];delta=x[:,None,:]-self.fields[None,:,:]
            ds=np.sum(delta*delta,axis=2);best=np.argmin(ds,axis=1);xy=self.xy[best]
            spatial=np.hypot(self.xy[None,:,0]-xy[:,None,0],self.xy[None,:,1]-xy[:,None,1])
            other=np.sqrt(np.where(spatial>=self.model['ambiguityDistance'],ds,np.inf).min(axis=1))
            residual=np.sqrt(ds[np.arange(len(x)),best])
            for f,p,res,oth in zip(x,xy,residual,other):
                signal=math.hypot(*f);ambiguous=bool(oth<=res+self.model['ambiguityMarginUT'])
                result.append(dict(xy=p.tolist(),residualUT=float(res),otherLocationResidualUT=float(oth),signalUT=signal,
                    shown=signal>=self.minimum,ambiguous=ambiguous,
                    accepted=bool(signal>=self.minimum and res<=self.model['residualLimitUT'] and not ambiguous)))
        return result


def summarize(rows):
    m=legacy_metrics(rows)
    m.update(within2p5Rate=sum(r['errorMM']<=2.5 for r in rows)/len(rows),within5Rate=sum(r['errorMM']<=5 for r in rows)/len(rows),
        fittedPlacements=sum(r['fittedPlacement'] for r in rows))
    return m


def run(out):
    if out.exists():raise ValueError('Use a fresh output directory')
    plan_path=ROOT/'evaluation/grid_density_plan.json';plan=json.loads(plan_path.read_bytes())
    source=ROOT/plan['source'];reference_path=ROOT/plan['referenceModel']
    batches=json.loads(source.read_bytes());reference=json.loads(reference_path.read_bytes())
    assert len(batches)==39 and {(b['repetition'],b['row']) for b in batches}=={(p,r) for p in (1,2,3) for r in range(1,14)}
    assert all(b['pose']['tipContact'] and b['pose']['tipHeightMM']==0 for b in batches)
    assert all([b['pose'][k] for k in ('phiDegrees','thetaDegrees','alphaDegrees')]==[0,90,0] for b in batches)
    out.mkdir(parents=True);(out/'models').mkdir();save(out/'plan.json',plan)
    save(out/'source_inventory.json',[dict(path=str(p.relative_to(ROOT)),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (plan_path,source,reference_path)])
    items=sorted([(b,p) for b in batches for p in b['points']],key=lambda bp:(bp[0]['repetition'],bp[1]['row'],bp[1]['column']))
    assert len(items)==819
    queries=[[v-s for v,s in zip(p['raw'],b['before']['raw'])] for b,p in items]
    results={};predictions={};parity=[]
    for nr in plan['rowCounts']:
        for nc in plan['columnCounts']:
            label=f'{nr}x{nc}';model=build(reference,batches,nr,nc)
            if (nr,nc)==(13,21):
                assert model['fieldsUT']==reference['fieldsUT']
                assert set(model['trainingTrialIDs'])==set(reference['trainingTrialIDs'])
            save(out/'models'/f'A1_{label}.json',model)
            projector=FastProjector(model);pred=projector.project_many(queries);fitted=set(model['trainingTrialIDs'])
            rows=[]
            for (b,p),f,pr in zip(items,queries,pred):
                rows.append(dict(passID=b['repetition'],row=p['row'],column=p['column'],session=p['session'],trial=p['trial'],targetXY=p['xy'],field=f,
                    fittedPlacement=p['session']+'/'+p['trial'] in fitted,
                    errorMM=math.hypot(50*(pr['xy'][0]-p['xy'][0]),30*(pr['xy'][1]-p['xy'][1])),**pr))
            predictions[label]=rows
            result=dict(rows=nr,columns=nc,trainingPoints=nr*nc,spacingXMM=50/(nc-1),spacingYMM=30/(nr-1),
                passes={str(p):summarize([r for r in rows if r['passID']==p]) for p in (1,2,3)},
                heldOut23=summarize([r for r in rows if r['passID'] in (2,3)]))
            for p in (1,2,3):
                subset=[r for r in rows if r['passID']==p]
                assert len(subset)==273 and sum(r['fittedPlacement'] for r in subset)==(nr*nc if p==1 else 0)
                if p!=1:assert not set(model['sourceSessions'])&{r['session'] for r in subset}
            results[label]=result
            save(out/(label+'-predictions.json'),rows)
            # Compare an unseen-pass vector and a retained anchor with the literal old Python estimator.
            slow=Projector(model)
            anchor=np.array(model['fieldsUT'][0][0]).tolist()
            for f in [queries[273+17],anchor]:
                a=slow.project(f);b=projector.project_many([f])[0]
                assert a['xy']==b['xy'] and a['accepted']==b['accepted'] and a['ambiguous']==b['ambiguous']
                assert abs(a['residualUT']-b['residualUT'])<1e-9
            parity.append(dict(grid=label,checkedInputs=2))
            print(label,[(p,round(result['passes'][str(p)]['meanRadialErrorMM'],3),round(100*result['passes'][str(p)]['within2p5Rate'],1)) for p in (1,2,3)],flush=True)
    # Full-density predictions must reproduce the archived A1 all-pass replay, not just its model.
    old_dir=source.parent
    for p in (1,2,3):
        old=json.loads((old_dir/f'A1-test{p}-predictions.json').read_bytes())['primary']
        lookup={(r['session'],r['trial']):r for r in old}
        for r in predictions['13x21']:
            if r['passID']!=p:continue
            previous=lookup[r['session'],r['trial']]
            assert r['xy']==previous['xy'] and r['accepted']==previous['accepted']
            assert abs(r['errorMM']-previous['errorMM'])<1e-10
    main=[f'{r}x{c}' for r,c in plan['presentationGrids']];changes={}
    for a,b in zip(main,main[1:]):
        aa,bb=predictions[a],predictions[b];groups={}
        for p in (1,2,3):
            diff=np.array([u['errorMM']-v['errorMM'] for u,v in zip(aa,bb) if u['passID']==p])
            groups[str(p)]=dict(improved=int(np.sum(diff>1e-9)),unchanged=int(np.sum(np.abs(diff)<=1e-9)),worsened=int(np.sum(diff<-1e-9)),meanReductionMM=float(diff.mean()))
        changes[a+'->'+b]=groups
    spatial={}
    for label,rows in predictions.items():
        spatial[label]=dict(perRow={str(i):summarize([r for r in rows if r['passID'] in (2,3) and r['row']==i]) for i in range(1,14)},
            perRegion={name:summarize([r for r in rows if r['passID'] in (2,3) and ((r['row'] in (1,13) or r['column'] in (1,21))==boundary)]) for name,boundary in [('boundary',True),('interior',False)]})
    summary=dict(models=results,presentationOrder=main,changes=changes,spatial=spatial,parity=parity,fullDensityReplayParityCount=819)
    save(out/'summary.json',summary)
    write_tables(out,summary,predictions)


def write_tables(out,summary,predictions):
    grids=summary['presentationOrder'];lines=['# 접촉 1회차 · 격자 밀도 비교','',
        '행×열. 각 셀은 평균 위치 오차(mm) / 2.5 mm 이내 비율. 모든 회차는 273점 전체 평가. 1회차는 학습 자료와 겹침.','',
        '| 학습 격자 | 점 수 | 평가 1회차 | 평가 2회차 | 평가 3회차 |',
        '|---|---:|---:|---:|---:|']
    for g in grids:
        m=summary['models'][g];cells=[f"{m['passes'][str(p)]['meanRadialErrorMM']:.3f} / {100*m['passes'][str(p)]['within2p5Rate']:.1f}%" for p in (1,2,3)]
        lines.append(f"| {g.replace('x','×')} | {m['trainingPoints']} | "+' | '.join(cells)+' |')
    (out/'presentation_table.md').write_text('\n'.join(lines)+'\n')
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>격자 밀도별 273개 위치 오차</title><style>body{font-family:system-ui;margin:32px;color:#182b42}table{border-collapse:collapse;font-variant-numeric:tabular-nums}td,th{padding:6px 12px;border:1px solid #dce3e9;text-align:right}th{position:sticky;top:0;background:#e7f1f5}.good{background:#e7f4ed}.bad{background:#fbeae7}summary{font-size:22px;margin:24px 0}a{margin-right:16px}</style>',
        '<h1>격자 밀도별 실제 위치 오차</h1><p>접촉 1회차만 학습. 셀 단위 mm. 초록: 오차 ≤ 2.5 mm. 빨강: 오차 &gt; 5 mm. 1회차에는 학습 배치가 포함됩니다.</p>']
    for p in (1,2,3):
        parts.append(f'<details open><summary>평가 {p}회차 · 273점</summary><table><tr><th>행</th><th>열</th>'+''.join(f'<th>{html.escape(g)}</th>' for g in grids)+'</tr>')
        lookup={g:{(r['row'],r['column']):r for r in predictions[g] if r['passID']==p} for g in grids}
        for row in range(1,14):
            for col in range(1,22):
                parts.append(f'<tr><td>{row}</td><td>{col}</td>'+''.join(f'<td class="{"good" if lookup[g][row,col]["errorMM"]<=2.5 else "bad" if lookup[g][row,col]["errorMM"]>5 else ""}">{lookup[g][row,col]["errorMM"]:.3f}</td>' for g in grids)+'</tr>')
        parts.append('</table></details>')
    (out/'all_273_positions.html').write_text('\n'.join(parts)+'</html>')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);args=p.parse_args();run(args.out)
