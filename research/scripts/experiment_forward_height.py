"""Smooth forward-field ablation: shared spatial regularity before inverse search."""
import numpy as np
from experiment_model_d import distance2, local_xy, training_arrays


def fit_forward(records, config, plan):
    maps=[]
    # A 1.25 mm candidate lattice, followed by a tangent-plane refinement.
    grid=np.array([[x,y] for y in np.linspace(0,30,25) for x in np.linspace(0,50,41)])
    for state in ('air','contact'):
        rs=[r for r in records if r['state']==state]
        coords=sorted({tuple(r['xy']) for r in rs})
        xy=np.array(coords)*[50,30]
        obs=[]
        for pos in coords:
            group=[r for r in rs if tuple(r['xy'])==pos]
            fields,_,_=training_arrays(group,config['representation'])
            obs.append(fields.mean(axis=0))
        obs=np.array(obs);mean=obs.mean(axis=0)
        k=np.exp(-distance2(xy,xy)/(2*config['bandwidth']**2))
        k.flat[::len(k)+1]+=config['ridge']
        alpha=np.linalg.solve(k,obs-mean)
        def forward(q):
            return np.exp(-distance2(q,xy)/(2*config['bandwidth']**2))@alpha+mean
        fields=forward(grid)
        grads=np.stack([(forward(grid+np.eye(2)[axis]*.1)-forward(grid-np.eye(2)[axis]*.1))/.2 for axis in range(2)],axis=-1)
        maps.append(dict(fields=fields.tolist(),gradients=grads.tolist(),grid=grid.tolist()))
    loc_x,_,loc_y=training_arrays(records,'mixed')
    return dict(version=1,method='smooth_forward_height_local_affine_xy',config=config,maps=maps,
        localFields=loc_x.tolist(),localXY=loc_y.tolist(),neighbors=plan['localXYNeighbors'],localRidge=plan['localXYRidge'],
        margin=0,minimumSignalUT=plan['minimumSignalUT'],supportLimitUT=plan['supportLimitUT'],
        trainingTrialIDs=sorted(r['session']+'/'+r['trial'] for r in records),sourceSessions=sorted({r['session'] for r in records}))


def predict_forward(model, fields, include_xy=True):
    q=np.array(fields);distances=[];candidates=[]
    for mp in model['maps']:
        g=np.array(mp['grid']);f=np.array(mp['fields']);j=np.array(mp['gradients'])
        ds=distance2(q,f);idx=np.argmin(ds,axis=1)
        tangent=j[idx];diff=q-f[idx]
        normal=np.einsum('nki,nkj->nij',tangent,tangent)+np.eye(2)[None,:,:]*1e-5
        step=np.linalg.solve(normal,np.einsum('nki,nk->ni',tangent,diff)[...,None])[...,0]
        step=np.clip(step,-1.25,1.25)
        points=np.clip(g[idx]+step,[0,0],[50,30]);step=points-g[idx]
        residual=diff-np.einsum('nki,ni->nk',tangent,step)
        distances.append(np.linalg.norm(residual,axis=1));candidates.append(points/[50,30])
    # Positive: contact closer. A normalized difference retains scale information.
    a,c=distances
    score=(a-c)/np.maximum(a+c,.5)
    xy,support=local_xy(model,q) if include_xy else (np.full((len(q),2),.5),np.sqrt(distance2(q,np.array(model['localFields'])).min(axis=1)))
    return dict(score=score,xy=xy,support=support,signal=np.linalg.norm(q,axis=1))
