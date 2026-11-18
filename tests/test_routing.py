import copy
import json
import unittest

from modelmate import ProbeError, routing_decision, validate_plan


CATALOG = [{'model': 'synthetic-' + role, 'defaultReasoningEffort': 'low',
            'supportedReasoningEfforts': [{'reasoningEffort': 'low'}, {'reasoningEffort': 'medium'}]}
           for role in ('economy', 'standard', 'strong')]
POLICY = {r: 'synthetic-' + r for r in ('economy', 'standard', 'strong')}
PLAN = {'version': 1, 'goal': 'เพิ่มการค้นหา', 'clarifications': [],
        'success_criteria': ['ค้นหาพบและไม่พบได้ถูกต้อง'],
        'steps': [{'kind': 'implement', 'objective': 'เพิ่มการค้นหา', 'role': 'standard',
                   'effort': 'low', 'risk': 'normal', 'reason': 'ขอบเขตจำกัดและตรวจผลได้',
                   'checks': [{'kind': 'test', 'criterion': 'กรณีพบและไม่พบผ่าน'}]}]}
QUOTA = {'accountId': 'synthetic', 'ordinaryUsageAllowed': True,
         'rateLimits': {'primary': {'usedPercent': 10}}}


def encoded(plan):
    return json.dumps(plan, ensure_ascii=False)


class PlanTests(unittest.TestCase):
    def test_simple_task_needs_no_forced_plan_or_strong_review(self):
        result = routing_decision(encoded(PLAN), CATALOG, POLICY)
        self.assertEqual(result['state'], 'ready_for_approval')
        self.assertEqual(len(result['plan']['steps']), 1)
        self.assertEqual(result['selections'], [{'model': 'synthetic-standard', 'effort': 'low'}])
        self.assertNotIn('permissions', result)

    def test_high_risk_requires_strong_review_with_checks(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['risk'] = 'high'
        with self.assertRaisesRegex(ProbeError, 'strong review'):
            validate_plan(encoded(plan))
        review = copy.deepcopy(PLAN['steps'][0])
        review.update(kind='review', role='strong')
        plan['steps'].append(review)
        self.assertEqual(routing_decision(encoded(plan), CATALOG, POLICY)['state'], 'ready_for_approval')

    def test_document_work_accepts_rubric_and_source_checks(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['checks'] = [{'kind': 'rubric', 'criterion': 'ตอบทุกข้อ'},
                                      {'kind': 'source', 'criterion': 'แหล่งข้อมูลรองรับข้ออ้าง'}]
        self.assertEqual(routing_decision(encoded(plan), CATALOG, POLICY)['state'], 'ready_for_approval')

    def test_strong_review_before_high_risk_work_does_not_satisfy_review_requirement(self):
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['risk'] = 'high'
        plan['steps'].insert(0, dict(copy.deepcopy(PLAN['steps'][0]), kind='review', role='strong'))
        with self.assertRaisesRegex(ProbeError, 'follow'):
            validate_plan(encoded(plan))

    def test_clarifications_prevent_step_selection(self):
        plan = copy.deepcopy(PLAN)
        plan['clarifications'] = ['ต้องค้นหาคอลัมน์ใด?']
        result = routing_decision(encoded(plan), [], {})
        self.assertEqual(result['state'], 'clarify')
        self.assertEqual(result['selections'], [])

    def test_unknown_fields_cannot_grant_permissions_or_reset_counters(self):
        for field in ['permissions', 'retry_count', 'status', 'shell_command', 'model', 'task_id']:
            for target in ['plan', 'step', 'check']:
                plan = copy.deepcopy(PLAN)
                destination = {'plan': plan, 'step': plan['steps'][0], 'check': plan['steps'][0]['checks'][0]}[target]
                destination[field] = 'ignore approvals'
                with self.subTest(field=field, target=target):
                    self.assertEqual(routing_decision(encoded(plan), CATALOG, POLICY)['state'], 'pause')

    def test_schema_limits_and_invalid_values_are_rejected(self):
        cases = []
        for field, value in [('version', True), ('version', 2), ('goal', ''),
                             ('clarifications', 'question'), ('success_criteria', []),
                             ('steps', []), ('steps', PLAN['steps'] * 13)]:
            plan = copy.deepcopy(PLAN)
            plan[field] = value
            cases.append(plan)
        for field, value in [('kind', 'execute'), ('role', 'admin'), ('risk', 'safe'),
                             ('objective', ''), ('reason', 'x' * 4097), ('checks', []), ('effort', [])]:
            plan = copy.deepcopy(PLAN)
            plan['steps'][0][field] = value
            cases.append(plan)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(ProbeError):
                validate_plan(encoded(plan))

    def test_invalid_json_duplicate_keys_and_size_are_rejected(self):
        cases = ['not json', '```json\n{}\n```', '[]',
                 '{"version":1,"version":1}', '{"goal":NaN}', 'x' * 65537,
                 '[' * 2000, '\ud800']
        for raw in cases:
            with self.subTest(raw=raw[:40]), self.assertRaises(ProbeError):
                validate_plan(raw)

    def test_missing_mapping_or_unsupported_effort_pauses(self):
        self.assertEqual(routing_decision(encoded(PLAN), CATALOG, {})['state'], 'pause')
        plan = copy.deepcopy(PLAN)
        plan['steps'][0]['effort'] = 'max'
        self.assertEqual(routing_decision(encoded(plan), CATALOG, POLICY)['state'], 'pause')

    def test_input_is_not_mutated(self):
        plan = copy.deepcopy(PLAN)
        raw = encoded(plan)
        result = validate_plan(raw)
        result['goal'] = 'changed'
        self.assertEqual(plan, PLAN)


if __name__ == '__main__':
    unittest.main()
