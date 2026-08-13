from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from pypdf.errors import PdfReadError
from pypdf.generic import NameObject, RectangleObject


POINTS_PER_MM = 72 / 25.4
A4_WIDTH_POINTS = 210 * POINTS_PER_MM
A4_HEIGHT_POINTS = 297 * POINTS_PER_MM
PAGE_MARGIN = 5 * POINTS_PER_MM
CELL_GAP = 2 * POINTS_PER_MM
ProgressCallback = Callable[[int, int, str], None]


class PageSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class FileRequest:
    source: Path
    pages: tuple[int, ...] | None = None
    page_expression: str = ""
    remove_last: bool = True


@dataclass(frozen=True)
class BatchRequest:
    files: tuple[FileRequest, ...]
    output_dir: Path
    create_batch_folder: bool = False


@dataclass(frozen=True)
class FileResult:
    source: Path
    output: Path | None
    error: str | None
    status: str = "success"

    @property
    def succeeded(self) -> bool:
        return self.status == "success" and self.output is not None


@dataclass(frozen=True)
class BatchResult:
    files: tuple[FileResult, ...]
    output_dir: Path | None = None
    error: str | None = None

    @property
    def succeeded(self) -> int:
        return sum(result.succeeded for result in self.files)

    @property
    def failed(self) -> int:
        return sum(result.status == "failed" for result in self.files)

    @property
    def skipped(self) -> int:
        return sum(result.status == "skipped" for result in self.files)


def resolve_pages(expression: str, page_count: int, remove_last: bool) -> tuple[int, ...]:
    """把用户页码表达式解析为按原文档顺序排列的页码。"""
    if page_count < 1:
        raise PageSelectionError("PDF 中没有页面")
    normalized = expression.strip()
    if not normalized:
        end = page_count - 1 if remove_last and page_count > 1 else page_count
        return tuple(range(1, end + 1))
    normalized = normalized.replace("，", ",")
    normalized = re.sub(r"[—–－]", "-", normalized)
    selected: set[int] = set()
    for raw_part in normalized.split(","):
        part = re.sub(r"\s+", "", raw_part)
        if not part:
            raise PageSelectionError("页码中存在空白片段")
        if re.fullmatch(r"\d+", part):
            selected.add(_checked_page(int(part), page_count))
            continue
        match = re.fullmatch(r"(\d+)-(\d+)", part)
        if match is None:
            raise PageSelectionError(f"无法识别页码“{raw_part.strip()}”")
        start, end = map(int, match.groups())
        _checked_page(start, page_count)
        _checked_page(end, page_count)
        if start > end:
            raise PageSelectionError(f"起始页 {start} 不能大于结束页 {end}")
        selected.update(range(start, end + 1))
    if not selected:
        raise PageSelectionError("至少选择一页")
    return tuple(sorted(selected))


def default_page_hint(page_count: int, remove_last: bool) -> str:
    pages = resolve_pages("", page_count, remove_last)
    return f"默认：1-{pages[-1]}" if len(pages) > 1 else "默认：1"


def process_batch(
    request: BatchRequest, progress: ProgressCallback | None = None
) -> BatchResult:
    """处理有序文件请求；单文件失败不会中断其他文件。"""
    target = request.output_dir
    if request.create_batch_folder:
        target = _new_batch_directory(target)
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        message = f"无法创建输出目录：{error}"
        return BatchResult(
            tuple(FileResult(f.source, None, message, "failed") for f in request.files),
            error=message,
        )

    results: list[FileResult] = []
    total = len(request.files)
    for index, file_request in enumerate(request.files, 1):
        if progress:
            progress(index - 1, total, file_request.source.name)
        output = _available_output_path(target, file_request.source.stem)
        try:
            _scale_file(file_request, output)
        except (PageSelectionError, PdfReadError) as error:
            results.append(FileResult(file_request.source, None, str(error), "skipped"))
        except Exception as error:
            results.append(FileResult(file_request.source, None, str(error), "failed"))
        else:
            results.append(FileResult(file_request.source, output, None))
        if progress:
            progress(index, total, file_request.source.name)
    if not any(item.succeeded for item in results) and request.create_batch_folder:
        try:
            target.rmdir()
            target_result: Path | None = None
        except OSError:
            target_result = target
    else:
        target_result = target
    return BatchResult(tuple(results), target_result)


