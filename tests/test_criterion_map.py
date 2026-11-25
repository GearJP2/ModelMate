import io
import json
import copy
import os
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modelmate import ProbeError, load_criterion_map, main, run_workflow_file
from test_routing import PLAN


class CriterionMapTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.root=Path(directory.name)
        self.path=self.root/'criteria.json'

    def load(self,data):
        self.path.write_text(json.dumps(data))
        return load_criterion_map(self.path,PLAN)

    def test_valid_mapping_uses_declared_references_not_evidence_ids(self):
        self.assertEqual(self.load(dict(version=1,criteria={'1':['1.1']})),['1=1.1'])
        self.assertIsNone(load_criterion_map(None,PLAN))

    def test_invalid_schema_missing_criteria_or_undeclared_refs_fail(self):
        good=dict(version=1,criteria={'1':['1.1']})
        for value in (dict(good,version=True),dict(good,grant='accept'),dict(version=1,criteria={}),
                      dict(version=1,criteria={'1':[]}),dict(version=1,criteria={'1':['1.1','1.1']}),
                      dict(version=1,criteria={'1':['2.1']}),dict(version=1,criteria={'1':['01.1']}),
                      dict(version=1,criteria={'1':['EVIDENCE_ID']}),dict(version=1,criteria={'1':[{}]}),
                      dict(version=1,criteria={'2':['1.1']})):
            with self.subTest(value=value),self.assertRaises(ProbeError):self.load(value)

    def test_duplicate_nonfinite_invalid_utf8_and_oversized_json_fail(self):
        for raw in (b'{"version":1,"version":1}',b'{"version":NaN}',b'\xff',b'x'*32769,b'['*1500):
            self.path.write_bytes(raw)
            with self.subTest(size=len(raw)),self.assertRaises(ProbeError):load_criterion_map(self.path,PLAN)

    def test_preview_shows_mapping_without_backend_or_grants(self):
        plan_path=self.root/'plan.json';plan_path.write_text(json.dumps(PLAN))
        self.load(dict(version=1,criteria={'1':['1.1']}))
        output=io.StringIO()
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('offline')):
            self.assertEqual(run_workflow_file(plan_path,['standard=synthetic-standard'],'auto',False,
                io.StringIO(),output,automatic_workflow=True,criterion_map=self.path),0)
        self.assertIn('User criterion map',output.getvalue())
        self.assertIn('1=1.1',output.getvalue())
        self.assertIn('ใช้ mapping ที่ยืนยัน ถ้าไม่มีต้อง /finish',output.getvalue())

    def test_cli_requires_explicit_auto_optin_and_forwards_path(self):
        with patch('sys.argv',['modelmate.py','--workflow','plan.json','--criterion-map','criteria.json']),patch('sys.stderr',new_callable=io.StringIO):
            with self.assertRaises(SystemExit) as caught:main()
            self.assertEqual(caught.exception.code,2)
        with patch('sys.argv',['modelmate.py','--workflow','plan.json','--workflow-mode','auto',
              '--experimental-auto-advance','--criterion-map','criteria.json']),patch('modelmate.run_workflow_file',return_value=0) as run:
            self.assertEqual(main(),0)
            self.assertEqual(run.call_args.kwargs['criterion_map'],'criteria.json')

    def test_file_mapping_reaches_bound_shell_only_after_start(self):
        from modelmate import NativeWorkflowConnection
        from test_native_workflow import SERVER
        plan=copy.deepcopy(PLAN);plan['steps'][0]['checks'][0]['kind']='manual'
        plan_path=self.root/'plan.json';plan_path.write_text(json.dumps(plan))
        self.load(dict(version=1,criteria={'1':['1.1']}))
        trace=self.root/'trace'
        def backend(command,timeout=15):
            return NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(trace),'text'],1)
        with tempfile.TemporaryFile('w+') as source,patch.dict(os.environ,{'XDG_STATE_HOME':str(self.root/'state')}),patch('modelmate.NativeWorkflowConnection',side_effect=backend),patch('modelmate.run_chat',return_value=0) as chat:
            source.write('START\n');source.seek(0)
            self.assertEqual(run_workflow_file(plan_path,['standard=synthetic-standard'],'auto',True,
                source,io.StringIO(),automatic_workflow=True,criterion_map=self.path),0)
            self.assertEqual(chat.call_args.kwargs['finish_references'],['1=1.1'])
            self.assertTrue(chat.call_args.kwargs['automatic_workflow'])

    def test_invalid_map_stops_before_backend_and_input(self):
        plan_path=self.root/'plan.json';plan_path.write_text(json.dumps(PLAN))
        self.path.write_text(json.dumps(dict(version=1,criteria={'1':['2.1']})))
        with patch('modelmate.NativeWorkflowConnection',side_effect=AssertionError('no backend')):
            with self.assertRaises(ProbeError):
                run_workflow_file(plan_path,['standard=synthetic-standard'],'auto',True,
                    io.StringIO(),io.StringIO(),automatic_workflow=True,criterion_map=self.path)
