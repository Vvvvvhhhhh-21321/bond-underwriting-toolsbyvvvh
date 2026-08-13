from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PySide6.QtCore import QMarginsF, QSize, QSizeF
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from disclosure_pdf_scaler.batch import BatchRequest, FileRequest, process_batch


A4_WIDTH_POINTS = 595.2755905511812
A4_HEIGHT_POINTS = 841.8897637795277


def _write_source_pdf(path: Path, page_count: int) -> None:
    writer = PdfWriter()
    for index in range(page_count):
        writer.add_blank_page(width=400 + index, height=600 + index)
    with path.open("wb") as output:
        writer.write(output)


def _write_shaded_pdf(
    path: Path, page_count: int, width_points: float, height_points: float
) -> None:
    writer = QPdfWriter(str(path))
    writer.setResolution(72)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(
                QSizeF(width_points, height_points),
                QPageSize.Unit.Point,
            ),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Point,
        )
    )
    painter = QPainter(writer)
    for index in range(page_count):
        if index:
            writer.newPage()
        shade = 30 + index * 20
        painter.fillRect(
            0,
            0,
            writer.width(),
            writer.height(),
            QColor(shade, shade, shade),
        )
    painter.end()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_dark_region_geometry(
    image: QImage,
    region: tuple[int, int, int, int],
    expected_ratio: float,
    tolerance: float,
) -> None:
    left, right, top, bottom = region
    dark_pixels = [
        (x, y)
        for y in range(top, bottom)
        for x in range(left, right)
        if image.pixelColor(x, y).alpha() > 128
        and image.pixelColor(x, y).lightness() < 32
    ]
    assert dark_pixels
    visible_left = min(x for x, _ in dark_pixels)
    visible_right = max(x for x, _ in dark_pixels)
    visible_top = min(y for _, y in dark_pixels)
    visible_bottom = max(y for _, y in dark_pixels)
    assert visible_left > left
    assert visible_right < right - 1
    assert visible_top > top
    assert visible_bottom < bottom - 1
    visible_ratio = (visible_right - visible_left + 1) / (
        visible_bottom - visible_top + 1
    )
    assert visible_ratio == pytest.approx(expected_ratio, abs=tolerance)


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate((*flags, False)):
        if active and start is None:
            start = index
        elif not active and start is not None:
            runs.append((start, index - 1))
            start = None
    return runs


def _assert_runs_match_mm(
    actual: list[tuple[int, int]],
    expected_mm: list[tuple[float, float]],
    pixels_per_mm: float,
) -> None:
    assert len(actual) == len(expected_mm)
    for (actual_start, actual_end), (expected_start, expected_end) in zip(
        actual, expected_mm, strict=True
    ):
        assert actual_start == pytest.approx(expected_start * pixels_per_mm, abs=2)
        assert actual_end + 1 == pytest.approx(expected_end * pixels_per_mm, abs=2)


def test_user_can_scale_two_selected_pages_without_changing_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "披露材料.pdf"
    output_dir = tmp_path / "结果"
    _write_source_pdf(source, page_count=3)
    source_hash = _sha256(source)

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=(1, 3)),),
            output_dir=output_dir,
        )
    )

    assert result.succeeded == 1
    assert result.files[0].selected_pages == (1, 3)
    assert result.failed == 0
    output = output_dir / "披露材料_缩放.pdf"
    assert result.files[0].output == output
    assert output.exists()
    assert _sha256(source) == source_hash

    reader = PdfReader(output)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(A4_WIDTH_POINTS, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(A4_HEIGHT_POINTS, abs=0.01)


def test_existing_result_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "披露材料.pdf"
    output_dir = tmp_path / "结果"
    output_dir.mkdir()
    existing = output_dir / "披露材料_缩放.pdf"
    existing.write_bytes(b"keep me")
    _write_source_pdf(source, page_count=2)

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=(1, 2)),),
            output_dir=output_dir,
        )
    )

    assert existing.read_bytes() == b"keep me"
    assert result.files[0].output == output_dir / "披露材料_缩放_2.pdf"
    assert result.files[0].output.exists()


