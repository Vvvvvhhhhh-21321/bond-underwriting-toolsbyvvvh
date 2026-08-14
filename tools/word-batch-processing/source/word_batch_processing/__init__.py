"""Word 批量处理的公共接口。"""

from .batch import BatchLifecycle, BatchState, BatchStateStore
from .models import (
    OperationName,
    OperationPreview,
    OperationResult,
    OperationStatus,
    ResultItem,
)
from .processor import DocumentBatchProcessor
from .word_process import IsolatedWordProcessAdapter

__all__ = [
    "BatchLifecycle",
    "BatchState",
    "BatchStateStore",
    "DocumentBatchProcessor",
    "IsolatedWordProcessAdapter",
    "OperationResult",
    "OperationName",
    "OperationPreview",
    "OperationStatus",
    "ResultItem",
]
