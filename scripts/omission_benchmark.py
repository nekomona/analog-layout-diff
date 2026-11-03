"""Measure bounded projection of a large supported design plus unknown objects."""
import json
from pathlib import Path
import tempfile
import time
from layoutdiff.data.storage import write_records
from layoutdiff.eda.virtuoso.omissions import project

out = Path(__file__).resolve().parents[1]/'evidence/omissions'
out.mkdir(parents=True, exist_ok=True)
results = []
for count in (10000, 100000):
    def records():
        yield dict(kind='cell', name='', props=[])
        for i in range(count):
            yield dict(kind='rect', layerName='MET1', purpose='drawing',
                       bBox=[[i*10,0],[i*10+5,5]], props=[], net=None, group=None, pin=None)
        yield dict(kind='unsupported', category='futureObject', props=[])
    with tempfile.TemporaryDirectory(prefix='ald_omission_benchmark_') as tmp:
        path = Path(tmp)
        full = write_records(records(), path/'full')
        started = time.perf_counter()
        result = project(full, path/'supported', path/'omissions.jsonl')
        elapsed = time.perf_counter() - started
        assert result.count == count+1 and result.omissions['omitted'] == 1
        row = dict(figures=count, projection_seconds=elapsed,
                   source_bytes=sum(p.stat().st_size for p in full.path.iterdir()),
                   result_records=result.count, omitted=1)
        results.append(row)
        print(row, flush=True)
        full.close(); result.close()
(out/'benchmark.json').write_text(json.dumps(results, indent=2))
