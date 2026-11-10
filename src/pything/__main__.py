import os
import subprocess
import sys

RESTART_EXIT_CODE = 65
SERVER_MODE = "PYTHING_SERVER_MODE"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))


def main() -> int:
    command = [sys.executable, sys.argv[0], *sys.argv[1:]]
    working_directory = os.path.dirname(os.path.abspath(__file__))
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
        import sys

        from pything.loader import main as start
        from pything.state import DEPENDENCY_DIR

        sys.path.insert(0, str(DEPENDENCY_DIR))

        return start()
    return main()


if __name__ == "__main__":
    raise SystemExit(cli())
