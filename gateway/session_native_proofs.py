"""Admission-specific, process-local handoff; never a wire capability.

Only the native commit's loop-side callback may retain an already issued proof.
A reconstructed event cannot issue one. Generic transports import no Atlas SDK.
Queued proofs expire at the existing 600s lifetime, without a request-count
ceiling. Claimed proofs move to their exact event and remain valid for its
existing revocation/output checks, not a cache TTL.
"""
import sys
import time
import asyncio
from contextlib import nullcontext

MAX_PENDING = 4096
MAX_AGE = 600

class NativeAdmissionDenied(PermissionError):
    pass

def handoff(authority):
    """Exclude an already-running drain's claim until commit AND retain finish.

    A row is visible to other worker connections before tracked_write's loop
    callback. Scheduling order alone is therefore insufficient. No Atlas gate
    installed means no change to the generic runtime's locking contract.
    """
    module = sys.modules.get('gateway.atlas_admission')
    if module is None or module.installed_gate() is None:
        return nullcontext()
    lock = getattr(authority, '_native_proof_handoff', None)
    if lock is None:
        lock = authority._native_proof_handoff = asyncio.Lock()
    return lock

def _gate(source):
    if getattr(getattr(source, 'platform', None), 'value', None) != 'telegram':
        return None
    module = sys.modules.get('gateway.atlas_admission')
    return module.installed_gate() if module is not None else None

def _identity(row):
    return tuple(row.get(k) for k in ('admission_id', 'principal_id', 'request_id', 'seq'))

def retain(authority, event, row, *, first_insert=False):
    """Called on the owner loop, before pending publication and drain scheduling.

    Only a durable first insert may create a proof; missing disposition denies.
    setdefault preserves the original actor if its commit callback is repeated.
    An unavailable/expired proof is refused at execution, not a post-commit throw.
    """
    gate = _gate(event.source)
    if gate is None or first_insert is not True:
        return
    proofs = getattr(authority, '_native_admission_proofs', None)
    if proofs is None:
        proofs = authority._native_admission_proofs = {}
    now = time.monotonic()
    for key, proof in list(proofs.items()):
        if now - proof[0] > MAX_AGE:
            proofs.pop(key, None)
    if row['status'] != 'queued' or not gate.source_authorized(event.source):
        return
    # Every first durable insert retains its own proof. A finite cache here
    # would ACK a queued row that can never be claimed, and leave pre-handoff
    # attachment authority ACTIVE without a pending retirement owner.
    proofs.setdefault(row['admission_id'], (
        now, authority.epoch, _identity(row), row['target_session_id'],
        event.source.to_dict(), event.source._atlas_binding,
        event.source._atlas_binding.username))
    queued = getattr(gate, 'queue_source', None)
    if queued is not None:queued(event.source)

def restore(authority, ref, row, event):
    """Consume once under the canonical claim. No live.source/last-actor lookup."""
    gate = _gate(event.source)
    if gate is None:
        return
    proof = getattr(authority, '_native_admission_proofs', {}).pop(row['admission_id'], None)
    if proof is None:
        raise NativeAdmissionDenied('native_admission_proof_unavailable')
    created, epoch, identity, owner, origin, binding, username = proof
    owner = authority._current_owner(owner)
    if (time.monotonic() - created > MAX_AGE or epoch != authority.epoch
            or identity != _identity(row) or owner != ref.session_id
            or row['target_session_id'] != ref.session_id
            or row['status'] != 'started' or type(row.get('generation')) is not int
            or row['generation'] <= 0 or event.source.to_dict() != origin
            or binding.username != username or not gate.valid(binding)):
        raise NativeAdmissionDenied('native_admission_proof_mismatch')
    gate.stamp_source(event.source, binding)
    if not gate.source_authorized(event.source):
        raise NativeAdmissionDenied('native_admission_source_mismatch')
    activate = getattr(gate, 'activate_source', None)
    if activate is not None:activate(event.source)

def drop(authority, admission_id):
    proof = getattr(authority, '_native_admission_proofs', {}).pop(admission_id, None)
    if proof is not None:
        # An unclaimed/dropped proof cannot leave its remote raw text alive.
        module = sys.modules.get('gateway.atlas_admission')
        gate = module.installed_gate() if module is not None else None
        retire = getattr(gate, 'revoke', None)
        if retire is not None:retire(proof[5])

def complete_source(source):
    gate = _gate(source)
    complete = getattr(gate, 'complete_source', None)
    if complete is not None:complete(source)
