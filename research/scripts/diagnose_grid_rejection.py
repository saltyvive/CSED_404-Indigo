"""Post-hoc spatial rejection diagnosis; no model or threshold changes."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics as st

from build_grid_model import Projector as AProjector
from build_knn_model import Projector as BProjector
from build_printed_grid_model import require
from compare_pass_combinations import save


def roi(row,col): return 4 <= row <= 10 and 14 <= col <= 21


def reasons(prediction, limit):
    return dict(rejected=not prediction['accepted'], ambiguous=prediction['ambiguous'],
                weak=not prediction['shown'], highResidual=prediction['residualUT'] > limit)


def aggregate(points):
    return dict(count=len(points),**{key:sum(p[key] for p in points) for key in ('rejected','ambiguous','weak','highResidual')})


def competing_location(projector, field):
    pred=projector.project(field);x,y=pred['xy']
    other=min((p for p in projector.candidates if math.hypot(p[0]-x,p[1]-y)>=projector.model['ambiguityDistance']),
              key=lambda p:math.dist(p[2],field))
    return dict(inputUT=field,prediction=pred,competingXY=list(other[:2]),competingFieldUT=other[2],
                separationMM=math.hypot(50*(x-other[0]),30*(y-other[1])),
                ambiguityGapUT=pred['otherLocationResidualUT']-pred['residualUT'])


def gradient_diagnosis(batches):
    lookup={(b['repetition'],p['row'],p['column']):(p,b) for b in batches for p in b['points']}
    def field(pass_id,row,col,mode):
        p,b=lookup[pass_id,row,col]
        return p['deltaUT'] if mode=='linear' else [v-z for v,z in zip(p['raw'],b[mode]['raw'])]
    results={}
    for mode in ('linear','before','after'):
        rows=[]
        for row in range(1,13):
            cosines=[]
            for col in range(1,22):
                g={p:[field(p,row+1,col,mode)[a]-field(p,row,col,mode)[a] for a in range(3)] for p in (1,2,3)}
                reference=[(x+y)/2 for x,y in zip(g[1],g[3])]
                cosine=sum(x*y for x,y in zip(reference,g[2]))/(math.hypot(*reference)*math.hypot(*g[2]))
                cosines.append(cosine)
            rows.append(dict(fromRow=row,toRow=row+1,oppositeColumns=[i+1 for i,c in enumerate(cosines) if c<0],
                             cosines=cosines,rightMiddleMedianCosine=st.median(cosines[13:])))
        results[mode]=rows
    return results


def live_diagnosis(root,catalog):
    sessions=[];inventory=[]
    for path in sorted(root.glob('*.metadata.json')):
        meta=json.loads(path.read_text())
        if 'trainingCombination' not in meta:continue
        stem=path.name.removesuffix('.metadata.json');combo=meta['trainingCombination']
        entry=next(e for e in catalog['entries'] if e['id']==combo)
        require(meta['modelASHA256']==entry['sha256A'] and meta['modelBSHA256']==entry['sha256B'],
                'Live metadata/model mismatch')
        for suffix,key in [('.model.json','sha256A'),('.knn-model.json','sha256B')]:
            require(hashlib.sha256((root/(stem+suffix)).read_bytes()).hexdigest()==entry[key],'Unknown live model snapshot')
        data=list(csv.DictReader((root/(stem+'.csv')).open()))
        require(all(r['training_combination']==combo for r in data),'Live CSV combination mismatch')
        end=root/(stem+'.end.json');stats=[]
        for family,prefix in [('A',''),('B','knn_')]:
            viewed=[r for r in data if r['viewed_model'].startswith(family)]
            if not viewed:continue
            visible=[r for r in viewed if r[prefix+'candidate_shown']=='1']
            fit=[r for r in visible if float(r[prefix+'residual_uT'])<=float(r[prefix+'residual_limit_uT'])]
            ambiguity_only=[r for r in fit if r[prefix+'ambiguous']=='1']
            stats.append(dict(family=family,frames=len(viewed),candidateShown=len(visible),signalAndResidualPass=len(fit),
                              ambiguityOnly=len(ambiguity_only),accepted=sum(r[prefix+'accepted']=='1' for r in viewed),
                              ambiguousEstimateMedianXY=[st.median(float(r[prefix+'estimated_'+a]) for r in ambiguity_only) for a in ('x','y')] if ambiguity_only else None))
        examples=[]
        if any(s['family']=='A' and s['ambiguityOnly'] for s in stats):
            candidates=[r for r in data if r['viewed_model'].startswith('A') and r['candidate_shown']=='1' and
                        r['ambiguous']=='1' and float(r['residual_uT'])<=float(r['residual_limit_uT']) and
                        float(r['estimated_x'])>.65 and .25<float(r['estimated_y'])<.85]
            if candidates:
                r=candidates[len(candidates)//2];projector=AProjector(json.loads((root/(stem+'.model.json')).read_text()))
                examples.append(dict(timestamp=float(r['timestamp_s']),**competing_location(projector,[float(r['filtered_delta_'+a+'_uT']) for a in ('x','y','z')])))
        sessions.append(dict(id=stem,combination=combo,end=json.loads(end.read_text()) if end.exists() else None,
                             status='closed' if end.exists() else 'open_snapshot',stats=stats,examples=examples))
        for file in sorted(root.glob(stem+'.*')):
            inventory.append(dict(file=file.name,bytes=file.stat().st_size,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    return sessions,inventory


def draw_maps(models,path):
    colors=['#f1f5f9','#fed7aa','#fb923c','#c2410c']
    svg=['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="1100" viewBox="0 0 1100 1100">',
         '<rect width="1100" height="1100" fill="white"/>',
         '<style>text{font-family:Arial,sans-serif;fill:#172033}</style>',
         '<text x="35" y="36" font-size="24" font-weight="bold">Spatial rejection: A / B x seven training combinations</text>',
         '<text x="35" y="63" font-size="15">Known target locations; all 3 passes replayed (includes training data). Diagnosis, not held-out accuracy.</text>']
    for i,color in enumerate(colors):
        svg += [f'<rect x="{35+210*i}" y="80" width="22" height="18" fill="{color}" stroke="#94a3b8"/>',
                f'<text x="{65+210*i}" y="94" font-size="14">{i}/3 placements rejected</text>']
    for k,combo in enumerate(['1','2','3','12','23','13','123']):
        for column,family in enumerate(['A','B']):
            m=next(m for m in models if m['family']==family and m['combination']==combo)
            slot=column*8+k
            left=45+(slot%4)*270;top=155+(slot//4)*230;w=10;h=10
            svg.append(f'<text x="{left}" y="{top-20}" font-size="16" font-weight="bold">{family}{combo} - {m["allReplay"]["rejected"]}/819 rejected</text>')
            for c in [1,11,21]:svg.append(f'<text x="{left+(c-.5)*w}" y="{top-5}" text-anchor="middle" font-size="12">{c}</text>')
            for r in [1,4,7,10,13]:svg.append(f'<text x="{left-9}" y="{top+(r-.25)*h}" text-anchor="end" font-size="12">{r}</text>')
            for r in range(1,14):
                for c in range(1,22):
                    cell=m['cells'][f'{r},{c}'];count=cell['rejected']
                    svg.append(f'<rect x="{left+(c-1)*w}" y="{top+(r-1)*h}" width="{w}" height="{h}" fill="{colors[count]}" stroke="white" stroke-width=".6"><title>{family}{combo} row {r}, column {c}: {count}/3 rejected, ambiguity {cell["ambiguous"]}/3</title></rect>')
            svg.append(f'<rect x="{left+13*w}" y="{top+3*h}" width="{8*w}" height="{7*h}" fill="none" stroke="#0891b2" stroke-width="2"/>')
            svg.append(f'<text x="{left}" y="{top+153}" font-size="10">Box: rows 4-10, columns 14-21</text>')
    svg.append('</svg>');path.write_text('\n'.join(svg))


def run(evaluation,live,out):
    require(not out.exists(),'Use a fresh output directory');out.mkdir(parents=True)
    batches=json.loads((evaluation/'observations.json').read_text());resources=Path(__file__).resolve().parents[1]/'MagAir/Resources'
    catalog=json.loads((resources/'model_catalog.json').read_text());models=[];inventory=[]
    for entry in catalog['entries']:
        for family in ['A','B']:
            raw=(resources/(entry['resource'+family]+'.json')).read_bytes();model=json.loads(raw)
            require(hashlib.sha256(raw).hexdigest()==entry['sha256'+family],'Model hash mismatch')
            allpoints=[];held=[]
            for test in (1,2,3):
                path=evaluation/f'{family}{entry["id"]}-test{test}-predictions.json'
                inventory.append(dict(file=path.name,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                preds=json.loads(path.read_text())['primary']
                points=[dict(row=p['row'],column=p['column'],testPass=test,**reasons(p,model['residualLimitUT'])) for p in preds]
                allpoints.extend(points)
                if test not in entry['passes']:held.extend(points)
            projector=(AProjector if family=='A' else BProjector)(model);self_points=[]
            for row in range(1,14):
                for col in range(1,22):
                    fields=[model['fieldsUT'][row-1][col-1]] if family=='A' else model['locations'][(row-1)*21+col-1]['fieldsUT'][::4]
                    for field in fields:self_points.append(dict(row=row,column=col,**reasons(projector.project(field),model['residualLimitUT'])))
            m=dict(family=family,combination=entry['id'],modelSHA256=entry['sha256'+family],
                   allReplay=aggregate(allpoints),heldOutReplay=aggregate(held) if held else None,
                   rightMiddleAll=aggregate([p for p in allpoints if roi(p['row'],p['column'])]),
                   rightMiddleHeldOut=aggregate([p for p in held if roi(p['row'],p['column'])]) if held else None,
                   exactStoredInput=aggregate(self_points),
                   exactStoredRejectedLocations=sorted({(p['row'],p['column']) for p in self_points if p['rejected']}),
                   cells={f'{r},{c}':aggregate([p for p in allpoints if p['row']==r and p['column']==c]) for r in range(1,14) for c in range(1,22)})
            if family=='A' and entry['id']=='2':
                m['conflictExamples']=[dict(targetRow=r,targetColumn=c,**competing_location(projector,model['fieldsUT'][r-1][c-1])) for r,c in [(7,21),(8,21),(9,18)]]
            models.append(m);print(f'Completed {family}{entry["id"]}',flush=True)
    live_sessions,live_inventory=live_diagnosis(live,catalog)
    result=dict(protocol='posthoc_spatial_rejection_diagnosis_v1',region=dict(rows=[4,10],columns=[14,21]),models=models,
                gradients=gradient_diagnosis(batches),liveSessions=live_sessions,
                limits=['All-pass and self-input diagnostics include training data; not independent accuracy.',
                        'Live coordinates are model estimates, never ground truth. No live free-motion accuracy can be inferred.',
                        'Reasons overlap. Weak-signal live intervals may be deliberate pen removal.',
                        'Row-gradient reversal is relative to other passes; it does not identify its physical cause.',
                        'Open live log is a copy-time snapshot; models and thresholds were not changed.'])
    save(out/'diagnosis.json',result);save(out/'prediction_inventory.json',inventory);save(out/'live_inventory.json',live_inventory)
    draw_maps(models,out/'rejection_maps.svg')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evaluation',type=Path,required=True)
    p.add_argument('--live',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();run(args.evaluation,args.live,args.out)
