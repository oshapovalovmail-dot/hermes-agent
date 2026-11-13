"""Task-owned, deny-default broker. No Hermes internals or credentials.

Trust boundary: the gateway/operator owns this module and its root. Untrusted
programs receive only their mounted task directory; root parents/export staging
are never mounted. No host-project import or host-file convenience API exists.
"""
from collections import namedtuple
from contextlib import contextmanager
import hashlib
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

OWNER = json.loads((Path(__file__).resolve().parents[3]/'control/operator.json').read_text())['owner_telegram_id']
if not isinstance(OWNER,str) or re.fullmatch(r'[1-9][0-9]{0,19}',OWNER) is None:raise PermissionError('canonical_operator_owner_required')
MAX_FILE = 2 * 1024 * 1024  # bounded text reads and ingress bytes, unchanged
MAX_EXPORT = 2 * 1024**3
MAX_EXECUTION_SECONDS = 86400
STREAM_CHUNK = 1024 * 1024
MIN_FREE_BYTES = 64 * 1024 * 1024
MAX_OUTPUT = 65536
Principal = namedtuple('Principal', 'user_id session_key role profile chat_id thread_id', defaults=('', '', ''))
_IDENTITY = ('HERMES_SESSION_PLATFORM', 'HERMES_SESSION_USER_ID',
             'HERMES_SESSION_KEY', 'HERMES_SESSION_CHAT_TYPE')

# Linux x86_64 only. no_new_privs + inherited seccomp filter: no fork/vfork,
# clone only for threads, clone3 ENOSYS (glibc uses the filtered clone fallback).
# Architecture is checked BEFORE interpreting syscall numbers, including x32.
# Reference: https://kernel.org/doc/html/latest/userspace-api/seccomp_filter.html
_SECCOMP = r'''
import ctypes
if os.uname().machine != 'x86_64':
 raise RuntimeError('unsupported_seccomp_architecture')
class F(ctypes.Structure):
 _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
class P(ctypes.Structure):
 _fields_=[('len',ctypes.c_ushort),('filter',ctypes.POINTER(F))]
ins=[(0x20,0,0,4),(0x15,1,0,0xc000003e),(0x06,0,0,0x80000000),
     (0x20,0,0,0),(0x35,0,1,0x40000000),(0x06,0,0,0x80000000)]
for nr in (57,58,101,155,165,248,249,250,272,298,304,308,310,311,321,323,425,426,427):
 ins.extend([(0x15,0,1,nr),(0x06,0,0,0x00050001)])
ins.extend([(0x15,0,1,435),(0x06,0,0,0x00050026),
            (0x15,0,4,56),(0x20,0,0,16),(0x45,1,0,0x10000),
            (0x06,0,0,0x00050001),(0x06,0,0,0x7fff0000),
            (0x06,0,0,0x7fff0000)])
f=(F*len(ins))(*(F(*i) for i in ins)); prog=P(len(ins),f)
libc=ctypes.CDLL('libc.so.6',use_errno=True)
if libc.prctl(38,1,0,0,0) or libc.prctl(22,2,ctypes.byref(prog),0,0):
 raise OSError(ctypes.get_errno(),'seccomp_required')
'''



