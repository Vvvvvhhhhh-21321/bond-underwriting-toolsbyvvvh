from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QPushButton, QSpinBox
from pypdf import PdfWriter

from disclosure_pdf_scaler.gui import MainWindow


def _write_source_pdf(path: Path) -> None:
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=400, height=600)
    with path.open("wb") as output:
        writer.write(output)


def test_user_can_choose_pdf_and_output_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "披露材料.pdf"
    output_dir = tmp_path / "结果"
    _write_source_pdf(source)
    window = MainWindow()

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(source), "PDF 文件 (*.pdf)"),
    )
    window.findChild(QPushButton, "addFileButton").click()
    application.processEvents()

    assert window.findChild(QLabel, "sourceFileLabel").text() == source.name
    assert window.findChild(QSpinBox, "endPageSpinBox").maximum() == 3

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(output_dir),
    )
    window.findChild(QPushButton, "chooseOutputButton").click()
    application.processEvents()

    assert window.findChild(QPushButton, "processButton").isEnabled()
    window.close()
