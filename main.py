"""Polaris desktop launcher. The independent component platform is the application."""
from pathlib import Path
import sys

# Source checkout and PyInstaller use the same platform and bundled plugin layout.
_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
_PLATFORM_ROOT = _ROOT / 'next'
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))


def main(argv=None):
    from polaris_platform.__main__ import main as platform_main
    return platform_main(argv, default_gui=True)


if __name__ == '__main__':
    raise SystemExit(main())
