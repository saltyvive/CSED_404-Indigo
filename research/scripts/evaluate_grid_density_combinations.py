"""All training/evaluation pass subsets, with 25 exact uniform A-model grids."""
import argparse
import copy
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import statistics as st

from build_grid_model import Projector
from evaluate_grid_density import FastProjector, indices, summarize
from train_joint_mlp import ROOT, save


def key(passes):
    return ''.join(map(str, sorted(passes)))


def role(train, test):
    overlap = set(train) & set(test)
    if not overlap:
        return 'held_out_only'
    return 'same_pass_only' if set(test) <= set(train) else 'mixed'


def build(reference, batches, passes, nr, nc):
    if not passes or len(set(passes)) != len(passes) or not set(passes) <= {1, 2, 3}:
        raise ValueError('Select distinct training passes 1..3')
    rr, cc = indices(13, nr), indices(21, nc)
    chosen = [(b['repetition'], p) for b in batches if b['repetition'] in passes
              for p in b['points'] if p['row'] in rr and p['column'] in cc]
    expected = {(t, r, c) for t in passes for r in rr for c in cc}
    if len(chosen) != len(expected) or {(t, p['row'], p['column']) for t, p in chosen} != expected:
        raise ValueError('Missing or duplicate selected placement')
    lookup = {}
    for r in rr:
        for c in cc:
            vectors = [p['deltaUT'] for _, p in chosen if (p['row'], p['column']) == (r, c)]
            lookup[r, c] = [st.median(v[k] for v in vectors) for k in range(3)]
    model = copy.deepcopy(reference)
    model.pop('printedGridContext', None)
    model.update(xKnots=[(c-1)/20 for c in cc], yKnots=[(r-1)/12 for r in rr],
                 fieldsUT=[[lookup[r, c] for c in cc] for r in rr],
                 trainingTrialIDs=sorted(p['session']+'/'+p['trial'] for _, p in chosen),
                 sourceSessions=sorted({p['session'] for _, p in chosen}),
                 sourceSession=f'contact-{key(passes)}-density-{nr}x{nc}',
                 scope='Offline density/subset comparison. Evaluation overlap is labeled separately; not an app deployment.')
    model['densityContext'] = dict(trainingPasses=sorted(passes), rows=nr, columns=nc,
        positions=nr*nc, placements=len(chosen), selectedRows=rr, selectedColumns=cc,
        widthMM=50, heightMM=30, spacingXMM=50/(nc-1), spacingYMM=30/(nr-1))
    return model


def pooled_metrics(rows, train, test):
    selected = [r for r in rows if r['passID'] in test]
    result = summarize(selected)
    result.update(role=role(train, test), evaluationPasses=sorted(test),
        samePassPlacements=sum(r['passID'] in train for r in selected),
        heldOutPlacements=sum(r['passID'] not in train for r in selected))
    return result


