"""Read-only Windows process parent/image witness for the frozen venv redirector."""
import ctypes
from ctypes import wintypes as W
from pathlib import Path
import sys

def view(pid):
    if sys.platform!='win32':
        raise ValueError('Windows process witness unavailable')
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',W.DWORD),('cntUsage',W.DWORD),('th32ProcessID',W.DWORD),
                  ('heap',ctypes.c_size_t),('module',W.DWORD),('threads',W.DWORD),
                  ('parent',W.DWORD),('priority',W.LONG),('flags',W.DWORD),('image',W.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]
    kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
    kernel.Process32FirstW.argtypes=kernel.Process32NextW.argtypes=[W.HANDLE,ctypes.POINTER(Entry)]
    kernel.Process32FirstW.restype=kernel.Process32NextW.restype=W.BOOL
    kernel.CloseHandle.argtypes=[W.HANDLE]
    kernel.CloseHandle.restype=W.BOOL
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    parent=None
    try:
        entry=Entry()
        entry.dwSize=ctypes.sizeof(entry)
        more=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            if entry.th32ProcessID==pid:
                parent=int(entry.parent)
                break
            more=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    if parent is None:
        raise ValueError('Process absent from live snapshot')
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]
    kernel.OpenProcess.restype=W.HANDLE
    process=kernel.OpenProcess(0x1000,False,pid)
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,ctypes.POINTER(W.DWORD)]
        kernel.QueryFullProcessImageNameW.restype=W.BOOL
        buffer=ctypes.create_unicode_buffer(32768)
        size=W.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'pid':pid,'parent_pid':parent,'image':str(Path(buffer.value).resolve())}
    finally:
        kernel.CloseHandle(process)
