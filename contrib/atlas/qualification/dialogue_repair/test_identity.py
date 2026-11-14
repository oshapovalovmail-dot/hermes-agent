"""Offline public payload integration; frozen native admission/session fixture.
Only synthetic Staff/bot/native runner; no gateway bootstrap or credentials.
"""
import asyncio, atexit, contextlib, datetime, hashlib, importlib.util, json, os
from pathlib import Path
import shutil, sys, tempfile, threading, types, unittest
ROOT=Path(__file__).resolve().parent
PAYLOAD=ROOT.parents[1]/'payload'
_temp=tempfile.TemporaryDirectory(prefix='.identity-',dir=ROOT)
atexit.register(_temp.cleanup)
FIX=Path(_temp.name)
for rel in ['home/plugins/qyp_guard/__init__.py','home/plugins/qyp_guard/policy.py',
            'home/plugins/qyp_guard/broker.py','home/plugins/qyp_guard/code_research.py']:
 target=FIX/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PAYLOAD/rel,target)
(FIX/'runtime/gateway').mkdir(parents=True)
for name in ['atlas_admission.py','session_context.py']:
 shutil.copyfile(ROOT/'native_fixture'/name,FIX/'runtime/gateway'/name)
(FIX/'control').mkdir();(FIX/'control/operator.json').write_text('{"owner_telegram_id":"900001"}\n')
gateway=types.ModuleType('gateway');gateway.__path__=[str(FIX/'runtime/gateway')];sys.modules['gateway']=gateway
from gateway import atlas_admission as native
from gateway import session_context as session
from telegram import Message,User,Chat

def load(name,path,package=False):
 spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)] if package else None)
 m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
plugin=load('identity_scoped_guard',FIX/'home/plugins/qyp_guard/__init__.py',True)
sidecar=load('identity_scoped_sidecar',PAYLOAD/'services/atlas-read/sidecar.py')
work=sidecar.load_service_backend('work_services')
OP='staff_api_mcp.person-full-info'
KEY='telegram_accounts.value_lower'

class Staff:
 def __init__(self):self.allowed=True;self.calls=[]
 async def verify(self,uid,username):
  self.calls.append((uid,username))
  return native.StaffProof(uid,'synthetic-employee-'+str(uid),self.allowed,True,False,username)
class Bot:
 async def get_chat_member(self,chat,uid):return types.SimpleNamespace(status='administrator',user=types.SimpleNamespace(id=uid,is_bot=True))

