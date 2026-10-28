import copy
import pytest
from layoutdiff.data.core import canonicalize, digest
from layoutdiff.virtuoso.native_equivalence import via_default_projection, mpp_path_cache_aliases


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


def mpp_cache_records():
    return [dict(kind='net', name='N', props=[]),
            dict(kind='path', layerName='ACT', purpose='drawing', points=[[0, 0], [100, 0]],
                 mpp=dict(name='ring', parts=[dict(type='offsetPath', lpp=['NW1', 'drawing'],
                     netName='deleted_net', termName=None, width=20, separation=0)])),
            dict(kind='path', layerName='NW1', purpose='drawing', points=[[0, 0], [100, 0]],
                 width=20, mppOwner='ring', net='N', pin=None, props=[])]


def cache_compare(expected, actual):
    aliases = mpp_path_cache_aliases(expected, actual)
    return (via_default_projection(expected, {}, mpp_connectivity=True, mpp_cache_aliases=aliases)[0],
            via_default_projection(actual, {}, mpp_connectivity=True)[0], aliases)


def test_held_mpp_cache_alias_is_opt_in_pairwise_and_preserves_raw_recipe_and_group_links():
    old = mpp_cache_records(); new = copy.deepcopy(old)
    new[1]['mpp']['parts'][0]['netName'] = 'N'
    for rows in (old, new):
        key = next(iter(canonicalize([rows[1]])['objects']))
        rows.append(group('guardring', key))
    expected, actual = canonicalize(old), canonicalize(new)
    original = copy.deepcopy(expected)
    assert via_default_projection(expected, {}, mpp_connectivity=True)[0] != via_default_projection(actual, {}, mpp_connectivity=True)[0]
    left, right, aliases = cache_compare(expected, actual)
    assert left == right
    assert aliases == [dict(mpp='ring', lpp=['NW1', 'drawing'], stored='deleted_net', effective='N')]
    assert expected == original
    assert mpp_path_cache_aliases(actual, expected) == []


@pytest.mark.parametrize('case', [
    'live_recipe_net', 'other_dangling_name', 'no_recipe_net', 'terminal', 'pin',
    'ambiguous_recipe', 'ambiguous_member', 'wrong_member_type', 'absent_effective_net',
    'geometry', 'connectivity', 'property', 'recipe_parameter', 'named_part',
])
def test_cache_comparison_does_not_hide_real_changes_or_ambiguous_recipes(case):
    old = mpp_cache_records(); new = copy.deepcopy(old)
    new[1]['mpp']['parts'][0]['netName'] = 'N'
    if case == 'live_recipe_net':
        for rows in (old, new): rows.append(dict(kind='net', name='deleted_net', props=[]))
    elif case == 'other_dangling_name': new[1]['mpp']['parts'][0]['netName'] = 'different_missing_net'
    elif case == 'no_recipe_net': old[1]['mpp']['parts'][0]['netName'] = None
    elif case == 'terminal':
        for rows in (old, new): rows[1]['mpp']['parts'][0]['termName'] = 'P'
    elif case == 'pin':
        for rows in (old, new): rows[2]['pin'] = {'name': 'P'}
    elif case == 'ambiguous_recipe':
        for rows in (old, new): rows[1]['mpp']['parts'].append(copy.deepcopy(rows[1]['mpp']['parts'][0]))
    elif case == 'ambiguous_member':
        for rows in (old, new): rows.append(copy.deepcopy(rows[2]))
    elif case == 'wrong_member_type':
        for rows in (old, new): rows[2]['kind'] = 'polygon'
    elif case == 'absent_effective_net':
        for rows in (old, new): rows[0]['name'] = 'unrelated'
    elif case == 'geometry': new[2]['points'][0][0] += 1
    elif case == 'connectivity': new[2]['net'] = 'OTHER'
    elif case == 'property': new[2]['props'] = [['sticky', 'boolean', True]]
    elif case == 'recipe_parameter': new[1]['mpp']['parts'][0]['width'] += 1
    elif case == 'named_part': new[1]['mpp']['parts'][0]['name'] = 'custom_name'
    left, right, aliases = cache_compare(canonicalize(old), canonicalize(new))
    assert aliases == []
    assert left != right
