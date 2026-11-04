import os
import sys
import sysconfig
from pathlib import Path

if sys.platform == "win32":
    CACHE_ROOT = os.environ.get("LOCALAPPDATA")
elif sys.platform == "darwin":
    CACHE_ROOT = os.path.join(os.path.expanduser("~"), "Library", "Caches")
else:
    CACHE_ROOT = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )


def dependency_target() -> Path:
    runtime = sys.implementation.cache_tag or (
        f"python-{sys.version_info.major}.{sys.version_info.minor}"
    )
    return (
        Path(CACHE_ROOT)
        / "pything"
        / "dependencies"
        / f"{runtime}-{sysconfig.get_platform()}"
    )
