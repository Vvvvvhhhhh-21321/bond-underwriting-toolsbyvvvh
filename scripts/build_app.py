from __future__ import annotations

import os
import tomllib
from pathlib import Path

os.environ["PYTHONNOUSERSITE"] = "1"

import PyInstaller.__main__


workspace = Path(__file__).resolve().parents[1]
project = tomllib.loads((workspace / "pyproject.toml").read_text(encoding="utf-8"))
version = str(project["project"]["version"])
version_parts = tuple(int(part) for part in version.split("."))
if not 1 <= len(version_parts) <= 4:
    raise ValueError("项目版本号必须包含一至四段数字")
file_version = (*version_parts, *(0 for _ in range(4 - len(version_parts))))
build_directory = workspace / "build"
build_directory.mkdir(exist_ok=True)
version_file = build_directory / "version_info.txt"
version_file.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={file_version}, prodvers={file_version}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('080404B0', [
    StringStruct('CompanyName', '本地工具'),
    StringStruct('FileDescription', '披露PDF缩放工具'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('InternalName', '披露PDF缩放工具'),
    StringStruct('OriginalFilename', '披露PDF缩放工具.exe'),
    StringStruct('ProductName', '披露PDF缩放工具'),
    StringStruct('ProductVersion', '{version}')
  ])]), VarFileInfo([VarStruct('Translation', [2052, 1200])])]
)
""",
    encoding="utf-8",
)
(build_directory / "app_version.txt").write_text(version, encoding="utf-8")
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
        f"--version-file={version_file}",
        str(workspace / "src/disclosure_pdf_scaler/__main__.py"),
    ]
)
