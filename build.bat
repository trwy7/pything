@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
"%SCRIPT_DIR%.venv\Scripts\uv.exe" run --python 3.12 pyinstaller --name pything-windows --onefile --add-data "%SCRIPT_DIR%src;src" --add-data "%SCRIPT_DIR%pyproject.toml;." --add-data "%SCRIPT_DIR%uv.lock;." --add-data "%SCRIPT_DIR%README.md;." --add-binary "%SCRIPT_DIR%.venv\Scripts\uv.exe;bin" --hidden-import uv --hidden-import engineio.async_drivers.threading "%SCRIPT_DIR%launch.py"

endlocal