"""Durable native workflow recovery with two fake server processes; no live inference."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
import os
from unittest.mock import patch

from modelmate import ChatShell, NativeWorkflowConnection, WorkflowController, SessionStore, ProbeError, run_workflow_file
from test_routing import PLAN, CATALOG, POLICY

SERVER = r'''
import json,sys
from pathlib import Path
trace,mode=sys.argv[1:]
state=Path(trace+'.state')
data=json.loads(state.read_text()) if state.exists() else {'count':0,'latest':None}
for line in sys.stdin:
 req=json.loads(line)
 with open(trace,'a') as f:f.write(json.dumps(req)+'\n')
 method=req.get('method');p=req.get('params',{})
 if method is None or 'id' not in req:continue
 if method=='initialize':result={}
 elif method=='account/read':result={'account':{'type':'chatgpt'}}
 elif method=='account/rateLimits/read':result={'accountId':'different' if mode=='account' else 'synthetic',
  'ordinaryUsageAllowed':True,'rateLimits':{'primary':{'usedPercent':5}}}
 elif method=='model/list':result={'data':[{'model':'synthetic-'+r,'defaultReasoningEffort':'low',
  'supportedReasoningEfforts':[{'reasoningEffort':'low'}]} for r in ('economy','standard','strong')]}
 elif method=='thread/start':
  data['thread']={'id':'thread','cwd':p['cwd'],'ephemeral':p['ephemeral'],'modelProvider':'openai','status':{'type':'idle'}}
  result={'thread':data['thread'],'approvalPolicy':'on-request','approvalsReviewer':'user','sandbox':{'type':'readOnly'}}
 elif method in ('thread/read','thread/resume'):
  thread=dict(data['thread'])
  if mode=='project':thread['cwd']='/different'
  if mode=='provider':thread['modelProvider']='other'
  if mode=='status_shape':thread['status']=None
  if mode=='resume_active' and method=='thread/resume':thread['status']={'type':'active'}
  if mode=='ephemeral':thread['ephemeral']=True
  if mode=='active' or (data['latest'] and data['latest']['status']=='inProgress'):thread['status']={'type':'active'}
  result={'thread':thread,'approvalPolicy':'on-request','approvalsReviewer':'user',
   'sandbox':{'type':'workspaceWrite' if mode=='permissions' else 'readOnly'}}
 elif method=='thread/turns/list':
  latest=data['latest']
  if mode=='turn_mismatch' and latest:latest=dict(latest,id='foreign')
  result={'data':[] if latest is None or mode=='empty_history' else [latest]}
 elif method=='turn/start':
  data['count']+=1
  objective=json.loads(p['input'][0]['text'])['step']['objective']
  if data['count']==1:data['remembered']=objective
  data['latest']={'id':str(data['count']),'status':'inProgress' if mode=='hang' else 'completed'}
  result={'turn':{} if mode=='unknown_start' else {'id':str(data['count'])}}
 elif method=='turn/interrupt':
  data['latest']['status']='interrupted';result={}
 else:raise RuntimeError(method)
 state.write_text(json.dumps(data))
 print(json.dumps({'id':req['id'],'result':result}),flush=True)
 if method=='turn/start':
  if mode=='hang':continue
  print(json.dumps({'method':'item/completed','params':{'threadId':'thread','turnId':str(data['count']),
    'item':{'id':'answer','type':'agentMessage','text':'ACK' if data['count']==1 else data['remembered']}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':'thread','turn':data['latest']}}),flush=True)
 if method=='turn/interrupt':
  print(json.dumps({'method':'turn/completed','params':{'threadId':'thread','turn':data['latest']}}),flush=True)
'''


class NativeResumeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.trace=self.root/'trace'
        self.store=SessionStore(self.project,self.root/'state');self.addCleanup(self.store.close)
        self.plan=copy.deepcopy(PLAN)
        self.plan['steps'][0]['checks']=[{'kind':'manual','criterion':'User checks answer'}]
        self.plan['steps'].append(copy.deepcopy(self.plan['steps'][0]))
        self.plan['steps'][0]['objective']='Remember synthetic native context value MM-RESUME'
        self.plan['steps'][1]['objective']='Recall the preceding synthetic context value'
        self.raw=json.dumps(self.plan)
        self.c=WorkflowController(self.raw,CATALOG,POLICY)

    def backend(self,mode='normal'):
        connection=NativeWorkflowConnection([sys.executable,'-u','-c',SERVER,str(self.trace),mode],1)
        self.addCleanup(connection.close)
        return connection

    def records(self):return [json.loads(line) for line in self.trace.read_text().splitlines()]

    def wait(self, connection):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            connection.drain()
            if connection.host._terminal is not None:return
            for key,_ in connection.selector.select(.05):connection.read_ready(key.fileobj)
        self.fail('synthetic native turn did not finish')

    def completed_first(self):
        connection=self.backend()
        host=connection.connect(self.c,self.project,POLICY,store=self.store)
        sid=connection.session_id
        host({'action':'next','task_id':self.c.task_id})
        if self.c.state=='AWAITING_MODEL_APPROVAL':
            self.c.answer_model(self.c.snapshot()['model_request']['token'],'approve')
            host({'action':'next','task_id':self.c.task_id})
        self.wait(connection)
        active=self.c.snapshot()['active_attempt']
        evidence=self.c.record_check(active['id'],0,origin='manual',result='pass',reference='user',finding='checked')
        host({'action':'check','task_id':self.c.task_id})
        self.c.pause();connection.close()
        return sid,evidence

    def test_durable_resume_keeps_context_counters_ids_and_requires_manual_revalidation(self):
        sid,evidence=self.completed_first()
        original=self.store.read(sid)['workflow']
        connection=self.backend()
        host=connection.resume(self.store,sid,self.project,POLICY,self.raw)
        c=host.controller
        self.assertEqual(c.snapshot()['step_index'],1)
        self.assertEqual(c.task_id,original['task_id'])
        self.assertEqual(c.snapshot()['steps'][0]['attempts'],1)
        self.assertIn(evidence['id'],c.snapshot()['stale_evidence'])
        output=io.StringIO();shell=ChatShell(output,workflow=c,workflow_action=host)
        answers=[]
        def observe(message):
            before=output.tell();shell.event(message)
            if message.get('type')=='text':answers.append(output.getvalue()[before:].strip())
        host.on_change=observe
        shell.line('/continue '+shell.show_workflow(render=False)['pause_token'])
        shell.line('/next');self.wait(connection)
        self.assertEqual(answers,[self.plan['steps'][0]['objective']])
        shell.line('/verify 1 pass');shell.line('/check')
        shell.line('/finish 1=1.1')
        self.assertNotEqual(c.state,'DONE')
        shell.line('/revalidate 1.1 pass');shell.line('/finish 1=1.1')
        self.assertEqual(c.state,'DONE')
        connection.close()
        self.assertEqual(self.store.read(sid)['workflow']['state'],'DONE')
        methods=[r.get('method') for r in self.records()]
        self.assertEqual(methods.count('thread/start'),1)
        self.assertEqual(methods.count('thread/resume'),1)
        self.assertEqual(methods.count('turn/start'),2)
        self.assertFalse(next(r['params']['ephemeral'] for r in self.records() if r.get('method')=='thread/start'))

    def test_recovery_refuses_project_active_ephemeral_permission_and_turn_mismatch(self):
        sid,_=self.completed_first()
        for mode in ('project','active','ephemeral','permissions','turn_mismatch','provider','status_shape','resume_active','empty_history'):
            with self.subTest(mode=mode):
                connection=self.backend(mode)
                with self.assertRaises(ProbeError):connection.resume(self.store,sid,self.project,POLICY,self.raw)
                connection.close()
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)
        self.assertEqual(sum(r.get('method')=='thread/start' for r in self.records()),1)

    def test_account_mismatch_does_not_modify_checkpoint(self):
        sid,_=self.completed_first()
        before=self.store.read(sid)
        connection=self.backend('account')
        with self.assertRaises(ProbeError):connection.resume(self.store,sid,self.project,POLICY,self.raw)
        connection.close()
        self.assertEqual(self.store.read(sid),before)

    def test_unknown_start_clears_previous_turn_identity_and_never_replays(self):
        sid,_=self.completed_first()
        connection=self.backend('unknown_start')
        host=connection.resume(self.store,sid,self.project,POLICY,self.raw)
        c=host.controller;c.answer_pause(c.snapshot()['pause_token'],'continue')
        request=connection.request
        def assert_cleared(method,params=None):
            if method=='turn/start':self.assertIsNone(self.store.read(sid)['turn_id'])
            return request(method,params)
        connection.request=assert_cleared
        with self.assertRaises(ProbeError):host({'action':'next','task_id':c.task_id})
        connection.close()
        self.assertIsNone(self.store.read(sid)['turn_id'])
        again=self.backend()
        with self.assertRaisesRegex(ProbeError,'match checkpoint'):
            again.resume(self.store,sid,self.project,POLICY,self.raw)
        again.close()
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),2)

    def test_binding_save_failure_cannot_reuse_previous_native_turn(self):
        sid,_=self.completed_first()
        connection=self.backend();host=connection.resume(self.store,sid,self.project,POLICY,self.raw)
        c=host.controller;c.answer_pause(c.snapshot()['pause_token'],'continue')
        save=self.store.save
        def fail_binding(record):
            if record.get('turn_id')=='2':raise OSError('synthetic binding save failure')
            return save(record)
        with patch.object(self.store,'save',fail_binding):
            with self.assertRaises(OSError):host({'action':'next','task_id':c.task_id})
        connection.close()
        self.assertIsNone(self.store.read(sid)['turn_id'])
        again=self.backend()
        with self.assertRaises(ProbeError):again.resume(self.store,sid,self.project,POLICY,self.raw)
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),2)

    def test_writer_lock_is_held_until_native_connection_closes(self):
        connection=self.backend();connection.connect(self.c,self.project,POLICY,store=self.store)
        sid=connection.session_id
        with SessionStore(self.project,self.root/'state') as other:
            with self.assertRaises(ProbeError):
                with other.edit(sid):self.fail('concurrent writer acquired lock')
            connection.close()
            with other.edit(sid) as record:record['summary']='inspection only'

    def test_model_approval_is_not_restored(self):
        self.c.change_mode('approve_plan')
        sid,_=self.completed_first()
        connection=self.backend();host=connection.resume(self.store,sid,self.project,POLICY,self.raw)
        c=host.controller;c.answer_pause(c.snapshot()['pause_token'],'continue')
        host({'action':'next','task_id':c.task_id})
        self.assertEqual(c.state,'AWAITING_MODEL_APPROVAL')
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_interrupted_native_turn_reconciles_without_reset_or_replay(self):
        connection=self.backend('hang')
        host=connection.connect(self.c,self.project,POLICY,store=self.store)
        sid=connection.session_id
        host({'action':'next','task_id':self.c.task_id});connection.close()
        blocked=self.backend()
        with self.assertRaises(ProbeError):blocked.resume(self.store,sid,self.project,POLICY,self.raw)
        blocked.close()
        state_path=Path(str(self.trace)+'.state')
        native=json.loads(state_path.read_text());native['latest']['status']='interrupted'
        state_path.write_text(json.dumps(native))
        recovered=self.backend();host=recovered.resume(self.store,sid,self.project,POLICY,self.raw)
        state=host.controller.snapshot()
        self.assertEqual(state['state'],'PAUSED')
        self.assertEqual(state['reason'],'outcome_unknown')
        self.assertIsNone(state['active_attempt'])
        self.assertEqual(state['steps'][0]['attempts'],1)
        self.assertEqual(sum(r.get('method')=='turn/start' for r in self.records()),1)

    def test_preview_resume_is_readonly_and_execute_roundtrip_uses_saved_plan(self):
        sid,evidence=self.completed_first()
        before=self.store.read(sid)
        env={'XDG_STATE_HOME':str(self.root/'state')}
        with patch('modelmate.os.getcwd',return_value=str(self.project)),patch.dict(os.environ,env):
            with patch('modelmate.subprocess.Popen',side_effect=AssertionError('preview opened backend')):
                self.assertEqual(run_workflow_file(None,['standard=synthetic-standard'],None,False,
                    io.StringIO(),io.StringIO(),resume_id=sid),0)
        self.assertEqual(self.store.read(sid),before)
        original=NativeWorkflowConnection.__init__
        def init(connection,command,timeout=15):
            original(connection,[sys.executable,'-u','-c',SERVER,str(self.trace),'normal'],1)
        def drive(_input,_output,**kwargs):
            host=kwargs['workflow_action'];c=kwargs['workflow'];backend=kwargs['backend']
            shell=ChatShell(io.StringIO(),workflow=c,workflow_action=host)
            shell.line('/continue '+c.snapshot()['pause_token'])
            shell.line('/next');self.wait(backend)
            shell.line('/verify 1 pass');shell.line('/check')
            shell.line('/revalidate 1.1 pass');shell.line('/finish 1=1.1')
            self.assertEqual(c.state,'DONE')
            return 0
        with tempfile.TemporaryFile('w+') as source:
            source.write('START\n');source.seek(0)
            with patch('modelmate.os.getcwd',return_value=str(self.project)),patch.dict(os.environ,env), \
                 patch('modelmate.NativeWorkflowConnection.__init__',init),patch('modelmate.run_chat',side_effect=drive):
                self.assertEqual(run_workflow_file(None,['standard=synthetic-standard'],None,True,
                    source,io.StringIO(),resume_id=sid),0)
        self.assertEqual(self.store.read(sid)['workflow']['state'],'DONE')
        self.assertEqual(sum(r.get('method')=='thread/start' for r in self.records()),1)

    def test_user_revalidation_cannot_approve_saved_tool_evidence(self):
        plan=copy.deepcopy(self.plan);plan['steps'][0]['checks'][0]['kind']='test'
        self.raw=json.dumps(plan);c=WorkflowController(self.raw,CATALOG,POLICY)
        connection=self.backend();host=connection.connect(c,self.project,POLICY,store=self.store)
        sid=connection.session_id
        host({'action':'next','task_id':c.task_id});self.wait(connection)
        aid=c.snapshot()['active_attempt']['id']
        evidence=c.record_check(aid,0,origin='tool',exit_code=0,reference='synthetic command',finding='observed exit')
        host({'action':'check','task_id':c.task_id});c.pause();connection.close()
        resumed=self.backend();host=resumed.resume(self.store,sid,self.project,POLICY,self.raw)
        shell=ChatShell(io.StringIO(),workflow=host.controller,workflow_action=host)
        shell.line('/revalidate 1.1 pass')
        self.assertIn(evidence['id'],host.controller.snapshot()['stale_evidence'])
        self.assertIn('tool checks need fresh tool observations',shell.output.getvalue())

    def test_changed_preview_cannot_resume_or_dispatch(self):
        sid,_=self.completed_first()
        connection=self.backend()
        with self.assertRaisesRegex(ProbeError,'changed'):
            connection.resume(self.store,sid,self.project,POLICY,'different plan')
        connection.close()
        self.assertEqual(sum(r.get('method')=='thread/resume' for r in self.records()),0)
