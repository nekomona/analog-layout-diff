import copy
import pytest
from layoutdiff.core import canonicalize, digest
from layoutdiff.native_equivalence import via_default_projection


DEFAULTS = {'V1': {'cutRows': 1, 'cutColumns': 1}}


def via(params, **fields):
    return {'kind': 'stdVia', 'viaDef': 'V1', 'origin': [0, 0], 'orient': 'R0',
            'params': params, 'props': [], 'net': 'N', **fields}


def projection(records, defaults=DEFAULTS):
    return via_default_projection(canonicalize(records), defaults)[0]


def test_redundant_defaults_compare_equal_without_rewriting_snapshots():
    before = canonicalize([via([['cutColumns', 1], ['cutRows', 12], ['cutSpacing', [.34, .5]]])])
    after = canonicalize([via([['cutRows', 12], ['cutSpacing', [.34, .5]]])])
    original = copy.deepcopy(before)
    result, count = via_default_projection(before, DEFAULTS)
    assert count == 1 and result == after
    assert before == original and digest(before) != digest(after)


@pytest.mark.parametrize('change', [
    {'params': [['cutColumns', 2]]}, {'params': [['cutRows', 2]]},
    {'params': [['cutColumns', 1], ['cutSpacing', [.34, .5]]]},
    {'origin': [1, 0]}, {'orient': 'MX'}, {'net': 'OTHER'},
    {'props': [['x', 'string', 'changed']]}, {'group': 'other', 'groupOrder': 0},
    {'viaDef': 'OTHER'},
])
def test_real_via_changes_remain_mismatches(change):
    expected = via([['cutColumns', 1]])
    actual = {**via([]), **change}
    assert projection([expected]) != projection([actual])


@pytest.mark.parametrize('defaults', [{}, {'V1': {'cutColumns': 2}}, {'V1': {'cutColumns': None}}])
def test_unknown_or_different_technology_defaults_are_not_assumed(defaults):
    assert projection([via([['cutColumns', 1]])], defaults) != projection([via([])], defaults)


def group(name, target):
    return {'kind': 'group', 'name': name, 'isOrdered': False,
            'members': [{'target': target, 'props': [['role', 'string', 'keep']]}]}


def nested(params):
    snap = canonicalize([via(params)])
    child = group('child', next(iter(snap['objects'])))
    child_key = next(iter(canonicalize([child])['objects']))
    return canonicalize([*snap['objects'].values(), child, group('parent', child_key)])


def test_nested_logical_group_keys_follow_normalized_via_identity():
    before, after = nested([['cutColumns', 1]]), nested([])
    assert via_default_projection(before, DEFAULTS)[0] == after


def test_duplicate_multiplicity_is_checked_and_ambiguous_links_are_rejected():
    a, b = via([['cutColumns', 1]]), via([])
    assert projection([a, b]) == projection([b, b])
    assert projection([a, b]) != projection([b])
    target = next(iter(canonicalize([a])['objects']))
    with pytest.raises(ValueError, match='Ambiguous'):
        projection([a, b, group('g', target)])


def test_non_unit_default_is_proven_from_technology_and_other_params_stay_exact():
    defaults = {'V1': {'cutRows': 3, 'cutColumns': 2}}
    assert projection([via([['cutRows', 3], ['cutColumns', 2]])], defaults) == projection([via([])], defaults)
    assert projection([via([['cutWidth', .2]])], defaults) != projection([via([])], defaults)
