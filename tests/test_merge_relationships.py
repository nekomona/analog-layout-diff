import copy
import pytest
from layoutdiff.data.core import canonicalize
from layoutdiff.data.merge import MergePlan
from layoutdiff.eda.virtuoso.adapter import normalize, coverage
from test_oa_content import records as annotations
from test_figgroups import fixture as ordered_groups
from test_merge import snap, rect
from test_mpp import records as mpp_records


def test_annotation_and_group_references_follow_selected_moved_shape():
    b = normalize(copy.deepcopy(annotations()))
    t_records = annotations(); t_records[1]['bBox'] = [[100, 0], [1100, 1000]]
    i_records = annotations(); i_records[1]['bBox'] = [[200, 0], [1200, 1000]]
    t, i = normalize(t_records), normalize(i_records)
    p = MergePlan(b, t, i)
    selected = {k: 'incoming' for k in p.unresolved()}
    result = p.result(selected)
    assert result == i
    assert not coverage(result)


def test_group_metadata_and_member_geometry_can_combine_with_reference_rekeying():
    b = normalize(copy.deepcopy(annotations()))
    t_records = annotations(); t_records[1]['bBox'] = [[100, 0], [1100, 1000]]
    i_records = annotations(); i_records[-1]['props'] = [['note', 'string', 'group edit']]
    expected = copy.deepcopy(t_records); expected[-1]['props'] = i_records[-1]['props']
    p = MergePlan(b, normalize(t_records), normalize(i_records))
    choices = {k: ('combined' if u['combined'] is not None else 'incoming')
               for k, u in p.units.items() if u['reasons']}
    assert p.result(choices) == normalize(expected)


def test_net_deletion_vs_modified_connected_geometry_is_one_decision():
    n = {'kind': 'net', 'name': 'N', 'props': []}
    b = snap(n, rect(net='N'))
    t = snap()
    i = snap(n, rect(20, net='N'))
    p = MergePlan(b, t, i)
    ident, = p.unresolved()
    assert p.result({ident: 'target'}) == t
    assert p.result({ident: 'incoming'}) == i


def test_ordered_group_reorder_conflicts_preserve_complete_selected_order():
    records = ordered_groups()
    records[3]['bBox'] = [[2000, 0], [3000, 1000]]
    b = canonicalize(records)
    t = copy.deepcopy(records); t[3]['groupOrder'], t[4]['groupOrder'] = 0, 2
    i = copy.deepcopy(records); i[2]['groupOrder'], i[3]['groupOrder'] = 2, 1
    t, i = canonicalize(t), canonicalize(i)
    p = MergePlan(b, t, i)
    result = p.result({k: 'target' for k in p.unresolved()})
    assert result == t and not coverage(result)


def test_master_drift_is_a_warning_and_does_not_block_a_merge():
    b = snap({'kind': 'dependency', 'name': 'TEST/child/layout', 'fingerprint': 'base'})
    t = snap({'kind': 'dependency', 'name': 'TEST/child/layout', 'fingerprint': 'target'})
    i = snap({'kind': 'dependency', 'name': 'TEST/child/layout', 'fingerprint': 'incoming'})
    p = MergePlan(b, t, i)
    assert not p.unresolved() and p.warnings


@pytest.mark.parametrize('kind', ['inst', 'mosaic'])
def test_pcell_or_mosaic_dimensions_are_not_independently_combined(kind):
    r = {'kind': kind, 'name': 'I0', 'libName': 'TEST', 'cellName': 'device',
         'origin': [0, 0], 'orient': 'R0', 'params': [['w','float',1.0]], 'props': []}
    b, t, i = snap(r), snap({**r, 'origin': [50, 0]}), snap({**r, 'params': [['w','float',2.0]]})
    p = MergePlan(b, t, i)
    ident, = p.unresolved()
    assert p.result({ident: 'incoming'}) == i
    with pytest.raises(ValueError, match='Keep both'):
        p.result({ident: 'both'})


def test_mpp_recipe_and_generated_members_are_one_choice():
    raw = mpp_records()
    t = copy.deepcopy(raw); i = copy.deepcopy(raw)
    t[2]['points'][1][0] += 100
    i[3]['bBox'][1][0] += 20
    b, t, i = map(canonicalize, (raw, t, i))
    plan = MergePlan(b, t, i)
    ident, = plan.unresolved()
    assert plan.result({ident: 'target'}) == t
    assert plan.result({ident: 'incoming'}) == i
