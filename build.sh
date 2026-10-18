#!/bin/bash
python -m PyInstaller --onefile --name pything-linux --paths src \
	--add-data "src/apps:apps" \
	--add-data "src/pages:pages" \
	--add-data "src/static:static" launcher.py