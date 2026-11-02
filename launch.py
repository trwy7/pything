from subprocess import run
from pathlib import Path
import uv


def launch_pything() -> None:
    run(
        [uv.find_uv_bin(), "run", "pything"],
        check=True,
        cwd=Path(__file__).resolve().parent,
    )


if __name__ == "__main__":
    launch_pything()
