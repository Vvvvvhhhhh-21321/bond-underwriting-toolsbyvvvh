from __future__ import annotations

from pathlib import Path

from disclosure_pdf_scaler.files import discover_pdfs


def test_files_and_folders_are_discovered_deduplicated_and_sorted(tmp_path: Path) -> None:
    first = tmp_path / "甲" / "报告.pdf"
    duplicate_name = tmp_path / "乙" / "报告.PDF"
    other = tmp_path / "乙" / "材料.pdf"
    ignored = tmp_path / "乙" / "说明.docx"
    for path in (first, duplicate_name, other, ignored):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    result = discover_pdfs((tmp_path / "乙", first, first))

    assert [item.name for item in result.files] == ["报告.PDF", "材料.pdf"]
    assert result.duplicate_paths == 1
    assert result.ignored_non_pdf == 1
    assert result.duplicate_names == ("报告.pdf",)
