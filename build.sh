#!/bin/bash
pyinstaller --onefile --name pything-linux \
	--add-data "src/apps:apps" \
	--add-data "src/pages:pages" \
	--add-data "src/ctroot:ctroot" \
	--add-data "src/customapps:customapps" \
	--add-data "src/static:static" src/init.py