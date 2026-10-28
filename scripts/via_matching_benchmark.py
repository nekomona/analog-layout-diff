"""Exercise the point-object matcher without external translation anchors."""
import argparse
import json
from pathlib import Path
import time
from layoutdiff.comparison.matching import pairs


def records(count, moved):
    for i in range(count):
        x=(i%1000)*1000+(40 if moved else 0)
        y=(i//1000)*1000+(20 if moved else 0)
        yield str(i),dict(kind='stdVia',viaDef='V1',purpose='drawing',origin=[x,y],
                         params=[['cutRows',2],['cutColumns',3]],orient='R0',net='N',props=[])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--sizes',type=int,nargs='+',default=[10000,100000])
    rows=[]
    for n in parser.parse_args().sizes:
        start=time.perf_counter();count=sum(1 for _ in pairs(records(n,False),records(n,True)))
        assert count==n,(n,count)
        rows.append(dict(vias=n,pairs=count,seconds=time.perf_counter()-start))
        print(json.dumps(rows[-1]),flush=True)
    (Path(__file__).resolve().parents[1]/'evidence/via-matching-benchmark.json').write_text(json.dumps(rows,indent=2))
