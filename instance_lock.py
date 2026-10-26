"""Windows kernel handle lock, released automatically if the process dies."""

import ctypes
from ctypes import wintypes
import hashlib
import os


class AlreadyRunningError(Exception):
    pass


class InstanceLock:
    def __init__(self, database_path):
        identity = os.path.normcase(str(database_path.resolve()))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.name = "Local\\StudyTimer-" + digest
        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def __enter__(self):
        ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:  # ERROR_ALREADY_EXISTS
            self.kernel.CloseHandle(handle)
            raise AlreadyRunningError("Study Timer is already open for this database.")
        self.handle = handle
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
