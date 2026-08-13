from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QLineEdit, QPushButton
from pypdf import PdfWriter

from disclosure_pdf_scaler.gui import MainWindow


def _write_source_pdf(path: Path, pages: int = 3) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=400, height=600)
    with path.open("wb") as output:
        writer.write(output)


def test_user_can_add_pdf_and_choose_output_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "披露材料.pdf"
    output_dir = tmp_path / "结果"
    _write_source_pdf(source)
    window = MainWindow()
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: ([str(source)], "PDF"))
    window.findChild(QPushButton, "addFileButton").click()
    app.processEvents()
    assert len(window.entries) == 1
    edit = window.findChild(QLineEdit, "pageExpressionEdit")
    assert edit.placeholderText() == "默认：1-2"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(output_dir))
    window.findChild(QPushButton, "chooseOutputButton").click()
    assert window.findChild(QPushButton, "processButton").isEnabled()
    window.close()


def test_toggle_updates_default_but_custom_expression_wins(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "披露材料.pdf"
    _write_source_pdf(source)
    window = MainWindow()
    window.add_inputs((source,))
    edit = window.findChild(QLineEdit, "pageExpressionEdit")
    toggle = window.findChild(QCheckBox, "removeLastCheckBox")
    toggle.setChecked(False)
    app.processEvents()
    assert edit.placeholderText() == "默认：1-3"
    edit.setText("1, 3")
    toggle.setChecked(True)
    app.processEvents()
    assert edit.text() == "1, 3"
    window.close()
