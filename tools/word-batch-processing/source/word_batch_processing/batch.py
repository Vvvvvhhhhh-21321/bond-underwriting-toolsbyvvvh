from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable

from .processor import collect_word_files


@dataclass(frozen=True)
class BatchState:
    workspace: Path
    backup: Path
    word_file_count: int
    batch_id: str = ""

    def to_json(self) -> dict[str, object]:
        data = asdict(self)
        data["workspace"] = str(self.workspace)
        data["backup"] = str(self.backup)
        return data

    @classmethod
    def from_json(cls, data: dict[str, object]) -> "BatchState":
        workspace = Path(str(data["workspace"]))
        backup = Path(str(data["backup"]))
        batch_id = str(data.get("batch_id") or "")
        if not batch_id:
            batch_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"{workspace.resolve()}|{backup.resolve()}"
            ).hex
        return cls(
            workspace=workspace,
            backup=backup,
            word_file_count=int(str(data["word_file_count"])),
            batch_id=batch_id,
        )


class BatchStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, state: BatchState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(state.to_json(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def load(self) -> BatchState | None:
        if not self.path.exists():
            return None
        try:
            return BatchState.from_json(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError):
            return None


class BatchLifecycle:
    def __init__(
        self,
        store: BatchStateStore,
        *,
        now: Callable[[], datetime] = datetime.now,
        copy_tree: Callable[[Path, Path], object] = shutil.copytree,
        free_space: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
        file_available: Callable[[Path], bool] | None = None,
        cloud_placeholder: Callable[[Path], bool] | None = None,
    ):
        self.store = store
        self.now = now
        self.copy_tree = copy_tree
        self.free_space = free_space
        self.file_available = file_available or _file_available
        self.cloud_placeholder = cloud_placeholder or _cloud_placeholder

    def import_folder(self, source: str | Path) -> BatchState:
        workspace = Path(source).resolve()
        self._preflight(workspace)
        backup = self._backup_path(workspace)

        workspace.rename(backup)
        try:
            self.copy_tree(backup, workspace)
        except Exception:
            if workspace.exists():
                shutil.rmtree(workspace)
            backup.rename(workspace)
            raise

        state = BatchState(
            workspace=workspace,
            backup=backup.resolve(),
            word_file_count=len(collect_word_files(workspace)),
            batch_id=uuid.uuid4().hex,
        )
        try:
            self.store.save(state)
        except Exception:
            shutil.rmtree(workspace)
            backup.rename(workspace)
            raise
        return state

    def resume(self) -> BatchState | None:
        state = self.store.load()
        if state is None or not state.workspace.is_dir() or not state.backup.is_dir():
            return None
        current_count = len(collect_word_files(state.workspace))
        if current_count != state.word_file_count:
            state = replace(state, word_file_count=current_count)
            self.store.save(state)
        return state

    def _preflight(self, source: Path) -> None:
        if not source.is_dir():
            raise FileNotFoundError(f"文件夹不存在：{source}")
        if str(source).startswith("\\\\"):
            raise ValueError("暂不支持网络共享路径")
        files = [path for path in source.rglob("*") if path.is_file()]
        placeholders = [path for path in files if self.cloud_placeholder(path)]
        if placeholders:
            raise ValueError(f"发现仅云端占位文件：{placeholders[0].name}")
        occupied = [path for path in files if not self.file_available(path)]
        if occupied:
            raise PermissionError(f"请先关闭正在使用的文件：{occupied[0].name}")
        required = sum(path.stat().st_size for path in files)
        free = self.free_space(source.parent)
        if free < required:
            raise OSError("磁盘可用空间不足，无法建立工作文件夹")

    def _backup_path(self, source: Path) -> Path:
        base = source.with_name(f"{source.name}_备份")
        if not base.exists():
            return base
        timestamp = self.now().strftime("%Y%m%d-%H%M%S")
        candidate = source.with_name(f"{source.name}_备份_{timestamp}")
        sequence = 2
        while candidate.exists():
            candidate = source.with_name(f"{source.name}_备份_{timestamp} ({sequence})")
            sequence += 1
        return candidate


def _cloud_placeholder(path: Path) -> bool:
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    cloud_flags = 0x00001000 | 0x00040000 | 0x00400000
    return bool(attributes & cloud_flags)


def _file_available(path: Path) -> bool:
    if os.name != "nt":
        try:
            with path.open("rb"):
                return True
        except OSError:
            return False
    try:
        import win32con
        import win32file

        handle = win32file.CreateFile(
            str(path),
            win32con.GENERIC_READ,
            0,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        handle.Close()
        return True
    except OSError:
        return False
