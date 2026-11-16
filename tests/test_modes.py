import copy
import json
import unittest

from modelmate import ModelApprovals, ProbeError
from test_routing import CATALOG, PLAN, POLICY


def proposal(role='standard', effort='low'):
    plan = copy.deepcopy(PLAN)
    plan['steps'][0].update(role=role, effort=effort)
    return plan


class ModeTests(unittest.TestCase):
    def decide(self, controller, plan=None, mode='ask_to_escalate', step_id='step-1', **kwargs):
        return controller.decision(json.dumps(plan or PLAN), CATALOG, POLICY,
                                   mode=mode, step_id=step_id, **kwargs)

    def controller(self):
        return ModelApprovals(CATALOG, POLICY)

    def test_default_is_ask_to_escalate(self):
        result = self.decide(self.controller(), proposal('strong'))
        self.assertEqual(result['state'], 'ask')
        self.assertEqual(result['scope'], 'model')

    def test_mode_matrix_initial_increase_and_downgrade(self):
        for mode in ('auto', 'ask_to_escalate', 'approve_plan'):
            for role, effort in [('standard', 'low'), ('economy', 'low'),
                                 ('strong', 'low'), ('standard', 'medium')]:
                with self.subTest(mode=mode, role=role, effort=effort):
                    result = self.decide(self.controller(), proposal(role, effort), mode)
                    ask = mode == 'approve_plan' or (mode == 'ask_to_escalate' and
                                                    (role == 'strong' or effort == 'medium'))
                    self.assertEqual(result['state'], 'ask' if ask else 'allow_model')
                    self.assertNotIn('tool_permission', result)
                    self.assertEqual(result['selection']['model'], POLICY[role])
                    self.assertTrue(result['reason'])

    def test_valid_grant_avoids_repeated_questions(self):
        for mode in ('ask_to_escalate', 'approve_plan'):
            c = self.controller()
            plan = proposal('strong')
            result = self.decide(c, plan, mode)
            self.assertEqual(self.decide(c, plan, mode)['token'], result['token'])
            c.answer(result['token'], 'approve')
            self.assertEqual(self.decide(c, plan, mode)['state'], 'allow_model')

    def test_changed_plan_invalidates_model_and_plan_grants(self):
        for mode in ('ask_to_escalate', 'approve_plan'):
            for change in ('goal', 'criterion', 'effort', 'role'):
                c = self.controller()
                plan = proposal('strong')
                c.answer(self.decide(c, plan, mode)['token'], 'approve')
                changed = copy.deepcopy(plan)
                if change == 'goal':
                    changed['goal'] += ' changed'
                elif change == 'criterion':
                    changed['success_criteria'].append('new condition')
                elif change == 'effort':
                    changed['steps'][0]['effort'] = 'medium'
                else:
                    changed['steps'][0].update(role='standard', effort='medium')
                self.assertEqual(self.decide(c, changed, mode)['state'], 'ask')

    def test_stale_token_is_rejected_after_plan_or_mode_changes(self):
        for mode in ('auto', 'approve_plan'):
            c = self.controller()
            old = self.decide(c, proposal('strong'))
            self.decide(c, proposal('strong'), mode)
            with self.assertRaises(ProbeError):
                c.answer(old['token'], 'approve')
        c = self.controller()
        old = self.decide(c, proposal('strong'))
        changed = proposal('strong', 'medium')
        self.decide(c, changed)
        with self.assertRaises(ProbeError):
            c.answer(old['token'], 'approve')

    def test_decline_or_pause_never_means_approve(self):
        for choice in ('decline', 'pause'):
            c = self.controller()
            plan = proposal('strong')
            result = self.decide(c, plan)
            c.answer(result['token'], choice)
            paused = self.decide(c, plan)
            self.assertEqual(paused['state'], 'pause')
            self.assertEqual(paused['choices'], ['revise_scope_or_model', 'pause'])
        for choice in ('', None, 'yes', True):
            c = self.controller()
            request = self.decide(c, proposal('strong'))
            with self.assertRaises(ProbeError):
                c.answer(request['token'], choice)
            self.assertEqual(self.decide(c, proposal('strong'))['state'], 'ask')

    def test_task_grants_and_baselines_do_not_leak_to_new_task(self):
        first, second = self.controller(), self.controller()
        plan = proposal('strong')
        first.answer(self.decide(first, plan)['token'], 'approve')
        self.assertNotEqual(first.task_id, second.task_id)
        self.assertEqual(self.decide(second, plan)['state'], 'ask')
        self.assertEqual(first.baseline, second.baseline)

    def test_grant_for_one_step_does_not_authorize_other_step(self):
        c = self.controller()
        plan = proposal('strong')
        plan['steps'].append(copy.deepcopy(plan['steps'][0]))
        c.answer(self.decide(c, plan)['token'], 'approve')
        self.assertEqual(self.decide(c, plan, step_id='step-2', step_index=1)['state'], 'ask')

    def test_plan_grant_covers_all_steps_but_not_changed_bindings(self):
        c = self.controller()
        plan = proposal('strong')
        plan['steps'].append(copy.deepcopy(plan['steps'][0]))
        c.answer(self.decide(c, plan, 'approve_plan')['token'], 'approve')
        self.assertEqual(self.decide(c, plan, 'approve_plan', step_id='step-2', step_index=1)['state'], 'allow_model')
        policy = dict(POLICY, strong=POLICY['economy'])
        result = c.decision(json.dumps(plan), CATALOG, policy, step_id='step-1', mode='approve_plan')
        self.assertEqual(result['state'], 'ask')

    def test_manual_selection_is_step_scoped_and_not_plan_approval(self):
        c = self.controller()
        raw = json.dumps(proposal('strong'))
        result = c.manual_select(raw, CATALOG, POLICY, step_id='step-1')
        self.assertEqual(result['state'], 'allow_model')
        self.assertEqual(c.decision(raw, CATALOG, POLICY, step_id='step-1', mode='approve_plan')['state'], 'ask')
        self.assertNotIn('permissions', result)

    def test_invalid_route_baseline_or_step_pauses_and_discards_pending(self):
        c = self.controller()
        token = self.decide(c, proposal('strong'))['token']
        for kwargs in [{'mode': 'invalid'}, {'step_index': True}, {'step_index': 99}, {'step_id': ''}]:
            self.assertEqual(self.decide(c, proposal('strong'), **kwargs)['state'], 'pause')
        with self.assertRaises(ProbeError):
            c.answer(token, 'approve')
        catalog = [m for m in CATALOG if m['model'] != POLICY['standard']]
        self.assertEqual(c.decision(json.dumps(proposal('strong')), catalog, POLICY, step_id='one')['state'], 'pause')

    def test_unknown_comparative_effort_policy_requires_approval(self):
        c = self.controller()
        catalog = copy.deepcopy(CATALOG)
        catalog[1]['supportedReasoningEfforts'].append({'reasoningEffort': 'future'})
        result = c.decision(json.dumps(proposal('standard', 'future')), catalog, POLICY, step_id='one')
        self.assertEqual(result['state'], 'ask')

    def test_old_grant_does_not_revive_when_plan_changes_back(self):
        for mode in ('ask_to_escalate', 'approve_plan'):
            c = self.controller()
            original = proposal('strong')
            c.answer(self.decide(c, original, mode)['token'], 'approve')
            changed = copy.deepcopy(original)
            changed['goal'] = 'different goal'
            self.decide(c, changed, mode)
            self.assertEqual(self.decide(c, original, mode)['state'], 'ask')

    def test_clarification_invalidates_previous_approval(self):
        c = self.controller()
        original = proposal('strong')
        c.answer(self.decide(c, original)['token'], 'approve')
        unclear = copy.deepcopy(original)
        unclear['clarifications'] = ['Which project?']
        self.assertEqual(self.decide(c, unclear)['state'], 'clarify')
        self.assertEqual(self.decide(c, original)['state'], 'ask')


if __name__ == '__main__':
    unittest.main()
