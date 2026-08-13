from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)
from pypdf import PdfWriter

from disclosure_pdf_scaler.gui import MainWindow


def _write_source_pdf(path: Path, pages: int = 3) -> None:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=400, height=600)
    with path.open("wb") as output:
        writer.write(output)


def _wait_until(app: QApplication, condition: object, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if callable(condition) and condition():
            return
        time.sleep(0.01)
    raise AssertionError("等待界面状态变化超时")


def test_user_can_add_pdf_and_choose_output_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "披露材料.pdf"
    output_dir = tmp_path / "结果"
    output_dir.mkdir()
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


def test_drop_sort_remove_clear_and_duplicate_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    source10 = tmp_path / "文件10.pdf"
    source2 = tmp_path / "文件2.pdf"
    _write_source_pdf(source10)
    _write_source_pdf(source2)
    notices: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda _parent, _title, text, *args, **kwargs: notices.append(text),
    )
    window = MainWindow()

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(source10)), QUrl.fromLocalFile(str(source2))])

    class Drop:
        def mimeData(self) -> QMimeData:
            return mime

        def acceptProposedAction(self) -> None:
            pass

    window.dropEvent(Drop())
    app.processEvents()
    assert [entry.path.name for entry in window.entries] == ["文件2.pdf", "文件10.pdf"]
    window.add_inputs((source2,))
    assert notices[-1] == "已忽略 1 个重复文件"
    window.remove_file(source2.resolve())
    assert [entry.path.name for entry in window.entries] == ["文件10.pdf"]
    window.clear_files()
    assert window.entries == []
    window.close()


def test_invalid_page_is_marked_and_processing_keeps_list_but_resets_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "披露材料.pdf"
    output_dir = tmp_path / "结果"
    output_dir.mkdir()
    _write_source_pdf(source)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    window = MainWindow()
    window.add_inputs((source,))
    edit = window.findChild(QLineEdit, "pageExpressionEdit")
    edit.setText("9")
    app.processEvents()
    assert edit.property("invalid") is True
    assert edit.toolTip()
    edit.setText("1-2")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(output_dir))
    window.findChild(QPushButton, "chooseOutputButton").click()
    window.findChild(QPushButton, "processButton").click()
    _wait_until(
        app,
        lambda: window.findChild(QLabel, "statusLabel").text() == "处理完成",
    )
    assert len(window.entries) == 1
    assert window.findChild(QLabel, "outputDirectoryLabel").text() == "每次处理前请选择输出位置"
    assert not window.findChild(QPushButton, "processButton").isEnabled()
    window.close()


def test_unwritable_output_and_close_during_processing_are_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    QApplication.instance() or QApplication([])
    source = tmp_path / "披露材料.pdf"
    blocked = tmp_path / "不是目录"
    _write_source_pdf(source)
    blocked.write_text("占用", encoding="utf-8")
    messages: list[str] = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(blocked))
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda _parent, _title, text, *args, **kwargs: messages.append(text),
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    window = MainWindow()
    window.add_inputs((source,))
    window.findChild(QPushButton, "chooseOutputButton").click()
    assert messages and not window.findChild(QPushButton, "processButton").isEnabled()
    window._processing = True
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted()
    window._processing = False
    window.close()


def test_real_pdf_processing_keeps_window_responsive_and_blocks_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "长篇披露材料.pdf"
    output_dir = tmp_path / "结果"
    output_dir.mkdir()
    _write_source_pdf(source, pages=200)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(output_dir))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    window = MainWindow()
    window.show()
    window.add_inputs((source,))
    window.findChild(QPushButton, "chooseOutputButton").click()

    window.findChild(QPushButton, "processButton").click()

    status = window.findChild(QLabel, "statusLabel")
    assert status.text() != "处理完成"
    window.close()
    app.processEvents()
    assert window.isVisible()
    _wait_until(app, lambda: status.text() == "处理完成")
    assert len(window.entries) == 1
    window.close()
