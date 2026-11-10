import importlib.metadata
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from packaging.requirements import Requirement

from .state import DEPENDENCY_DIR

logger = logging.getLogger(__name__)
UV_BINARY = os.environ.get("PYTHING_UV") or shutil.which("uv")


def is_requirement_installed(req_str: str) -> bool:
    """Check whether a requirement specification is satisfied at runtime."""
    try:
        req = Requirement(req_str)
        if req.marker is not None and not req.marker.evaluate():
            return True
        installed_version = importlib.metadata.version(req.name)
        return req.specifier.contains(installed_version)
    except (importlib.metadata.PackageNotFoundError, ValueError):
        return False


def install_requirements(requirements: Iterable[str]) -> None:
    """Install missing app requirements into a runtime-local import directory."""
    # logger.debug("Loading app dependencies from %s", target)
    # if str(target) not in sys.path:
    #    sys.path.insert(0, str(target))

    missing: list[str] = []
    for requirement in dict.fromkeys(requirements):
        # Validate even if installation is unnecessary, so malformed manifests fail clearly.
        req = Requirement(requirement)
        if req.marker is not None and not req.marker.evaluate():
            continue
        if not is_requirement_installed(requirement):
            missing.append(requirement)

    if not missing:
        return

    DEPENDENCY_DIR.mkdir(parents=True, exist_ok=True)
    python_target = os.environ.get("PYTHING_PYTHON")
    python_option = (
        ["--python", python_target]
        if python_target
        else [
            "--python-version",
            f"{sys.version_info.major}.{sys.version_info.minor}",
        ]
    )
    command = [
        UV_BINARY or "uv",
        "pip",
        "install",
        "--target",
        str(DEPENDENCY_DIR),
        *python_option,
        *missing,
    ]
    logger.info("Installing app dependencies: %s", ", ".join(missing))
    try:
        subprocess.run(command, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            f"Failed to install app dependencies with uv: {exc}"
        ) from exc


def install_app_requirements(app_directories: Iterable[str]) -> None:
    """Read platform-specific requirements from installed app manifests and install."""
    platform_key = {
        "win32": "requirements-windows",
        "linux": "requirements-linux",
        "darwin": "requirements-darwin",
    }.get(sys.platform)
    requirements: list[str] = []
    for directory in app_directories:
        manifest_path = Path(directory) / "manifest.json"
        with manifest_path.open(encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        if not isinstance(manifest, dict):
            raise TypeError(f"App manifest '{manifest_path}' must be an object")
        for key in ("requirements", platform_key):
            if key is None:
                continue
            values = manifest.get(key, [])
            if not isinstance(values, list) or not all(
                isinstance(value, str) for value in values
            ):
                raise RuntimeError(
                    f"App manifest '{manifest_path}' has invalid {key} requirements"
                )
            requirements.extend(values)
    install_requirements(requirements)
