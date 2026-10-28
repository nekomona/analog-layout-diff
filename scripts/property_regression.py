import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore import ROOT
from inventory import LIB
from virtuoso_bridge import VirtuosoClient
from layoutdiff.virtuoso.adapter import VirtuosoAdapter
from layoutdiff.data.core import empty_snapshot, diff, apply_diff, digest
from layoutdiff.data.history import atomic_json

c = VirtuosoClient.from_env()
token = uuid.uuid4().hex[:8]
cell, dest = "props_"+token, "props_rebuilt_"+token
with c.layout.create(LIB, cell) as edit:
    edit.add('dbCreateRect(cv list("MET1" "drawing") list(list(0 0) list(1 1)))')
    edit.add('dbReplaceProp(cv "falseFlag" "boolean" nil)')
    edit.add('dbReplaceProp(cv "trueFlag" "boolean" t)')
    edit.add('dbReplaceProp(cv "zero" "int" 0)')
    edit.add('dbReplaceProp(cv "asString" "string" "0001")')
    edit.add('dbReplaceProp(cv "precise" "float" 0.123456789012345)')
    edit.add('dbReplaceProp(cv "nestedList" "ILList" list("123" 123 0.123456789012345 nil t \'sample list(1 2 3)))')
    edit.add('dbReplaceProp(cv "tagLikeList" "ILList" list("@float" "123"))')
a = VirtuosoAdapter(c, ROOT / "evidence/properties/raw")
snap = a.capture(LIB, cell)
assert next(p[2] for p in snap["objects"]["cell:"]["props"] if p[0] == "tagLikeList") == ["@float", "123"]
commit = diff(empty_snapshot(), snap)
actual = a.reconstruct(apply_diff(empty_snapshot(), commit), LIB, dest)
assert snap == actual
atomic_json(ROOT / "evidence/properties/snapshot.json", snap)
atomic_json(ROOT / "evidence/properties/report.json", {"source": cell, "destination": dest, "digest": digest(snap), "native_equal": True})
print("PASS typed properties: FALSE/TRUE, strings/numbers, nested ILList, symbols, 17-digit floats")
