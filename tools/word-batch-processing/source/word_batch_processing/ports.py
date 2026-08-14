from __future__ import annotations

from pathlib import Path
from typing import Protocol


class OperationCancelled(RuntimeError):
    """用户取消当前外部 Word 调用。"""


class WordAdapter(Protocol):
    """Word 外部系统在文档批次处理模块中的内部接缝。"""

    def begin_task(self) -> None: ...

    def cancel_current(self) -> None: ...

    def search(self, path: Path, text: str) -> bool: ...

    def replace_text(
        self,
        path: Path,
        find_text: str,
        replace_text: str,
        track_changes: bool,
    ) -> bool: ...

    def count_revisions(self, path: Path) -> int: ...

    def accept_all_revisions(self, path: Path) -> bool: ...

    def count_comments(self, path: Path) -> int: ...

    def delete_all_comments(self, path: Path) -> bool: ...

    def update_toc_page_numbers(self, path: Path) -> bool: ...
