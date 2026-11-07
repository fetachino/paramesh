"""Start the local ParamMesh operations stack from a packaged Windows bundle."""

import subprocess
import sys
from pathlib import Path

from scripts.quickstart import main as quickstart


def main() -> None:
    root = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    quickstart_script = root / "scripts" / "quickstart.py"
    if not getattr(sys, "frozen", False) and not quickstart_script.is_file():
        raise SystemExit("This launcher must stay beside the ParamMesh bundle files.")
    if getattr(sys, "frozen", False):
        quickstart()
    else:
        subprocess.run([sys.executable, str(quickstart_script)], cwd=root, check=True)


if __name__ == "__main__":
    main()
