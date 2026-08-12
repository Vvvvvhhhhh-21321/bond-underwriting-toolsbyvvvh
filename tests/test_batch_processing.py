from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
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