def inventory(paths):
    return [dict(path=str(p.relative_to(ROOT)), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]


def run(out):
    if out.exists():
        raise ValueError('Use a fresh output directory')
    plan_path = ROOT/'evaluation/grid_density_combinations_plan.json'
    plan = json.loads(plan_path.read_bytes()); source = ROOT/plan['source']
    batches = json.loads(source.read_bytes())
    assert len(batches) == 39 and {(b['repetition'], b['row']) for b in batches} == {(p,r) for p in (1,2,3) for r in range(1,14)}
    assert all(b['pose']['tipContact'] and b['pose']['tipHeightMM'] == 0 and
               [b['pose'][k] for k in ('phiDegrees','thetaDegrees','alphaDegrees')] == [0,90,0] for b in batches)
    items = sorted([(b,p) for b in batches for p in b['points']], key=lambda bp:(bp[0]['repetition'],bp[1]['row'],bp[1]['column']))
    assert len(items) == 819 and len({(b['repetition'],p['row'],p['column']) for b,p in items}) == 819
    queries = [[v-s for v,s in zip(p['raw'],b['before']['raw'])] for b,p in items]
    refs = {key(t):ROOT/plan['referenceModels'].format(combination=key(t)) for t in plan['trainingSets']}
    out.mkdir(parents=True); (out/'models').mkdir(); save(out/'plan.json',plan)
    save(out/'source_inventory.json',inventory([plan_path,source,*refs.values(),Path(__file__),ROOT/'scripts/evaluate_grid_density.py']))
    results = {}; predictions = {}; parity = []; full_parity = 0
    for train in plan['trainingSets']:
        combo = key(train); reference = json.loads(refs[combo].read_bytes())
        assert reference['printedGridContext']['passes'] == sorted(train)
        for nr in plan['rowCounts']:
            for nc in plan['columnCounts']:
                grid = f'{nr}x{nc}'; name = f'A{combo}_{grid}'
                model = build(reference,batches,train,nr,nc)
                save(out/'models'/f'{name}.json',model)
                projector = FastProjector(model); pred = projector.project_many(queries)
                fitted = set(model['trainingTrialIDs']); rows = []
                for (b,p),f,pr in zip(items,queries,pred):
                    rows.append(dict(passID=b['repetition'],row=p['row'],column=p['column'],session=p['session'],trial=p['trial'],
                        targetXY=p['xy'],field=f,fittedPlacement=p['session']+'/'+p['trial'] in fitted,
                        errorMM=math.hypot(50*(pr['xy'][0]-p['xy'][0]),30*(pr['xy'][1]-p['xy'][1])),**pr))
                for test in (1,2,3):
                    subset = [r for r in rows if r['passID']==test]
                    assert len(subset)==273 and sum(r['fittedPlacement'] for r in subset)==(nr*nc if test in train else 0)
                    if test not in train:
                        assert not set(model['sourceSessions']) & {r['session'] for r in subset}
                groups = {key(test):pooled_metrics(rows,train,test) for test in plan['evaluationSets']}
                held = [p for p in (1,2,3) if p not in train]
                held_rows = [r for r in rows if r['passID'] in held]
                results[name] = dict(trainingPasses=train,grid=grid,rows=nr,columns=nc,trainingPoints=nr*nc,
                    trainingPlacements=len(train)*nr*nc,groups=groups,heldOutKey=key(held) if held else None,
                    heldOutRegions={label:summarize([r for r in held_rows if ((r['row'] in (1,13) or r['column'] in (1,21))==boundary)])
                        for label,boundary in [('boundary',True),('interior',False)]} if held else None)
                predictions[name] = rows; save(out/f'{name}-predictions.json',rows)
                slow = Projector(model)
                for f in (queries[17+273*((max(train))%3)],model['fieldsUT'][0][0]):
                    a = slow.project(f); b = projector.project_many([f])[0]
                    assert a['xy']==b['xy'] and a['accepted']==b['accepted'] and a['ambiguous']==b['ambiguous']
                    assert abs(a['residualUT']-b['residualUT'])<1e-9
                parity.append(dict(model=name,checkedInputs=2))
                if (nr,nc)==(13,21):
                    assert model['fieldsUT']==reference['fieldsUT']
                    assert set(model['trainingTrialIDs'])==set(reference['trainingTrialIDs'])
                    for test in (1,2,3):
                        old_path = source.parent/f'A{combo}-test{test}-predictions.json'
                        old = {(r['session'],r['trial']):r for r in json.loads(old_path.read_bytes())['primary']}
                        for r in rows:
                            if r['passID']!=test: continue
                            a=old[r['session'],r['trial']]
                            assert r['xy']==a['xy'] and r['accepted']==a['accepted'] and abs(r['errorMM']-a['errorMM'])<1e-10
                            full_parity+=1
                report = groups[key(held)] if held else groups['123']
                print(f'{name}: {"held out "+key(held) if held else "same-pass 123"}, mean {report["meanRadialErrorMM"]:.3f} mm, <=2.5 {report["within2p5Rate"]:.1%}',flush=True)
    main = [f'{r}x{c}' for r,c in plan['presentationGrids']]
    selection = {}
    for test in plan['evaluationSets']:
        test_key = key(test)
        eligible = [(name,m) for name,m in results.items() if m['groups'][test_key]['role']=='held_out_only']
        if not eligible: continue
        best_mean = min(eligible,key=lambda nm:(nm[1]['groups'][test_key]['meanRadialErrorMM'],nm[1]['trainingPlacements'],nm[0]))[0]
        best_rate = min(eligible,key=lambda nm:(-nm[1]['groups'][test_key]['within2p5Rate'],nm[1]['groups'][test_key]['meanRadialErrorMM'],nm[0]))[0]
        selection[test_key] = dict(bestMeanModel=best_mean,bestWithin2p5Model=best_rate)
    matched = {}
    for grid in (f'{r}x{c}' for r in plan['rowCounts'] for c in plan['columnCounts']):
        singles=[];pairs=[];folds=[]
        for test in (1,2,3):
            others=[t for t in (1,2,3) if t!=test]
            s=[r for t in others for r in predictions[f'A{t}_{grid}'] if r['passID']==test]
            p=[r for r in predictions[f'A{key(others)}_{grid}'] if r['passID']==test]
            singles.extend(s);pairs.extend(p)
            folds.append(dict(testPass=test,singlePooled=summarize(s),pair=summarize(p)))
        matched[grid]=dict(singlePooled=summarize(singles),pairPooled=summarize(pairs),folds=folds)
    changes = {}
    for train in plan['trainingSets']:
        held=[p for p in (1,2,3) if p not in train]
        if not held: continue
        combo=key(train);changes[combo]={}
        for a,b in [('3x3','13x21'),('4x6','7x11'),('7x11','13x21')]:
            errors=[]
            for r in range(1,14):
                for c in range(1,22):
                    def at(g):
                        return st.mean(p['errorMM'] for p in predictions[f'A{combo}_{g}'] if p['passID'] in held and p['row']==r and p['column']==c)
                    errors.append(at(a)-at(b))
            changes[combo][a+'->'+b]=dict(improved=sum(e>1e-9 for e in errors),unchanged=sum(abs(e)<=1e-9 for e in errors),
                worsened=sum(e< -1e-9 for e in errors),meanReductionMM=st.mean(errors))
    summary=dict(models=results,presentationOrder=main,selectionByHeldOutEvaluation=selection,matchedLearningCurves=matched,
        perLocationChanges=changes,parity=parity,fullDensityReplayParityCount=full_parity,
        modelCount=len(results),evaluationCount=sum(len(m['groups']) for m in results.values()),predictionCount=sum(map(len,predictions.values())))
    assert (summary['modelCount'],summary['evaluationCount'],summary['predictionCount'],full_parity)==(175,1225,143325,5733)
    save(out/'summary.json',summary)
    write_tables(out,summary,plan)


ROLE_KO={'held_out_only':'학습 제외','same_pass_only':'같은 회차','mixed':'혼합'}


def write_tables(out,s,plan):
    table=[]
    for name,m in s['models'].items():
        for t,g in m['groups'].items():
            table.append(dict(model=name,trainingPasses=key(m['trainingPasses']),grid=m['grid'],trainingPoints=m['trainingPoints'],
                trainingPlacements=m['trainingPlacements'],evaluationPasses=t,**{k:v for k,v in g.items() if k!='evaluationPasses'}))
    with (out/'all_1225_results.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    lines=['# 학습 회차·격자 밀도·평가 묶음 전체 비교','',
        '각 셀: 평균 위치 오차 mm / 2.5 mm 이내 비율. 1개 회차=273개, 2개=546개, 3개=819개 평가 배치.','',
        '학습 제외: 학습과 평가 회차가 겹치지 않음. 같은 회차: 평가 회차가 모두 학습에 포함. 혼합: 두 종류를 합산.','']
    parts=['<!doctype html><html lang="ko"><meta charset="utf-8"><title>격자·회차 전체 비교</title><style>body{font-family:system-ui;margin:32px;color:#20364b}table{border-collapse:collapse;margin-bottom:30px;font-variant-numeric:tabular-nums}td,th{border:1px solid #d7e0e6;padding:8px 12px;text-align:right;white-space:nowrap}th{background:#edf2f6;position:sticky;top:0}.held_out_only{background:#e6f5ee}.mixed{background:#fff3d9}.same_pass_only{color:#69798a;background:#eef0f3}small{display:block;font-size:11px;margin-top:3px}h2{margin-top:45px}</style><h1>175개 모델 × 7개 평가 묶음</h1><p>각 셀: 평균 오차 mm / 2.5 mm 이내 비율. 표시는 보류된 후보도 포함.</p><p>초록=학습 제외 / 회색=같은 회차 / 노랑=혼합. 평가 묶음은 자기장을 평균하지 않고 모든 점 예측을 합산합니다.</p>']
    for train in plan['trainingSets']:
        combo=key(train);heading='학습 '+ '+'.join(map(str,train))+'회차'
        lines.extend(['## '+heading,'','| 격자 | 점 수 | '+' | '.join('+'.join(map(str,t))+' 평가' for t in plan['evaluationSets'])+' |',
            '|---|---:|'+ '|'.join(['---:']*7)+'|'])
        parts.append('<h2>'+heading+'</h2><table><tr><th>행×열 / 점 수</th>'+''.join('<th>'+ '+'.join(map(str,t))+' 평가</th>' for t in plan['evaluationSets'])+'</tr>')
        for nr in plan['rowCounts']:
            for nc in plan['columnCounts']:
                grid=f'{nr}x{nc}';m=s['models'][f'A{combo}_{grid}'];cells=[]
                parts.append(f'<tr><th>{nr}×{nc} / {nr*nc}점</th>')
                for t in plan['evaluationSets']:
                    g=m['groups'][key(t)];cell=f'{g["meanRadialErrorMM"]:.3f} / {g["within2p5Rate"]:.1%}'
                    cells.append(cell+' ('+ROLE_KO[g['role']]+')')
                    parts.append(f'<td class="{g["role"]}">{html.escape(cell)}<small>{ROLE_KO[g["role"]]} · {g["count"]}개</small></td>')
                parts.append('</tr>')
                if grid in s['presentationOrder']:lines.append(f'| {nr}×{nc} | {nr*nc} | '+' | '.join(cells)+' |')
        parts.append('</table>');lines.append('')
    (out/'presentation_tables.md').write_text('\n'.join(lines)+'\n')
    (out/'all_combinations.html').write_text('\n'.join(parts)+'</html>')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
