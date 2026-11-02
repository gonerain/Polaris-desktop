"""Explicit Python process-component entry for a frozen Polaris executable."""
import os
from pathlib import Path
import runpy
import sys


def restore_stdio(*, attach_console=False):
    """Recover inherited Windows pipe handles in a windowed frozen executable."""
    if os.name != 'nt' or all(stream is not None for stream in (sys.stdin, sys.stdout, sys.stderr)):
        return
    import ctypes
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    invalid = ctypes.c_void_p(-1).value
    if attach_console and kernel.GetStdHandle(-11 & 0xffffffff) in (None, invalid):
        kernel.AttachConsole(ctypes.c_ulong(-1 & 0xffffffff))
    for name, handle_id, mode, flags in (
        ('stdin', -10, 'r', os.O_RDONLY),
        ('stdout', -11, 'w', os.O_WRONLY),
        ('stderr', -12, 'w', os.O_WRONLY),
    ):
        if getattr(sys, name) is not None:
            continue
        handle = kernel.GetStdHandle(handle_id & 0xffffffff)
        if handle not in (None, invalid):
            try:
                fd = msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
                stream = os.fdopen(fd, mode, encoding='utf-8', buffering=1)
                setattr(sys, name, stream)
                continue
            except OSError:
                pass
        setattr(sys, name, open(os.devnull, mode, encoding='utf-8'))


def run_python(argv):
    """Run a script or module under the bundled interpreter, without a desktop."""
    restore_stdio()
    if not argv:
        print('Polaris component worker requires a script or -m module', file=sys.stderr)
        return 2
    try:
        if argv[0] == '-m' and len(argv) >= 2:
            sys.argv = argv[1:]
            # Process-component cwd is its own plugin directory, like python -m.
            sys.path.insert(0, str(Path.cwd()))
            runpy.run_module(argv[1], run_name='__main__', alter_sys=True)
        elif argv[0] == '-c' and len(argv) >= 2:
            sys.argv = ['-c', *argv[2:]]
            sys.path.insert(0, str(Path.cwd()))
            exec(compile(argv[1], '<string>', 'exec'), {'__name__': '__main__'})
        elif not argv[0].startswith('-'):
            script = Path(argv[0]).resolve()
            sys.argv = [str(script), *argv[1:]]
            sys.path.insert(0, str(script.parent))
            runpy.run_path(str(script), run_name='__main__')
        else:
            print('Polaris component worker supports a script, -m module or -c code', file=sys.stderr)
            return 2
    except SystemExit as error:
        if error.code is not None and not isinstance(error.code, int):
            print(error.code, file=sys.stderr)
        return error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    return 0
