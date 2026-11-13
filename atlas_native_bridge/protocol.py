"""Closed authenticated application frames; never a URL, SDK or shell proxy."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

from atlas_bridge.contract import Denied, canonical, digest

MAX_FRAME = 131072
CHUNK = 49152
BOT_ID = '9229862070'
KINDS = frozenset(('input','input_receipt','recheck','recheck_result','egress','egress_result',
                   'memory','memory_result','stream_open','stream_chunk','stream_close',
                   'stream_result','ready','close','denied','refresh_input','work_read','work_read_result','work_read_cancel'))
_FIELDS = frozenset(('v','sender','epoch','nonce','iat','exp','kind','body','signature'))


def decode(raw):
    def unique(pairs):
        result = {}
        for k,v in pairs:
            if k in result:raise Denied('duplicate_field')
            result[k] = v
        return result
    try:
        if isinstance(raw,bytes):raw=raw.decode('utf-8')
        if type(raw) is not str or len(raw.encode())>MAX_FRAME:raise Denied('bounded_frame_required')
        value=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        if type(value) is not dict:raise ValueError()
        return value
    except (ValueError,UnicodeError,RecursionError):raise Denied('invalid_frame') from None


def directory(path):
    """Open every component nofollow; return an owned directory descriptor."""
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise Denied('absolute_trusted_directory_required')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=nxt
        return fd
    except BaseException:
        os.close(fd);raise


def load_key(path):
    path=Path(path)
    dfd=directory(path.parent)
    try:
        parent=os.fstat(dfd)
        if parent.st_uid!=os.getuid() or stat.S_IMODE(parent.st_mode)!=0o700:raise Denied('private_key_directory_required')
        try:fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
        except OSError:raise Denied('private_key_file_required') from None
        try:
            st=os.fstat(fd)
            if (not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o600
                    or st.st_nlink!=1 or not 32<=st.st_size<=256):raise Denied('private_key_file_required')
            key=os.read(fd,257)
            if len(key)!=st.st_size:raise Denied('key_changed')
            return key
        finally:os.close(fd)
    finally:os.close(dfd)


class Codec:
    def __init__(self,key,epoch,role):
        if type(key) is not bytes or len(key)<32:raise Denied('strong_key_required')
        if type(epoch) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,80}',epoch) is None:raise Denied('epoch_required')
        if role not in ('mac','qyp'):raise Denied('fixed_role_required')
        self._key=key;self.epoch=epoch;self.role=role

    def _mac(self,frame):
        domain=b'atlas-native-application-v1\0'+frame['sender'].encode()+b'\0'+frame['kind'].encode()+b'\0'
        return hmac.new(self._key,domain+canonical(frame),hashlib.sha256).hexdigest()

    def sign(self,kind,body,*,now=None):
        now=int(time.time()) if now is None else now
        if kind not in KINDS or type(body) is not dict or type(now) is not int:raise Denied('closed_application_kind')
        frame={'v':1,'sender':self.role,'epoch':self.epoch,'nonce':secrets.token_hex(16),
               'iat':now,'exp':now+30,'kind':kind,'body':body}
        result={**frame,'signature':self._mac(frame)}
        if len(canonical(result))>MAX_FRAME:raise Denied('bounded_frame_required')
        return result

    def verify(self,wire,*,now=None,for_reconciliation=False):
        now=int(time.time()) if now is None else now
        if type(wire) is not dict or set(wire)!=_FIELDS:raise Denied('closed_signed_frame_required')
        frame={k:v for k,v in wire.items() if k!='signature'}
        if (type(frame['v']) is not int or frame['v']!=1 or frame['sender']==self.role
                or frame['sender'] not in ('mac','qyp') or frame['epoch']!=self.epoch
                or frame['kind'] not in KINDS or type(frame['body']) is not dict
                or type(frame['nonce']) is not str or re.fullmatch(r'[0-9a-f]{32}',frame['nonce']) is None):raise Denied('foreign_frame')
        # Allow only one integer-second of peer clock lead for live frames.
        # Reconciliation and the absolute expiry/signed lifetime stay unchanged.
        if (type(frame['iat']) is not int or type(frame['exp']) is not int or type(now) is not int
                or not 0<frame['exp']-frame['iat']<=30
                or (now if for_reconciliation is True else now+1)<frame['iat']
                or (now>=frame['exp'] and for_reconciliation is not True)):raise Denied('stale_frame')
        signature=wire['signature']
        if (type(signature) is not str or len(signature)!=64 or len(canonical(wire))>MAX_FRAME
                or not hmac.compare_digest(self._mac(frame),signature)):raise Denied('invalid_signature')
        # Detach caller-owned dictionaries: mutation after verification grants nothing.
        return json.loads(canonical(frame))
