import os
import sys
from pathlib import Path
from subprocess import run

import uv

from src.pything.utils import CACHE_ROOT, dependency_target

REQUIRED_PACKAGES = [
    "flask==3.1.2",
    "flask-socketio==5.5.1",
    "pip-system-certs==5.3",
    "packaging>=24.0",
]


def frozen_python() -> Path:
    required_version = "3.12" if sys.platform == "win32" else "3.14"
    uv_binary = uv.find_uv_bin()
    global_python = run(
        [
            uv_binary,
            "python",
            "find",
            "--system",
            "--no-project",
            "--no-python-downloads",
            required_version,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if global_python.returncode == 0:
        return Path(global_python.stdout.strip())

    venv_dir = Path(CACHE_ROOT) / "pything" / "venv"
    run(
        [
            uv_binary,
            "venv",
            "--python",
            required_version,
            "--allow-existing",
            str(venv_dir),
        ],
        check=True,
    )
    return venv_dir / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )


def launch_pything() -> None:
    if getattr(sys, "frozen", False) and os.environ.get("PYTHING_SERVER_MODE") == "1":
        sys.path.insert(0, str(dependency_target()))
        from src.pything import main

        main()
        return

    # install dependencies to the dependency target directory
    dependency_dir = dependency_target()
    dependency_dir.mkdir(parents=True, exist_ok=True)
    python_target = frozen_python() if getattr(sys, "frozen", False) else None
    python_option = ["--python", str(python_target)] if python_target else []
    run(
        [
            uv.find_uv_bin(),
            "pip",
            "install",
            *python_option,
            "--target",
            str(dependency_dir),
        ]
        + REQUIRED_PACKAGES,
        cwd=Path(__file__).resolve().parent,
        check=True,
    )
    environment = {**os.environ}
    if getattr(sys, "frozen", False):
        command = [sys.executable]
        environment["PYTHING_SERVER_MODE"] = "1"
        environment["PYTHING_PYTHON"] = str(python_target)
    else:
        command = [sys.executable, "-m", "pything"]
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent / "src")
    run(command, check=True, cwd=Path(__file__).resolve().parent, env=environment)


if __name__ == "__main__":
    launch_pything()
