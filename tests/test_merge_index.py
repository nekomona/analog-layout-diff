import copy
from layoutdiff.data.core import canonicalize
from layoutdiff.data.merge import MergePlan
from layoutdiff.comparison.merge_index import MergeIndex
from layoutdiff.eda.virtuoso.support import coverage
from layoutdiff.eda.virtuoso.adapter import normalize
from test_merge import rect, snap
from test_oa_content import records


def test_projection_preserves_annotation_links_and_omits_unrelated_geometry():
    raw = records()
    base = normalize(copy.deepcopy(raw))
    target = copy.deepcopy(raw); target[1]['props'] = [['note', 'string', 'changed']]
    plan = MergePlan(base, normalize(target), base)
    index = MergeIndex(plan)
    try:
        for ident in plan.units:
            projected, selected, truncated = index.projection('target', ident)
            assert not coverage(projected)
            assert not truncated and set(selected) <= projected['objects'].keys()
    finally:
        index.close()


def test_net_selection_has_connected_figures_and_projection_is_bounded():
    n = {'kind': 'net', 'name': 'N', 'props': []}
    base = snap(n, rect(net='N'), rect(50000))
    target = snap({**n, 'props': [['note', 'string', 'change']]}, rect(net='N'), rect(50000))
    plan = MergePlan(base, target, base)
    index = MergeIndex(plan)
    try:
        ident, = plan.units
        projected, selected, truncated = index.projection('target', ident)
        assert len(projected['objects']) == 3
        assert any(projected['objects'][key]['kind'] == 'rect' for key in selected)
    finally:
        index.close()


def test_navigation_pages_and_spatial_pick_are_indexed():
    base = snap(*[rect(j*10000) for j in range(120)])
    target = snap(*[rect(j*10000, props=[['note', 'string', 'edit']]) for j in range(120)])
    plan = MergePlan(base, target, base)
    index = MergeIndex(plan)
    try:
        assert len(index.page()) == 50
        assert len(index.page(offset=100)) == 20
        assert set(index.page()).isdisjoint(index.page(offset=50))
        assert len(index.pick([.01, .01])) == 1
        unit = index.page()[0]
        projection, selected, _ = index.projection('target', unit)
        assert len(projection['objects']) == 2
    finally:
        index.close()
