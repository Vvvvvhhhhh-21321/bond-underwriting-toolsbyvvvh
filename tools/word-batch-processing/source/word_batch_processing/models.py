from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OperationStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationName(str, Enum):
    SEARCH = "search"
    REPLACE = "replace"
    ACCEPT_REVISIONS = "accept_revisions"
    DELETE_COMMENTS = "delete_comments"
    UPDATE_TOC = "update_toc"
    RENAME = "rename"


class ItemStatus(str, Enum):
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ResultItem:
    path: str
    status: ItemStatus
    reason: str


@dataclass
class OperationResult:
    status: OperationStatus = OperationStatus.COMPLETED
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    hits: list[str] = field(default_factory=list)
    items: list[ResultItem] = field(default_factory=list)
    can_retry: bool = False
    can_undo: bool = False

    def add_failure(self, path: str, reason: str) -> None:
        self.failed += 1
        self.items.append(ResultItem(path, ItemStatus.FAILED, reason))
        self._refresh_status()

    def add_skip(self, path: str, reason: str) -> None:
        self.skipped += 1
        self.items.append(ResultItem(path, ItemStatus.SKIPPED, reason))
        self._refresh_status()

    def _refresh_status(self) -> None:
        if self.failed or self.skipped:
            self.status = (
                OperationStatus.PARTIAL
                if self.succeeded
                else OperationStatus.FAILED
            )


@dataclass(frozen=True)
class OperationPreview:
    affected_files: int
    affected_items: int
