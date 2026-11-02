from subprocess import run
from pathlib import Path
import uv



def _uv_command() -> list[str]:
    return [uv.find_uv_bin()]

def launch_pything() -> None:
    uv_cmd = _uv_command()
    run(
        uv_cmd + ["run", "pything"],
        check=True,
        cwd=Path(__file__).resolve().parent,
    )

if __name__ == "__main__":
    launch_pything()