"""Live unsaved-edit counters and unavailable-master warning checks."""
import json
import sys
import uuid
import warnings
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore import ROOT
from inventory import LIB
from virtuoso_bridge import VirtuosoClient
from layoutdiff.data.core import canonicalize
from layoutdiff.virtuoso.dependencies import DependencyWarning
from layoutdiff.data.history import atomic_json
from layoutdiff.virtuoso.sexpr import dumps as sk, loads
from layoutdiff.virtuoso.adapter import VirtuosoAdapter

c = VirtuosoClient.from_env()
run = uuid.uuid4().hex[:8]
out = ROOT / "evidence" / ("hierarchy_edges_" + run)
out.mkdir(parents=True)
adapter = VirtuosoAdapter(c, out / "raw")
cell = "dep_dirty_" + run
with c.layout.create(LIB, cell) as edit:
    edit.add('dbCreateRect(cv list("MET1" "drawing") list(list(0 0) list(1 1)))')
initial = adapter.hierarchy.read(identities=[[LIB, cell, "layout"]])
assert initial[0]["dirty"] is False
paths = ["/tmp/ald_dirty_" + run + "_" + str(step) for step in range(2)]
# Both observations execute before the editor's save, inside an explicit modify context.
with c.layout.modify(LIB, cell) as edit:
    for step, path in enumerate(paths):
        edit.add(f'dbCreateRect(cv list("MET2" "drawing") list(list({step+2} 0) list({step+3} 1)))')
        edit.add(f'ALDCheckDependencies({sk([[LIB, cell, "layout"]])} {sk(path)})')
observations = []
for step, remote in enumerate(paths):
    local = out / f"unsaved{step}.sexpr"
    c.download_file(remote, str(local))
    observations.append(dict(loads(local.read_text().strip())))
assert all(r["dirty"] for r in observations)
assert observations[0]["dirtyCounter"] != observations[1]["dirtyCounter"]
saved = adapter.hierarchy.read(identities=[[LIB, cell, "layout"]])
assert not saved[0]["dirty"] and saved[0]["dirtyCounter"] is None
assert saved[0]["fingerprint"] != initial[0]["fingerprint"]
missing = dict(initial[0], cellName="dep_missing_" + run)
missing["name"] = json.dumps([LIB, missing["cellName"], "layout"], separators=(",", ":"))
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always", DependencyWarning)
    issues = adapter.check_dependencies(canonicalize([missing]))
assert len(caught) == len(issues) == 1
assert issues[0]["current"]["fingerprint"]["status"] == "unresolved"
atomic_json(out / "report.json", {"test_cell": cell, "unsaved_observations": observations,
    "saved": saved, "missing_master_warnings": issues, "passed": True})
print("PASS unsaved/missing hierarchy checks", out)
