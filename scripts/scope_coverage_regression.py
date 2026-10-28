"""Excluded collections must not disable rejection of other unsupported data."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter
from layoutdiff.virtuoso.support import UnsupportedContentError
from layoutdiff.data.history import atomic_json

lib='LAYOUT_DIFF_TEST'; cell='scope_coverage_'+uuid.uuid4().hex[:8]
out=Path(__file__).resolve().parents[1]/'evidence'/cell; out.mkdir(parents=True)
c=VirtuosoClient.from_env()
with c.layout.create(lib,cell) as e:
    e.add('dbCreateRect(cv list("MET1" "drawing") list(0:0 1:1)) '
        'dbCreateRoute(cv) '
        'dbCreateMarker(cv "ignored" "LayoutDiffRegression" list(0:0 1:0 1:1 0:1)) '
        'dbCreateSteiner(cv list(0:0 0:0) "MET1") '
        'foreach(x list(0 2 4) dbCreateGuide(cv list(x 0) list(x+1 1) "MET1" "MET1"))')
try:
    VirtuosoAdapter(c,out/'capture').capture_store(lib,cell,dependencies=False,temporary=True)
    raise AssertionError('Guides must still block capture')
except UnsupportedContentError as exc:
    assert exc.counts=={'unsupported collection: guides':3}, exc.counts
    assert len(exc.report.read_text().splitlines())==3
    report={'unsupported':{'source':[lib,cell,'layout'],'counts':exc.counts,'report':str(exc.report),'details':3}}
    atomic_json(out/'report.json',report)
    print(json.dumps(report,indent=2))
print(out)
