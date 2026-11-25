"""Tables and figures for exhaustive density/train/test subset comparisons."""
import argparse
import json
from pathlib import Path
import zipfile

from plot_grid_density import export, setup_font, plt, np
from evaluate_grid_density_combinations import ROLE_KO, key, role


COLORS={'held_out_only':'#e4f3ec','same_pass_only':'#edf0f4','mixed':'#fff2d8'}


def style_table(tab, train, tests, font_size=13):
    tab.auto_set_font_size(False);tab.set_fontsize(font_size)
    for (r,c),cell in tab.get_celld().items():
        cell.set_edgecolor('white');cell.set_linewidth(2)
        if r==0:
            cell.set_facecolor('#19334e');cell.set_text_props(color='white',weight='bold',fontsize=11)
        else:
            color=COLORS[role(train,tests[c-2])] if c>=2 else '#f2f5f8'
            cell.set_facecolor(color);cell.set_text_props(color='#173047')


def run(out):
    setup_font();s=json.loads((out/'summary.json').read_bytes());plan=json.loads((out/'plan.json').read_bytes())
    models=s['models'];grids=s['presentationOrder'];tests=plan['evaluationSets'];trains=plan['trainingSets']
    for train in trains:
        combo=key(train);fig=plt.figure(figsize=(14,7.875))
        fig.text(.045,.92,'학습 '+ '+'.join(map(str,train))+'회차 · 격자 밀도별 전체 평가',fontsize=24,weight='bold',color='#19334e')
        fig.text(.045,.865,'동일한 이중선형 보간 · 각 평가 회차의 273점 전체 · 셀: 평균 오차(mm) / 2.5 mm 이내 비율',fontsize=12,color='#50677e')
        ax=fig.add_axes([.04,.27,.92,.50]);ax.axis('off')
        headers=['격자\n행×열','점 수']+['+'.join(map(str,t))+' 평가\n'+ROLE_KO[role(train,t)] for t in tests]
        cells=[]
        for grid in grids:
            m=models[f'A{combo}_{grid}']
            cells.append([grid.replace('x','×'),str(m['trainingPoints'])]+[
                f'{m["groups"][key(t)]["meanRadialErrorMM"]:.3f} mm\n{100*m["groups"][key(t)]["within2p5Rate"]:.1f}%' for t in tests])
        tab=ax.table(cellText=cells,colLabels=headers,cellLoc='center',bbox=[0,0,1,1],colWidths=[.11,.06]+[.83/7]*7)
        style_table(tab,train,tests)
        fig.text(.045,.20,'초록: 학습에서 제외된 회차만  |  회색: 학습과 같은 회차만  |  노랑: 두 종류 혼합',fontsize=12,color='#41566b')
        fig.text(.045,.15,'평가 1개 회차 = 273개, 2개 = 546개, 3개 = 819개 측정 배치. 묶음은 모든 예측을 합산.',fontsize=11,color='#61778a')
        fig.text(.045,.10,'학습점 수는 서로 다른 위치 수. 학습 배치 수 = 점 수 × 학습 회차 수. 표시 보류 후보도 지표에 포함.',fontsize=11,color='#61778a')
        fig.text(.045,.055,'같은 회차·혼합 결과는 독립 성능 지표가 아님. 1+2+3 학습은 별도 평가 회차가 남아 있지 않음.',fontsize=11,color='#986b2e')
        export(fig,out,f'train_{combo}_evaluation_table')
    # All training/test combinations at the same maximum density; same colors for overlap.
    for metric,title,fmt in [('meanRadialErrorMM','평균 위치 오차 (mm)',lambda x:f'{x:.3f}'),
                              ('within2p5Rate','2.5 mm 이내 비율',lambda x:f'{x:.1%}')]:
        fig=plt.figure(figsize=(14,7.875));fig.text(.05,.91,'273점 고정 · 모든 회차 조합의 '+title,fontsize=23,weight='bold',color='#19334e')
        ax=fig.add_axes([.05,.20,.90,.62]);ax.axis('off')
        cells=[['+'.join(map(str,train))]+[fmt(models[f'A{key(train)}_13x21']['groups'][key(t)][metric]) for t in tests] for train in trains]
        tab=ax.table(cellText=cells,colLabels=['학습 ↓ / 평가 →']+['+'.join(map(str,t)) for t in tests],cellLoc='center',bbox=[0,0,1,1])
        tab.auto_set_font_size(False);tab.set_fontsize(15)
        for (r,c),cell in tab.get_celld().items():
            cell.set_edgecolor('white');cell.set_linewidth(2)
            if r==0:cell.set_facecolor('#19334e');cell.set_text_props(color='white',weight='bold',fontsize=13)
            else:cell.set_facecolor(COLORS[role(trains[r-1],tests[c-1])] if c else '#f0f4f7')
        fig.text(.05,.13,'초록=학습 제외 · 회색=같은 회차 · 노랑=혼합. 일반화 성능 비교에는 초록 셀을 사용.',fontsize=12,color='#41566b')
        fig.text(.05,.08,'각 평가 회차 273점 전체. 2개 회차 546개, 3개 회차 819개. 모든 결과는 기존 세 회차의 사후 분석.',fontsize=11,color='#61778a')
        export(fig,out,'full_density_'+('error' if metric=='meanRadialErrorMM' else 'accuracy'))
    n=[models[f'A1_{g}']['trainingPoints'] for g in grids]
    fig,axes=plt.subplots(1,2,figsize=(13,5.8),layout='constrained')
    for train,color in [(1,'#008b77'),(2,'#db853a'),(3,'#6464bd')]:
        held=key([p for p in (1,2,3) if p!=train]);ms=[models[f'A{train}_{g}']['groups'][held] for g in grids]
        label=f'학습 {train} → 평가 {"+".join(held)}'
        axes[0].plot(n,[m['meanRadialErrorMM'] for m in ms],marker='o',color=color,label=label)
        axes[1].plot(n,[100*m['within2p5Rate'] for m in ms],marker='o',color=color,label=label)
    for ax in axes:
        ax.set_xscale('log');ax.set_xticks(n,n);ax.minorticks_off();ax.grid(axis='y',alpha=.2);ax.set_xlabel('학습 위치 수 · 로그 축');ax.legend(frameon=False)
    axes[0].set_ylabel('평균 위치 오차 (mm)');axes[1].set_ylabel('2.5 mm 이내 비율 (%)')
    axes[1].set_ylim(0,100);axes[0].set_ylim(bottom=0)
    fig.suptitle('단일 회차 학습 → 나머지 두 회차 546개 평가\n선마다 평가 회차가 다름: 성능 차이를 학습 품질만으로 단정하지 않음',fontsize=16,weight='bold')
    export(fig,out,'single_pass_held_out_curves')
    fig,axes=plt.subplots(1,2,figsize=(13,5.8),layout='constrained')
    for kind,color,label in [('singlePooled','#008b77','1회차 분량 학습 · 6방향 평균'),('pairPooled','#6464bd','2회차 분량 학습 · 3방향 평균')]:
        ms=[s['matchedLearningCurves'][g][kind] for g in grids]
        axes[0].plot(n,[m['meanRadialErrorMM'] for m in ms],marker='o',color=color,label=label)
        axes[1].plot(n,[100*m['within2p5Rate'] for m in ms],marker='o',color=color,label=label)
    for ax in axes:
        ax.set_xscale('log');ax.set_xticks(n,n);ax.minorticks_off();ax.grid(axis='y',alpha=.2);ax.set_xlabel('각 학습 회차에서 선택한 위치 수');ax.legend(frameon=False)
    axes[0].set_ylabel('평균 위치 오차 (mm)');axes[0].set_ylim(bottom=0)
    axes[1].set_ylabel('2.5 mm 이내 비율 (%)');axes[1].set_ylim(0,100)
    fig.suptitle('같은 시험 회차로 비교한 학습량 효과\n시험 회차를 하나씩 제외 · 단일 학습은 각 시험점을 두 모델로 예측',fontsize=16,weight='bold')
    export(fig,out,'matched_test_learning_curves')
    fig,axes=plt.subplots(2,3,figsize=(15,9),layout='constrained')
    rr=plan['rowCounts'];cc=plan['columnCounts']
    for ax,train in zip(axes.flat,trains[:-1]):
        held=key([p for p in (1,2,3) if p not in train]);combo=key(train)
        z=np.array([[models[f'A{combo}_{r}x{c}']['groups'][held]['meanRadialErrorMM'] for c in cc] for r in rr])
        im=ax.imshow(z,cmap='YlOrRd',vmin=0,vmax=6.5)
        for i in range(5):
            for j in range(5):ax.text(j,i,f'{z[i,j]:.2f}',ha='center',va='center',color='white' if z[i,j]>4.5 else '#192f44')
        ax.set_xticks(range(5),cc);ax.set_yticks(range(5),rr);ax.set_xlabel('가로 점 수 (열)');ax.set_ylabel('세로 점 수 (행)')
        ax.set_title(f'학습 {"+".join(combo)} → 평가 {"+".join(held)}')
    fig.colorbar(im,ax=axes,shrink=.8,label='평균 위치 오차 (mm)',extend='max')
    fig.suptitle('학습 제외 회차에서 본 등간격 격자 25종',fontsize=19,weight='bold')
    export(fig,out,'all_grid_held_out_errors')
    # Every position, model, and evaluation grouping remains locally reviewable.
    error_data={}
    for name in models:
        preds=json.loads((out/f'{name}-predictions.json').read_bytes())
        error_data[name]={str(p):[round(r['errorMM'],6) for r in preds if r['passID']==p] for p in (1,2,3)}
    shell='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>273개 위치별 오차</title>
