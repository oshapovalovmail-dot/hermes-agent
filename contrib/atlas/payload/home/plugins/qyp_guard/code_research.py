"""Closed local source reader; source descriptors are ALWAYS O_RDONLY.

Only trusted operator configuration supplies the mount root. No command, URL,
write, generic host path or mount operation is exposed. Read snapshots are handed
as bytes to the existing principal-bound input broker, never mounted Arcadia.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat

SCOPES=('neuroexpert','junk/ovshapovalov','frontend/browserweb/projects/neuro-expert',
        'alice','agents/eval','agents/sdk-go','taxi/tplatform/ai_infra/ai_minion',
        'zootopia/analytics/ml/stefania','portal/alice-cowork','browser')
MAX_SOURCE_BYTES=2*1024*1024
MAX_SCAN_BYTES=8*1024*1024
MAX_SCAN_ENTRIES=4096
_FIELDS={'operation','scope','path','start_line','line_count','query','limit','after_path','after_line'}
_SECRET=re.compile(r'^(?:\.env(?:\..*)?|\.(?:envrc|netrc|npmrc|pypirc|git-credentials|docker|gnupg|kube|azure)|\.tokens?|\.git|\.ssh|\.aws|\.config|credentials?(?:\..*)?|cookies?(?:\..*)?|auth\.(?:json|yaml|yml|db|sqlite|sqlite3)|(?:secrets?|keyring|token-store)(?:\..*)?|tokens?(?:\..*)?|id_(?:rsa|ed25519)(?:\..*)?)$|\.(?:pem|key|p12|pfx|keychain|keychain-db)$',re.I)


def parts(path,*,empty=False):
    if type(path) is not str or '\x00' in path or '\\' in path or '%' in path:
        raise PermissionError('canonical_source_relative_path_required')
    if not path and empty:return []
    out=path.split('/')
    if any(p in ('','.','..') or _SECRET.search(p) for p in out):
        raise PermissionError('source_path_or_secret_storage_denied')
    return out


def integer(value,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError('bounded_integer_required')
    return value


def fingerprint(st):
    return (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,st.st_nlink)


class CodeReader:
    def __init__(self,root):
        self.root=Path(root)
        if not self.root.is_absolute() or '..' in self.root.parts:
            raise PermissionError('operator_absolute_source_root_required')

    @contextmanager
    def _open(self,relative,directory=False):
        # Hold and revalidate EACH parent descriptor. A moved directory, swapped
        # intermediate symlink or changed final inode invalidates the operation.
        components=list(self.root.parts[1:])+relative
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY);fds=[fd];chain=[]
        try:
            for index,name in enumerate(components):
                flags=os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK
                if index<len(components)-1 or directory:flags|=os.O_DIRECTORY
                nxt=os.open(name,flags,dir_fd=fd)
                st=os.fstat(nxt);chain.append((fd,name,nxt,(st.st_dev,st.st_ino)))
                fd=nxt;fds.append(fd)
            def validate():
                for parent,name,child,identity in chain:
                    current=os.stat(name,dir_fd=parent,follow_symlinks=False)
                    held=os.fstat(child)
                    if stat.S_ISLNK(current.st_mode) or (current.st_dev,current.st_ino)!=identity or (held.st_dev,held.st_ino)!=identity:
                        raise PermissionError('source_path_changed')
            validate();yield fd,validate;validate()
        finally:
            for item in reversed(fds):os.close(item)

    def _read(self,fd):
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>MAX_SOURCE_BYTES:
            raise PermissionError('single_link_bounded_source_file_required')
        data=bytearray()
        while True:
            block=os.read(fd,min(65536,MAX_SOURCE_BYTES+1-len(data)))
            if not block:break
            data.extend(block)
            if len(data)>MAX_SOURCE_BYTES:raise PermissionError('source_file_capacity')
        if fingerprint(before)!=fingerprint(os.fstat(fd)):
            raise PermissionError('source_changed_during_read')
        return bytes(data)

    def _file(self,relative):
        with self._open(relative) as (fd,validate):
            before=fingerprint(os.fstat(fd));data=self._read(fd);validate()
            if before!=fingerprint(os.fstat(fd)):raise PermissionError('source_changed_during_read')
            return data

    def _entries(self,relative):
        with self._open(relative,directory=True) as (fd,validate):
            entries=[];seen=0
            with os.scandir(fd) as scan:
                for entry in scan:
                    seen+=1
                    if seen>MAX_SCAN_ENTRIES:raise PermissionError('source_scan_capacity_narrow_path')
                    if _SECRET.search(entry.name):continue
                    st=entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(st.st_mode):continue
                    if stat.S_ISDIR(st.st_mode):kind='directory'
                    elif stat.S_ISREG(st.st_mode) and st.st_nlink==1:kind='file'
                    else:continue
                    entries.append((entry.name,kind))
            validate();return sorted(entries)

    def query(self,args):
        if type(args) is not dict or set(args)-_FIELDS or not {'operation','scope','path'}<=set(args):
            raise PermissionError('closed_code_research_arguments_required')
        op=args['operation'];scope=args['scope']
        if op not in ('read','list','search') or scope not in SCOPES:
            raise PermissionError('explicit_allowed_source_subtree_required')
        relative=parts(scope)+parts(args['path'],empty=op!='read')
        result={'scope':scope,'path':args['path'],'readonly':True,'snapshot_consistent':False}
        if op=='read':
            if set(args)-{'operation','scope','path','start_line','line_count'}:raise PermissionError('operation_arguments_denied')
            start=integer(args.get('start_line',1),1,2147483647);count=integer(args.get('line_count',200),1,200)
            data=self._file(relative)
            try:lines=data.decode('utf-8').splitlines()
            except UnicodeDecodeError:raise PermissionError('utf8_source_required') from None
            result.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),snapshot_consistent=True,
                lines=[{'line':i+1,'text':line} for i,line in enumerate(lines[start-1:start-1+count],start-1)],
                has_more=start-1+count<len(lines),next_line=start+count if start-1+count<len(lines) else None)
            return result,data
        if set(args)-{'operation','scope','path','query','limit','after_path','after_line'}:raise PermissionError('operation_arguments_denied')
        limit=integer(args.get('limit',200),1,200)
        after=args.get('after_path','');parts(after,empty=True)
        after_line=integer(args.get('after_line',0),0,2147483647)
        if op=='list':
            if 'query' in args or after_line:raise PermissionError('operation_arguments_denied')
            entries=[{'path':name,'kind':kind} for name,kind in self._entries(relative) if name>after]
            result.update(entries=entries[:limit],has_more=len(entries)>limit,
                continuation={'after_path':entries[limit-1]['path']} if len(entries)>limit else None)
            return result,None
        query=args.get('query')
        if type(query) is not str or not 1<=len(query)<=256 or '\x00' in query:raise ValueError('bounded_literal_query_required')
        pending=[('',relative)];matches=[];scanned=0;size=0
        while pending:
            local,current=pending.pop()
            with self._open(current) as (fd,validate):isdir=stat.S_ISDIR(os.fstat(fd).st_mode)
            if isdir:
                entries=self._entries(current);scanned+=len(entries)
                if scanned>MAX_SCAN_ENTRIES:raise PermissionError('source_scan_capacity_narrow_path')
                for name,kind in reversed(entries):pending.append((local+'/'+name if local else name,current+[name]))
                continue
            if not local:local=args['path']
            if local<after:continue
            data=self._file(current);size+=len(data)
            if size>MAX_SCAN_BYTES:raise PermissionError('source_scan_capacity_narrow_path')
            try:lines=data.decode('utf-8').splitlines()
            except UnicodeDecodeError:continue
            for index,line in enumerate(lines,1):
                if local==after and index<=after_line:continue
                if query in line:
                    matches.append({'path':local or args['path'],'line':index,'text':line})
                    if len(matches)>limit:
                        last=matches[limit-1]
                        result.update(matches=matches[:limit],has_more=True,continuation={'after_path':last['path'],'after_line':last['line']})
                        return result,None
        result.update(matches=matches,has_more=False,continuation=None)
        return result,None
