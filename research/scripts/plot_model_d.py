"""Standalone scientific figures for the retrospective model D comparison."""
import os
os.environ.setdefault('MPLCONFIGDIR', '/private/tmp/magair-model-d-matplotlib')
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
import numpy as np
from train_joint_mlp import ROOT
from compare_model_d import load_old


def main():
    folder=ROOT/'reports/model-d-20261125-hybrid';old=load_old()
    colors=['#168c78','#e66558','#d6dce2'];cmap=ListedColormap(colors)
    fig,axes=plt.subplots(2,4,figsize=(14,6.8),layout='constrained')
    for i,(train,test) in enumerate([('1',2),('2',1)]):
        for j,f in enumerate('ABCD'):
            rs=(json.loads((folder/f'air{train}-to-air{test}-predictions.json').read_bytes()) if f=='D' else
                [r for r in old[train][f] if r['truth']=='air' and r['passID']==test and r['mode']=='primary'])
            z=np.full((13,21),np.nan)
            for r in rs:z[r['row']-1,r['column']-1]={'air':0,'contact':1,'uncertain':2}[r['predicted']]
            ax=axes[i,j];ax.imshow(z,cmap=cmap,vmin=-.5,vmax=2.5,extent=[.5,21.5,13.5,.5],interpolation='nearest')
            count=[int((z==k).sum()) for k in range(3)]
            ax.set_title(f'{f}   {count[0]} / {count[1]} / {count[2]}',fontsize=12)
            ax.set_xticks([1,7,14,21]);ax.set_yticks([1,5,10,13]);ax.set_xlabel('Grid column')
            if j==0:ax.set_ylabel(f'Air train {train} → test {test}\nGrid row')
            for spine in ax.spines.values():spine.set_visible(False)
    fig.suptitle('Same 273 targets, different air pass: A / B / C / experimental D\nContact training stays at passes 1+3; retrospective development comparison',fontsize=14)
    fig.legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,['Correct air','Wrong contact','Abstain'])],loc='outside lower center',ncol=3,frameon=False)
    fig.savefig(folder/'cross_pass_height_maps.png',dpi=180);plt.close(fig)
    s=json.loads((folder/'summary.json').read_bytes())
    fig,axes=plt.subplots(1,2,figsize=(11,4.7),layout='constrained')
    for ax,key,title in zip(axes,['crossPass','finalReplay'],['Other air pass (retrospective)','Final model: training replay']):
        entries=s[key];names=list(entries)
        vals=np.array([[entries[n]['air'][k] for k in ('correct','wrong','abstain')] for n in names])/546*100
        bottom=np.zeros(len(names))
        for k,color in enumerate(colors):
            ax.bar(names,vals[:,k],bottom=bottom,color=color)
            for i,v in enumerate(vals[:,k]):
                if v>7:ax.text(i,bottom[i]+v/2,f'{v:.1f}%',ha='center',va='center',fontsize=10,color='white' if k!=2 else '#334155')
            bottom+=vals[:,k]
        ax.set_ylim(0,100);ax.set_title(title);ax.set_ylabel('% of all air placements');ax.spines[['top','right']].set_visible(False)
    fig.legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,['Correct air','Wrong contact','Abstain'])],loc='outside lower center',ncol=3,frameon=False)
    fig.savefig(folder/'air_outcome_comparison.png',dpi=180);plt.close(fig)


if __name__=='__main__':main()
