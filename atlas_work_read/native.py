"""New minimal native canonical-turn seam, NOT an existing published proof API.

No model arguments, JSON scope, UID or authorization boolean can construct a
turn. Only the native FIFO execution site enters canonical_execution with its
restored source and actual started ledger row. Full native acceptance requires
parent fixture approval; contract tests do not claim that acceptance.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from atlas_bridge.contract import Denied
from .rpc import request

_CURRENT=ContextVar('atlas_closed_read_canonical_turn',default=None)
_ACTIVE={}
_CONFIG={}

@dataclass(eq=False)
class _CanonicalTurn:
    authority:object
    ref:object
    row:dict
    event:object
    gate:object
    binding:object
    home:Path
    active:bool=True
    def check(self,*,tool_context=False):
        if not self.active or _ACTIVE.get(id(self))is not self:raise Denied('native_canonical_turn_required')
        from hermes_state_runtime import get_session_admission
        row=get_session_admission(self.authority.db,admission_id=self.row['admission_id'])
        if (type(self.authority.epoch)is not int or self.authority.epoch<=0
            or type(self.row['authority_epoch'])is not int or self.row['authority_epoch']<=0):raise Denied('native_canonical_epoch_required')
        if (row is None or row['status']!='started' or row['generation']!=self.row['generation'] or row['target_session_id']!=self.ref.session_id
            or self.authority.epoch!=self.row['authority_epoch'] or not self.gate.source_authorized(self.event.source)
            or getattr(self.event.source,'_atlas_binding',None)is not self.binding):raise Denied('native_canonical_turn_revoked')
        if tool_context:
            from gateway.atlas_admission import current_binding
            from gateway.session_context import bound_session_key
            from hermes_constants import get_hermes_home
            if current_binding()is not self.binding or get_hermes_home().resolve()!=self.home or bound_session_key()!=self.gate.scope(self.binding)['session_key']:raise Denied('exact_native_tool_profile_required')
        from tools.interrupt import is_interrupted
        if is_interrupted():raise InterruptedError('native_read_cancelled')

@contextmanager
def canonical_execution(authority,ref,row,event):
    from gateway.atlas_admission import installed_gate
    gate=installed_gate()
    # Keep generic/unsupported source behavior unchanged. Atlas calls still deny
    # without a registered native turn; never promote executing_admission=True.
    if gate is None or not gate.source_authorized(event.source) or not callable(getattr(gate,'scope',None)):
        yield
        return
    source=event.source
    home=Path(str(authority.profile_id)).resolve(strict=True)
    turn=_CanonicalTurn(authority,ref,{'admission_id':row['admission_id'],'generation':row['generation'],'authority_epoch':authority.epoch},event,gate,source._atlas_binding,home)
    _ACTIVE[id(turn)]=turn;token=_CURRENT.set(turn)
    try:
        turn.check();yield
    finally:
        turn.active=False;_ACTIVE.pop(id(turn),None);_CURRENT.reset(token)

def current_turn():
    turn=_CURRENT.get()
    if type(turn)is not _CanonicalTurn or _ACTIVE.get(id(turn))is not turn:raise Denied('native_canonical_turn_required')
    turn.check(tool_context=True)
    return turn

def _issue_active_request(turn,method,args,bundle_id):
    if type(turn)is not _CanonicalTurn or _ACTIVE.get(id(turn))is not turn:raise Denied('native_canonical_turn_required')
    turn.check()
    # Native retains the exact positive integer epoch. Only this wire boundary
    # encodes it as canonical ASCII decimal, as required by closed RPC consumers.
    return turn.gate.codec.sign('work_read',request(turn.gate.scope(turn.binding),{'admission_id':turn.row['admission_id'],'session_id':turn.ref.session_id,'generation':turn.row['generation'],'authority_epoch':str(turn.authority.epoch)},method,args,bundle_id))

def issue_request(turn,method,args,bundle_id):
    if type(turn)is not _CanonicalTurn or _ACTIVE.get(id(turn))is not turn:raise Denied('native_canonical_turn_required')
    turn.check(tool_context=True)
    return _issue_active_request(turn,method,args,bundle_id)

class NativeCallLease:
    def __init__(self,turn,name,args,bundle):
        import json
        from atlas_bridge.contract import canonical
        turn.check(tool_context=True)
        self.turn=turn;self.name=name;self.args=json.loads(canonical(args));self.bundle=bundle
    def meta(self):
        # New nonce for each actual SDK attempt, after the last await/queue lock.
        self.bundle.verify()
        return {'atlas.nativeSessionProof':_issue_active_request(self.turn,self.name,self.args,self.bundle.bundle_id)}
    def after(self):self.turn.check()

def configure(ctx):
    """Provisioner-owned setting; called by the scoped native PluginManager."""
    settings=ctx.get_config('typed_work_read')
    if settings is None:return
    if type(settings)is not dict or set(settings)!={'bundle_root','bundle_pins'}:raise Denied('closed_read_configuration')
    from .bundle import Bundle
    from hermes_constants import get_hermes_home
    home=get_hermes_home().resolve(strict=True)
    _CONFIG[home]=Bundle(settings['bundle_root'],settings['bundle_pins'])

def allow_original_trace(args):
    """QYP guard projection of the authenticated original Mac ingress only.

    Mac still requires its own actual-SDK URL and selected-tab proof. The
    projection is not a grant and cannot supply identity or a tab identifier.
    """
    from .rpc import original_human_urls
    try:
        turn=current_turn();bundle=_CONFIG.get(turn.home)
        if bundle is None or type(args)is not dict or set(args)-{'url','max_chars'}:return False
        bundle.verify();bundle.module.validate_trace(args.get('url'));bundle.module.valid_bound(args.get('max_chars',12000))
        original=turn.gate.canonical_text(turn.binding)
        return args['url'] in original_human_urls(original)
    except Exception:return False

def prepare_native_call(server_name,name,args):
    if server_name!='atlas_read':return None
    turn=current_turn();bundle=_CONFIG.get(turn.home)
    if bundle is None:raise Denied('native_read_bundle_not_configured')
    return NativeCallLease(turn,name,args,bundle)
