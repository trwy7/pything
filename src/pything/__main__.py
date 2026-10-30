import os
import subprocess
import sys

RESTART_EXIT_CODE = 65
SERVER_MODE = "PYTHING_SERVER_MODE"

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def server_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, sys.argv[0], *sys.argv[1:]]


def main() -> int:
    command = server_command()
    working_directory = (
        os.path.dirname(sys.executable)
        if getattr(sys, "frozen", False)
        else os.path.dirname(os.path.abspath(__file__))
    )
    environment = os.environ.copy()
    environment[SERVER_MODE] = "1"
    while True:
        result = subprocess.run(
            command,
            cwd=working_directory,
            env=environment,
            check=False,
        )
        if result.returncode != RESTART_EXIT_CODE:
            return result.returncode


def cli() -> int | None:
    if os.environ.get(SERVER_MODE) == "1":
        from . import main as start

        return start()
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
