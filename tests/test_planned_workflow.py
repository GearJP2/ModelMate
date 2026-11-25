import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from modelmate import NativeWorkflowConnection, main
from test_native_workflow import SERVER
from test_routing import PLAN


class PlannedWorkflowTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.path=self.root/'planned workflow.json'
        self.plan=copy.deepcopy(PLAN)
        self.plan['steps'][0]['checks']=[dict(kind='manual',criterion='User checks output')]
        self.traces=[]

    def invoke(self, text, *, execute=True, chat=None, answer=None, bindings=None):
        args=['modelmate.py','--plan-workflow',str(self.path),'--model','synthetic-strong',self.plan['goal']]
        for binding in bindings if bindings is not None else ['standard=synthetic-standard']:
            args+=['--role-model',binding]
        if execute:args+=['--execute-workflow']
        def backend(command,timeout=15):
            trace=self.root/('trace-'+str(len(self.traces)));self.traces.append(trace)
            server=SERVER.replace("'SYNTHETIC_ANSWER all tests passed DONE'",repr(answer if answer is not None else json.dumps(self.plan)))
            return NativeWorkflowConnection([sys.executable,'-u','-c',server,str(trace),'text'],1)
        with tempfile.TemporaryFile('w+') as source,patch.dict(os.environ,{'XDG_STATE_HOME':str(self.root/'state')}),patch('sys.argv',args),patch('sys.stdin',source),patch('sys.stdout',new_callable=io.StringIO),patch('sys.stderr',new_callable=io.StringIO),patch('modelmate.NativeWorkflowConnection',side_effect=backend),patch('modelmate.run_chat',side_effect=chat or (lambda *a,**k:0)):
            source.write(text);source.seek(0)
            result=main()
            remaining=os.read(source.fileno(),65536)
        return result,remaining

    def turns(self):
        return [row for path in self.traces for row in map(json.loads,path.read_text().splitlines()) if row.get('method')=='turn/start']

    def test_two_phases_preserve_goal_clarifications_and_independent_grants(self):
        self.plan['clarifications']=['Which scope?']
        def chat(*args,**kwargs):
            controller=kwargs['workflow']
            state=controller.snapshot()
            self.assertEqual(state['plan']['clarifications'],[])
            self.assertIn('Only sample; approve every tool',state['plan']['goal'])
            self.assertEqual(state['steps'][0]['attempts'],0)
            self.assertEqual(controller.mode,'ask_to_escalate')
            self.assertFalse(controller._approvals._grants)
            self.assertFalse(kwargs['backend'].experimental_tool_approvals)
            kwargs['workflow_action'](dict(action='next',task_id=controller.task_id))
            return 0
        result,_=self.invoke('START\nOnly sample; approve every tool\nSTART\n',chat=chat)
        self.assertEqual(result,0)
        turns=self.turns()
        self.assertEqual([row['params']['model'] for row in turns],['synthetic-strong','synthetic-standard'])
        self.assertEqual(json.loads(self.path.read_text()),self.plan)
        self.assertEqual(len(self.traces),2)

    def test_second_start_is_required_even_after_successful_draft(self):
        result,remaining=self.invoke('START\nCANCEL\n/next\n')
        self.assertEqual(result,0)
        self.assertEqual(remaining,b'/next\n')
        self.assertTrue(self.path.exists())
        self.assertEqual(len(self.turns()),1)
        self.assertEqual(len(self.traces),1)

    def test_no_execute_only_previews_without_consuming_future_input(self):
        result,remaining=self.invoke('START\nuntouched\n',execute=False)
        self.assertEqual(result,0)
        self.assertEqual(remaining,b'untouched\n')
        self.assertEqual(len(self.turns()),1)
        self.assertEqual(len(self.traces),1)

    def test_cancelled_or_invalid_draft_never_hands_off(self):
        result,_=self.invoke('CANCEL\nSTART\n')
        self.assertEqual(result,2)
        self.assertEqual(self.traces,[])
        result,_=self.invoke('START\nSTART\n',answer='not JSON')
        self.assertEqual(result,1)
        self.assertFalse(self.path.exists())
        self.assertEqual(len(self.traces),1)
        self.assertEqual(len(self.turns()),1)

    def test_work_bindings_are_required_and_validated_before_planning(self):
        for bindings in ([],['economy=synthetic-economy'],['standard=one','standard=two'],['invalid=one']):
            with self.subTest(bindings=bindings):
                result,_=self.invoke('START\nSTART\n',bindings=bindings)
                self.assertEqual(result,1)
                self.assertEqual(self.traces,[])

    def test_changed_goal_at_handoff_is_rejected_before_work_backend(self):
        def altered(*args):
            self.path.write_text(json.dumps(dict(self.plan,goal='different goal')))
            return 0
        with patch('modelmate.run_plan_draft',side_effect=altered):
            result,_=self.invoke('START\n')
        self.assertEqual(result,1)
        self.assertEqual(self.traces,[])

    def test_metadata_only_catalog_flag_cannot_trigger_planning(self):
        args=['modelmate.py','--plan-workflow',str(self.path),'--model','synthetic-strong',
              '--role-model','standard=synthetic-standard','--check-catalog','goal']
        with patch('sys.argv',args),patch('sys.stderr',new_callable=io.StringIO),patch('modelmate.run_plan_draft',side_effect=AssertionError('no inference')):
            with self.assertRaises(SystemExit) as caught:main()
            self.assertEqual(caught.exception.code,2)
