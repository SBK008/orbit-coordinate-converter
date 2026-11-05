# PyInstaller recipe for the standalone desktop app.
#
# Build (from the repo folder, after pip install . -r packaging/requirements.txt):
#     pyinstaller --noconfirm packaging/coordinate_converter.spec
#
# On macOS this makes "dist/Coordinate Converter.app". Python, the code, and
# every library are sealed inside, so users need nothing else installed.
# The app is ad-hoc signed (free); see packaging/README.md.

import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
APP_NAME = "Coordinate Converter"
BUNDLE_ID = "io.github.sbk008.orbit-converter"

with open(os.path.join(ROOT, "xyz_to_lla.py"), encoding="utf-8") as f:
    VERSION = re.search(r'^__version__ = "([^"]+)"', f.read(), re.M).group(1)

# Data the converter reads at run time:
#   pyproj: the PROJ database (pyproj's own hook collects it)
#   astropy: its config and data files, and the IERS Earth orientation tables
#            that space-fixed frames (EME2000, GCRF, ...) need
datas = []
datas += collect_data_files("astropy")
datas += collect_data_files("astropy_iers_data")
datas += copy_metadata("astropy")

# astropy loads its coordinate frames by name, so list them for PyInstaller
hiddenimports = collect_submodules("astropy.coordinates") + ["erfa"]

a = Analysis(
    [os.path.join(ROOT, "converter_gui.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    # Big optional extras the app never uses
    excludes=["matplotlib", "IPython", "jupyter", "pytest", "scipy", "PyQt5", "PyQt6",
              "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,             # no Terminal window
    argv_emulation=False,
    codesign_identity=None,    # None = free ad-hoc signature on macOS
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        bundle_identifier=BUNDLE_ID,
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHumanReadableCopyright": "MIT License",
        },
    )
