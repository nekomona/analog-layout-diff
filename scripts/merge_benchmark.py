"""Measure Python reference analysis and indexed queries on synthetic layouts."""
import argparse
import json
from pathlib import Path
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from layoutdiff.data.core import canonicalize
from layoutdiff.data.merge import MergePlan
from layoutdiff.comparison.merge_index import MergeIndex


def measure(count, trace=False):
    if trace:
        tracemalloc.start()
    meta = {'kind': 'cell', 'name': '', 'technology': 'TEST', 'dbu': 1000}
    rows = [{'kind': 'rect', 'layerName': 'M1', 'purpose': 'drawing', 'props': [],
             'bBox': [[j*2000, 0], [j*2000+1000, 1000]]} for j in range(count)]
    base = canonicalize([meta, *rows])
    # Sparse, independent edits resemble incremental branch development.
    target = canonicalize([meta, *[{**r, 'props': [['target', 'string', 'edit']]} if j%100 == 0 else r
                                   for j,r in enumerate(rows)]])
    incoming = canonicalize([meta, *[{**r, 'props': [['incoming', 'string', 'edit']]} if j%100 == 1 else r
                                     for j,r in enumerate(rows)]])
    start = time.perf_counter(); plan = MergePlan(base, target, incoming)
    analyzed = time.perf_counter(); index = MergeIndex(plan)
    indexed = time.perf_counter()
    for _ in range(100):
        index.page(); index.pick([.5, .5])
    queried = time.perf_counter()
    result = plan.result()
    end = time.perf_counter()
    peak = tracemalloc.get_traced_memory()[1] if trace else None
    if trace:
        tracemalloc.stop()
    index.close()
    assert len(result['objects']) == count+1
    return {'objects': count, 'decisions': len(plan.units), 'analysis_seconds': analyzed-start,
            'index_seconds': indexed-analyzed, 'query_pair_ms': (queried-indexed)*10,
            'materialize_seconds': end-queried, 'python_peak_mib': peak/1024**2 if peak else None,
            'memory_tracing': trace}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sizes', nargs='+', type=int, default=[1000, 10000, 100000])
    p.add_argument('--output', type=Path)
    p.add_argument('--trace-memory', action='store_true', help='Trace Python allocations; substantially slows timing')
    args = p.parse_args()
    results = []
    for count in args.sizes:
        results.append(measure(count, args.trace_memory))
        print(json.dumps(results[-1]), flush=True)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2) + '\n')
