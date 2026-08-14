"""Word 批量处理 V2 启动入口。"""

import sys
from multiprocessing import freeze_support
from pathlib import Path

if __name__ == "__main__":
    freeze_support()

from word_batch_processing.app import run_app
from word_batch_processing.word_process import IsolatedWordProcessAdapter


def _run_packaging_smoke(path: Path) -> int:
    """供发布验收使用：验证冻结程序能启动隔离 Word 工作进程。"""
    with IsolatedWordProcessAdapter(timeout=60) as adapter:
        adapter.count_comments(path)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-word":
        raise SystemExit(_run_packaging_smoke(Path(sys.argv[2])))
    raise SystemExit(run_app())
