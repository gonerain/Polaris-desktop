import argparse
import json
import os
import sys
from pathlib import Path
from .metadata import APP_NAME, DISPLAY_VERSION


def main(argv=None, *, default_gui=False):
    argv = list(sys.argv[1:] if argv is None else argv)
    # A frozen executable is not a Python interpreter. Only this explicit worker
    # entry executes process-component Python code, before any GUI setup.
    if argv[:1] == ['--component-python']:
        from .worker import run_python
        return run_python(argv[1:])
    if argv or not default_gui:
        from .worker import restore_stdio
        restore_stdio(attach_console=True)
    parser = argparse.ArgumentParser(prog=APP_NAME if default_gui else 'polaris-platform')
    parser.add_argument('--version', action='version', version=f'{APP_NAME} {DISPLAY_VERSION}')
    parser.add_argument('--updates', action='store_true', help='Open the GitHub Release update window')
    parser.add_argument("--config", help="JSON assembly configuration; defaults to the three headless foundation components")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--gui', dest='gui', action='store_true', help='Open the Polaris desktop')
    mode.add_argument('--headless', dest='gui', action='store_false', help='Print the component snapshot and exit')
    parser.set_defaults(gui=default_gui)
    parser.add_argument('--bridge-stdio', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument("--state-dir", help="Optional local installation and authorization record directory")
    if '--bridge-stdio' in argv:
        parser.error('The legacy --bridge-stdio protocol is unavailable. Install the Polaris Agent plugin from its independent repository instead.')
    args = parser.parse_args(argv)
    if args.updates:
        from PySide6.QtGui import QGuiApplication
        from .desktop.updates import UpdateController
        app = QGuiApplication.instance() or QGuiApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setQuitOnLastWindowClosed(True)
        updates = UpdateController(app)
        updates.show()
        updates.check()
        return app.exec()
    from .bootstrap import from_file, build, default_config
    state_dir = args.state_dir
    if args.gui and state_dir is None:
        root = os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else os.environ.get("XDG_DATA_HOME")
        state_dir = Path(root) / "polaris-platform" if root else Path.home() / ".local" / "share" / "polaris-platform"
    runtime = from_file(args.config, state_dir=state_dir) if args.config else build(default_config(), state_dir=state_dir)
    result = 0
    cleanup_errors = []
    try:
        if args.gui:
            from .desktop import run
            result = run(runtime)
        else:
            print(json.dumps(runtime.snapshot(), ensure_ascii=False, indent=2))
    finally:
        for record in reversed(runtime.snapshot()):
            if record["state"] in ("running", "starting", "stopping", "failed"):
                try:
                    runtime.stop_component(record["id"], persist=False)
                except Exception as error:
                    cleanup_errors.append(f"{record['id']}: {error}")
        for error in cleanup_errors:
            print("Cleanup failed: " + error, file=sys.stderr)

    return 1 if cleanup_errors else result


if __name__ == "__main__":
    raise SystemExit(main())
