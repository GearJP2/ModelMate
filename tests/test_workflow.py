"""Offline controller tests; evidence adapters are trusted host inputs, not live tools."""
import copy
import json
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from modelmate import ProbeError, WorkflowController
from test_routing import CATALOG, PLAN, POLICY, QUOTA


class WorkflowTests(unittest.TestCase):
    def controller(self, plan=None, mode='ask_to_escalate'):
        return WorkflowController(json.dumps(plan or PLAN), CATALOG, POLICY, mode)

    def begin(self, controller, quota=None, catalog=None, policy=None):
        return controller.request_attempt(QUOTA if quota is None else quota, time.monotonic(),
                                          CATALOG if catalog is None else catalog,
                                          POLICY if policy is None else policy)

    def check_attempt(self, controller, exit_code=0):
        state = self.begin(controller)
        self.assertIn('dispatch', state)
        aid = state['dispatch']['attempt_id']
        index = state['step_index']
        controller.finish_attempt(aid, 'completed')
        evidence = []
        for check_index, check in enumerate(state['dispatch']['step']['checks']):
            kind = check['kind']
            evidence.append(controller.record_check(aid, check_index,
                origin='tool' if kind in ('test', 'lint') else 'source' if kind == 'source' else 'manual',
                result='pass', exit_code=exit_code if kind in ('test', 'lint') else None,
                reference='https://example.org/synthetic' if kind == 'source' else 'synthetic host check',
                finding='Host checked criterion for step ' + str(index)))
        return controller.evaluate_attempt(aid), evidence

    def test_simple_code_uses_observed_process_exit_then_explicit_criterion_coverage(self):
        c = self.controller()
        observed = subprocess.run([sys.executable, '-c', 'raise SystemExit(0)'], timeout=5)
        result, evidence = self.check_attempt(c, observed.returncode)
        self.assertEqual(result['state'], 'CHECKING')
        self.assertEqual(c.finish_task({})['state'], 'UNVERIFIED')
        coverage = {0: [evidence[0]['id']]}
        done = c.finish_task(coverage)
        self.assertEqual(done['state'], 'DONE')
        self.assertEqual(done['criterion_evidence'], coverage)
        self.assertEqual(len(done['history']), 1)

    def test_valid_large_thai_plan_is_not_inflated_beyond_json_limit(self):
        plan = copy.deepcopy(PLAN)
        plan['goal'] = 'ก' * 4096
        plan['steps'][0].update(objective='ข' * 4096, reason='ค' * 4096)
        raw = json.dumps(plan, ensure_ascii=False)
        self.assertLess(len(raw.encode()), 65536)
        self.assertGreater(len(json.dumps(plan, ensure_ascii=True).encode()), 65536)
        c = WorkflowController(raw, CATALOG, POLICY)
        self.check_attempt(c, 1)
        plan['steps'][0]['objective'] = 'ง' * 4096
        c.revise_step(json.dumps(plan, ensure_ascii=False))
        self.assertEqual(self.begin(c)['state'], 'RUNNING')

    def test_plan_implement_and_strong_review_walk_in_order_with_stable_ids(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'] = [dict(copy.deepcopy(PLAN['steps'][0]), kind=kind,
                              role='strong' if kind == 'review' else 'standard')
                         for kind in ('plan', 'implement', 'review')]
        plan['steps'][1]['risk'] = 'high'
        c = self.controller(plan, 'auto')
        ids = [step['id'] for step in c.snapshot()['steps']]
        self.assertEqual(len(set(ids)), 3)
        for index in range(3):
            result, evidence = self.check_attempt(c)
            self.assertEqual(result['history'][-1]['step_id'], ids[index])
        self.assertEqual(c.finish_task({0: [evidence[0]['id']]})['state'], 'DONE')
        self.assertTrue(all(step['attempts'] == 1 for step in result['steps']))

    def test_document_task_uses_host_rubric_and_verified_source_findings(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['checks'] = [{'kind': 'rubric', 'criterion': 'ตอบครบทุกข้อ'},
                                      {'kind': 'source', 'criterion': 'แหล่งข้อมูลรองรับข้ออ้าง'}]
        c = self.controller(plan)
        _, evidence = self.check_attempt(c)
        self.assertEqual([e['origin'] for e in evidence], ['manual', 'source'])
        self.assertEqual(c.finish_task({0: [e['id'] for e in evidence]})['state'], 'DONE')

    def test_initial_plus_two_corrections_then_pause_without_hidden_fourth_attempt(self):
        c = self.controller()
        observed = subprocess.run([sys.executable, '-c', 'raise SystemExit(1)'], timeout=5)
        for number in (1, 2, 3):
            state, _ = self.check_attempt(c, observed.returncode)
            self.assertEqual(state['steps'][0]['attempts'], number)
            self.assertEqual(state['history'][-1]['number'], number)
        self.assertEqual(state['reason'], 'correction_limit')
        self.assertEqual(state['choices'], ['continue', 'revise_scope', 'pause'])
        self.assertNotIn('dispatch', self.begin(c))
        self.assertEqual(len(c.snapshot()['history']), 3)

    def test_user_extends_budget_explicitly_and_old_cycle_remains_in_ledger(self):
        c = self.controller()
        for _ in range(3):state, _ = self.check_attempt(c, 1)
        token = state['pause_token']
        with self.assertRaises(ProbeError):c.answer_pause('stale', 'continue')
        c.answer_pause(token, 'continue')
        with self.assertRaises(ProbeError):c.answer_pause(token, 'continue')
        next_attempt = self.begin(c)
        self.assertEqual(next_attempt['steps'][0]['cycle'], 1)
        self.assertEqual(next_attempt['steps'][0]['attempts'], 1)
        self.assertEqual([item['number'] for item in next_attempt['history'] if 'number' in item], [1, 2, 3])
        self.assertEqual(next_attempt['history'][-1]['kind'], 'budget_extension')

    def test_renaming_or_revising_scope_never_resets_attempt_identity_or_budget(self):
        c = self.controller()
        self.check_attempt(c, 1)
        before = c.snapshot()['steps'][0]
        plan = copy.deepcopy(PLAN);plan['steps'][0]['objective'] = 'renamed by proposal'
        after = c.revise_step(json.dumps(plan))['steps'][0]
        self.assertEqual((after['id'], after['attempts']), (before['id'], 1))
        for _ in range(2):state, _ = self.check_attempt(c, 1)
        revised = c.answer_pause(state['pause_token'], 'revise_scope')
        c.revise_step(json.dumps(plan))
        c.answer_pause(c.snapshot()['pause_token'], 'continue')
        self.assertEqual(self.begin(c)['reason'], 'correction_limit')
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 3)
        self.assertEqual(revised['steps'][0]['id'], before['id'])

    def test_model_or_effort_change_repeats_gate_and_stale_tokens_cannot_approve(self):
        c = self.controller()
        self.check_attempt(c, 1)
        plan = copy.deepcopy(PLAN);plan['steps'][0]['role'] = 'strong'
        c.revise_step(json.dumps(plan))
        request = self.begin(c)
        self.assertEqual(request['state'], 'AWAITING_MODEL_APPROVAL')
        self.assertEqual(request['steps'][0]['attempts'], 1)
        old = request['model_request']['token']
        plan['steps'][0]['effort'] = 'medium'
        c.revise_step(json.dumps(plan))
        with self.assertRaises(ProbeError):c.answer_model(old, 'approve')
        request = self.begin(c)
        c.answer_model(request['model_request']['token'], 'approve')
        running = self.begin(c)
        self.assertEqual(running['steps'][0]['attempts'], 2)
        self.assertEqual(running['dispatch']['selection'], {'model': POLICY['strong'], 'effort': 'medium'})
        self.assertEqual(running['dispatch']['tool_permissions'], 'none')

    def test_approve_plan_covers_unchanged_steps_but_each_attempt_checks_quota_again(self):
        plan = copy.deepcopy(PLAN);plan['steps'].append(copy.deepcopy(plan['steps'][0]))
        c = self.controller(plan, 'approve_plan')
        request = self.begin(c)
        self.assertEqual(request['steps'][0]['attempts'], 0)
        c.answer_model(request['model_request']['token'], 'approve')
        self.check_attempt(c)
        exhausted = self.begin(c, dict(QUOTA, ordinaryUsageAllowed=False))
        self.assertEqual(exhausted['state'], 'PAUSED')
        self.assertEqual(exhausted['steps'][1]['attempts'], 0)

    def test_unknown_stale_changed_account_or_missing_model_cannot_start(self):
        for quota in ({}, dict(QUOTA, ordinaryUsageAllowed=False)):
            c = self.controller()
            self.assertEqual(self.begin(c, quota)['state'], 'PAUSED')
            self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)
        c = self.controller()
        self.assertEqual(c.request_attempt(QUOTA, time.monotonic() - 16, CATALOG, POLICY)['reason'], 'quota_stale')
        c = self.controller();self.check_attempt(c, 1)
        self.assertEqual(self.begin(c, dict(QUOTA, accountId='changed'))['reason'], 'account_changed')
        c = self.controller()
        self.assertEqual(self.begin(c, catalog=[])['state'], 'PAUSED')

    def test_quota_exhausted_mid_attempt_waits_for_terminal_event_and_never_replays(self):
        c = self.controller();running = self.begin(c);aid = running['dispatch']['attempt_id']
        paused = c.observe_quota(dict(QUOTA, ordinaryUsageAllowed=False), time.monotonic())
        self.assertEqual(paused['state'], 'PAUSED')
        with self.assertRaisesRegex(ProbeError, 'unknown'):c.answer_pause(paused['pause_token'], 'continue')
        interrupted = c.finish_attempt(aid, 'interrupted')
        self.assertEqual(interrupted['reason'], 'outcome_unknown')
        self.assertEqual(interrupted['steps'][0]['attempts'], 1)
        c.answer_pause(interrupted['pause_token'], 'continue')
        self.assertEqual(self.begin(c)['steps'][0]['attempts'], 2)

    def test_missing_checks_and_model_test_claims_are_unverified_not_done(self):
        for model_claim in (False, True):
            c = self.controller();running = self.begin(c);aid = running['dispatch']['attempt_id']
            c.finish_attempt(aid, 'completed')
            if model_claim:
                evidence = c.record_check(aid, 0, origin='model_review', result='pass',
                    reference='model review', finding='The model claims all tests passed')
                self.assertEqual(evidence['result'], 'unknown')
            self.assertEqual(c.evaluate_attempt(aid)['state'], 'UNVERIFIED')
            self.assertNotIn('dispatch', self.begin(c))

    def test_exit_code_overrides_claimed_success_and_boolean_codes_are_rejected(self):
        c = self.controller();aid = self.begin(c)['dispatch']['attempt_id'];c.finish_attempt(aid, 'completed')
        with self.assertRaises(ProbeError):
            c.record_check(aid, 0, origin='tool', exit_code=True, reference='check', finding='check')
        evidence = c.record_check(aid, 0, origin='tool', result='pass', exit_code=1, reference='check', finding='failed')
        self.assertEqual(evidence['result'], 'fail')
        self.assertEqual(c.evaluate_attempt(aid)['reason'], 'checks_failed')

    def test_stale_duplicate_or_out_of_phase_evidence_is_rejected(self):
        c = self.controller();aid = self.begin(c)['dispatch']['attempt_id']
        args = dict(origin='tool', exit_code=0, reference='check', finding='passed')
        with self.assertRaises(ProbeError):c.record_check(aid, 0, **args)
        c.finish_attempt(aid, 'completed')
        for attempt, index in [('wrong', 0), (aid, True), (aid, 99)]:
            with self.assertRaises(ProbeError):c.record_check(attempt, index, **args)
        c.record_check(aid, 0, **args)
        with self.assertRaises(ProbeError):c.record_check(aid, 0, **args)
        c.evaluate_attempt(aid)
        with self.assertRaises(ProbeError):c.evaluate_attempt(aid)

    def test_criteria_cannot_reference_old_failed_attempt_or_fabricated_evidence(self):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['checks'] *= 2
        c = self.controller(plan);aid = self.begin(c)['dispatch']['attempt_id'];c.finish_attempt(aid, 'completed')
        old = c.record_check(aid, 0, origin='tool', exit_code=0, reference='check', finding='passed')
        c.record_check(aid, 1, origin='tool', exit_code=1, reference='check', finding='failed')
        c.evaluate_attempt(aid)
        _, current = self.check_attempt(c)
        for ids in ([old['id']], ['model says DONE']):
            with self.assertRaises(ProbeError):c.finish_task({0: ids})
        self.assertEqual(c.finish_task({0: [e['id'] for e in current]})['state'], 'DONE')

    def test_untrusted_plan_cannot_inject_permissions_status_ids_or_reset_fields(self):
        for key in ('status', 'retry_count', 'step_id', 'permissions'):
            plan = copy.deepcopy(PLAN);plan['steps'][0][key] = 'override'
            with self.assertRaises(ProbeError):self.controller(plan)
        c = self.controller()
        for change in ('goal', 'steps', 'checks'):
            plan = copy.deepcopy(PLAN)
            if change == 'goal':plan['goal'] = 'new task'
            elif change == 'steps':plan['steps'] *= 2
            else:plan['steps'][0]['checks'][0]['criterion'] = 'easier criterion'
            with self.assertRaises(ProbeError):c.revise_step(json.dumps(plan))

    def test_snapshots_do_not_mutate_controller_and_controller_starts_no_process(self):
        with patch('modelmate.subprocess.Popen') as spawn:
            c = self.controller();state = self.begin(c)
            state['steps'][0]['attempts'] = 0
            state['dispatch']['step']['objective'] = 'mutated externally'
            self.assertEqual(c.snapshot()['steps'][0]['attempts'], 1)
            self.assertEqual(state['dispatch']['execution'], 'not_dispatched')
            spawn.assert_not_called()

    def test_execution_failure_and_clarification_never_mean_done(self):
        c = self.controller();aid = self.begin(c)['dispatch']['attempt_id']
        self.assertEqual(c.finish_attempt(aid, 'failed')['state'], 'FAILED')
        with self.assertRaises(ProbeError):c.finish_task({0: ['invented']})
        plan = copy.deepcopy(PLAN);plan['clarifications'] = ['Which scope?']
        c = self.controller(plan)
        self.assertEqual(self.begin(c)['state'], 'CLARIFYING')
        self.assertEqual(c.snapshot()['steps'][0]['attempts'], 0)

    def test_declined_model_never_consumes_a_slot_or_grants_tools(self):
        plan = copy.deepcopy(PLAN);plan['steps'][0]['role'] = 'strong'
        c = self.controller(plan);request = self.begin(c)
        paused = c.answer_model(request['model_request']['token'], 'decline')
        self.assertEqual(paused['state'], 'PAUSED')
        self.assertEqual(paused['steps'][0]['attempts'], 0)
        self.assertNotIn('dispatch', self.begin(c))

    def test_correction_budget_belongs_to_each_step_not_the_whole_task(self):
        plan = copy.deepcopy(PLAN);plan['steps'].append(copy.deepcopy(plan['steps'][0]))
        c = self.controller(plan)
        self.check_attempt(c, 1);self.check_attempt(c, 1);self.check_attempt(c, 0)
        second = self.begin(c)
        self.assertEqual(second['step_index'], 1)
        self.assertEqual([step['attempts'] for step in second['steps']], [3, 1])
        self.assertEqual(second['active_attempt']['number'], 1)

    def test_pausing_checks_requires_explicit_choice_but_does_not_reexecute_attempt(self):
        c = self.controller();aid = self.begin(c)['dispatch']['attempt_id']
        c.finish_attempt(aid, 'completed')
        paused = c.pause()
        c.answer_pause(paused['pause_token'], 'continue')
        self.assertEqual(c.snapshot()['state'], 'CHECKING')
        self.assertNotIn('dispatch', self.begin(c))
        self.assertEqual(c.snapshot()['active_attempt']['id'], aid)
        self.assertEqual(c.snapshot()['history'][-1]['kind'], 'user_choice')

    def test_all_task_criteria_require_explicit_accepted_coverage(self):
        plan = copy.deepcopy(PLAN);plan['success_criteria'].append('second criterion')
        c = self.controller(plan);_, evidence = self.check_attempt(c)
        eid = evidence[0]['id']
        self.assertEqual(c.finish_task({0: [eid]})['state'], 'UNVERIFIED')
        for coverage in ({True: [eid]}, {99: [eid]}, {0: []}, {'0': [eid]}):
            with self.assertRaises(ProbeError):c.finish_task(coverage)
        self.assertEqual(c.finish_task({0: [eid], 1: [eid]})['state'], 'DONE')

    def test_source_evidence_needs_valid_url_and_finding_and_model_rubric_is_unknown(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['checks'] = [{'kind': 'source', 'criterion': 'claim supported'},
                                      {'kind': 'rubric', 'criterion': 'all points covered'}]
        c = self.controller(plan);aid = self.begin(c)['dispatch']['attempt_id'];c.finish_attempt(aid, 'completed')
        for reference, finding in [('file:///private', 'claim'), ('https://example.org', ''), ('http://[', 'claim')]:
            with self.assertRaises(ProbeError):
                c.record_check(aid, 0, origin='source', result='pass', reference=reference, finding=finding)
        c.record_check(aid, 0, origin='source', result='pass', reference='https://example.org', finding='host verified claim')
        model = c.record_check(aid, 1, origin='model_review', result='pass', reference='model', finding='claims complete')
        self.assertEqual(model['result'], 'unknown')
        self.assertEqual(c.evaluate_attempt(aid)['state'], 'UNVERIFIED')


if __name__ == '__main__':
    unittest.main()
