"""
Not to be executed. Hints to pyinstaller that certain modules need to be included in the package.
"""

import engineio.async_drivers.threading
import psutil
import humanize
import numpy
from PIL import Image
from sklearn.cluster import KMeans
import colorsys
import platform
import pathlib
import tempfile
import shutil
import zipfile
import urllib.request
import subprocess