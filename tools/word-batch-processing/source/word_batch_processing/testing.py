from __future__ import annotations

from pathlib import Path


class TextWordAdapter:
    """只供测试使用：把伪 Word 文件当 UTF-8 文本处理。"""

    def __init__(
        self,
        fail_on: set[str] | None = None,
        fail_once_on: set[str] | None = None,
    ):
        self.fail_on = fail_on or set()
        self.fail_once_on = fail_once_on or set()
        self._failed_once: set[str] = set()
        self.revision_modes: list[bool] = []
        self.operations: list[tuple[str, str]] = []

    def begin_task(self) -> None:
        return None

    def cancel_current(self) -> None:
        return None

    def _check(self, path: Path) -> None:
        if path.name in self.fail_on:
            raise RuntimeError("测试适配器模拟失败")
        if path.name in self.fail_once_on and path.name not in self._failed_once:
            self._failed_once.add(path.name)
            raise RuntimeError("测试适配器模拟单次失败")

    def search(self, path: Path, text: str) -> bool:
        self.operations.append(("search", path.name))
        self._check(path)
        return text in path.read_text(encoding="utf-8")

    def replace_text(
        self,
        path: Path,
        find_text: str,
        replace_text: str,
        track_changes: bool,
    ) -> bool:
        self.operations.append(("replace", path.name))
        self._check(path)
        self.revision_modes.append(track_changes)
        content = path.read_text(encoding="utf-8")
        path.write_text(content.replace(find_text, replace_text), encoding="utf-8")
        return find_text in content

    def count_revisions(self, path: Path) -> int:
        return path.read_text(encoding="utf-8").count("[REV]")

    def accept_all_revisions(self, path: Path) -> bool:
        self.operations.append(("accept_revisions", path.name))
        self._check(path)
        content = path.read_text(encoding="utf-8")
        count = content.count("[REV]")
        path.write_text(content.replace("[REV]", "").replace("  ", " "), encoding="utf-8")
        return count > 0

    def count_comments(self, path: Path) -> int:
        return path.read_text(encoding="utf-8").count("[COMMENT]")

    def delete_all_comments(self, path: Path) -> bool:
        self.operations.append(("delete_comments", path.name))
        self._check(path)
        content = path.read_text(encoding="utf-8")
        count = content.count("[COMMENT]")
        path.write_text(
            content.replace("[COMMENT]", "").replace("  ", " "), encoding="utf-8"
        )
        return count > 0

    def update_toc_page_numbers(self, path: Path) -> bool:
        self.operations.append(("update_toc", path.name))
        self._check(path)
        content = path.read_text(encoding="utf-8")
        count = content.count("[TOC:")
        if count:
            start = content.index("[TOC:")
            end = content.index("]", start) + 1
            content = content[:start] + "[TOC:新页码]" + content[end:]
            path.write_text(content, encoding="utf-8")
        return count > 0
