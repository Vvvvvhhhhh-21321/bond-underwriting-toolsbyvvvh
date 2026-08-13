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


def test_same_name_keeps_first_input_before_natural_sort(tmp_path: Path) -> None:
    first = tmp_path / "乙" / "报告10.pdf"
    later_same_name = tmp_path / "甲" / "报告10.pdf"
    numbered = tmp_path / "甲" / "报告2.pdf"
    for path in (first, later_same_name, numbered):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    result = discover_pdfs((first, later_same_name, numbered))

    assert first.resolve() in result.files
    assert later_same_name.resolve() not in result.files
    assert [path.name for path in result.files] == ["报告10.pdf", "报告2.pdf"]


def test_files_in_same_folder_use_natural_full_path_order(tmp_path: Path) -> None:
    report10 = tmp_path / "报告10.pdf"
    report2 = tmp_path / "报告2.pdf"
    report10.write_bytes(b"x")
    report2.write_bytes(b"x")

    result = discover_pdfs((report10, report2))

    assert [path.name for path in result.files] == ["报告2.pdf", "报告10.pdf"]