<style>body{font-family:system-ui;color:#20364b;margin:32px}label{margin-right:20px}select{padding:8px}table{border-collapse:collapse;margin-top:24px;font-variant-numeric:tabular-nums}td,th{padding:6px 15px;border:1px solid #d7e0e6;text-align:right}th{position:sticky;top:0;background:#edf2f6}.good{background:#e5f4ed}.bad{background:#fde9e5}</style>
<h1>각 위치의 실제 오차 · 175개 모델</h1><p>행×열. 표시된 각 회차는 273개 점 전체입니다. 위치별 평균은 선택한 평가 회차의 오차 평균이며, 임계값 비율은 각 측정 배치에서 따로 계산합니다.</p>
<label>학습 <select id="train"></select></label><label>격자 <select id="grid"></select></label><label>평가 <select id="test"></select></label><p id="info"></p><table id="table"></table>
<script>const errors=ERRORS, summary=SUMMARY, sets=SETS, grids=GRIDS;
for(const id of ['train','test'])for(const t of sets){const o=document.createElement('option');o.value=t;o.textContent=t.split('').join('+');document.getElementById(id).append(o);}
for(const g of grids){const o=document.createElement('option');o.value=g;o.textContent=g.replace('x','×');document.getElementById('grid').append(o);}document.getElementById('grid').value='13x21';document.getElementById('test').value='23';
function render(){const tr=document.getElementById('train').value,g=document.getElementById('grid').value,te=document.getElementById('test').value,name='A'+tr+'_'+g,m=summary[name].groups[te];
const names={held_out_only:'학습 제외',same_pass_only:'같은 회차',mixed:'혼합'};document.getElementById('info').textContent=names[m.role]+' / 평가 '+m.count+'개 / 평균 '+m.meanRadialErrorMM.toFixed(3)+' mm / 2.5 mm 이내 '+(100*m.within2p5Rate).toFixed(1)+'%';
let s='<tr><th>행</th><th>열</th>'+[...te].map(t=>'<th>'+t+'회차 오차 mm</th>').join('')+'<th>위치별 평균 mm</th></tr>';
for(let i=0;i<273;i++){const es=[...te].map(t=>errors[name][t][i]),mean=es.reduce((a,b)=>a+b,0)/es.length;s+='<tr><td>'+ (Math.floor(i/21)+1)+'</td><td>'+(i%21+1)+'</td>'+[...es,mean].map(e=>'<td class="'+(e<=2.5?'good':e>5?'bad':'')+'">'+e.toFixed(3)+'</td>').join('')+'</tr>';}document.getElementById('table').innerHTML=s;}
for(const id of ['train','test','grid'])document.getElementById(id).addEventListener('change',render);render();</script></html>'''
    shell=shell.replace('ERRORS',json.dumps(error_data,separators=(',',':'))).replace('SUMMARY',json.dumps(models,separators=(',',':'))).replace('SETS',json.dumps([key(t) for t in trains])).replace('GRIDS',json.dumps([f'{r}x{c}' for r in rr for c in cc]))
    (out/'all_273_positions.html').write_text(shell)
    with zipfile.ZipFile(out/'presentation_assets.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            if f.suffix in ('.png','.svg','.html','.md','.csv'):z.write(f,f.name)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    run(parser.parse_args().out)
