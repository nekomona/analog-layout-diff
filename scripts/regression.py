"""Seeded edits in native Virtuoso; history replay; semantic and GDS checks."""
import argparse
import copy
import json
import random
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from explore import ROOT
from inventory import LIB
from virtuoso_bridge import VirtuosoClient
from layoutdiff.data.core import empty_snapshot, diff, apply_diff, digest
from layoutdiff.eda.virtuoso.adapter import VirtuosoAdapter, checked, coverage
from layoutdiff.eda.virtuoso.geometry import export, compare_gds
from layoutdiff.eda.virtuoso.sexpr import dumps as sk


def drawing(rng, index):
    x, y = rng.randrange(-100, 100) / 10, rng.randrange(-100, 100) / 10
    w, h = rng.randrange(2, 20) / 10, rng.randrange(2, 20) / 10
    lpp = sk([rng.choice(["MET1", "MET2", "MET3"]), "drawing"])
    kind = index % 6
    if kind == 0:
        expr = f"dbCreateRect(cv {lpp} {sk([[x,y],[x+w,y+h]])})"
    elif kind == 1:
        expr = f"dbCreatePolygon(cv {lpp} {sk([[x,y],[x+w,y],[x+w,y+h],[x+w/2,y+h*1.5],[x,y+h]])})"
    elif kind == 2:
        expr = f"dbCreatePath(cv {lpp} {sk([[x,y],[x+w,y],[x+w,y+h]])} 0.2 {sk(rng.choice(['truncateExtend','extendExtend','roundRound']))})"
    elif kind == 3:
        expr = f"dbCreateLabel(cv {lpp} {sk([x,y])} {sk('tag '+str(index)+' "quoted" \\')} \"centerCenter\" {sk(rng.choice(['R0','R90','MX','MYR90']))} \"roman\" 0.3)"
    elif kind == 4:
        expr = f"dbCreateEllipse(cv {lpp} {sk([[x,y],[x+w,y+h]])})"
    else:
        expr = f"dbCreatePathSeg(cv {lpp} {sk([x,y])} {sk([x+w,y])} 0.2 \"variable\" \"truncate\" list(0.15 0.0))"
    return f"let((o) o={expr} unless(o error(\"random shape creation failed\")) dbReplaceProp(o \"test_index\" \"int\" {index}))"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=4)
    p.add_argument("--steps", type=int, default=6)
    p.add_argument("--no-gds", action="store_true")
    args = p.parse_args()
    c = VirtuosoClient.from_env()
    run = uuid.uuid4().hex[:8]
    out = ROOT / "evidence" / ("regression_" + run)
    out.mkdir(parents=True)
    a = VirtuosoAdapter(c, out / "raw")
    stream_map = out / "stream.map"
    stream_map.write_text("MET1 drawing 81 0\nMET2 drawing 82 0\nMET3 drawing 83 0\n", encoding="ascii")
    report = {"run": run, "seeds": args.seeds, "steps": args.steps, "cases": []}
    for seed in range(args.seeds):
        rng = random.Random(seed)
        cell = f"rnd_{run}_{seed}"
        with c.layout.create(LIB, cell) as edit:
            for index in range(12):
                edit.add(drawing(rng, index))
            # Identical overlapping objects must retain multiplicity.
            for _ in range(2):
                edit.add('dbCreateRect(cv list("MET1" "drawing") list(list(-1 -1) list(1 1)))')
        state, replay, parent = empty_snapshot(), empty_snapshot(), None
        for step in range(args.steps):
            if step:
                with c.layout.modify(LIB, cell) as edit:
                    edit.add('let((o) o=car(cv~>shapes) when(o dbDeleteObject(o)))')
                    edit.add(drawing(rng, 12 + step))
                    edit.add(f'dbReplaceProp(cv "revision" "int" {step})')
                    # Move an actual rectangle, not one re-created by our renderer.
                    edit.add(f'let((o) o=car(setof(s cv~>shapes s~>objType=="rect")) when(o o~>bBox=list(list({step/10} 0) list({step/10+1} 1))))')
            snap = a.capture(LIB, cell)
            assert not coverage(snap), coverage(snap)
            commit = diff(state, snap, parent=parent, message=f"seed {seed}, step {step}")
            replay = apply_diff(replay, commit, parent=parent)
            assert replay == snap
            assert apply_diff(snap, commit, parent=parent, reverse=True) == state
            (out / f"seed{seed}_commit{step}.json").write_text(json.dumps(commit, indent=2), encoding="utf-8")
            dest = f"reb_{run}_{seed}_{step}"
            rebuilt = a.reconstruct(replay, LIB, dest)
            if rebuilt != snap:
                (out / "mismatch.json").write_text(json.dumps(diff(snap, rebuilt), indent=2), encoding="utf-8")
                raise AssertionError(f"Native semantic mismatch: {out / 'mismatch.json'}")
            case = {"seed": seed, "step": step, "source": cell, "reconstructed": dest,
                    "objects": len(snap["objects"]), "operations": len(commit["operations"]),
                    "digest": digest(snap), "semantic_equal": True}
            if not args.no_gds and step == args.steps-1:
                left, right = out / f"{cell}.gds", out / f"{dest}.gds"
                export(c, LIB, cell, left, stream_map)
                export(c, LIB, dest, right, stream_map)
                case["gds"] = compare_gds(left, right, left_top=cell, right_top=dest)
                assert case["gds"]["equal"] and case["gds"]["has_geometry"], case
            report["cases"].append(case)
            (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"PASS seed={seed} step={step} objects={len(snap['objects'])} ops={len(commit['operations'])}" + (" GDS XOR=empty" if "gds" in case else ""), flush=True)
            parent, state = commit["id"], snap
    print(out, flush=True)


if __name__ == "__main__":
    main()
