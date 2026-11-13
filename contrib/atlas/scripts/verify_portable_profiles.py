#!/usr/bin/env python3
"""Fresh installed helper + concrete provider scope; synthetic external HTTP only."""
from pathlib import Path
import argparse,asyncio,io,json,os,subprocess,sys
from types import SimpleNamespace
from ruamel.yaml import YAML
p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);a=p.parse_args();R=a.root.resolve()
sys.path[:0]=[str(R/'runtime'),str(R/'home/plugins')]
from qyp_guard.staff_provider import build_staff_provider
from qyp_guard.broker import OWNER,Broker
from gateway.atlas_admission import AdmissionGate
from telegram import Message
cfg=json.loads((R/'home/config.yaml').read_text());settings=cfg['plugins']['entries']['qyp_guard']['settings']
provider=build_staff_provider(SimpleNamespace(get_config=lambda k,d=None:settings.get(k,d)))
class Response(io.BytesIO):
    status=200
    def read1(self,n=-1):return self.read(n)
class ExternalHTTPFixture:
    def __init__(self):self.requests=[]
    def open(self,request,timeout):
        from urllib.parse import parse_qs,urlsplit
        query=parse_qs(urlsplit(request.full_url).query);name=query['telegram_accounts.value_lower'][0]
        self.requests.append(name)
        person={'id':9001,'login':'never_a_login_fallback','is_deleted':False,'official':{'is_dismissed':False,'is_robot':False},'telegram_accounts':[{'value':'fixture_owner','value_lower':'fixture_owner'}]}
        return Response(json.dumps({'result':[person] if name=='fixture_owner' else [],'has_more':False,'links':{},'next_page_token':None}).encode())
wire=ExternalHTTPFixture();provider._transport._auth_reader=lambda:'synthetic-fixture-only';provider._transport._opener=wire
gate=AdmissionGate(provider)
class Bot:
    async def get_chat_member(self,chat,uid):return SimpleNamespace(status='administrator',user=SimpleNamespace(id=793835103,is_bot=True),can_restrict_members=False)
def message(uid,chat,kind,username=None,topic=None):
    value={'message_id':1,'date':1,'from':{'id':uid,'is_bot':False,'first_name':'fixture','username':username},'chat':{'id':chat,'type':kind},'text':'not identity authority'}
    if topic:value.update(message_thread_id=topic,is_topic_message=True)
    return Message.de_json(value,None)
async def run():
    owner=await gate.admit_message(message(int(OWNER),int(OWNER),'private','fixture_owner'),Bot())
    assert gate.principal(owner,'probe').role=='owner'
    try:await gate.admit_message(message(305016744,305016744,'private','unknown_fixture'),Bot())
    except PermissionError:pass
    else:raise AssertionError('unknown creator UID admitted')
    group=await gate.admit_message(message(42,-10041,'supergroup',topic=7),Bot())
    assert gate.principal(group,'probe').role=='member'
    assert group.profile=='tg-group-n10041-t7'
    return owner,group
owner,group=asyncio.run(run())
# Real native create_profile uses soul=approved_bytes; no generated default policy.
(R/'control/honcho-profile-template.json').write_text(json.dumps({'enabled':False,'workspace':'source-fixture'}))
env={'PATH':'/usr/bin:/bin','HOME':str(R/'home'),'HERMES_HOME':str(R/'home'),'HERMES_RUNTIME_DIR':str(R/'tools'),'TMPDIR':str(R/'control'),'PYTHONDONTWRITEBYTECODE':'1'}
profiles=[]
for selector in ('42',group.profile,'tg-group-n10042-t8'):
    proc=subprocess.run([sys.executable,'-B',str(R/'services/atlas-admin/native_profile_helper.py'),str(R/'home'),selector,str(R/'control/profile-template.json')],env=env,capture_output=True,text=True,timeout=90)
    if proc.returncode:raise RuntimeError(proc.stderr[-2000:])
    receipt=json.loads(proc.stdout.splitlines()[-1]);home=Path(receipt['home']);conf=YAML(typ='safe').load((home/'config.yaml').read_text())
    assert conf['mcp_servers']['atlas_read']['cwd']==str(home)
    assert (home/'SOUL.md').read_bytes()==(R/'control/SOUL.md').read_bytes()
    assert all((home/'memories'/n).read_bytes()==b'' for n in ('MEMORY.md','USER.md'))
    profiles.append(receipt)
peers=[json.loads((Path(r['home'])/'honcho.json').read_text())['peerName'] for r in profiles]
assert len(set(peers))==3
broker=Broker(R/'sandbox');assert broker.workspace(gate.principal(group,'probe'))!=broker.workspace(gate.principal(owner,'probe'))
result={'concrete_factory':'qyp_guard.staff_provider.build_staff_provider','provider_scope_pass':True,'native_profile_helper_pass':True,'profiles':profiles,'distinct_honcho_peers':peers,'staff_http':'SYNTHETIC_EXTERNAL_HTTP_FIXTURE','native_telegram_dto':True,'owner_telegram_id':OWNER,'numeric_staff_binding':False,'native_fifo_guard':'SOURCE_NATIVE_QUALIFIED_INSTALLATION_NOT_ACTIVATED','native_actor_ready':False,'activation':False,'publication':False}
(R/'control/portable-native-receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