@pytest.mark.parametrize("selected_count", range(2, 10))
def test_two_to_nine_selected_pages_fit_on_one_a4_page(
    tmp_path: Path,
    selected_count: int,
) -> None:
    source = tmp_path / f"{selected_count}页材料.pdf"
    output_dir = tmp_path / "结果"
    _write_source_pdf(source, page_count=selected_count)

    result = process_batch(
        BatchRequest(
            files=(
                FileRequest(
                    source=source,
                    pages=tuple(range(1, selected_count + 1)),
                ),
            ),
            output_dir=output_dir,
        )
    )

    assert result.succeeded == 1
    output = result.files[0].output
    assert output is not None
    reader = PdfReader(output)
    assert len(reader.pages) == 1
    assert float(reader.pages[0].mediabox.width) == pytest.approx(
        A4_WIDTH_POINTS, abs=0.01
    )
    assert float(reader.pages[0].mediabox.height) == pytest.approx(
        A4_HEIGHT_POINTS, abs=0.01
    )


def test_unreadable_request_returns_structured_failure(tmp_path: Path) -> None:
    missing = tmp_path / "不存在.pdf"

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=missing, pages=(1, 2)),),
            output_dir=tmp_path / "结果",
        )
    )

    assert result.succeeded == 0
    assert result.failed == 1
    assert result.files[0].source == missing
    assert result.files[0].output is None
    assert result.files[0].error == "处理失败，请检查源文件和输出位置"


def test_damaged_pdf_is_skipped_without_stopping_batch(tmp_path: Path) -> None:
    damaged = tmp_path / "损坏.pdf"
    valid = tmp_path / "有效.pdf"
    damaged.write_bytes(b"not a pdf")
    _write_source_pdf(valid, 2)

    result = process_batch(
        BatchRequest(
            files=(FileRequest(damaged), FileRequest(valid, pages=(1, 2))),
            output_dir=tmp_path / "结果",
        )
    )

    assert result.skipped == 1
    assert result.succeeded == 1
    assert result.files[0].status == "skipped"
    assert result.files[0].error == "PDF 文件损坏或无法解析，已跳过"


def test_empty_explicit_page_selection_is_skipped(tmp_path: Path) -> None:
    source = tmp_path / "披露材料.pdf"
    _write_source_pdf(source, page_count=2)

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=()),),
            output_dir=tmp_path / "结果",
        )
    )

    assert result.skipped == 1
    assert result.files[0].status == "skipped"
    assert result.files[0].error == "至少选择一页"


@pytest.mark.parametrize(
    ("selected_count", "expected_output_pages"),
    [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 1), (10, 2), (18, 2), (20, 3)],
)
def test_selected_pages_are_grouped_by_nine(
    tmp_path: Path, selected_count: int, expected_output_pages: int
) -> None:
    source = tmp_path / f"{selected_count}页.pdf"
    _write_source_pdf(source, selected_count)
    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=tuple(range(1, selected_count + 1))),),
            output_dir=tmp_path / "结果",
        )
    )
    output = result.files[0].output
    assert output is not None
    assert len(PdfReader(output).pages) == expected_output_pages


def test_single_selected_page_keeps_original_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "单页材料.pdf"
    output_dir = tmp_path / "结果"
    _write_source_pdf(source, page_count=1)

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=(1,)),),
            output_dir=output_dir,
        )
    )

    output = result.files[0].output
    assert output is not None
    page = PdfReader(output).pages[0]
    assert float(page.mediabox.width) == pytest.approx(400)
    assert float(page.mediabox.height) == pytest.approx(600)


