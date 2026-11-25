import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from modelmate import NativeWorkflowConnection, ProbeError, main, run_plan_draft
from test_native_workflow import SERVER
from test_routing import PLAN


class PlanDraftTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.destination=self.root/'new plan.json'
        self.trace=self.root/'trace'

    def draft(self, answer, *, mode='text', confirmation='START\n', prompt=None, output=None):
        server=SERVER.replace("'SYNTHETIC_ANSWER all tests passed DONE'",repr(answer))
        server=server.replace("if mode=='metrics':", "if mode in ('metrics','text-metrics'):")
        server=server.replace("if mode in ('text','text-only','text-only-fail'):",
                              "if mode in ('text','text-only','text-only-fail','text-metrics','changed-answer'):")
        server=server.replace("  if mode in ('metrics','text-metrics'):",
            "  if mode=='changed-answer':\n"
            "   emit({'method':'item/completed','params':{'threadId':'thread','turnId':str(turn),"
            "'item':{'id':'answer','type':'agentMessage','text':'different completed text'}}})\n"
            "  if mode in ('metrics','text-metrics'):")
        def backend(command):
            return NativeWorkflowConnection([sys.executable,'-u','-c',server,str(self.trace),mode],1)
        with tempfile.TemporaryFile('w+') as source,patch('modelmate.NativeWorkflowConnection',side_effect=backend):
            source.write(confirmation);source.seek(0)
            output=io.StringIO() if output is None else output
            try:
                return run_plan_draft(prompt or PLAN['goal'],'synthetic-standard','low',self.destination,source,output)
            finally:
                self.output=output.getvalue()

    def metrics(self):
        rows=[line.removeprefix('Planning metrics: ') for line in self.output.splitlines()
              if line.startswith('Planning metrics: ')]
        self.assertEqual(len(rows),1)
        return json.loads(rows[0])

    def records(self):
        return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def test_one_confirmed_turn_publishes_valid_private_draft_without_task_dispatch(self):
        self.assertEqual(self.draft(json.dumps(PLAN)),0)
        self.assertEqual(json.loads(self.destination.read_text()),PLAN)
        self.assertEqual(self.destination.stat().st_mode & 0o777,0o600)
        self.assertEqual(list(self.root.glob('.modelmate-draft-*')),[])
        turns=[row for row in self.records() if row.get('method')=='turn/start']
        self.assertEqual(len(turns),1)
        self.assertEqual(turns[0]['params']['model'],'synthetic-standard')
        thread=next(row for row in self.records() if row.get('method')=='thread/start')
        self.assertIs(thread['params']['ephemeral'],True)
        self.assertEqual(thread['params']['approvalPolicy'],'on-request')

    def test_invalid_proposals_never_publish_or_start_a_second_turn(self):
        invalid=['not JSON','```json\n'+json.dumps(PLAN)+'\n```',json.dumps(dict(PLAN,approved=True)),
                 json.dumps(dict(PLAN,goal='different goal')),json.dumps(dict(PLAN,steps=[]))]
        for answer in invalid:
            with self.subTest(answer=answer[:40]),self.assertRaises(ProbeError):
                self.draft(answer)
            self.assertFalse(self.destination.exists())
        self.assertEqual(sum(row.get('method')=='turn/start' for row in self.records()),len(invalid))

    def test_clarifications_remain_unanswered_in_draft(self):
        plan=copy.deepcopy(PLAN);plan['clarifications']=['Which scope?']
        self.assertEqual(self.draft(json.dumps(plan)),0)
        self.assertEqual(json.loads(self.destination.read_text())['clarifications'],['Which scope?'])
        self.assertEqual(sum(row.get('method')=='turn/start' for row in self.records()),1)

    def test_cancellation_and_existing_destination_do_not_connect(self):
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('no connect')):
            for text in ('','CANCEL\n','START'):
                with tempfile.TemporaryFile('w+') as source:
                    source.write(text);source.seek(0)
                    self.assertEqual(run_plan_draft(PLAN['goal'],'synthetic-standard','low',self.destination,source,io.StringIO()),2)
            self.destination.write_bytes(b'original')
            with self.assertRaises(ProbeError):
                run_plan_draft(PLAN['goal'],'synthetic-standard','low',self.destination,io.StringIO(),io.StringIO())
        self.assertEqual(self.destination.read_bytes(),b'original')

    def test_missing_quota_wrong_account_or_permissions_never_dispatch(self):
        for mode in ('unknown','api','permissions'):
            with self.subTest(mode=mode),self.assertRaises(ProbeError):
                self.draft(json.dumps(PLAN),mode=mode)
            self.assertFalse(self.destination.exists())
        self.assertFalse(any(row.get('method')=='turn/start' for row in self.records()))

    def test_oversized_and_goal_changed_output_is_rejected(self):
        for answer in ('x'*65537,json.dumps(dict(PLAN,goal='changed'))):
            with self.subTest(length=len(answer)),self.assertRaises(ProbeError):self.draft(answer)
            self.assertFalse(self.destination.exists())

    def test_maximum_goal_is_not_duplicated_into_instruction_limit(self):
        plan=copy.deepcopy(PLAN);plan['goal']='x'*4096
        self.assertEqual(self.draft(json.dumps(plan),prompt=plan['goal']),0)
        self.assertEqual(json.loads(self.destination.read_text())['goal'],plan['goal'])

    def test_cli_requires_prompt_and_selected_model_and_forwards_arguments(self):
        for args in (['--draft-plan','new.json'],['--draft-plan','new.json','goal']):
            with patch('sys.argv',['modelmate.py',*args]),patch('sys.stderr',new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as caught:main()
                self.assertEqual(caught.exception.code,2)
        with patch('sys.argv',['modelmate.py','--draft-plan','new.json','--model','synthetic-standard','goal']),patch('modelmate.run_plan_draft',return_value=0) as draft:
            self.assertEqual(main(),0)
            self.assertEqual(draft.call_args.args[:4],('goal','synthetic-standard','low','new.json'))

    def test_late_destination_creation_never_overwrites_and_cleans_snapshot(self):
        def competing_publish(source,destination):
            Path(destination).write_bytes(b'other writer')
            raise FileExistsError('already exists')
        with patch('modelmate.os.link',side_effect=competing_publish),self.assertRaises(FileExistsError):
            self.draft(json.dumps(PLAN))
        self.assertEqual(self.destination.read_bytes(),b'other writer')
        self.assertEqual(list(self.root.glob('.modelmate-draft-*')),[])
        self.assertEqual(sum(row.get('method')=='turn/start' for row in self.records()),1)

    def test_disconnect_does_not_publish_or_replay(self):
        with self.assertRaises(ProbeError):self.draft(json.dumps(PLAN),mode='disconnect')
        self.assertFalse(self.destination.exists())
        self.assertEqual(sum(row.get('method')=='turn/start' for row in self.records()),1)

    def test_conflicting_completed_item_does_not_publish_or_replay(self):
        with self.assertRaisesRegex(ProbeError,'changed after completion'):
            self.draft(json.dumps(PLAN),mode='changed-answer')
        self.assertFalse(self.destination.exists())
        self.assertFalse(self.metrics()['proposalSaved'])
        self.assertEqual(sum(row.get('method')=='turn/start' for row in self.records()),1)

    def test_missing_usage_stays_unknown_without_prompt_or_native_ids(self):
        self.assertEqual(self.draft(json.dumps(PLAN)),0)
        report=self.metrics()
        self.assertTrue(report['proposalSaved'])
        self.assertIsNone(report['tokenUsage'])
        self.assertIsNone(report['tokenUsageScope'])
        self.assertNotIn(PLAN['goal'],json.dumps(report,ensure_ascii=False))
        self.assertNotIn('threadId',json.dumps(report))
        self.assertNotIn('accountId',json.dumps(report))
        self.assertEqual(report['planningTurnMeasurements'][0]['terminalStatus'],'completed')

    def test_observed_usage_and_reroute_are_not_requested_model_guesses(self):
        self.assertEqual(self.draft(json.dumps(PLAN),mode='text-metrics'),0)
        report=self.metrics()
        self.assertEqual(report['tokenUsage']['last']['totalTokens'],11)
        self.assertEqual(report['tokenUsage']['last']['cachedInputTokens'],3)
        self.assertEqual(report['requestedSelection']['model'],'synthetic-standard')
        self.assertEqual(report['planningTurnMeasurements'][0]['modelReroutes'],[
            dict(fromModel='synthetic-standard',toModel='synthetic-fallback')])
        records=self.records();start=next(i for i,row in enumerate(records) if row.get('method')=='turn/start')
        self.assertFalse(any(row.get('method') in ('account/read','account/rateLimits/read') for row in records[start+1:]))

    def test_invalid_proposal_is_distinct_from_native_completed_status(self):
        with self.assertRaises(ProbeError):self.draft('not JSON')
        report=self.metrics()
        self.assertFalse(report['proposalSaved'])
        self.assertEqual(report['planningTurnMeasurements'][0]['terminalStatus'],'completed')
        self.assertFalse(self.destination.exists())

    def test_metrics_write_error_does_not_lose_published_draft(self):
        class BrokenMetrics(io.StringIO):
            def write(self,text):
                if text.startswith('Planning metrics: '):raise OSError('synthetic output failure')
                return super().write(text)
        self.assertEqual(self.draft(json.dumps(PLAN),output=BrokenMetrics()),0)
        self.assertEqual(json.loads(self.destination.read_text()),PLAN)
        self.assertEqual(sum(row.get('method')=='turn/start' for row in self.records()),1)
