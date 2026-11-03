import os
import sys
from pathlib import Path
from subprocess import run

import uv

from src.pything.utils import dependency_target

REQUIRED_PACKAGES = [
    "flask==3.1.2",
    "flask-socketio==5.5.1",
    "pip-system-certs==5.3",
    "packaging>=24.0",
]


def launch_pything() -> None:
    if getattr(sys, "frozen", False) and os.environ.get("PYTHING_SERVER_MODE") == "1":
        sys.path.insert(0, str(dependency_target()))
        from src.pything import main

        main()
        return

    # install dependencies to the dependency target directory
    dependency_dir = dependency_target()
    dependency_dir.mkdir(parents=True, exist_ok=True)
    run(
        [uv.find_uv_bin(), "pip", "install", "--target", str(dependency_dir)]
        + REQUIRED_PACKAGES,
        cwd=Path(__file__).resolve().parent,
        check=True,
    )
    environment = {**os.environ}
    if getattr(sys, "frozen", False):
        command = [sys.executable]
        environment["PYTHING_SERVER_MODE"] = "1"
    else:
        command = [sys.executable, "-m", "pything"]
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent / "src")
    run(command, check=True, cwd=Path(__file__).resolve().parent, env=environment)


if __name__ == "__main__":
    launch_pything()