def test_output_directory_failure_is_returned_as_structured_result(
    tmp_path: Path,
) -> None:
    source = tmp_path / "披露材料.pdf"
    output_path = tmp_path / "不是目录"
    _write_source_pdf(source, page_count=2)
    output_path.write_text("occupied", encoding="utf-8")

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=(1, 2)),),
            output_dir=output_path,
        )
    )

    assert result.succeeded == 0
    assert result.failed == 1
    assert result.error == "无法创建输出目录，请检查目录权限或更换输出位置"
    assert result.files[0].error == result.error


def test_batch_folder_is_created_and_one_failure_does_not_stop_rest(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "有效.pdf"
    missing = tmp_path / "缺失.pdf"
    _write_source_pdf(valid, 2)

    result = process_batch(
        BatchRequest(
            files=(
                FileRequest(missing, pages=(1,)),
                FileRequest(valid, pages=(1, 2)),
            ),
            output_dir=tmp_path / "输出根目录",
            create_batch_folder=True,
        )
    )

    assert result.succeeded == 1
    assert result.failed == 1
    assert result.output_dir is not None
    assert result.output_dir.name.startswith("PDF缩放结果_")
    assert [path.name for path in result.output_dir.iterdir()] == ["有效_缩放.pdf"]


def test_empty_batch_result_folder_is_removed(tmp_path: Path) -> None:
    result = process_batch(
        BatchRequest(
            files=(FileRequest(tmp_path / "缺失.pdf", pages=(1,)),),
            output_dir=tmp_path / "输出根目录",
            create_batch_folder=True,
        )
    )

    assert result.succeeded == 0
    assert result.output_dir is None
    assert list((tmp_path / "输出根目录").iterdir()) == []


def test_visible_page_geometry_is_scaled_uniformly_inside_a4(tmp_path: Path) -> None:
    source = tmp_path / "带边缘标记的材料.pdf"
    output_dir = tmp_path / "结果"
    writer = QPdfWriter(str(source))
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QSizeF(400, 600), QPageSize.Unit.Point),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Point,
        )
    )
    painter = QPainter(writer)
    painter.fillRect(0, 0, writer.width(), writer.height(), QColor("black"))
    writer.newPage()
    painter.fillRect(0, 0, writer.width(), writer.height(), QColor("black"))
    painter.end()

    result = process_batch(
        BatchRequest(
            files=(FileRequest(source=source, pages=(1, 2)),),
            output_dir=output_dir,
        )
    )

    output_pdf = result.files[0].output
    assert output_pdf is not None
    rendered_pdf = QPdfDocument(None)
    assert rendered_pdf.load(str(output_pdf)) == QPdfDocument.Error.None_
    image = rendered_pdf.render(0, QSize(1190, 1684))

    for top, bottom in ((0, image.height() // 2), (image.height() // 2, image.height())):
        _assert_dark_region_geometry(
            image, (0, image.width(), top, bottom), 400 / 600, 0.02
        )


@pytest.mark.parametrize(
    ("page_count", "columns", "rows"),
    ((3, 2, 2), (5, 2, 3), (8, 3, 3)),
)
def test_incomplete_last_row_uses_exact_physical_layout_and_reading_order(
    tmp_path: Path,
    page_count: int,
    columns: int,
    rows: int,
) -> None:
    margin_mm = 5.0
    gap_mm = 2.0
    cell_width_mm = (210 - 2 * margin_mm - (columns - 1) * gap_mm) / columns
    cell_height_mm = (297 - 2 * margin_mm - (rows - 1) * gap_mm) / rows
    points_per_mm = 72 / 25.4
    source = tmp_path / f"{page_count}页布局.pdf"
    _write_shaded_pdf(
        source,
        page_count,
        cell_width_mm * points_per_mm,
        cell_height_mm * points_per_mm,
    )

    result = process_batch(
        BatchRequest(
            (FileRequest(source, pages=tuple(range(1, page_count + 1))),),
            tmp_path / "结果",
        )
    )

    output = result.files[0].output
    assert output is not None
    document = QPdfDocument(None)
    assert document.load(str(output)) == QPdfDocument.Error.None_
    pixels_per_mm = 6.0
    image = document.render(0, QSize(1260, 1782))
    def is_dark(x: int, y: int) -> bool:
        color = image.pixelColor(x, y)
        return bool(color.alpha() > 128 and color.lightness() < 220)

    visible_rows = _runs(
        [any(is_dark(x, y) for x in range(image.width())) for y in range(image.height())]
    )
    expected_rows = [
        (
            margin_mm + row * (cell_height_mm + gap_mm),
            margin_mm + row * (cell_height_mm + gap_mm) + cell_height_mm,
        )
        for row in range(rows)
    ]
    _assert_runs_match_mm(visible_rows, expected_rows, pixels_per_mm)

    sampled_shades: list[int] = []
    for row in range(rows):
        pages_in_row = min(columns, page_count - row * columns)
        row_width_mm = pages_in_row * cell_width_mm + (pages_in_row - 1) * gap_mm
        row_start_mm = (210 - row_width_mm) / 2
        expected_columns = [
            (
                row_start_mm + column * (cell_width_mm + gap_mm),
                row_start_mm + column * (cell_width_mm + gap_mm) + cell_width_mm,
            )
            for column in range(pages_in_row)
        ]
        y_mm = margin_mm + row * (cell_height_mm + gap_mm) + cell_height_mm / 2
        y = round(y_mm * pixels_per_mm)
        visible_columns = _runs([is_dark(x, y) for x in range(image.width())])
        _assert_runs_match_mm(visible_columns, expected_columns, pixels_per_mm)
        for left_mm, right_mm in expected_columns:
            sampled_shades.append(
                image.pixelColor(round((left_mm + right_mm) / 2 * pixels_per_mm), y).lightness()
            )
    assert sampled_shades == sorted(sampled_shades)
    assert len(set(sampled_shades)) == page_count


def test_rotated_inverted_and_slightly_different_pages_render(tmp_path: Path) -> None:
    plain = tmp_path / "原始.pdf"
    source = tmp_path / "复杂页面.pdf"
    pdf_writer = QPdfWriter(str(plain))
    pdf_writer.setPageLayout(
        QPageLayout(
            QPageSize(QSizeF(400, 600), QPageSize.Unit.Point),
            QPageLayout.Orientation.Portrait,
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Point,
        )
    )
    painter = QPainter(pdf_writer)
    for index in range(3):
        if index:
            pdf_writer.newPage()
        painter.fillRect(
            pdf_writer.width() // 10,
            pdf_writer.height() // 10,
            pdf_writer.width() * 8 // 10,
            pdf_writer.height() * 8 // 10,
            QColor("black"),
        )
    painter.end()
    reader = PdfReader(plain)
    reader.pages[0].rotate(90)
    reader.pages[1].mediabox = RectangleObject((400, 600, 0, 0))
    reader.pages[1].cropbox = RectangleObject((400, 600, 0, 0))
    reader.pages[2].mediabox = RectangleObject((0, 0, 400.2, 600.1))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    with source.open("wb") as stream:
        writer.write(stream)

    result = process_batch(
        BatchRequest((FileRequest(source, pages=(1, 2, 3)),), tmp_path / "结果")
    )

    assert result.succeeded == 1
    output = result.files[0].output
    assert output is not None
    rendered = QPdfDocument(None)
    assert rendered.load(str(output)) == QPdfDocument.Error.None_
    image = rendered.render(0, QSize(595, 842))
    assert not image.isNull()
    regions = (
        (0, image.width() // 2, 0, image.height() // 2, 600 / 400),
        (image.width() // 2, image.width(), 0, image.height() // 2, 400 / 600),
        (image.width() // 4, image.width() * 3 // 4, image.height() // 2, image.height(), 400.2 / 600.1),
    )
    for left, right, top, bottom, expected_ratio in regions:
        _assert_dark_region_geometry(
            image, (left, right, top, bottom), expected_ratio, 0.03
        )
