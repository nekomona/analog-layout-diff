"""Bounded-memory matching benchmark over 10K/100K translated figures."""
import argparse
import json
from pathlib import Path
import time
from layoutdiff.matching import pairs


def records(count, moved):
    for i in range(count):
        x=(i%1000)*100 + (20 if moved else 0)
        y=(i//1000)*100 + (30 if moved else 0)
        # Two unique fingerprints provide translation evidence for the array.
        w=11+i if i<2 else 7
        yield str(i),dict(kind='rect',layerName='MET1',purpose='drawing',bBox=[[x,y],[x+w,y+20]])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--sizes',nargs='+',type=int,default=[10000,100000]);args=p.parse_args()
    results=[]
    for n in args.sizes:
        start=time.perf_counter()
        count=sum(1 for _ in pairs(records(n,False),records(n,True)))
        result=dict(figures=n,pairs=count,seconds=time.perf_counter()-start)
        assert count==n
        print(json.dumps(result),flush=True);results.append(result)
    out=Path(__file__).resolve().parents[1]/'evidence/mpp/matching-benchmark.json'
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(results,indent=2))
