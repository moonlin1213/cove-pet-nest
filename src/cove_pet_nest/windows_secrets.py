"""Seal a provider credential and its destination to the current Windows user."""
import base64
import ctypes
from ctypes import wintypes
import os


class DataBlob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.c_void_p)]


def _dpapi(payload, *, decrypt):
    if os.name != 'nt':
        raise OSError('Windows account required')
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    # No description, entropy, reserved data or UI prompt structure.
    operation.argtypes = [ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    operation.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    contents = ctypes.create_string_buffer(payload)
    source = DataBlob(len(payload), ctypes.cast(contents, ctypes.c_void_p))
    output = DataBlob()
    try:
        # CRYPTPROTECT_UI_FORBIDDEN; use current-user protection scope.
        if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(contents, 0, len(contents))
        if output.data:
            ctypes.memset(output.data, 0, output.size)
            kernel.LocalFree(output.data)


def protect_key(value):
    return base64.b64encode(_dpapi(value.encode('utf-8'), decrypt=False)).decode('ascii')


def unprotect_key(value):
    return _dpapi(base64.b64decode(value, validate=True), decrypt=True).decode('utf-8')
