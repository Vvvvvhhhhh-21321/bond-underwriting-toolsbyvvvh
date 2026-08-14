# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path


project = Path(SPEC).resolve().parent
conda_bin = Path(sys.prefix) / "Library" / "bin"
os.environ["PATH"] = str(conda_bin) + os.pathsep + os.environ.get("PATH", "")
lgpl = Path(
    "D:/anaconda/Lib/site-packages/gmpy2-2.2.1.dist-info/COPYING.LESSER"
)

a = Analysis(
    [str(project / "batch_word_replace.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "packaging" / "THIRD-PARTY-NOTICES.txt"), "licenses"),
        (str(lgpl), "licenses"),
    ],
    hiddenimports=[
        "psutil",
        "pythoncom",
        "pywintypes",
        "win32com",
        "win32com.client",
        "win32con",
        "win32file",
        "win32process",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Word批量处理",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(project / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Word批量处理",
)
