"""Native OS credential storage. No plaintext token files or fallback backend."""
import ctypes as C
import os


class CredentialStore:
    def __init__(self, account):
        self.account = account

    def _linux(self, action, value=None):
        secret = C.CDLL('libsecret-1.so.0')
        glib = C.CDLL('libglib-2.0.so.0')
        # SecretSchema's public ABI (libsecret/secret-schema.h).
        class Attribute(C.Structure):
            _fields_ = [('name', C.c_char_p), ('type', C.c_int)]
        class Schema(C.Structure):
            _fields_ = [('name', C.c_char_p), ('flags', C.c_int),
                        ('attributes', Attribute * 32), ('reserved', C.c_int),
                        *[('reserved' + str(i), C.c_void_p) for i in range(1, 8)]]
        class Error(C.Structure):
            _fields_ = [('domain', C.c_uint), ('code', C.c_int), ('message', C.c_char_p)]
        schema = Schema(name=b'org.polaris.schedule.Google', flags=0)
        schema.attributes[0] = Attribute(b'account', 0)
        glib.g_hash_table_new.restype = C.c_void_p
        glib.g_hash_table_new.argtypes = [C.c_void_p, C.c_void_p]
        glib.g_hash_table_insert.argtypes = [C.c_void_p, C.c_char_p, C.c_char_p]
        glib.g_hash_table_unref.argtypes = [C.c_void_p]
        glib.g_error_free.argtypes = [C.c_void_p]
        table = glib.g_hash_table_new(C.cast(glib.g_str_hash, C.c_void_p), C.cast(glib.g_str_equal, C.c_void_p))
        account = self.account.encode()
        glib.g_hash_table_insert(table, b'account', account)
        error = C.POINTER(Error)()
        common = [C.POINTER(Schema), C.c_void_p]
        tail = [C.c_void_p, C.POINTER(C.POINTER(Error))]
        try:
            if action == 'set':
                fn = secret.secret_password_storev_sync
                fn.argtypes = common + [C.c_char_p, C.c_char_p, C.c_char_p] + tail
                fn.restype = C.c_int
                result = fn(C.byref(schema), table, b'default', b'Polaris Google Calendar', value.encode(), None, C.byref(error))
            elif action == 'get':
                fn = secret.secret_password_lookupv_sync
                fn.argtypes = common + tail
                fn.restype = C.c_void_p
                result = fn(C.byref(schema), table, None, C.byref(error))
            else:
                fn = secret.secret_password_clearv_sync
                fn.argtypes = common + tail
                fn.restype = C.c_int
                result = fn(C.byref(schema), table, None, C.byref(error))
            if error:
                message = error.contents.message.decode()
                glib.g_error_free(error)
                raise RuntimeError('系统凭据库：' + message)
            if action == 'get' and result:
                try:
                    return C.string_at(result).decode()
                finally:
                    secret.secret_password_free.argtypes = [C.c_void_p]
                    secret.secret_password_free(result)
            return None
        finally:
            glib.g_hash_table_unref(table)

    def _windows(self, action, value=None):
        from ctypes import wintypes as W
        class Credential(C.Structure):
            _fields_ = [('Flags', W.DWORD), ('Type', W.DWORD), ('TargetName', W.LPWSTR),
                        ('Comment', W.LPWSTR), ('LastWritten', W.FILETIME),
                        ('CredentialBlobSize', W.DWORD), ('CredentialBlob', C.c_void_p),
                        ('Persist', W.DWORD), ('AttributeCount', W.DWORD),
                        ('Attributes', C.c_void_p), ('TargetAlias', W.LPWSTR), ('UserName', W.LPWSTR)]
        api = C.WinDLL('Advapi32', use_last_error=True)
        target = 'Polaris.Schedule.Google:' + self.account
        if action == 'set':
            blob = C.create_string_buffer(value.encode())
            entry = Credential(Type=1, TargetName=target, CredentialBlobSize=len(value.encode()),
                               CredentialBlob=C.cast(blob, C.c_void_p), Persist=2, UserName='Google Calendar')
            api.CredWriteW.argtypes = [C.POINTER(Credential), W.DWORD]
            ok = api.CredWriteW(C.byref(entry), 0)
        elif action == 'get':
            entry = C.POINTER(Credential)()
            api.CredReadW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.POINTER(C.POINTER(Credential))]
            ok = api.CredReadW(target, 1, 0, C.byref(entry))
            if ok:
                try:
                    return C.string_at(entry.contents.CredentialBlob, entry.contents.CredentialBlobSize).decode()
                finally:
                    api.CredFree.argtypes = [C.c_void_p]
                    api.CredFree(entry)
        else:
            api.CredDeleteW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD]
            ok = api.CredDeleteW(target, 1, 0)
        if not ok and C.get_last_error() != 1168:
            raise C.WinError(C.get_last_error())
        return None

    def get(self):
        return (self._windows if os.name == 'nt' else self._linux)('get')

    def set(self, value):
        (self._windows if os.name == 'nt' else self._linux)('set', value)

    def delete(self):
        (self._windows if os.name == 'nt' else self._linux)('delete')
