"""Typed local shared-Honcho operations. No URLs, peers or methods from a model."""
import asyncio
import hashlib
import json
import re
import sqlite3
from urllib.parse import urlsplit
from atlas_bridge.contract import digest,PrivateStore
from .protocol import Denied


def peers_for(scope,mapping):
    if type(mapping) is not dict or set(mapping)!={'owner_user_peer','owner_assistant_peer','namespace'}:raise Denied('parent_approved_existing_Honcho_mapping_required')
    if any(type(v) is not str or not v or len(v)>256 for v in mapping.values()):raise Denied('fixed_memory_mapping_required')
    uid=scope.get('user_id');chat=scope.get('chat_id');kind=scope.get('chat_type');topic=scope.get('thread_id');profile=scope.get('profile')
    if type(uid) is not str or re.fullmatch('[1-9][0-9]*',uid) is None:raise Denied('numeric_memory_principal_required')
    expected='tg-'+uid if kind=='dm' else 'tg-group-n'+str(chat)[1:]+'-t'+(topic or '0')
    if profile!=expected or (kind=='dm' and (chat!=uid or topic is not None)) or kind not in ('dm','group'):raise Denied('native_memory_scope_required')
    if uid=='305016744' and kind=='dm':return mapping['owner_user_peer'],mapping['owner_assistant_peer']
    key=hashlib.sha256(json.dumps([mapping['namespace'],profile,uid],separators=(',',':')).encode()).hexdigest()
    return 'atlas-user-'+key,'atlas-assistant-'+key


def safe_projection(native_user,assistant,messages):
    """Only genuine signed ingress and native final text; never raw history/sidecars.

    An explicit empty/filtered capture remains empty. Unknown metadata and tool/
    reasoning fields cannot be reconstructed from serialized content fallbacks.
    """
    if messages==[]:return []
    if type(native_user) is not str or type(assistant) is not str:return []
    if messages is not None:
        if type(messages) is not list:return []
        currents=[m for m in messages if type(m) is dict and m.get('capture_current_turn') is True]
        if currents and not any(m.get('role')=='user' and m.get('source_kind') in (None,'human') and m.get('content')==native_user for m in currents):return []
        finals=[m for m in messages if type(m) is dict and m.get('role')=='assistant' and not m.get('tool_calls') and type(m.get('content')) is str]
        if not finals or finals[-1]['content']!=assistant:assistant=''
    result=[]
    if native_user.strip():result.append({'role':'user','content':native_user})
    if assistant.strip():result.append({'role':'assistant','content':assistant})
    return result


class LocalHonchoAdapter:
    def __init__(self,client,mapping,*,journal=None):
        url=urlsplit(str(client.base_url))
        if url.scheme!='http' or url.hostname!='127.0.0.1' or url.port!=8000 or url.path not in ('','/') or url.username or url.password or url.query or url.fragment:raise Denied('existing_Mac_localhost_8000_Honcho_only')
        self.client=client;self.mapping=dict(mapping)
        self._store=None if journal is None else PrivateStore(journal)
        self.journal=sqlite3.connect(':memory:',isolation_level=None) if self._store is None else self._store.db
        self.journal.execute('CREATE TABLE IF NOT EXISTS captures(id TEXT PRIMARY KEY,status TEXT NOT NULL)')
        self.lock=asyncio.Lock()
    def close(self):self.journal.close()
    async def handle(self,body):
        if type(body) is not dict or body.get('operation') not in ('recall','capture'):raise Denied('closed_local_memory_operation')
        op=body['operation'];shapes={'recall':{'scope','challenge','operation','query'},'capture':{'scope','challenge','operation','messages'}}
        if op=='capture' and 'projection' in body:
            shapes['capture']|={'projection','part'}
            if type(body['projection']) is not str or re.fullmatch('[0-9a-f]{64}',body['projection']) is None or type(body.get('part')) is not int or body['part']<0:raise Denied('native_capture_part_required')
        if set(body)!=shapes[op] or type(body['challenge']) is not str or len(body['challenge'])!=32:raise Denied('closed_local_memory_schema')
        user,assistant=peers_for(body['scope'],self.mapping)
        async with self.lock:
            if op=='recall':
                query=body['query']
                if type(query) is not str or not query or len(query.encode())>65536:raise Denied('bounded_memory_query_required')
                rows=await asyncio.to_thread(lambda:self.client.peer(user).search(query,limit=10))
                # Explicitly project content, never headers, SDK state, raw
                # backend metadata or other-peer handles into QYP/model traffic.
                texts=[row.content for row in rows if row.peer_id==user]
                if sum(len(t.encode()) for t in texts)>80000:raise Denied('memory_response_requires_typed_paging')
                return {'challenge':body['challenge'],'texts':texts}
            messages=body['messages']
            if type(messages) is not list:raise Denied('safe_memory_projection_required')
            for row in messages:
                if (type(row) is not dict or set(row)!={'role','content'} or row['role'] not in ('user','assistant') or type(row['content']) is not str):raise Denied('safe_memory_projection_required')
            if sum(len(row['content'].encode()) for row in messages)>80000:raise Denied('memory_projection_must_be_chunked')
            if not messages:return {'challenge':body['challenge'],'status':'empty'}
            stable=digest({key:value for key,value in body.items() if key!='challenge'})
            prior=self.journal.execute('SELECT status FROM captures WHERE id=?',(stable,)).fetchone()
            if prior:return {'challenge':body['challenge'],'status':prior[0]}
            self.journal.execute('INSERT INTO captures VALUES (?,?)',(stable,'ambiguous'))
            session='atlas-session-'+digest([body['scope']['profile'],body['scope']['session_key'],body['scope']['user_id']])
            def capture():
                payload=[self.client.peer(user if row['role']=='user' else assistant).message(row['content']) for row in messages]
                return self.client.session(session).add_messages(payload)
            await asyncio.to_thread(capture)
            self.journal.execute('UPDATE captures SET status=? WHERE id=?',('stored',stable))
            return {'challenge':body['challenge'],'status':'stored'}
