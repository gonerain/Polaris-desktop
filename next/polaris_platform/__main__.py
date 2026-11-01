import argparse
import json
import os
import sys
from pathlib import Path
from .bootstrap import from_file, build, default_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", help="JSON assembly configuration; defaults to the three headless foundation components")
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--state-dir", help="Optional local installation and authorization record directory")
    args = parser.parse_args()
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
