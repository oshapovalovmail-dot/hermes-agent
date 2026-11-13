"""Native Podman backend for the explicitly scoped Atlas rootful store.

Host operator/source are trusted. Model code is only stdin data to a pinned,
read-only image supervisor. No generic Podman argv or model host-path API.
"""
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time
import uuid

ATLAS=Path('/home/ovshapovalov/.local/share/hermes-atlas')
CAPS={'CAP_CHOWN','CAP_DAC_OVERRIDE','CAP_FOWNER','CAP_FSETID','CAP_KILL','CAP_NET_BIND_SERVICE','CAP_SETFCAP','CAP_SETGID','CAP_SETPCAP','CAP_SETUID','CAP_SYS_CHROOT'}
LIMITS={'RLIMIT_NOFILE':(64,64),'RLIMIT_FSIZE':(2147483648,2147483648),'RLIMIT_CORE':(0,0),'RLIMIT_CPU':(86400,86400),'RLIMIT_NPROC':(4194304,4194304)}
SUPERVISOR='/opt/atlas/podman_supervisor.py'

def validate_raw(info,*,image,uid,gid,workspace,inputs=None,entrypoint=None):
    """Validate genuine Podman 4.9.3 JSON. Never synthesize Docker JSON.

    Expanded CapDrop is an engine representation, NOT runtime zero-cap proof.
    The trusted supervisor and host cgroups must independently pass before GO.
    """
    try:
        h=info['HostConfig'];c=info['Config'];mounts=info['Mounts']
        expected={'/work':(str(workspace),True)}
        if inputs is not None:expected['/inputs']=(str(inputs),False)
        actual={m['Destination']:(m['Source'],m['RW']) for m in mounts if m['Type']=='bind'}
        good=(info['Image'].removeprefix('sha256:')==image.removeprefix('sha256:') and
            h['Privileged'] is False and h['CapAdd']==[] and set(h['CapDrop'])==CAPS and len(h['CapDrop'])==len(CAPS) and
            h['SecurityOpt']==['no-new-privileges'] and h['NetworkMode']=='none' and h['ReadonlyRootfs'] is True and
            h['IpcMode']=='none' and h['CgroupMode']=='private' and h['PidMode']=='private' and
            not h['Devices'] and not h['GroupAdd'] and not h['PortBindings'] and
            c['User']==str(uid)+':'+str(gid) and c['WorkingDir']=='/work' and
            (entrypoint is None or c['Entrypoint']==entrypoint) and
            len(mounts)==len(expected) and actual==expected and
            all(m['Propagation']=='rprivate' for m in mounts) and
            h['Memory']==536870912 and h['PidsLimit']==32 and h['NanoCpus']==1000000000 and
            h['CpuQuota']==100000 and h['CpuPeriod']==100000 and
            {u['Name']:(u['Soft'],u['Hard']) for u in h['Ulimits']}==LIMITS and len(h['Ulimits'])==5 and
            h['Tmpfs']=={'/tmp':'rw,noexec,nosuid,nodev,size=33554432,mode=1777,rprivate,tmpcopyup'})
        if not good:raise PermissionError('podman_raw_isolation_contract_mismatch')
        return True
    except (KeyError,TypeError,ValueError,AttributeError):
        raise PermissionError('podman_raw_isolation_contract_mismatch') from None

def validate_runtime(proof,uid,gid,host_namespaces):
    try:
        good=(proof['uid']==uid and proof['gid']==gid and
            proof['status']['NoNewPrivs']=='1' and proof['status']['Seccomp']=='2' and
            all(int(proof['status'][cap],16)==0 for cap in ('CapEff','CapBnd','CapPrm','CapAmb','CapInh')) and
            proof['limits']=={'nofile':[64,64],'fsize':[2147483648,2147483648],'core':[0,0],'cpu':[86400,86400]} and
            set(proof['namespaces'])=={'net','mnt','pid','ipc','cgroup'} and
            all(proof['namespaces'][n]!=host_namespaces[n] for n in host_namespaces))
        if not good:raise PermissionError('runtime_security_contract_mismatch')
        return True
    except (KeyError,TypeError,ValueError):raise PermissionError('runtime_security_contract_mismatch') from None

def outcome(exitcode,before,after,forced=None):
    if forced:return forced
    if after is None or before is None or after<before:return 'oom_observation_unknown'
    if after>before:return 'memory_limit'
    return None

