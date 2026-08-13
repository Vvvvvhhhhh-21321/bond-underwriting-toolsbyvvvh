from __future__ import annotations

import os
from pathlib import Path

os.environ["PYTHONNOUSERSITE"] = "1"

import PyInstaller.__main__


workspace = Path(__file__).resolve().parents[1]
PyInstaller.__main__.run(
    [
        "--noconfirm",
        "--clean",
        "--windowed",
        "--exclude-module=numpy",
        "--exclude-module=PIL",
        "--exclude-module=matplotlib",
        "--exclude-module=pandas",
        "--exclude-module=scipy",
        "--name=披露PDF缩放工具",
        f"--icon={workspace / 'src/disclosure_pdf_scaler/assets/app.ico'}",
        f"--add-data={workspace / 'src/disclosure_pdf_scaler/assets'};disclosure_pdf_scaler/assets",
        f"--version-file={workspace / 'installer/version_info.txt'}",
        str(workspace / "src/disclosure_pdf_scaler/__main__.py"),
    ]
)
