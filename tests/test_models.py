import copy
import unittest
from unittest.mock import Mock

from modelmate import (MODEL_ROLE_POLICY, ProbeError, model_change_requires_approval,
                       read_models, select_model, select_role)


def entry(name='test-standard', efforts=('low', 'medium', 'high'), default='medium', **extra):
    return dict(model=name, defaultReasoningEffort=default,
                supportedReasoningEfforts=[{'reasoningEffort': e} for e in efforts], **extra)


CATALOG = [entry('test-economy'), entry('test-standard'), entry('test-strong')]
POLICY = {'economy': 'test-economy', 'standard': 'test-standard', 'strong': 'test-strong'}


class CatalogTests(unittest.TestCase):
    def test_pagination_filters_hidden_models_and_private_fields(self):
        connection = Mock()
        connection.request.side_effect = [
            {'data': [entry('first', private='secret'), entry('hidden', hidden=True)], 'nextCursor': 'next'},
            {'data': [entry('second')]},
        ]
        catalog = read_models(connection)
        self.assertEqual([m['model'] for m in catalog], ['first', 'second'])
        self.assertNotIn('private', catalog[0])
        self.assertEqual(connection.request.call_args.args, ('model/list', {'limit': 100, 'cursor': 'next'}))

    def test_bad_pages_entries_cursors_duplicates_and_cycles_fail(self):
        cases = [
            [{'data': None}], [{'data': [None]}], [{'data': [{'model': ''}]}],
            [{'data': [entry(hidden='false')]}], [{'data': [], 'nextCursor': []}],
            [{'data': [], 'nextCursor': ''}],
            [{'data': [entry('same')], 'nextCursor': 'next'}, {'data': [entry('same')]}],
            [{'data': [], 'nextCursor': 'same'}, {'data': [], 'nextCursor': 'same'}],
        ]
        for pages in cases:
            with self.subTest(pages=pages):
                connection = Mock()
                connection.request.side_effect = pages
                with self.assertRaises(ProbeError):
                    read_models(connection)

    def test_read_models_refreshes_instead_of_reusing_old_catalog(self):
        connection = Mock()
        connection.request.side_effect = [{'data': [entry('old')]}, {'data': [entry('new')]}]
        old = select_model(read_models(connection), 'old')
        refreshed = read_models(connection)
        with self.assertRaises(ProbeError):
            select_model(refreshed, old['model'], old['effort'])
        self.assertEqual(select_model(refreshed, 'new')['model'], 'new')


class SelectionTests(unittest.TestCase):
    def test_manual_selection_uses_catalog_default_or_explicit_effort(self):
        self.assertEqual(select_model(CATALOG, 'test-standard'), {'model': 'test-standard', 'effort': 'medium'})
        self.assertEqual(select_model(CATALOG, 'test-standard', 'low')['effort'], 'low')

    def test_unknown_model_can_be_manually_selected_without_invented_role(self):
        catalog = [entry('unrecognized-model')]
        self.assertEqual(select_model(catalog, 'unrecognized-model')['model'], 'unrecognized-model')
        self.assertEqual(MODEL_ROLE_POLICY, {})
        with self.assertRaisesRegex(ProbeError, 'unassigned'):
            select_role(catalog, 'strong')

    def test_all_role_bindings_are_explicit_and_catalog_validated(self):
        for role, name in POLICY.items():
            self.assertEqual(select_role(CATALOG, role, POLICY)['model'], name)
        for role, policy in [('other', POLICY), ('standard', {}), ('strong', {'strong': 'missing'}),
                             ('standard', {'wrong': 'test-standard'}), ('strong', {'strong': 1})]:
            with self.subTest(role=role, policy=policy), self.assertRaises(ProbeError):
                select_role(CATALOG, role, policy)

    def test_unsupported_hidden_duplicate_and_malformed_selections_fail(self):
        cases = [([entry()], 'missing', None), ([entry(hidden=True)], 'test-standard', None),
                 ([entry(hidden=0)], 'test-standard', None),
                 ([entry(), entry()], 'test-standard', None),
                 ([entry()], 'test-standard', 'max'),
                 ([entry(efforts=(), default='medium')], 'test-standard', None),
                 ([entry(efforts=('low', 'low'))], 'test-standard', None),
                 ([entry(default='unsupported')], 'test-standard', None)]
        bad = entry()
        bad['supportedReasoningEfforts'] = [None]
        cases.append(([bad], 'test-standard', 'low'))
        for catalog, model, effort in cases:
            with self.subTest(catalog=catalog, effort=effort), self.assertRaises(ProbeError):
                select_model(catalog, model, effort)

    def test_selection_does_not_mutate_catalog_or_policy(self):
        catalog, policy = copy.deepcopy(CATALOG), dict(POLICY)
        select_role(catalog, 'standard', policy, 'low')
        self.assertEqual(catalog, CATALOG)
        self.assertEqual(policy, POLICY)


class ComparisonTests(unittest.TestCase):
    def selection(self, model='test-standard', effort='medium'):
        return {'model': model, 'effort': effort}

    def test_same_model_increase_asks_lower_or_equal_does_not(self):
        old = self.selection()
        for effort, expected in [('low', False), ('medium', False), ('high', True)]:
            self.assertEqual(model_change_requires_approval(old, self.selection(effort=effort)), expected)

    def test_unknown_models_or_effort_order_always_ask(self):
        old = self.selection()
        self.assertTrue(model_change_requires_approval(old, self.selection(model='new')))
        self.assertTrue(model_change_requires_approval(old, self.selection(effort='future')))
        self.assertTrue(model_change_requires_approval(None, old))
        self.assertTrue(model_change_requires_approval(old, {'model': 'x', 'effort': []}))

    def test_reviewed_role_policy_allows_only_non_increasing_changes(self):
        old = self.selection()
        self.assertFalse(model_change_requires_approval(old, self.selection('test-economy', 'low'), POLICY))
        self.assertTrue(model_change_requires_approval(old, self.selection('test-strong', 'low'), POLICY))
        self.assertTrue(model_change_requires_approval(old, self.selection('test-economy', 'high'), POLICY))

    def test_ambiguous_or_invalid_mapping_cannot_bypass_approval(self):
        old, new = self.selection(), self.selection('test-economy', 'low')
        for policy in [{}, {'economy': 'test-standard', 'standard': 'test-standard', 'strong': 'test-economy'},
                       {'invalid': 'test-economy'}, None]:
            self.assertTrue(model_change_requires_approval(old, new, policy))


if __name__ == '__main__':
    unittest.main()