def private_dir(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:raise PermissionError('canonical_private_directory_required')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        s=os.fstat(fd)
        if s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o700:raise PermissionError('private_owned_directory_required')
        return fd
    except BaseException:os.close(fd);raise

def record(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())

class ScopedEngine:
    """Closed privileged-command builder; only owned typed operations exist.

    The host owner already has sudo. This wrapper does not limit that owner.
    Operation metadata is private, immutable and never mounted in the sandbox.
    """
    def __init__(self,metadata,image,broker_root):
        self.metadata=Path(metadata);self.broker_root=Path(broker_root);self.image=image;self.ids={}
        for p in (self.metadata,self.broker_root):
            if not p.is_relative_to(ATLAS):raise PermissionError('atlas_only')
            fd=private_dir(p);os.close(fd)
        if not re.fullmatch('sha256:[0-9a-f]{64}',image):raise ValueError('pinned_image_required')
        self.tmp=self.metadata/'tmp';self.tmp.mkdir(mode=0o700,exist_ok=True);fd=private_dir(self.tmp);os.close(fd)
        self.prefix=['/usr/bin/sudo','-n','TMPDIR='+str(self.tmp),'/usr/bin/podman','--root',str(ATLAS/'control/podman-rootful-store'),'--runroot','control/podman-rootful-run','--cgroup-manager','cgroupfs','--tmpdir',str(self.tmp)]
    def _invoke(self,argv):
        return subprocess.run(self.prefix+argv,cwd=ATLAS,env={'PATH':'/usr/bin:/bin'},stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=30)
    def _owned(self,cid):
        if not re.fullmatch('[0-9a-f]{64}',cid) or cid not in self.ids:raise PermissionError('exact_owned_id_required')
    def path(self,p,kind):
        p=Path(p);rel=p.relative_to(self.broker_root/kind)
        if len(rel.parts)!=2 or not re.fullmatch(r'(?:[1-9][0-9]{0,19}|tg-group-n[1-9][0-9]{0,19}-t[0-9]+-u[1-9][0-9]{0,19})',rel.parts[0]) or not re.fullmatch('[0-9a-f]{64}',rel.parts[1]):raise PermissionError('exact_broker_task_scope_required')
        fd=private_dir(p);os.close(fd);return p
    def _resolve_creation(self,request,expected=None):
        # Only a freshly pre-recorded internal intent is reconciled; no scans,
        # caller-selected names, default store or prefix-based removal.
        name=request['name'];p=self._invoke(['container','exists',name])
        if p.returncode!=0:raise RuntimeError('create_reconciliation_unknown')
        p=self._invoke(['inspect',name])
        if p.returncode:raise RuntimeError('create_reconciliation_inspect_failed')
        values=json.loads(p.stdout)
        if not isinstance(values,list) or len(values)!=1:raise PermissionError('creation_ownership_unknown')
        info=values[0];cid=info.get('Id')
        if (not isinstance(cid,str) or not re.fullmatch('[0-9a-f]{64}',cid) or
            (expected is not None and cid!=expected) or info.get('Name')!=name or
            info.get('Config',{}).get('Labels',{}).get('qyp.task')!='atlas-doc'):
            raise PermissionError('creation_ownership_unknown')
        workspace=self.path(request['workspace'],'workspaces');s=workspace.stat()
        if [s.st_dev,s.st_ino]!=request['workspace_identity']:raise PermissionError('creation_workspace_identity_changed')
        validate_raw(info,image=request['image'],uid=os.getuid(),gid=os.getgid(),workspace=workspace,
            inputs=request['inputs'],entrypoint='/usr/local/bin/python3')
        self.ids[cid]=request['operation']
        return cid
    def create(self,workspace,workspacefd,inputs):
        self.last_creation=None
        workspace=self.path(workspace,'workspaces')
        s=workspace.stat();f=os.fstat(workspacefd)
        if (s.st_dev,s.st_ino)!=(f.st_dev,f.st_ino):raise PermissionError('workspace_fd_identity_mismatch')
        if inputs is not None:
            inputs=self.path(inputs,'inputs')
            if inputs.relative_to(self.broker_root/'inputs')!=workspace.relative_to(self.broker_root/'workspaces'):raise PermissionError('input_task_scope_mismatch')
        op=uuid.uuid4().hex;name='atlas-doc-'+op
        request={'operation':op,'name':name,'workspace':str(workspace),'inputs':str(inputs) if inputs else None,'image':self.image,'workspace_identity':[s.st_dev,s.st_ino]}
        record(self.metadata/(op+'.request.json'),request)
        a=['create','--name',name,'--label','qyp.task=atlas-doc','--pull','never','--log-driver','none','--image-volume','ignore','--interactive','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=33554432,mode=1777','--user',str(os.getuid())+':'+str(os.getgid()),'--pids-limit','32','--memory','512m','--cpus','1','--ipc','none','--cgroupns','private','--ulimit','nofile=64:64','--ulimit','fsize=2147483648:2147483648','--ulimit','core=0:0','--ulimit','cpu=86400:86400','--env','HOME=/nonexistent','--env','LANG=C.UTF-8','--env','TMPDIR=/tmp','--env','PYTHONPATH=','--env','PYTHONSTARTUP=','--env','NODE_OPTIONS=','--workdir','/work','--mount','type=bind,src='+str(workspace)+',dst=/work']
        if inputs is not None:a+=['--mount','type=bind,src='+str(inputs)+',dst=/inputs,readonly']
        a+=['--entrypoint','/usr/local/bin/python3',self.image,'-I','-S','-u',SUPERVISOR]
        cid=None;creation={'operation':op,'name':name,'cleanup':{'status':'unknown'}};self.last_creation=creation
        try:
            p=self._invoke(a)
            if p.returncode:raise RuntimeError('container_create_failed:'+p.stderr[-1000:])
            returned=p.stdout.strip()
            if not re.fullmatch('[0-9a-f]{64}',returned):raise RuntimeError('invalid_container_id')
            cid=self._resolve_creation(request,returned)
            creation['id']=cid
            record(self.metadata/(op+'.created.json'),{'id':cid,'argv':a,'exit':p.returncode})
            return cid
        except BaseException as exc:
            # Includes lost daemon ACK, failed ID journal and cancellation.
            # The original exception wins even if reconciliation/journaling fails.
            try:
                if cid is None:cid=self._resolve_creation(request)
                creation['id']=cid
                creation['cleanup']={'status':'removed',**self.remove(cid)}
            except BaseException as cleanup_error:
                creation['cleanup']={'status':'unknown','id':cid,'error':repr(cleanup_error)}
            creation['exception']=repr(exc)
            try:record(self.metadata/(op+'.create-failure.json'),creation)
            except BaseException as journal_error:creation['journal_error']=repr(journal_error)
            exc.add_note('create_cleanup:'+json.dumps(creation['cleanup']))
            raise
    def inspect(self,cid):
        self._owned(cid);p=self._invoke(['inspect',cid])
        if p.returncode:raise RuntimeError('owned_container_inspect_failed')
        return json.loads(p.stdout)[0]
    def attach(self,cid):
        self._owned(cid)
        return subprocess.Popen(self.prefix+['start','--attach','--interactive',cid],cwd=ATLAS,env={'PATH':'/usr/bin:/bin'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    def kill(self,cid):
        self._owned(cid);p=self._invoke(['kill','--signal','KILL',cid])
        if p.returncode and self.inspect(cid)['State']['Running']:raise RuntimeError('owned_container_kill_failed')
    def remove(self,cid):
        self._owned(cid);p=self._invoke(['rm','--force',cid]);check=self._invoke(['container','exists',cid])
        receipt={'id':cid,'remove_exit':p.returncode,'exists_exit':check.returncode}
        # Physical removal/readback precede best-effort metadata. ENOSPC must
        # not turn a journal write into a barrier to owned-container cleanup.
        try:record(self.metadata/(self.ids[cid]+'.cleanup.json'),receipt)
        except BaseException as journal_error:receipt['journal_error']=repr(journal_error)
        if p.returncode or check.returncode!=1:raise RuntimeError('owned_container_cleanup_unverified:'+cid)
        return receipt

class OwnedCgroup:
    """Retained counter observation, armed while trusted PID1 blocks on GO.

    PID1 holds the cgroup alive after the payload exits until final counter read.
    Unexpected supervisor death/ENODEV is unknown, never an invented OOM.
    """
    def __init__(self,pid,cid):
        self.pid=pid;self.cid=cid;self.start=self.identity();self.fds={};self.samples=[]
        raw=Path('/proc/'+str(pid)+'/cgroup').read_text();groups={}
        for line in raw.splitlines():
            _,names,path=line.split(':',2)
            if cid not in path:raise PermissionError('foreign_cgroup_forbidden')
            for n in names.split(','):groups[n]=path
        def location(controller,file):return Path('/sys/fs/cgroup')/controller/groups[controller].lstrip('/')/file
        self.paths={k:str(location(c,f)) for k,c,f in [('oom','memory','memory.oom_control'),('memory','memory','memory.limit_in_bytes'),('peak','memory','memory.max_usage_in_bytes'),('pids','pids','pids.max'),('quota','cpu','cpu.cfs_quota_us'),('period','cpu','cpu.cfs_period_us'),('throttle','cpu','cpu.stat')]}
        try:
            for key,path in self.paths.items():self.fds[key]=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            self.before=self.sample()
            if self.before['memory']!='536870912' or self.before['pids']!='32' or self.before['quota']!='100000' or self.before['period']!='100000':raise PermissionError('kernel_resource_contract_mismatch')
            if self.identity()!=self.start:raise PermissionError('pid_start_identity_changed')
        except BaseException:self.close();raise
    def identity(self):
        raw=Path('/proc/'+str(self.pid)+'/stat').read_text();return raw.rsplit(')',1)[1].split()[19]
    def sample(self):
        values={}
        for k,fd in self.fds.items():os.lseek(fd,0,0);values[k]=os.read(fd,4096).decode().strip()
        values['oom_kill']=int(re.search(r'^oom_kill (\d+)$',values['oom'],re.M).group(1))
        if not self.samples or values!=self.samples[-1]:self.samples.append(values)
        return values
    def close(self):
        for fd in self.fds.values():os.close(fd)
        self.fds={}

class PodmanSandbox:
    requires_execution_callbacks=True
    def __init__(self,image,broker_root,metadata):
        if os.getuid()==0:raise PermissionError('nonroot_operator_required')
        self.engine=ScopedEngine(metadata,image,broker_root);self.image=image;self.last_receipt=None
    def run(self,workspace,workspacefd,language,code,timeout=86400,*,inputs=None,quota_check=None,cancel_check=None):
        if language not in ('python','javascript') or not isinstance(code,str) or len(code.encode())>65536:raise ValueError('bounded_python_or_javascript_required')
        if isinstance(timeout,bool) or not isinstance(timeout,(float,int)) or not 1<=timeout<=86400:raise ValueError('wall_limit_required')
        e=self.engine;cid=None;p=None;observer=None;result=None;failure=None
        receipt={'id':None,'source':'native_podman','observer_armed_before_payload':False};self.last_receipt=receipt
        try:
            cid=e.create(workspace,workspacefd,inputs);receipt['id']=cid
            info=e.inspect(cid);receipt['inspect_before']=info
            validate_raw(info,image=self.image,uid=os.getuid(),gid=os.getgid(),workspace=workspace,inputs=inputs,entrypoint='/usr/local/bin/python3')
            p=e.attach(cid);selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ,'stdout');selector.register(p.stderr,selectors.EVENT_READ,'stderr')
            streams={'stdout':bytearray(),'stderr':bytearray()};deadline=time.monotonic()+20;payload_started=False;forced=None;token=uuid.uuid4().hex+uuid.uuid4().hex;after=None
            def send(value):p.stdin.write((json.dumps(value)+'\n').encode());p.stdin.flush()
            send({'token':token,'language':language,'code':code})
            try:
                while p.poll() is None or selector.get_map():
                    if payload_started and observer:
                        try:after=observer.sample()
                        except OSError:after=None
                    if payload_started and cancel_check and cancel_check():forced='cancelled'
                    if payload_started and quota_check:
                        try:quota_check()
                        except PermissionError:forced='quota_exceeded'
                    if time.monotonic()>=deadline:forced='timeout' if payload_started else 'trusted_startup_timeout'
                    if forced:
                        e.kill(cid);p.wait(timeout=10);break
                    for key,_ in selector.select(.02):
                        chunk=os.read(key.fileobj.fileno(),65536)
                        if not chunk:selector.unregister(key.fileobj);continue
                        buf=streams[key.data];buf.extend(chunk)
                        if len(buf)>1048576:raise RuntimeError('trusted_protocol_overflow')
                        if key.data!='stdout':continue
                        while b'\n' in buf:
                            line,_,rest=buf.partition(b'\n');buf[:]=rest
                            msg=json.loads(line)
                            if msg.get('token')!=token:raise PermissionError('trusted_protocol_token_mismatch')
                            if msg['phase']=='ready' and not payload_started:
                                proof=msg['proof'];receipt['runtime_proof']=proof
                                host_namespaces={n:os.readlink('/proc/self/ns/'+n) for n in ('net','mnt','pid','ipc','cgroup')}
                                validate_runtime(proof,os.getuid(),os.getgid(),host_namespaces)
                                receipt['host_namespaces']=host_namespaces
                                state=e.inspect(cid);observer=OwnedCgroup(state['State']['Pid'],cid);receipt['cgroup']={'pid':observer.pid,'start_identity':observer.start,'paths':observer.paths,'before':observer.before};receipt['observer_armed_before_payload']=True
                                send({'phase':'go','token':token});payload_started=True;deadline=time.monotonic()+timeout
                            elif msg['phase']=='done' and payload_started and result is None:
                                # Supervisor still alive and waiting for ACK: final read
                                # happens BEFORE cgroup deletion, even for instant OOM.
                                after=observer.sample();receipt['cgroup']['after']=after
                                result=msg['result'];error=outcome(result['exit'],observer.before['oom_kill'],after['oom_kill'])
                                if error:result['error']=error
                                send({'phase':'ack','token':token});deadline=time.monotonic()+10
                            else:raise RuntimeError('invalid_trusted_protocol_state')
                p.wait(timeout=10)
            finally:selector.close()
            receipt['attach_exit']=p.returncode;receipt['attach_stderr']=streams['stderr'].decode(errors='replace');receipt['inspect_after']=e.inspect(cid)
            if result is None:
                result={'exit':receipt['inspect_after']['State']['ExitCode'],'stdout':'','stderr':'','truncated':False,'error':forced or 'oom_observation_unknown'}
                if not forced and after is not None and observer:result['error']=outcome(result['exit'],observer.before['oom_kill'],after['oom_kill']) or 'trusted_supervisor_lost'
            elif p.returncode!=0:raise RuntimeError('trusted_supervisor_exit_failed')
            result['isolation']={'engine':'podman','raw_validated':True,'runtime_preexec_validated':receipt['observer_armed_before_payload'],'memory':536870912,'observer_armed':receipt['observer_armed_before_payload']}
            receipt['result']=result
        except BaseException as exc:
            failure=exc
            raise
        finally:
            errors=[]
            if observer:
                receipt['samples']=observer.samples
                try:observer.close()
                except BaseException as exc:errors.append(exc)
            try:
                if cid is not None:receipt['cleanup']={'status':'removed',**e.remove(cid)}
                elif e.last_creation:
                    receipt['creation']=e.last_creation
                    receipt['id']=e.last_creation.get('id')
                    receipt['cleanup']=e.last_creation['cleanup']
                    # A cancellation may cross the create-return/assignment
                    # handoff. The engine's validated CID still owns cleanup.
                    if receipt['id'] in e.ids and 'exception' not in e.last_creation:
                        receipt['cleanup']={'status':'removed',**e.remove(receipt['id'])}
                else:receipt['cleanup']={'status':'not_created'}
            except BaseException as exc:
                receipt['cleanup']={'status':'unknown','id':cid,'error':repr(exc)};errors.append(exc)
            if p:
                try:
                    if p.poll() is None:os.killpg(p.pid,signal.SIGKILL);p.wait(timeout=10)
                except BaseException as exc:errors.append(exc)
                for stream in (p.stdin,p.stdout,p.stderr):
                    try:stream.close()
                    except BaseException as exc:errors.append(exc)
            op=e.ids.get(cid) or (e.last_creation or {}).get('operation')
            if op:
                try:record(e.metadata/(op+'.receipt.json'),receipt)
                except BaseException as exc:receipt['journal_error']=repr(exc);errors.append(exc)
            if result is not None:result['container_removed']=receipt['cleanup']['status']=='removed'
            if failure:
                for exc in errors:failure.add_note('cleanup_or_receipt_error:'+repr(exc))
            elif errors:raise errors[0]
        return result
