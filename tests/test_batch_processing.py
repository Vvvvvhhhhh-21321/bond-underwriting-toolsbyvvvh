from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from PySide6.QtCore import QMarginsF, QSize, QSizeF
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtPdf import QPdfDocument
from pypdf import PdfReader, PdfWriter

from disclosure_pdf_scaler.batch import BatchRequest, FileRequest, process_batch


A4_WIDTH_POINTS = 595.2755905511812
A4_HEIGHT_POINTS = 841.8897637795277


def _write_source_pdf(path: Path, page_count: int) -> None:
    writer = PdfWriter()
    for index in range(page_count):
        writer.add_blank_page(width=400 + index, height=600 + index)
    with path.open("wb") as output:
        writer.write(output)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    assert result.files[0].error


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
    assert result.error
    assert result.files[0].error == result.error


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
        dark_pixels = [
            (x, y)
            for y in range(top, bottom)
            for x in range(image.width())
            if image.pixelColor(x, y).alpha() > 128
            and image.pixelColor(x, y).lightness() < 32
        ]
        assert dark_pixels
        left = min(x for x, _ in dark_pixels)
        right = max(x for x, _ in dark_pixels)
        upper = min(y for _, y in dark_pixels)
        lower = max(y for _, y in dark_pixels)
        assert left > 0
        assert right < image.width() - 1
        assert upper >= top
        assert lower < bottom
        visible_ratio = (right - left + 1) / (lower - upper + 1)
        assert visible_ratio == pytest.approx(400 / 600, abs=0.02)