def _checked_page(page: int, page_count: int) -> int:
    if page < 1 or page > page_count:
        raise PageSelectionError(f"页码 {page} 超出 1-{page_count}")
    return page


def _new_batch_directory(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / f"PDF缩放结果_{stamp}"
    suffix = 2
    while candidate.exists():
        candidate = root / f"PDF缩放结果_{stamp}_{suffix}"
        suffix += 1
    return candidate


def _available_output_path(output_dir: Path, source_stem: str) -> Path:
    candidate = output_dir / f"{source_stem}_缩放.pdf"
    suffix = 2
    while candidate.exists():
        candidate = output_dir / f"{source_stem}_缩放_{suffix}.pdf"
        suffix += 1
    return candidate


def _scale_file(request: FileRequest, output: Path) -> None:
    reader = PdfReader(request.source)
    if reader.is_encrypted:
        raise PageSelectionError("PDF 受密码保护，已跳过")
    numbers = (
        request.pages
        if request.pages is not None
        else resolve_pages(
            request.page_expression, len(reader.pages), request.remove_last
        )
    )
    if not numbers:
        raise PageSelectionError("至少选择一页")
    selected = [_prepared_page(reader.pages[_checked_page(n, len(reader.pages)) - 1]) for n in numbers]
    writer = PdfWriter()
    for offset in range(0, len(selected), 9):
        group = selected[offset : offset + 9]
        output_page = group[0] if len(group) == 1 else _compose_a4_page(group)
        output_page.pop(NameObject("/Annots"), None)
        writer.add_page(output_page)
    writer.metadata = {}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile("wb", delete=False, dir=output.parent, suffix=".tmp") as stream:
            temp_path = Path(stream.name)
            writer.write(stream)
        temp_path.replace(output)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _prepared_page(page: PageObject) -> PageObject:
    if page.rotation:
        page.transfer_rotation_to_content()
    box = page.cropbox
    left, right = sorted((float(box.left), float(box.right)))
    bottom, top = sorted((float(box.bottom), float(box.top)))
    normalized = RectangleObject((left, bottom, right, top))
    page.mediabox = normalized
    page.cropbox = normalized
    page.pop(NameObject("/Annots"), None)
    return page


def _grid(page_count: int) -> tuple[int, int]:
    if page_count == 2:
        return 1, 2
    if page_count <= 4:
        return 2, 2
    if page_count <= 6:
        return 2, 3
    return 3, 3


def _compose_a4_page(source_pages: list[PageObject]) -> PageObject:
    columns, rows = _grid(len(source_pages))
    usable_width = A4_WIDTH_POINTS - 2 * PAGE_MARGIN - (columns - 1) * CELL_GAP
    usable_height = A4_HEIGHT_POINTS - 2 * PAGE_MARGIN - (rows - 1) * CELL_GAP
    cell_width = usable_width / columns
    cell_height = usable_height / rows
    destination = PageObject.create_blank_page(width=A4_WIDTH_POINTS, height=A4_HEIGHT_POINTS)
    for index, source in enumerate(source_pages):
        row_from_top = index // columns
        items_in_row = min(columns, len(source_pages) - row_from_top * columns)
        position_in_row = index % columns
        row_width = items_in_row * cell_width + (items_in_row - 1) * CELL_GAP
        row_start = (A4_WIDTH_POINTS - row_width) / 2
        cell_left = row_start + position_in_row * (cell_width + CELL_GAP)
        cell_bottom = A4_HEIGHT_POINTS - PAGE_MARGIN - (row_from_top + 1) * cell_height - row_from_top * CELL_GAP
        width, height = float(source.mediabox.width), float(source.mediabox.height)
        scale = min(cell_width / width, cell_height / height)
        x = cell_left + (cell_width - width * scale) / 2 - float(source.mediabox.left) * scale
        y = cell_bottom + (cell_height - height * scale) / 2 - float(source.mediabox.bottom) * scale
        destination.merge_transformed_page(source, Transformation().scale(scale).translate(x, y))
    return destination
