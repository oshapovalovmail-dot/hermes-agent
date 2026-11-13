"""Image-owned PID1: no untrusted exec until the host arms kernel observation.

Payload stdout/stderr are private pipes, never the trusted protocol transport.
PID1 is non-dumpable before receiving the per-run token and holds its cgroup
until host ACK after the payload result and final kernel-counter read.
"""
import ctypes
import json
import os
from pathlib import Path
import re
import resource
import selectors
import subprocess
import sys
import time

def request(value):
    if (not isinstance(value,dict) or set(value)!={'token','language','code'} or
        not isinstance(value['token'],str) or not re.fullmatch('[0-9a-f]{64}',value['token']) or
        value['language'] not in ('python','javascript') or not isinstance(value['code'],str) or len(value['code'].encode())>65536):
        raise ValueError('typed_bounded_payload_required')
    return value

def kernel_proof():
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
    return {'uid':os.getuid(),'gid':os.getgid(),'status':{k:status[k].strip() for k in ['CapEff','CapBnd','CapPrm','CapAmb','CapInh','NoNewPrivs','Seccomp']},
        'limits':{k:list(resource.getrlimit(v)) for k,v in {'nofile':resource.RLIMIT_NOFILE,'fsize':resource.RLIMIT_FSIZE,'core':resource.RLIMIT_CORE,'cpu':resource.RLIMIT_CPU}.items()},
        'namespaces':{n:os.readlink('/proc/self/ns/'+n) for n in ['net','mnt','pid','ipc','cgroup']}}

def read_control():
    line=sys.stdin.buffer.readline(1048577)
    if len(line)>1048576 or not line.endswith(b'\n'):raise ValueError('bounded_control_line_required')
    return json.loads(line)

def main():
    # Deny same-UID payload access to PID1 memory and protocol descriptors.
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(4,0,0,0,0):raise OSError(ctypes.get_errno(),'PR_SET_DUMPABLE')
    value=request(read_control());token=value['token']
    def emit(msg):
        msg['token']=token;print(json.dumps(msg),flush=True)
    emit({'phase':'ready','proof':kernel_proof()})
    if read_control()!={'phase':'go','token':token}:raise ValueError('host_observer_barrier_required')
    argv=(['/opt/atlas/bin/python3','-I','-S','-c',value['code']] if value['language']=='python' else ['/usr/local/bin/node','--max-old-space-size=128','--eval',value['code']])
    def child_setup():
        # Make the payload the preferred OOM victim, not the tiny trusted holder.
        # No capability is added; raising one's own score is permitted non-root.
        # PID1 stays non-dumpable. Reset only the not-yet-exec child so its
        # /proc/self files are owned by its non-root UID, not namespace root.
        if libc.prctl(4,1,0,0,0):raise OSError(ctypes.get_errno(),'child_dumpable')
        Path('/proc/self/oom_score_adj').write_text('1000')
    child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':'/opt/atlas/bin:/usr/local/bin:/usr/bin:/bin','HOME':'/nonexistent','LANG':'C.UTF-8','TMPDIR':'/tmp'},close_fds=True,preexec_fn=child_setup)
    selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ,'stdout');selector.register(child.stderr,selectors.EVENT_READ,'stderr')
    outputs={'stdout':bytearray(),'stderr':bytearray()};truncated=False;finished=None
    try:
        while selector.get_map():
            if child.poll() is not None:
                if finished is None:finished=time.monotonic()
                if time.monotonic()-finished>.1:break
            for key,_ in selector.select(.02):
                data=os.read(key.fileobj.fileno(),65536)
                if not data:selector.unregister(key.fileobj);continue
                room=65536-len(outputs[key.data]);outputs[key.data].extend(data[:room]);truncated|=len(data)>room
        code=child.wait();code=128-code if code<0 else code
        emit({'phase':'done','result':{'exit':code,'stdout':outputs['stdout'].decode('utf-8','replace'),'stderr':outputs['stderr'].decode('utf-8','replace'),'truncated':truncated}})
        # No post-exit path race: the host reads oom_kill while PID1 is alive.
        if read_control()!={'phase':'ack','token':token}:raise ValueError('final_observation_ack_required')
    finally:
        selector.close();child.stdout.close();child.stderr.close()
if __name__=='__main__':main()
