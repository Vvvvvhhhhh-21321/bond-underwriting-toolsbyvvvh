from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from pypdf import PdfReader

from disclosure_pdf_scaler.batch import BatchRequest, FileRequest, process_batch
from disclosure_pdf_scaler.files import discover_pdfs


def main() -> int:
    source_root = Path(sys.argv[1] if len(sys.argv) > 1 else "测试文件集")
    output_root = Path(sys.argv[2] if len(sys.argv) > 2 else "tmp/pdfs/acceptance")
    files = discover_pdfs((source_root,)).files
    before = {path: _fingerprint(path) for path in files}
    started = time.monotonic()
    result = process_batch(
        BatchRequest(
            tuple(FileRequest(path, page_expression="", remove_last=True) for path in files),
            output_root,
            create_batch_folder=True,
        ),
        lambda done, total, name: print(f"{done}/{total} {name}", flush=True),
    )
    after = {path: _fingerprint(path) for path in files}
    outputs = [_inspect(item.output) for item in result.files if item.output]
    report = {
        "inputs": len(files),
        "success": result.succeeded,
        "failed": result.failed,
        "skipped": result.skipped,
        "source_unchanged": before == after,
        "seconds": round(time.monotonic() - started, 2),
        "outputs": outputs,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.succeeded == 8 and before == after else 1


def _fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def _inspect(path: Path) -> dict[str, object]:
    reader = PdfReader(path)
    return {
        "name": path.name,
        "pages": len(reader.pages),
        "annotations": sum(len(page.get("/Annots", [])) for page in reader.pages),
        "metadata": bool(reader.metadata and len(reader.metadata) > 1),
        "text_chars": sum(len(page.extract_text() or "") for page in reader.pages),
    }


if __name__ == "__main__":
    raise SystemExit(main())