def bound_principal(get_session_env, environment):
    # Public get_session_env has an env fallback. Reject that entire ambiguous
    # situation instead of importing private ContextVars or trusting env IDs.
    if any(name in environment for name in _IDENTITY):
        raise PermissionError('ambient_identity_forbidden')
    platform, uid, key, chat_type = (get_session_env(name, '') for name in _IDENTITY)
    if (platform != 'telegram' or chat_type != 'dm' or
            not isinstance(uid, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', uid) or
            not isinstance(key, str) or not key or len(key) > 1024):
        raise PermissionError('bound_private_telegram_identity_required')
    return Principal(uid, key, 'owner' if uid == OWNER else 'member')


def _parts(path):
    if not isinstance(path, str) or not path or '\x00' in path or path.startswith('/'):
        raise PermissionError('relative_path_required')
    parts = path.split('/')
    if any(p in ('', '.', '..') for p in parts):
        raise PermissionError('noncanonical_path')
    return parts


def _directory(path):
    """Walk every component with openat O_NOFOLLOW, never resolve-then-open."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise PermissionError('absolute_broker_root_required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nxt
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise PermissionError('broker_directory_must_be_private_owned_0700')
        return fd
    except BaseException:
        os.close(fd)
        raise


class ExportCancelled(Exception):
    """Public cancellation outcome, without private native interrupt details."""


def _check_export_cancel(cancel_check):
    if cancel_check is not None and cancel_check():
        raise ExportCancelled()


class Broker:
    def __init__(self, root, backend=None):
        self.root = Path(root)
        fd = _directory(self.root); os.close(fd)
        self.backend = backend or (BwrapSandbox() if sys.platform == 'linux' else DisabledSandbox())
        self._locks = {}
        self._locks_guard = threading.Lock()
        self._exports = {}
        self._input_roots = {}
        self.max_principal_bytes = 2 * 1024**3
        self.max_files = 256
        self.max_batch_files = 32
        self.max_concurrency = 2

    @staticmethod
    def _fingerprint(st):
        return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink]

    def _record_path(self, exported):
        rel = Path(exported).relative_to(self.root / 'exports')
        name = rel.name
        if name.startswith('.') and name.endswith('.partial'):
            name = name[1:-len('.partial')]
        return self.root / 'control' / 'snapshots' / rel.parent / (name + '.json')

    def _record(self, exported):
        try:
            target = self._record_path(exported)
            dfd = _directory(target.parent)
            try:
                fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                with os.fdopen(fd, 'rb') as f:
                    st = os.fstat(f.fileno())
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > 8192:
                        return None
                    return json.loads(f.read(8193))
            finally:
                os.close(dfd)
        except (OSError, ValueError, TypeError):
            return None

    def _put_record(self, path, record, *, replace=False):
        """Private atomic copy ledger, never mounted in a sandbox."""
        dfd = _directory(path.parent)
        temporary = '.' + uuid.uuid4().hex + '.json.partial'
        try:
            fd = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dfd)
            with os.fdopen(fd,'w') as stream:
                json.dump(record,stream);stream.flush();os.fsync(stream.fileno())
            if replace:
                os.replace(temporary,path.name,src_dir_fd=dfd,dst_dir_fd=dfd)
            else:
                os.link(temporary,path.name,src_dir_fd=dfd,dst_dir_fd=dfd,follow_symlinks=False)
                os.unlink(temporary,dir_fd=dfd)
        finally:
            try:os.unlink(temporary,dir_fd=dfd)
            except FileNotFoundError:pass
            os.close(dfd)

    def check_quota(self, principal):
        """2 GiB per transport user across DM/group scopes and all tasks.

        An unchanged workspace file and its verified immutable snapshot represent
        one logical object. Credit only exact inode+size+mtime+ctime fingerprints
        recorded after streaming equal bytes. Any edit loses that credit; every
        independent snapshot remains charged. This is NOT a physical-disk quota:
        private snapshot copying may consume up to twice the charged data, and
        free-space checks remain independent. No global user/count storage cap.
        """
        self._key(principal)
        uid = principal.user_id
        size = count = 0
        regular = {}; exports = []
        for category in ('workspaces', 'inputs', 'exports'):
            base = self.root / category
            if not base.exists():continue
            for scope in base.iterdir():
                if scope.name != uid and not scope.name.endswith('-u' + uid):continue
                if scope.is_symlink() or not scope.is_dir():continue
                count += 1
                for directory, dirs, files in os.walk(scope, followlinks=False):
                    for name in dirs[:]:
                        if (Path(directory)/name).is_symlink():dirs.remove(name)
                    for name in dirs + files:
                        path = Path(directory)/name
                        try:st = path.lstat()
                        except FileNotFoundError:continue
                        count += 1
                        if stat.S_ISREG(st.st_mode):
                            size += st.st_size
                            regular[str(path.relative_to(self.root))] = self._fingerprint(st)
                            if category == 'exports':exports.append(path)
        credited = set()
        for path in exports:
            record = self._record(path)
            if not isinstance(record,dict):continue
            src = record.get('source')
            if (not isinstance(src,str) or not src.startswith('workspaces/') or src in credited):continue
            current = regular.get(str(path.relative_to(self.root)))
            original = record.get('original');snapshot = record.get('snapshot')
            if not (isinstance(original,list) and len(original)==6 and
                    isinstance(snapshot,list) and len(snapshot)==6 and current):continue
            # A protected in-progress copy is a prefix of this unchanged object.
            # Bind its exact inode; charge all independent/abandoned copies, and
            # grant at most one copy's credit per original. No hidden staging pool.
            matches = current == snapshot
            if record.get('pending') is True:
                matches = current[:2] == snapshot[:2] and current[5] == 1 and current[2] <= original[2]
            if matches and regular.get(src) == original:
                size -= current[2]
                credited.add(src)
        if size > self.max_principal_bytes or count > self.max_files:
            raise PermissionError('aggregate_workspace_quota')
        return {'bytes':size, 'files':count, 'total_bytes':size}

    @contextmanager
    def execution_slot(self, principal):
        """Cross-profile/process nonblocking global cap and one job per principal."""
        uid, _ = self._key(principal)
        root = self.root / 'control' / 'slots'
        fd = _directory(root);os.close(fd)
        held = []
        try:
            user = os.open(root / ('user-' + uid), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            held.append(user)
            try:fcntl.flock(user, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:raise PermissionError('principal_busy') from None
            for index in range(self.max_concurrency):
                slot = os.open(root / ('global-' + str(index)), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                try:fcntl.flock(slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:os.close(slot)
                else:
                    held.append(slot);break
            else:raise PermissionError('sandbox_concurrency_limit')
            yield
        finally:
            for fd in held:os.close(fd)

    def _key(self, principal):
        if (not isinstance(principal, Principal) or
                not re.fullmatch(r'[1-9][0-9]{0,19}', principal.user_id) or
                not isinstance(principal.session_key, str) or not principal.session_key or
                principal.role != ('owner' if principal.user_id == OWNER else 'member')):
            raise PermissionError('invalid_principal')
        scope=principal.user_id
        if principal.profile:
            if principal.chat_id==principal.user_id:
                if principal.profile!='tg-'+principal.user_id:raise PermissionError('private_profile_mismatch')
            else:
                if (not re.fullmatch(r'-[1-9][0-9]{0,19}',principal.chat_id) or
                        (principal.thread_id and not re.fullmatch(r'[1-9][0-9]{0,19}',principal.thread_id)) or
                        principal.profile!='tg-group-n'+principal.chat_id[1:]+'-t'+(principal.thread_id or '0')):
                    raise PermissionError('group_profile_mismatch')
                scope=principal.profile+'-u'+principal.user_id
        return scope, hashlib.sha256(principal.session_key.encode()).hexdigest()

    def workspace(self, principal):
        uid, task = self._key(principal)
        path = self.root / 'workspaces' / uid / task
        fd = _directory(path); os.close(fd)
        return path

    @contextmanager
    def _lock(self, principal):
        key = self._key(principal)
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            yield

    def read(self, principal, path):
        parts = _parts(path)
        with self._lock(principal):
            fd = _directory(self.workspace(principal))
            try:
                for part in parts[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd); fd = nxt
                filefd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    st = os.fstat(filefd)
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_FILE:
                        raise PermissionError('single_link_bounded_regular_file_required')
                    chunks = []; size = 0
                    while True:
                        chunk = os.read(filefd, min(65536, MAX_FILE + 1 - size))
                        if not chunk: break
                        size += len(chunk)
                        if size > MAX_FILE: raise PermissionError('file_too_large')
                        chunks.append(chunk)
                    return b''.join(chunks)
                finally:
                    os.close(filefd)
            finally:
                os.close(fd)

    def export(self, principal, path, *, cancel_check=None, commit_if_not_cancelled=None):
        # Native callers supply a worker-scoped commit gate. Only the in-memory
        # registration runs under it: no filesystem I/O or interrupt re-entry.
        def commit(callback):
            _check_export_cancel(cancel_check)
            if commit_if_not_cancelled is None:
                callback()
            elif not commit_if_not_cancelled(callback):
                raise ExportCancelled()

        _check_export_cancel(cancel_check)
        parts = _parts(path)
        with self._lock(principal):
            _check_export_cancel(cancel_check)
            self.check_quota(principal)
            uid, task = self._key(principal)
            source_root = self.workspace(principal)
            sfd = _directory(source_root)
            filefd = None
            try:
                for part in parts[:-1]:
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=sfd)
                    os.close(sfd);sfd=nxt
                filefd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=sfd)
                before = os.fstat(filefd)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_EXPORT:
                    raise PermissionError('single_link_bounded_export_required')
                source = str((source_root.joinpath(*parts)).relative_to(self.root))
                # Reuse only the already-issued immutable object for this task.
                for issued, expected in list(self._exports.items()):
                    record = self._record(issued)
                    if (expected[0] == self._key(principal) and record and
                            record.get('source') == source and record.get('original') == self._fingerprint(before) and
                            self.resolve_export(principal, issued, principal.session_key, cancel_check=cancel_check)):
                        commit(lambda: None)  # No new object to roll back on reuse.
                        return {'path':issued, 'media':'MEDIA:'+issued, 'bytes':before.st_size}
                _check_export_cancel(cancel_check)
                directory = self.root / 'exports' / uid / task
                dfd = _directory(directory)
                suffix = PurePosixPath(path).suffix.lower()
                if suffix not in ('.txt','.md','.json','.csv','.html','.pdf','.zip','.docx','.xlsx','.pptx','.png','.jpg'):
                    suffix = '.txt'
                name = uuid.uuid4().hex + suffix
                temporary = '.' + name + '.partial'
                path_out = str(directory/name)
                record_path = self._record_path(path_out)
                published = False
                try:
                    fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
                    with os.fdopen(fd, 'w+b') as out:
                        self._put_record(record_path,{'source':source,'original':self._fingerprint(before),
                            'snapshot':self._fingerprint(os.fstat(out.fileno())),'pending':True})
                        digest = hashlib.sha256();size=0
                        while True:
                            _check_export_cancel(cancel_check)
                            chunk=os.read(filefd, STREAM_CHUNK)
                            _check_export_cancel(cancel_check)
                            if not chunk:break
                            size += len(chunk)
                            if size > MAX_EXPORT:raise PermissionError('export_file_too_large')
                            digest.update(chunk)
                            # Preserve zero ranges as holes: exact bytes and hash,
                            # not a size-only fixture or a multi-GiB RAM buffer.
                            if chunk.count(0) == len(chunk):out.seek(len(chunk),os.SEEK_CUR)
                            else:
                                free = os.fstatvfs(out.fileno())
                                if free.f_bavail * free.f_frsize < MIN_FREE_BYTES + len(chunk):
                                    raise PermissionError('physical_disk_headroom_required')
                                out.write(chunk)
                        out.truncate(size);out.flush();os.fsync(out.fileno())
                        if size != before.st_size or self._fingerprint(os.fstat(filefd)) != self._fingerprint(before):
                            raise PermissionError('source_changed_during_export')
                        os.fchmod(out.fileno(),0o400)
                        snapshot = self._fingerprint(os.fstat(out.fileno()))
                    _check_export_cancel(cancel_check)
                    os.rename(temporary,name,src_dir_fd=dfd,dst_dir_fd=dfd)
                    published = True
                    _check_export_cancel(cancel_check)
                    # Rename may change ctime; bind the final published inode.
                    snapshot = self._fingerprint(os.stat(name,dir_fd=dfd,follow_symlinks=False))
                    self._put_record(record_path,{'source':source,'original':self._fingerprint(before),
                        'snapshot':snapshot,'sha256':digest.hexdigest()},replace=True)
                    self.check_quota(principal)
                    expected = (self._key(principal),digest.hexdigest())
                    # Recipient visibility commits here, atomically with native
                    # worker cancellation. A later /stop does not undo this object.
                    commit(lambda: self._exports.__setitem__(path_out,expected))
                    return {'path':path_out,'media':'MEDIA:'+path_out,'bytes':size}
                except BaseException:
                    # Failed publication must not consume an invisible user budget.
                    self._exports.pop(path_out,None)
                    for item in (name if published else temporary,):
                        try:os.unlink(item,dir_fd=dfd)
                        except FileNotFoundError:pass
                    try:record_path.unlink()
                    except FileNotFoundError:pass
                    raise
                finally:os.close(dfd)
            finally:
                if filefd is not None:os.close(filefd)
                os.close(sfd)

    def stage_input_stream(self, principal, path, source, *, size, sha256, cancel_check=None):
        """Trusted native attachment capability -> bounded immutable sandbox input.

        Not a model tool. The caller owns the already-open exact-scope snapshot;
        paths remain relative names below this principal's input root.
        """
        parts=_parts(path)
        if (len(parts)!=1 or type(size) is not int or not 0<=size<=MAX_EXPORT
                or type(sha256) is not str or re.fullmatch('[0-9a-f]{64}',sha256) is None
                or not callable(getattr(source,'read',None))):
            raise PermissionError('bounded_native_input_stream_required')
        with self._lock(principal):
            uid,task=self._key(principal);root=self.root/'inputs'/uid/task
            self.check_quota(principal);dfd=_directory(root)
            temporary='.'+uuid.uuid4().hex+'.partial';published=False
            try:
                fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dfd)
                try:
                    total=0;sha=hashlib.sha256()
                    with os.fdopen(fd,'wb') as out:
                        while True:
                            if cancel_check is not None and cancel_check():raise PermissionError('native_attachment_cancelled')
                            chunk=source.read(STREAM_CHUNK)
                            if not chunk:break
                            total+=len(chunk)
                            if total>size:raise PermissionError('native_attachment_length_mismatch')
                            out.write(chunk);sha.update(chunk);out.flush();self.check_quota(principal)
                        if total!=size or sha.hexdigest()!=sha256:raise PermissionError('native_attachment_hash_mismatch')
                        out.flush();os.fsync(out.fileno())
                        if cancel_check is not None and cancel_check():raise PermissionError('native_attachment_cancelled')
                        os.fchmod(out.fileno(),0o400)
                    # No overwrite: retries can only recover the exact already
                    # issued immutable input, never replace another report.
                    try:os.link(temporary,parts[0],src_dir_fd=dfd,dst_dir_fd=dfd,follow_symlinks=False)
                    except FileExistsError:
                        existing=os.open(parts[0],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=dfd)
                        with os.fdopen(existing,'rb') as old:
                            st=os.fstat(old.fileno())
                            if (not stat.S_ISREG(st.st_mode) or st.st_mode&0o222 or st.st_size!=size
                                    or hashlib.file_digest(old,'sha256').hexdigest()!=sha256):raise PermissionError('native_input_identity_conflict')
                    else:published=True
                    os.unlink(temporary,dir_fd=dfd);os.fsync(dfd)
                    self.check_quota(principal)
                    if cancel_check is not None and cancel_check():raise PermissionError('native_attachment_cancelled')
                    self._input_roots[self._key(principal)]=root
                except BaseException:
                    if published:
                        try:os.unlink(parts[0],dir_fd=dfd)
                        except FileNotFoundError:pass
                    raise
            finally:
                try:os.unlink(temporary,dir_fd=dfd)
                except FileNotFoundError:pass
                os.close(dfd)

    def stage_input(self, principal, path, content):
        """Trusted ingress: snapshot selected BYTES, never a host source path.

        No model-facing import tool. Parent transport must authorize the selected
        attachment/source before supplying bytes. Existing snapshots cannot change.
        """
        parts = _parts(path)
        if not isinstance(content, bytes) or len(content) > MAX_FILE:
            raise ValueError('bounded_input_bytes_required')
        with self._lock(principal):
            uid, task = self._key(principal)
            root = self.root / 'inputs' / uid / task
            self.check_quota(principal)
            dfd = _directory(root.joinpath(*parts[:-1]))
            try:
                fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=dfd)
                try:
                    with os.fdopen(fd, 'wb') as file:
                        file.write(content)
                    self.check_quota(principal)
                except BaseException:
                    os.unlink(parts[-1],dir_fd=dfd)
                    raise
                self._input_roots[self._key(principal)] = root
            finally:
                os.close(dfd)

    def resolve_export(self, principal, path, session_key, *, cancel_check=None):
        with self._lock(principal):
            expected = self._exports.get(path)
            if not expected or expected[0] != self._key(principal) or session_key != principal.session_key:
                return None
            # Export parents are operator-owned, never writable by a sandbox.
            # Reopen nofollow and verify content to reject host-side corruption too.
            dfd = _directory(Path(path).parent)
            try:
                fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
                with os.fdopen(fd, 'rb') as file:
                    st = os.fstat(file.fileno())
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_EXPORT:
                        return None
                    before=self._fingerprint(st);digest=hashlib.sha256();size=0
                    while True:
                        _check_export_cancel(cancel_check)
                        chunk=file.read(STREAM_CHUNK)
                        _check_export_cancel(cancel_check)
                        if not chunk:break
                        size+=len(chunk)
                        if size>MAX_EXPORT:return None
                        digest.update(chunk)
                    if (digest.hexdigest()!=expected[1] or size!=st.st_size or
                            self._fingerprint(os.fstat(file.fileno()))!=before):return None
            finally:
                os.close(dfd)
            return path

    def execute(self, principal, language, code, timeout=MAX_EXECUTION_SECONDS, *, cancel_check=None):
        if language not in ('python', 'javascript'):
            raise ValueError('only_python_or_javascript')
        if not isinstance(code, str) or len(code.encode()) > 65536:
            raise ValueError('code_too_large')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= MAX_EXECUTION_SECONDS:
            raise ValueError('timeout_must_be_1_to_86400_seconds')
        with self._lock(principal), self.execution_slot(principal):
            workspace = self.workspace(principal)
            before = self.check_quota(principal)
            workspacefd = _directory(workspace)
            try:
                options = {'inputs':self._input_roots.get(self._key(principal))}
                if isinstance(self.backend,DockerSandbox) or getattr(self.backend,'requires_execution_callbacks',False):
                    options['quota_check'] = lambda: self.check_quota(principal)
                    options['cancel_check'] = cancel_check
                result = self.backend.run(workspace, workspacefd, language, code, timeout, **options)
                after = self.check_quota(principal)
                if after['files'] - before['files'] > self.max_batch_files:
                    raise PermissionError('batch_file_limit')
                return result
            finally:
                os.close(workspacefd)


class SandboxBackend:
    """Only boundary: exact principal task dir + code; no host path tool args."""
    def run(self, workspace, workspacefd, language, code, timeout, *, inputs=None):
        raise NotImplementedError


class DisabledSandbox(SandboxBackend):
    def run(self, workspace, workspacefd, language, code, timeout, *, inputs=None):
        raise PermissionError('operator_must_select_verified_sandbox_backend')


class BwrapSandbox(SandboxBackend):
    """Historical Linux-only backend. Not Mac acceptance evidence."""
    def run(self, workspace, workspacefd, language, code, timeout, *, inputs=None):
        argv = ['/usr/bin/bwrap', '--unshare-all', '--unshare-user', '--disable-userns', '--die-with-parent',
                '--new-session', '--cap-drop', 'ALL', '--clearenv',
                '--setenv', 'PATH', '/usr/bin', '--setenv', 'HOME', '/nonexistent',
                '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'TMPDIR', '/tmp',
                '--dir', '/usr', '--dir', '/usr/bin', '--dir', '/usr/lib',
                '--dir', '/usr/lib64', '--symlink', 'usr/lib', '/lib',
                '--symlink', 'usr/lib64', '/lib64']
        # OS-distribution read-only runtime assets, not host /usr or / home mounts.
        for source in ('/usr/bin/python3.12', '/usr/lib/python3.12',
                       '/usr/lib/x86_64-linux-gnu', '/usr/lib64/ld-linux-x86-64.so.2'):
            argv += ['--ro-bind', source, source]
        if language == 'javascript':
            argv += ['--ro-bind', '/usr/bin/node', '/usr/bin/node',
                     '--ro-bind', '/usr/share/nodejs', '/usr/share/nodejs']
        if inputs is not None:
            argv += ['--ro-bind', str(inputs), '/inputs']
        argv += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                 '--bind', '/proc/self/fd/' + str(workspacefd), '/work', '--chdir', '/work',
                 '--remount-ro', '/', '--', '/usr/bin/python3.12', '-I', '-S', '-c']
        # Limits are hard-set before untrusted code; no preexec_fn in threaded gateway.
        bootstrap = "import resource,os,sys\n" + "\n".join(
            "resource.setrlimit(resource.%s,(%d,%d))" % (limit, value, value)
            for limit, value in [('RLIMIT_CPU', MAX_EXECUTION_SECONDS), ('RLIMIT_FSIZE', MAX_EXPORT),
                                 ('RLIMIT_NOFILE', 64), ('RLIMIT_NPROC', 2048),
                                 ('RLIMIT_CORE', 0), ('RLIMIT_AS', 2 * 1024**3)])
        bootstrap += '\n' + _SECCOMP
        if language == 'python':
            bootstrap += '\nexec(compile(' + repr(code) + ",'<auxiliary>','exec'),{'__name__':'__main__'})"
        else:
            bootstrap += '\nos.execv("/usr/bin/node",["node","--max-old-space-size=128","--eval",' + repr(code) + '])'
        argv.append(bootstrap)
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env={}, pass_fds=(workspacefd,), start_new_session=True)
        return _capture(p, timeout)


def _capture(p, timeout, quota_check=None, cancel_check=None):
    selector = selectors.DefaultSelector()
    output = {'stdout': bytearray(), 'stderr': bytearray()}; truncated = False
    deadline = time.monotonic() + timeout; timed_out = False; cancelled = False
    for stream, name in ((p.stdout,'stdout'),(p.stderr,'stderr')):
        os.set_blocking(stream.fileno(), False); selector.register(stream, selectors.EVENT_READ, name)
    try:
        while selector.get_map():
            if cancel_check is not None and cancel_check():
                cancelled=True
                os.killpg(p.pid, signal.SIGKILL)
                break
            if quota_check is not None:quota_check()
            if time.monotonic() >= deadline:
                timed_out = True
                os.killpg(p.pid, signal.SIGKILL)
                break
            for key, _ in selector.select(min(0.1, max(0, deadline-time.monotonic()))):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj); continue
                buf = output[key.data]; room = MAX_OUTPUT-len(buf)
                buf.extend(chunk[:room]); truncated |= len(chunk) > room
        p.wait(timeout=3)
    finally:
        selector.close()
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL); p.wait(timeout=3)
        p.stdout.close(); p.stderr.close()
    result = {'exit': p.returncode, 'stdout': output['stdout'].decode('utf-8','replace')[:MAX_OUTPUT],
              'stderr': output['stderr'].decode('utf-8','replace')[:MAX_OUTPUT], 'truncated': truncated}
    if timed_out: result['error'] = 'timeout'
    if cancelled: result['error'] = 'cancelled'
    return result


class DockerSandbox(SandboxBackend):
    """Mac host / Linux VM isolation. No ambient Docker config or client env.

    Operator pins the image and daemon endpoint. An image must contain the named
    interpreters; this class never pulls, installs or runs a host interpreter.
    """
    def __init__(self, image, docker_host, client_config, docker='/opt/homebrew/bin/docker', python='/usr/local/bin/python3', node=None):
        if not isinstance(image,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',image):
            raise ValueError('immutable_local_image_id_required')
        if not isinstance(docker_host,str) or not docker_host.startswith('unix:///'):
            raise ValueError('operator_local_unix_daemon_required')
        if not Path(docker).is_absolute() or not Path(python).is_absolute():
            raise ValueError('absolute_operator_runtime_paths_required')
        fd=_directory(client_config);os.close(fd)
        self.image=image
        self.python=python
        self.node=node
        self.client=[docker,'--config',str(client_config),'--host',docker_host]

    def _cli(self,args):
        return subprocess.run(self.client+args,env={},stdin=subprocess.DEVNULL,
                              capture_output=True,text=True,timeout=20)

    def run(self,workspace,workspacefd,language,code,timeout,*,inputs=None,quota_check=None,cancel_check=None):
        if language=='javascript' and not self.node:
            raise PermissionError('javascript_not_in_verified_image')
        uid=os.getuid();gid=os.getgid()
        if uid==0:raise PermissionError('nonroot_host_owner_required')
        # Match the private bind's actual non-root owner on the host. No chmod
        # widening, daemon socket, home, host runtime, browser or driver mount.
        name='qyp-security-'+uuid.uuid4().hex
        argv=['create','--name',name,'--label','qyp.task=security','--pull','never','--log-driver','none',
              '--network','none','--cap-drop','ALL','--security-opt','no-new-privileges',
              '--read-only','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=33554432,mode=1777',
              '--user',str(uid)+':'+str(gid),'--pids-limit','32','--memory','512m',
              '--cpus','1','--ipc','none','--cgroupns','private',
              '--ulimit','nofile=64:64','--ulimit','fsize='+str(MAX_EXPORT)+':'+str(MAX_EXPORT),
              '--ulimit','core=0:0','--ulimit','cpu=86400:86400',
              '--env','HOME=/nonexistent','--env','LANG=C.UTF-8','--env','TMPDIR=/tmp',
              '--env','PYTHONPATH=','--env','PYTHONSTARTUP=','--env','NODE_OPTIONS=',
              '--workdir','/work','--mount','type=bind,src='+str(workspace)+',dst=/work',
              '--entrypoint',self.python if language=='python' else self.node,
              self.image]
        if inputs is not None:
            argv[-1:-1] = ['--mount','type=bind,src='+str(inputs)+',dst=/inputs,readonly']
        argv+=['-I','-S','-c',code] if language=='python' else ['--max-old-space-size=128','--eval',code]
        created=self._cli(argv)
        if created.returncode:raise RuntimeError('container_create_failed')
        identifier=created.stdout.strip()
        if not re.fullmatch(r'[0-9a-f]{64}',identifier):raise RuntimeError('container_id_invalid')
        result=None
        try:
            raw=self._cli(['inspect',identifier])
            if raw.returncode:raise RuntimeError('container_inspect_failed')
            info=json.loads(raw.stdout)[0];host=info['HostConfig'];conf=info['Config'];mounts=info['Mounts']
            facts={k:host[k] for k in ('NetworkMode','ReadonlyRootfs','CapDrop','SecurityOpt')}
            facts.update(User=conf['User'],bind_destinations=[m['Destination'] for m in mounts if m['Type']=='bind'],
                         Memory=host['Memory'],NanoCpus=host['NanoCpus'],PidsLimit=host['PidsLimit'],Ulimits=host['Ulimits'])
            expected_mounts = {'/work':(str(workspace),True)}
            if inputs is not None:expected_mounts['/inputs']=(str(inputs),False)
            actual_mounts = {m['Destination']:(m['Source'],m['RW']) for m in mounts if m['Type']=='bind'}
            if (facts['NetworkMode']!='none' or facts['ReadonlyRootfs'] is not True or
                facts['CapDrop']!=['ALL'] or 'no-new-privileges' not in facts['SecurityOpt'] or
                conf['User']!=str(uid)+':'+str(gid) or len(mounts)!=len(expected_mounts) or
                actual_mounts!=expected_mounts or host['Memory']!=512*1024**2 or
                host['NanoCpus']!=1000000000 or host['PidsLimit']!=32 or
                {u['Name']:(u['Soft'],u['Hard']) for u in host['Ulimits']} !=
                {'nofile':(64,64),'fsize':(MAX_EXPORT,MAX_EXPORT),'core':(0,0),'cpu':(86400,86400)}):
                raise PermissionError('daemon_isolation_contract_mismatch')
            p=subprocess.Popen(self.client+['start','--attach',identifier],env={},
                               stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
            result=_capture(p,timeout,quota_check=quota_check,cancel_check=cancel_check)
            result['isolation']=facts
        finally:
            removed=self._cli(['rm','--force',identifier])
            check=self._cli(['inspect',identifier])
            if removed.returncode or check.returncode==0 or 'no such object' not in check.stderr.lower():
                raise RuntimeError('owned_container_cleanup_unverified:'+identifier)
            if result is not None:result['container_removed']=True
        return result
