"""Windows-only bounded process tree; no scientific modules or execution authority.

A suspended Python child joins a kill-on-close Job before any child code runs.
All descendants inherit that Job. This also covers descendants surviving their
parent, unlike taskkill /T invoked after the root process has already exited.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong), ('LimitFlags', wintypes.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wintypes.DWORD), ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]


class _IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IO),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_longlong) for name in
                ('TotalUserTime', 'TotalKernelTime', 'ThisPeriodTotalUserTime', 'ThisPeriodTotalKernelTime')]
    _fields_ += [(name, wintypes.DWORD) for name in
                 ('TotalPageFaultCount', 'TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG), ('dwFlags', wintypes.DWORD)]


def _kernel():
    if os.name != 'nt':
        raise RuntimeError('UNQUALIFIED_PLATFORM')
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateJobObjectW': ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        'SetInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        'QueryInformationJobObject': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        'AssignProcessToJobObject': ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        'TerminateJobObject': ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        'CreateToolhelp32Snapshot': ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        'Thread32First': ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        'Thread32Next': ([wintypes.HANDLE, ctypes.POINTER(_ThreadEntry)], wintypes.BOOL),
        'OpenThread': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'ResumeThread': ([wintypes.HANDLE], wintypes.DWORD),
        'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
    }
    for name, (args, result) in signatures.items():
        getattr(k, name).argtypes, getattr(k, name).restype = args, result
    return k


def _check(ok):
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


class _Job:
    def __init__(self):
        self.k = _kernel()
        self.handle = self.k.CreateJobObjectW(None, None)
        _check(self.handle)
        try:
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            _check(self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.close()
            raise

    def assign(self, process):
        _check(self.k.AssignProcessToJobObject(self.handle, int(process._handle)))

    def active(self):
        info = _Accounting()
        _check(self.k.QueryInformationJobObject(self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None))
        return info.ActiveProcesses

    def terminate(self):
        _check(self.k.TerminateJobObject(self.handle, 1))

    def process_handles(self):
        # Bound the experiment tree inventory; unexpected expansion fails closed.
        class ProcessList(ctypes.Structure):
            _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD),
                        ('pids', ctypes.c_size_t * 256)]
        info = ProcessList()
        _check(self.k.QueryInformationJobObject(self.handle, 3, ctypes.byref(info), ctypes.sizeof(info), None))
        handles = []
        try:
            for pid in info.pids[:info.count]:
                handle = self.k.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE
                if handle:
                    handles.append(handle)
                elif ctypes.get_last_error() != 87:  # already deleted process
                    raise ctypes.WinError(ctypes.get_last_error())
            return handles
        except BaseException:
            for handle in handles:
                self.k.CloseHandle(handle)
            raise

    def wait_handles(self, handles, deadline):
        try:
            for handle in handles:
                remaining_ms = max(0, int((deadline - time.perf_counter()) * 1000))
                if self.k.WaitForSingleObject(handle, remaining_ms) != 0:
                    raise RuntimeError('PROCESS_NOT_SIGNALED_AT_DEADLINE')
        finally:
            for handle in handles:
                _check(self.k.CloseHandle(handle))

    def close(self):
        if self.handle:
            _check(self.k.CloseHandle(self.handle))
            self.handle = None


def _resume(process):
    """Resume the single initial thread using documented Win32 APIs."""
    k = _kernel()
    snapshot = k.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    thread = None
    try:
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        found = k.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == process.pid:
                thread = k.OpenThread(2, False, entry.th32ThreadID)  # THREAD_SUSPEND_RESUME
                _check(thread)
                if k.ResumeThread(thread) != 1:
                    raise RuntimeError('UNEXPECTED_INITIAL_SUSPEND_COUNT')
                return
            found = k.Thread32Next(snapshot, ctypes.byref(entry))
        raise RuntimeError('SUSPENDED_INITIAL_THREAD_NOT_FOUND')
    finally:
        if thread:
            _check(k.CloseHandle(thread))
        _check(k.CloseHandle(snapshot))


def supervise(command, directory, deadline, cwd):
    """Run one Python worker with an absolute perf_counter deadline, no retry.

    Two seconds are reserved for tree termination and reaping. The caller must
    establish this same deadline before manifest creation and pass it to worker
    validation/execution. Failure to prove cleanup or meet time is never PASS.
    """
    started = time.perf_counter()
    directory = Path(directory)
    receipt = {'started': started, 'deadline': deadline, 'timed_out': False,
               'cleanup_errors': [], 'returncode': None, 'tree_empty': False,
               'job_assigned_before_resume': False}
    child, job = None, None
    # Reserve both evidence names before launch; previous attempts are immutable.
    with (directory / 'process_receipt.json').open('x', encoding='utf-8') as receipt_file:
        try:
            with (directory / 'worker.log').open('x', encoding='utf-8') as log:
                if time.perf_counter() >= deadline - 2:
                    raise TimeoutError('NO_STARTUP_BUDGET')
                if os.name != 'nt' or not command or command[0] != sys.executable:
                    raise RuntimeError('UNQUALIFIED_LAUNCH_INTERPRETER')
                job = _Job()
                env = dict(os.environ)
                env['__PYVENV_LAUNCHER__'] = sys.executable
                actual = [sys._base_executable, *command[1:]]
                child = subprocess.Popen(actual, cwd=cwd, env=env, stdout=log,
                                         stderr=subprocess.STDOUT, creationflags=4)  # CREATE_SUSPENDED
                receipt['pid'] = child.pid
                job.assign(child)
                receipt['job_assigned_before_resume'] = True
                if time.perf_counter() >= deadline - 2:
                    raise TimeoutError('STARTUP_DEADLINE')
                _resume(child)
                try:
                    receipt['returncode'] = child.wait(timeout=max(.001, deadline - 2 - time.perf_counter()))
                except subprocess.TimeoutExpired:
                    receipt['timed_out'] = True
        except BaseException as exc:
            receipt['exception'] = {'type': type(exc).__name__, 'message': str(exc)}
        finally:
            # Always terminate the Job, including when the root already exited.
            if job is not None:
                handles = []
                try:
                    handles = job.process_handles()
                    receipt['cleanup_process_handles'] = len(handles)
                    job.terminate()
                    waiting_handles = handles
                    handles = []
                    job.wait_handles(waiting_handles, deadline)
                    while job.active() and time.perf_counter() < deadline:
                        time.sleep(min(.01, max(0, deadline - time.perf_counter())))
                    receipt['tree_empty'] = job.active() == 0
                    if not receipt['tree_empty']:
                        raise RuntimeError('JOB_NOT_EMPTY_AT_DEADLINE')
                except BaseException as exc:
                    receipt['cleanup_errors'].append(str(exc))
                finally:
                    try:
                        job.close()  # kill-on-close remains a fallback on cleanup error
                    except BaseException as exc:
                        receipt['cleanup_errors'].append(str(exc))
                    if handles:
                        try:
                            job.wait_handles(handles, deadline)
                        except BaseException as exc:
                            receipt['cleanup_errors'].append(str(exc))
            if child is not None:
                try:
                    if child.poll() is None and not receipt['job_assigned_before_resume']:
                        child.kill()  # suspended child never acquired permission to run
                    child.wait(timeout=max(.001, deadline - time.perf_counter()))
                except BaseException as exc:
                    receipt['cleanup_errors'].append(str(exc))
            receipt['reaped'] = child is not None and child.poll() is not None
            if child is not None:
                receipt['final_returncode'] = child.returncode
            receipt['elapsed_s'] = time.perf_counter() - started
            receipt['within_deadline'] = time.perf_counter() <= deadline
            receipt['passed'] = (receipt['returncode'] == 0 and receipt['reaped'] and
                                 receipt['tree_empty'] and not receipt['timed_out'] and
                                 not receipt['cleanup_errors'] and 'exception' not in receipt and
                                 receipt['within_deadline'])
            json.dump(receipt, receipt_file, indent=2)
            receipt_file.write('\n')
    return receipt