class RoleTests(unittest.TestCase):
 def setUp(self):
  self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self.loop.run_forever);self.thread.start()
  self.staff=Staff();self.gate=native.AdmissionGate(self.staff);self.bot=Bot()
  self.b=self.admit();self.service=plugin.Service.__new__(plugin.Service)
  self.service.admission=self.gate;self.service.ctx=types.SimpleNamespace(profile_name=self.b.profile)
 def tearDown(self):
  session.clear_session_vars([]);self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join();self.loop.close()
 def admit(self,uid=900001,username='Fixture_User',group=False,topic=None):
  chat=Chat(-900010 if group else uid,'supergroup' if group else 'private',is_forum=bool(topic))
  message=Message(1,datetime.datetime.now(datetime.timezone.utc),chat,from_user=User(uid,'Fixture',False,username=username),message_thread_id=topic,is_topic_message=bool(topic))
  return asyncio.run_coroutine_threadsafe(self.gate.admit_message(message,self.bot),self.loop).result(3)
 @contextlib.contextmanager
 def bound(self,b=None,key='fixture-session'):
  b=b or self.b
  # Public native session setter without optional runtime-cwd initialization.
  # Bind native ContextVars directly, then actual public bound_session_key reads them.
  tokens=[]
  for name,value in {'PLATFORM':'telegram','USER_ID':b.user_id,'CHAT_ID':b.chat_id,'CHAT_TYPE':b.chat_type,'THREAD_ID':b.thread_id or '', 'PROFILE':b.profile,'KEY':key}.items():
   var=session._VAR_MAP['HERMES_SESSION_'+name];tokens.append((var,var.set(value)))
  with native.binding_scope(b):
   try:yield
   finally:
    for var,token in reversed(tokens):var.reset(token)
 def call(self,args=None):return json.loads(self.service.handler('qyp_role')({} if args is None else args))
 def test_self_metadata_from_original_authenticated_canonical_username(self):
  with self.bound():r=self.call()
  self.assertTrue(r['ok']);self.assertEqual(r.get('telegram_username'),'fixture_user','business identity missing from real Service.handler(qyp_role)')
  self.assertEqual(r['user_id'],self.b.user_id);self.assertEqual(r['role'],'owner');self.assertEqual(r['ceiling'],'isolated_auxiliary_only')
  self.assertGreaterEqual(len(self.staff.calls),3) # admission + actual handler + fresh metadata read
 def test_member_role_ceiling_and_distinct_identity(self):
  b=self.admit(900002,'Other_User');self.service.ctx.profile_name=b.profile
  with self.bound(b):r=self.call()
  self.assertEqual(r.get('telegram_username'),'other_user');self.assertEqual(r['role'],'member');self.assertEqual(r['ceiling'],'isolated_auxiliary_only')
 def test_native_unauthorized_denied(self):
  with self.bound(native.Binding('900001','900001','dm',None,'tg-900001','fixture_user')):r=self.call()
  self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_native_revocation_denied(self):
  self.staff.allowed=False
  with self.bound():r=self.call()
  self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_native_missing_username_denied(self):
  with self.assertRaises(PermissionError):self.admit(username=None)
 def test_foreign_plugin_profile_denied(self):
  self.service.ctx.profile_name='tg-900002'
  with self.bound():self.assertFalse(self.call()['ok'])
 def test_group_returns_unknown_even_if_human_has_username(self):
  b=self.admit(group=True,topic=7);self.service.ctx.profile_name=b.profile
  with self.bound(b):r=self.call()
  self.assertTrue(r['ok']);self.assertIn('telegram_username',r);self.assertIsNone(r['telegram_username'])
 def test_model_argument_identity_injection_denied(self):
  for arg in ({'telegram_username':'injected'},{'user_id':'900002'},{'search_by':{KEY:'injected'}},{'profile':self.b.profile}):
   with self.subTest(arg=arg),self.bound():
    r=self.call(arg);self.assertFalse(r['ok']);self.assertEqual(r['error'],'invalid_arguments');self.assertNotIn('telegram_username',r)
 def test_ambient_identity_denied(self):
  old=os.environ.get('HERMES_SESSION_USER_ID');os.environ['HERMES_SESSION_USER_ID']='900001'
  try:
   with self.bound():self.assertFalse(self.call()['ok'])
  finally:
   if old is None:os.environ.pop('HERMES_SESSION_USER_ID',None)
   else:os.environ['HERMES_SESSION_USER_ID']=old
 def test_swapped_foreign_binding_between_principal_and_projection(self):
  foreign=self.admit(900002,'Other_User');original=self.service.authorized_principal
  def swapped():
   who=original();native._BINDING.set(foreign);return who
  self.service.authorized_principal=swapped
  with self.bound():r=self.call()
  self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_swapped_same_principal_binding_is_not_original_identity(self):
  foreign=self.admit(username='Replacement_User');original=self.service.authorized_principal
  # Admitting another username revokes the earlier source; recreate original and
  # then admit another same-username turn so both bindings are genuinely valid.
  self.b=self.admit(username='Replacement_User')
  def swapped():
   who=original();native._BINDING.set(foreign);return who
  self.service.authorized_principal=swapped
  with self.bound():r=self.call()
  self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_each_who_component_must_match_unchanged_current_binding(self):
  original=plugin.Service.authorized_principal.__get__(self.service)
  for field,value in [('user_id','900002'),('chat_id','900002'),('profile','tg-900002'),('thread_id','7'),('session_key','foreign-session'),('role','member')]:
   with self.subTest(field=field):
    def changed(field=field,value=value):return original()._replace(**{field:value})
    self.service.authorized_principal=changed
    with self.bound():r=self.call()
    self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_changed_session_between_principal_and_projection(self):
  original=self.service.authorized_principal
  def swapped():
   who=original();session._SESSION_KEY.set('foreign-session');return who
  self.service.authorized_principal=swapped
  with self.bound():r=self.call()
  self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_empty_bound_session_never_projects(self):
  with self.bound(key=''):r=self.call()
  self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_swapped_chat_profile_topic_or_user_between_principal_and_projection(self):
  from dataclasses import replace
  for field,value in [('user_id','900002'),('chat_id','900002'),('profile','tg-900002'),('thread_id','7')]:
   with self.subTest(field=field):
    # A genuinely issued second group/topic proves topic mismatch without forging admission.
    foreign=self.admit(group=True,topic=7) if field=='thread_id' else self.admit(900002,'Other_User')
    original=plugin.Service.authorized_principal.__get__(self.service)
    def swapped(original=original,foreign=foreign,field=field,value=value):
     who=original();native._BINDING.set(foreign)
     # Keep remaining old tuple parts to isolate each comparison independently.
     return who._replace(**{k:getattr(foreign,k) if k!='thread_id' else foreign.thread_id or '' for k in ('user_id','chat_id','profile','thread_id') if k!=field})
    self.service.authorized_principal=swapped
    with self.bound():r=self.call()
    self.assertFalse(r['ok']);self.assertNotIn('telegram_username',r)
 def test_description_business_metadata_not_staff_or_authority(self):
  d=plugin.SCHEMAS['qyp_role']['description']
  self.assertIn('Staff',d);self.assertIn('ACL',d);self.assertIn('not a Staff login',d)

