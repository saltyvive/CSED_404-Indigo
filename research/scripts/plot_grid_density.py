"""Presentation-ready figures and per-location tables for the density experiment."""
import argparse
import json
import os
from pathlib import Path
import zipfile
os.environ.setdefault('MPLCONFIGDIR','/private/tmp/magair-density-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np


def setup_font():
    font=Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')
    if font.exists():
        font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'axes.unicode_minus':False,'svg.fonttype':'path','font.size':11,'axes.spines.top':False,'axes.spines.right':False})


def export(fig,out,name):
    fig.savefig(out/(name+'.png'),dpi=200,facecolor='white')
    fig.savefig(out/(name+'.svg'),facecolor='white')
    plt.close(fig)


def run(out):
    setup_font();s=json.loads((out/'summary.json').read_bytes());grids=s['presentationOrder'];models=s['models']
    names=[g.replace('x','×') for g in grids];n=[models[g]['trainingPoints'] for g in grids]
    fig=plt.figure(figsize=(14,7.875));fig.patch.set_facecolor('white')
    fig.text(.055,.91,'학습 격자 밀도에 따른 위치 추정 성능',fontsize=25,weight='bold',color='#152c46')
    fig.text(.055,.851,'접촉 1회차에서 등간격 점 선택 · 동일한 이중선형 보간 · 각 회차 273점 전체 평가',fontsize=14,color='#50677e')
    ax=fig.add_axes([.05,.29,.90,.48]);ax.axis('off')
    headers=['학습 격자\n행×열','학습점 수','평가 1회차*','평가 2회차','평가 3회차','2·3회차 평균\n위치 오차']
    cells=[]
    for g in grids:
        m=models[g]
        cells.append([g.replace('x','×'),str(m['trainingPoints'])]+[f"{100*m['passes'][str(p)]['within2p5Rate']:.1f}%" for p in (1,2,3)]+[f"{m['heldOut23']['meanRadialErrorMM']:.3f} mm"])
    tab=ax.table(cellText=cells,colLabels=headers,cellLoc='center',loc='center',bbox=[0,0,1,1],colWidths=[.14,.13,.17,.17,.17,.22])
    tab.auto_set_font_size(False);tab.set_fontsize(15)
    for (r,c),cell in tab.get_celld().items():
        cell.set_edgecolor('white');cell.set_linewidth(2)
        if r==0:cell.set_facecolor('#19334e');cell.set_text_props(color='white',weight='bold',fontsize=14)
        else:
            cell.set_facecolor('#e7f4ef' if r==4 else '#f0f4f8' if r%2 else '#f8fafc')
            cell.set_text_props(color='#173047')
            if c==2:cell.set_text_props(color='#778391')
            if r==4 and c in (3,5):cell.set_text_props(weight='bold',color='#08785b')
    fig.text(.055,.225,'정확도 = 전체 273점 중 위치 오차가 2.5 mm 이내인 비율',fontsize=13,color='#173047')
    fig.text(.055,.183,'* 1회차에는 학습에 사용한 점이 포함됨. 2·3회차는 학습에서 제외. 표시 보류 후보도 분모에 포함.',fontsize=11,color='#677c8f')
    fig.text(.055,.11,'9점 → 273점: 반복 회차 평균 오차 47.5% 감소',fontsize=19,weight='bold',color='#08785b')
    fig.text(.055,.065,'77점 이후에는 반복 회차 성능이 포화 · 모든 위치에서 단조롭게 개선된 결과는 아님',fontsize=13,color='#687b8c')
    export(fig,out,'presentation_accuracy_table')
    fig,axes=plt.subplots(1,2,figsize=(13,5.7),layout='constrained')
    for p,color,label in [(1,'#94a3b8','1회차 · 학습 자료 포함'),(2,'#168c78','2회차 · 학습 제외'),(3,'#d78136','3회차 · 학습 제외')]:
        m=[models[g]['passes'][str(p)] for g in grids]
        axes[0].plot(n,[x['meanRadialErrorMM'] for x in m],marker='o',color=color,linestyle='--' if p==1 else '-',label=label)
        axes[1].plot(n,[100*x['within2p5Rate'] for x in m],marker='o',color=color,linestyle='--' if p==1 else '-',label=label)
    for ax in axes:
        ax.set_xscale('log');ax.set_xticks(n,[str(v) for v in n]);ax.minorticks_off();ax.grid(axis='y',alpha=.2);ax.set_xlabel('학습점 수 · 로그 축')
    axes[0].set_ylabel('평균 위치 오차 (mm)');axes[0].set_ylim(0,5.4);axes[0].set_title('평균 오차: 희소 격자 대비 감소')
    axes[1].set_ylabel('2.5 mm 이내 비율 (%)');axes[1].set_ylim(0,105);axes[1].set_title('반복 측정: 77점 이후 포화')
    axes[1].legend(loc='lower right',frameon=False)
    fig.suptitle('접촉 1회차만 학습 · 동일한 273개 위치로 평가',fontsize=18,weight='bold')
    export(fig,out,'density_learning_curve')
    preds={g:json.loads((out/(g+'-predictions.json')).read_bytes()) for g in grids}
    def matrix(g,p):
        z=np.zeros((13,21))
        for r in preds[g]:
            if r['passID']==p:z[r['row']-1,r['column']-1]=r['errorMM']
        return z
    fig,axes=plt.subplots(3,5,figsize=(16,9),layout='constrained')
    for i,p in enumerate((1,2,3)):
        for j,g in enumerate(grids):
            ax=axes[i,j];im=ax.imshow(matrix(g,p),cmap='YlOrRd',vmin=0,vmax=8,extent=[.5,21.5,13.5,.5],interpolation='nearest')
            if i==0:ax.set_title(f'{g.replace("x","×")} · {models[g]["trainingPoints"]}점')
            if j==0:ax.set_ylabel(f'{p}회차'+(' (학습 자료 포함)' if p==1 else ' (학습 제외)')+'\n행')
            ax.set_xticks([1,11,21]);ax.set_yticks([1,7,13])
            if i==2:ax.set_xlabel('열')
    fig.colorbar(im,ax=axes,shrink=.8,label='위치 오차 (mm), 8 mm 이상은 같은 색',extend='max')
    fig.suptitle('273개 위치별 오차 · 모든 패널이 같은 색 범위',fontsize=19,weight='bold')
    export(fig,out,'all_pass_spatial_errors')
    fig,axes=plt.subplots(1,2,figsize=(12,4.9),layout='constrained')
    for ax,a,b,title in [(axes[0],'3x3','13x21','9점 → 273점'),(axes[1],'7x11','13x21','77점 → 273점')]:
        delta=sum(matrix(a,p)-matrix(b,p) for p in (2,3))/2
        limit=8 if a=='3x3' else 2
        im=ax.imshow(delta,cmap='RdBu',vmin=-limit,vmax=limit,extent=[.5,21.5,13.5,.5],interpolation='nearest')
        better=int(np.sum(delta>1e-9));same=int(np.sum(abs(delta)<=1e-9));worse=int(np.sum(delta< -1e-9))
        ax.set_title(f'{title}\n개선 {better} · 동일 {same} · 악화 {worse}')
        ax.set_xticks([1,7,14,21]);ax.set_yticks([1,5,10,13]);ax.set_xlabel('열');ax.set_ylabel('행')
        fig.colorbar(im,ax=ax,shrink=.8,label='오차 감소량 (mm)',extend='both')
    fig.suptitle('위치별 변화: 2·3회차 오차 평균 · 파랑=개선, 빨강=악화',fontsize=16,weight='bold')
    export(fig,out,'per_location_improvement')
    # All 25 predetermined combinations, including worse-performing layouts.
    rr=[3,4,5,7,13];cc=[3,5,6,11,21]
    fig,axes=plt.subplots(1,2,figsize=(10,5.5),layout='constrained')
    for ax,p in zip(axes,(2,3)):
        z=np.array([[models[f'{r}x{c}']['passes'][str(p)]['meanRadialErrorMM'] for c in cc] for r in rr])
        im=ax.imshow(z,cmap='YlOrRd',vmin=.5,vmax=5.5)
        for i in range(5):
            for j in range(5):ax.text(j,i,f'{z[i,j]:.2f}',ha='center',va='center',color='white' if z[i,j]>3.8 else '#192f44')
        ax.set_xticks(range(5),cc);ax.set_yticks(range(5),rr);ax.set_xlabel('가로 점 수 (열)');ax.set_ylabel('세로 점 수 (행)');ax.set_title(f'평가 {p}회차')
    fig.colorbar(im,ax=axes,label='평균 위치 오차 (mm)');fig.suptitle('미리 정한 등간격 격자 25종 전체 비교',fontsize=17,weight='bold')
    export(fig,out,'all_25_grid_shapes')
    with zipfile.ZipFile(out/'presentation_assets.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()):
            if f.suffix in ('.png','.svg','.html','.md'):z.write(f,f.name)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);args=p.parse_args();run(args.out)
