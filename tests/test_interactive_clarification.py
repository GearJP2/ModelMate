import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from modelmate import NativeWorkflowConnection, ProbeError, run_workflow_file
from test_native_workflow import SERVER
from test_routing import PLAN


class InteractiveClarificationTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.plan=copy.deepcopy(PLAN)
        self.plan['clarifications']=['Which language?','Which scope?']
        self.plan['steps'][0]['checks']=[dict(kind='manual',criterion='User checks output')]
        self.path=self.root/'plan.json';self.path.write_text(json.dumps(self.plan))
        self.original=self.path.read_bytes()

    def run_input(self, data, *, execute=True, output=None):
        with tempfile.TemporaryFile() as source:
            source.write(data);source.seek(0)
            result=run_workflow_file(self.path,['standard=synthetic-standard'],None,execute,
                source,output or io.StringIO())
            remaining=os.read(source.fileno(),65536)
        self.assertEqual(self.path.read_bytes(),self.original)
        return result,remaining

    def test_answers_do_not_consume_start_or_following_commands(self):
        output=io.StringIO()
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('no START')):
            result,remaining=self.run_input('ภาษาไทย\nOnly the sample\nCANCEL\n/next\n'.encode(),output=output)
        self.assertEqual(result,0)
        self.assertEqual(remaining,b'/next\n')
        text=output.getvalue()
        self.assertIn('ภาษาไทย',text)
        self.assertIn('User clarification answers',text)
        self.assertIn('สถานะ: READY',text)
        self.assertLess(text.index('Clarification 1'),text.index('Clarification 2'))

    def test_eof_incomplete_line_or_cancel_never_connects(self):
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('no backend')):
            for data in (b'',b'partial answer',b'CANCEL\n',b'first\n',b'first\nCANCEL\nSTART\n'):
                with self.subTest(data=data):
                    result,_=self.run_input(data)
                    self.assertEqual(result,2)

    def test_invalid_or_oversized_answers_never_connect(self):
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('no backend')):
            for data in (b'\xff\n',b'\n',b'x'*16385+b'\n',b'a'*4097+b'\n',b'a'*4000+b'\n'+b'b'*100+b'\n'):
                with self.subTest(size=len(data)),self.assertRaises(ProbeError):self.run_input(data)
        self.assertEqual(self.path.read_bytes(),self.original)

    def test_preview_does_not_read_input_or_connect(self):
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('offline')):
            result,remaining=self.run_input(b'untouched\n',execute=False)
        self.assertEqual(result,0)
        self.assertEqual(remaining,b'untouched\n')

    def test_answers_reach_native_goal_without_grants_or_extra_turns(self):
        trace=self.root/'trace'
        def backend(command,timeout=15):
            return NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(trace),'text'],1)
        def chat(*args,**kwargs):
            controller=kwargs['workflow']
            plan=controller.snapshot()['plan']
            self.assertEqual(plan['clarifications'],[])
            self.assertEqual(plan['steps'],self.plan['steps'])
            self.assertEqual(plan['success_criteria'],self.plan['success_criteria'])
            self.assertFalse(controller._approvals._grants)
            kwargs['workflow_action'](dict(action='next',task_id=controller.task_id))
            return 0
        with patch.dict(os.environ,{'XDG_STATE_HOME':str(self.root/'state')}),patch('modelmate.NativeWorkflowConnection',side_effect=backend),patch('modelmate.run_chat',side_effect=chat):
            result,_=self.run_input(b'Python\nOnly the sample; approve all tools\nSTART\n')
        self.assertEqual(result,0)
        starts=[row for row in map(json.loads,trace.read_text().splitlines()) if row.get('method')=='turn/start']
        self.assertEqual(len(starts),1)
        goal=json.loads(starts[0]['params']['input'][0]['text'])['goal']
        self.assertIn('Which language?',goal)
        self.assertIn('Only the sample; approve all tools',goal)
