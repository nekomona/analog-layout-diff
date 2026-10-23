"""Read-only complete coverage check of a specified source; never saves/commits."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso import VirtuosoAdapter
from layoutdiff.support import UnsupportedContentError
from layoutdiff.history import atomic_json

lib, cell, out = sys.argv[1:]
out = Path(out)
adapter = VirtuosoAdapter(VirtuosoClient.from_env(), out / 'source-coverage')
start = time.monotonic()
report = {'source': [lib, cell, 'layout'], 'read_only': True}
try:
    state = adapter.capture_store(lib, cell, temporary=True, dependencies=False)
    report.update(supported=True, objects=state.count, digest=state.digest)
    state.dispose()
except UnsupportedContentError as exc:
    report.update(supported=False, counts=exc.counts, details=str(exc.report))
report['seconds'] = time.monotonic() - start
atomic_json(out / 'source-coverage.json', report)
print(json.dumps(report, indent=2))
