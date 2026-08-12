from __future__ import annotations

from dataclasses import dataclass
from math import ceil, sqrt
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject


A4_WIDTH_POINTS = 210 / 25.4 * 72
A4_HEIGHT_POINTS = 297 / 25.4 * 72


@dataclass(frozen=True)
class FileRequest:
    source: Path
    pages: tuple[int, ...]


@dataclass(frozen=True)
class BatchRequest:
    files: tuple[FileRequest, ...]
    output_dir: Path


@dataclass(frozen=True)
class FileResult:
    source: Path
    output: Path | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.output is not None


@dataclass(frozen=True)
class BatchResult:
    files: tuple[FileResult, ...]
    error: str | None = None

    @property
    def succeeded(self) -> int:
        return sum(result.succeeded for result in self.files)

    @property
    def failed(self) -> int:
        return len(self.files) - self.succeeded


def process_batch(request: BatchRequest) -> BatchResult:
    """处理有序文件请求，并返回每份文件的结果。"""
    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        message = f"无法创建输出目录：{error}"
        return BatchResult(
            files=tuple(
                FileResult(source=file.source, output=None, error=message)
                for file in request.files
            ),
            error=message,
        )
    results: list[FileResult] = []
    for file_request in request.files:
        output = _available_output_path(request.output_dir, file_request.source.stem)
        try:
            _scale_file(file_request, output)
        except Exception as error:
            results.append(
                FileResult(source=file_request.source, output=None, error=str(error))
            )
        else:
            results.append(FileResult(file_request.source, output, None))
    return BatchResult(tuple(results))


def _available_output_path(output_dir: Path, source_stem: str) -> Path:
    candidate = output_dir / f"{source_stem}_缩放.pdf"
    suffix = 2
    while candidate.exists():
        candidate = output_dir / f"{source_stem}_缩放_{suffix}.pdf"
        suffix += 1
    return candidate


def _scale_file(request: FileRequest, output: Path) -> None:
    reader = PdfReader(request.source)
    selected_pages = []
    for page_number in request.pages:
        if page_number < 1 or page_number > len(reader.pages):
            raise ValueError(f"页码 {page_number} 超出 1-{len(reader.pages)}")
        selected_pages.append(reader.pages[page_number - 1])
    if not selected_pages:
        raise ValueError("至少选择一页")
    if len(selected_pages) > 9:
        raise ValueError("工单 01 每份文件最多选择 9 页")

    writer = PdfWriter()
    if len(selected_pages) == 1:
        writer.add_page(selected_pages[0])
    else:
        writer.add_page(_compose_a4_page(selected_pages))
    with output.open("wb") as stream:
        writer.write(stream)


def _compose_a4_page(source_pages: list[PageObject]) -> PageObject:
    rows = ceil(sqrt(len(source_pages)))
    columns = ceil(len(source_pages) / rows)
    cell_width = A4_WIDTH_POINTS / columns
    cell_height = A4_HEIGHT_POINTS / rows
    destination = PageObject.create_blank_page(
        width=A4_WIDTH_POINTS,
        height=A4_HEIGHT_POINTS,
    )

    for index, source in enumerate(source_pages):
        width = float(source.mediabox.width)
        height = float(source.mediabox.height)
        scale = min(cell_width / width, cell_height / height)
        column = index % columns
        row_from_top = index // columns
        x = column * cell_width + (cell_width - width * scale) / 2
        y = A4_HEIGHT_POINTS - (row_from_top + 1) * cell_height
        y += (cell_height - height * scale) / 2
        destination.merge_transformed_page(
            source,
            Transformation().scale(scale).translate(x, y),
        )
    return destination
