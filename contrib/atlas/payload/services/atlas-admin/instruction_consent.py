"""One interprocess consent boundary for bootstrap and native home admission.

The stable lock inode is never replaced/unlinked. Only the small control-plane
read/validate/merge/commit is locked; native creation runs after lock release.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


@contextmanager
def consent_lock(root):
    control = Path(root) / 'control'
    if control.is_symlink() or not control.is_dir():
        raise PermissionError('controlled_consent_directory_required')
    try:
        fd = os.open(control / 'instruction-policy-approval.lock',
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as exc:
        raise PermissionError('safe_consent_lock_required') from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid() or info.st_nlink != 1):
            raise PermissionError('private_consent_lock_required')
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def atomic_consent_write(root, consent):
    """Caller holds consent_lock. Failures before replace preserve old bytes."""
    control = Path(root) / 'control'
    target = control / 'instruction-policy-approval.json'
    if target.is_symlink():
        raise PermissionError('safe_consent_record_required')
    fd, temporary = tempfile.mkstemp(prefix='.instruction-policy-approval.', suffix='.tmp', dir=control)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(consent, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        # A directory fsync failure is post-commit durability uncertainty, not
        # permission to restore an older grant over a concurrent newer record.
        directory = os.open(control, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fresh_consent(root, role_policy):
    target = root / 'control/instruction-policy-approval.json'
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise PermissionError('safe_consent_record_required')
            consent = json.load(stream)
    except (OSError, ValueError) as exc:
        raise PermissionError('approved_role_policy_consent_required') from exc
    sha = hashlib.sha256(role_policy.encode()).hexdigest()
    if (not isinstance(consent, dict) or consent.get('approved') is not True
            or consent.get('scope') != 'native-home-initialization'
            or not isinstance(consent.get('provenance'), str) or not consent['provenance'].strip()
            or consent.get('sha256') != sha):
        raise PermissionError('approved_role_policy_consent_required')
    homes = consent.get('homes')
    home = root / 'home'
    if not isinstance(homes, list) or not homes or any(not isinstance(h, str) for h in homes):
        raise PermissionError('approved_home_list_required')
    for value in homes:
        p = Path(value)
        if (str(p) != value or not p.is_absolute() or '..' in p.parts or p.is_symlink()
                or (p != home and (p.parent != home / 'profiles' or not re.fullmatch(
                    r'tg-(?:[1-9][0-9]{0,19}|group-n[1-9][0-9]{0,19}-t(?:0|[1-9][0-9]{0,19}))', p.name)))):
            raise PermissionError('approved_home_list_required')
    existing = {str(home)}
    for p in (home / 'profiles').glob('*'):
        # Native create_profile stages outside the consent lock, before its
        # atomic directory publication. A staging sibling is not a new home.
        staging = re.fullmatch(r'\.(.+)\.staging-[1-9][0-9]*', p.name)
        if staging and str(p.parent / staging[1]) in homes and not p.is_symlink():
            continue
        existing.add(str(p))
    if not existing <= set(homes):
        raise PermissionError('existing_home_consent_required')
    # No fallback/default policy, including retries after interrupted creation.
    for policy in (root / 'control/SOUL.md', home / 'SOUL.md'):
        if policy.is_symlink() or not policy.is_file() or hashlib.sha256(policy.read_bytes()).hexdigest() != sha:
            raise PermissionError('approved_source_policy_required')
    return consent


def authorize_home(home, path, role_policy, *, created):
    root = Path(home).parent
    with consent_lock(root):
        consent = _fresh_consent(root, role_policy)
        if not created:
            if str(path) not in consent['homes']:
                raise PermissionError('existing_home_consent_required')
            return
        consent['homes'] = sorted(set(consent['homes']) | {str(path)})
        atomic_consent_write(root, consent)
