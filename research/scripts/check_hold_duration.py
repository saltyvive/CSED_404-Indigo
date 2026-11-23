#!/usr/bin/env python3
"""Reproduce the 2026-11-24 first-pass truncation diagnostic (not independent accuracy). Run from research/."""
import sys,json,statistics as st,math
from pathlib import Path
sys.path.insert(0,'scripts')
import analyze_session as a
from build_grid_model import Projector
from build_printed_grid_model import extract
model=json.loads(Path('evaluation/frozen/pass1.json').read_text()); projector=Projector(model)
points=[]
for path in sorted(Path('data/printed-grid-20261123-pass1').glob('MagAir-*/')):
 m,rows=a.read_session(path)
 batch=extract(path,allow_transient_motion=True,review_note='Reproduce the already reviewed first-pass truncation diagnostic; no independent accuracy claim.')
 for t in m['trials']:
  if t['status']!='completed' or t['spec']['kind']!='mapHold':continue
  start=t['startUptime']+t['settleSeconds']; spec=t['spec']; versions={}
  for seconds in [3,2,1.5]:
   data=[r for r in rows if r['trial_id']==spec['id'] and r['phase']=='hold' and start+.4<=float(r['timestamp_s'])<start+seconds-.2]
   center=a.median_vector([a.vector(r) for r in data]); noise=math.sqrt(st.mean(math.dist(a.vector(r),center)**2 for r in data))
   time=st.median(float(r['timestamp_s']) for r in data); f=(time-batch['before']['time'])/(batch['after']['time']-batch['before']['time'])
   bg=[x+f*(y-x) for x,y in zip(batch['before']['raw'],batch['after']['raw'])]
   pred=projector.project([x-b for x,b in zip(center,bg)])
   versions[str(seconds)]=dict(raw=center,samples=len(data),noiseUT=noise,xy=pred['xy'])
  points.append(dict(session=m['id'],trial=spec['id'],versions=versions))
def quant(v,p):
 v=sorted(v); i=(len(v)-1)*p; l=int(i); return v[l]+(v[min(l+1,len(v)-1)]-v[l])*(i-l)
result={}
for seconds in ['2','1.5']:
 diffs=[math.dist(p['versions'][seconds]['raw'],p['versions']['3']['raw']) for p in points]
 shifts=[math.hypot(50*(p['versions'][seconds]['xy'][0]-p['versions']['3']['xy'][0]),30*(p['versions'][seconds]['xy'][1]-p['versions']['3']['xy'][1])) for p in points]
 result[seconds]=dict(positions=len(points),samplesMin=min(p['versions'][seconds]['samples'] for p in points),deltaUTMedian=st.median(diffs),deltaUTP95=quant(diffs,.95),shiftMMMedian=st.median(shifts),shiftMMP95=quant(shifts,.95),shiftMMMax=max(shifts))
Path('reports').mkdir(exist_ok=True)
Path('reports/duration-check-20261124.json').write_text(json.dumps(dict(summary=result,points=points,limitations='Within-training-hold truncation only. Does not validate shorter preparation, automated motion, or independent accuracy.'),indent=2))
print(json.dumps(result,indent=2))
