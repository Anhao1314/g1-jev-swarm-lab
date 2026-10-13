"""Read-only native observer and budget accounting, no simulation imports."""
import hashlib
import math
import time
from entry import canonical

class NativeLedger:
    def __init__(self,path,deadline):
        self.stream=path.open('x',encoding='utf-8',buffering=1)
        self.deadline=deadline; self.attempts=0; self.completed=0
        self.hash=hashlib.sha256(); self.failed=False
    def check(self):
        if time.perf_counter()>=self.deadline: raise TimeoutError('NATIVE_WALL_BUDGET')
        if self.attempts>=32000: raise RuntimeError('NATIVE_ATTEMPT_BUDGET')
        if self.failed: raise RuntimeError('PRIOR_PHYSICAL_OR_TECHNICAL_FAILURE')
    def record(self,row):
        blob=canonical(row)
        self.stream.write(blob.decode()+'\n'); self.hash.update(blob)
    def before(self,snapshot):
        self.check(); self.attempts+=1
        self.record({'phase':'before','step':self.attempts,**snapshot})
    def after(self,snapshot):
        self.completed+=1
        self.record({'phase':'after','step':self.completed,**snapshot})
    def close(self): self.stream.close()

def physical_flags(qpos,qvel,ctrl):
    finite=all(math.isfinite(x) for x in [*qpos,*qvel,*ctrl])
    if not finite: return {'nonfinite':True,'fallen':False}
    w,x,y,z=qpos[3:7]; norm=w*w+x*x+y*y+z*z
    tilt=math.degrees(math.acos(max(-1.,min(1.,1-2*(x*x+y*y)/norm)))) if norm else float('inf')
    return {'nonfinite':False,'fallen':qpos[2]<.45 or tilt>65.}