class ValidatorTests(unittest.TestCase):
 def args(self,value='fixture_user'):return {'search_by':{KEY:value},'fields_to_return':'id,login,name'}
 def valid(self,args):return sidecar.service_input_valid('service_read',{'operation':OP,'arguments':args})
 def test_published_validator_accepts_exact_business_selector(self):
  self.assertTrue(self.valid(self.args()),'selected published validator rejects legitimate business selector')
  work.validate(self.args(),work.PUBLIC_ARGUMENT_SCHEMAS[OP])
  work.validate({'operation':OP,'arguments':self.args()},work.INPUT_SCHEMA)
 def test_exact_native_field_mapping(self):
  calls=[]
  def runner(argv):
   calls.append(argv);return json.dumps({'result':{'content':[{'type':'text','text':'{"items":[]}'}]}})
  result=work.Backend(runner=runner).read(operation=OP,arguments=self.args())
  self.assertTrue(result['ok'],result)
  self.assertEqual(len(calls),1)
  self.assertEqual(calls[0][:5],[work.MCP,'connect','staff_api_mcp','--tool','person-full-info'])
  self.assertIn('search_by:'+json.dumps({KEY:'fixture_user'},separators=(',',':')),calls[0]);self.assertIn('fields_to_return:id,login,name',calls[0]);self.assertEqual(calls[0][-1],'--raw')
 def test_malformed_canonical_username_no_dispatch(self):
  values=['','@fixture','Fixture','has space','x\n','x\r','x.y','é','а','x'*33,None,1,True,[],{},'authorization:Bearer x']
  for value in values:
   with self.subTest(value=value):
    args=self.args(value);self.assertFalse(self.valid(args))
    calls=[];r=work.Backend(runner=lambda a:calls.append(a)).read(operation=OP,arguments=args)
    self.assertFalse(r['ok']);self.assertEqual(calls,[])
 def test_short_and_maximum_canonical_names(self):
  for value in ['a','0','_','a_1','x'*32]:
   with self.subTest(value=value):self.assertTrue(self.valid(self.args(value)))
 def test_extra_headers_credentials_closed_no_dispatch(self):
  for args in [self.args()|{'headers':{'Authorization':'fixture'}},self.args()|{'credential':'fixture'},self.args()|{'setup_server_args':[]},{'search_by':{KEY:'fixture_user','headers':'fixture'}},{'search_by':{'telegram_accounts':{'value_lower':'fixture_user'}}},{'search_by':{'telegram_accounts.value':'fixture_user'}},{'search_by':{}},{'search_by':{KEY:'fixture_user'},'fields_to_return':'authorization'}]:
   with self.subTest(args=args):
    self.assertFalse(self.valid(args));calls=[];r=work.Backend(runner=lambda a:calls.append(a)).read(operation=OP,arguments=args)
    self.assertFalse(r['ok']);self.assertEqual(calls,[])
 def test_existing_staff_login_route_preserved(self):self.assertTrue(self.valid({'search_by':{'login':'fixture'}}))
 def test_sanitizer_credentials_unchanged(self):
  r=work.sanitize_data({'login':'fixture','headers':{'Authorization':'fixture'},'password':'fixture','input_tokens':5})
  self.assertEqual(r,{'login':'fixture','headers':'[REDACTED]','password':'[REDACTED]','input_tokens':5})

if __name__=='__main__':unittest.main(verbosity=2)
