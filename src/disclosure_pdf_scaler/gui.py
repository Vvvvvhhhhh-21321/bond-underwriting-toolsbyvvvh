from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader
from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDropEvent, QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from disclosure_pdf_scaler.batch import (
    BatchRequest,
    BatchResult,
    FileRequest,
    PageSelectionError,
    default_page_hint,
    process_batch,
    resolve_pages,
)
from disclosure_pdf_scaler.files import DiscoveryResult, discover_pdfs, natural_path_key


@dataclass
class FileEntry:
    path: Path
    page_count: int
    row: QWidget
    expression: QLineEdit


class ElidedLabel(QLabel):  # type: ignore[misc]
    def __init__(self, text: str) -> None:
        super().__init__()
        self._full_text = text
        self.setToolTip(text)
        self.setMinimumWidth(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideMiddle, event.size().width()
            )
        )
        super().resizeEvent(event)


class BatchWorker(QObject):  # type: ignore[misc]
    progress = Signal(int, int, str)
    finished = Signal(object)

    def __init__(self, request: BatchRequest) -> None:
        super().__init__()
        self._request = request

    def run(self) -> None:
        result = process_batch(self._request, self.progress.emit)
        self.finished.emit(result)


class MainWindow(QMainWindow):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[FileEntry] = []
        self._output_root: Path | None = None
        self._processing = False
        self._worker: BatchWorker | None = None
        self._worker_thread: QThread | None = None
        self.setWindowTitle("披露PDF缩放工具")
        self.resize(900, 650)
        self.setMinimumSize(720, 520)
        self.setAcceptDrops(True)
        icon = Path(__file__).with_name("assets") / "app.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        self.setCentralWidget(self._build_content())
        self.setStyleSheet(STYLESHEET)

    def _build_content(self) -> QWidget:
        content = QWidget()
        content.setObjectName("canvas")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(44, 34, 44, 32)
        layout.setSpacing(18)

        eyebrow = QLabel("披露文件工作台")
        eyebrow.setObjectName("eyebrow")
        layout.addWidget(eyebrow)
        title = QLabel("让厚重的披露文件，\n落在更少的纸张上。")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("原生 PDF 拼版 · 文字保持可搜索 · 全程本地处理")
        subtitle.setObjectName("subtitle")
        layout.addWidget(subtitle)

        toolbar = QHBoxLayout()
        add_files = QPushButton("＋  添加文件")
        add_files.setObjectName("addFileButton")
        add_files.clicked.connect(self._choose_files)
        add_folder = QPushButton("添加文件夹")
        add_folder.setObjectName("addFolderButton")
        add_folder.clicked.connect(self._choose_folder)
        clear = QPushButton("清空列表")
        clear.setObjectName("clearButton")
        clear.clicked.connect(self._clear_with_confirmation)
        toolbar.addWidget(add_files)
        toolbar.addWidget(add_folder)
        toolbar.addStretch()
        toolbar.addWidget(clear)
        layout.addLayout(toolbar)

        self._empty_state = QFrame()
        self._empty_state.setObjectName("dropZone")
        empty_layout = QVBoxLayout(self._empty_state)
        empty_layout.setContentsMargins(24, 36, 24, 36)
        glyph = QLabel("▦")
        glyph.setObjectName("dropGlyph")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(glyph)
        hint = QLabel("将 PDF 或文件夹拖到这里")
        hint.setObjectName("dropTitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(hint)
        small = QLabel("支持递归读取子文件夹")
        small.setObjectName("dropHint")
        small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(small)
        layout.addWidget(self._empty_state, 1)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("fileScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_content = QWidget()
        self._list_layout = QVBoxLayout(self._list_content)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_content)
        self._scroll.hide()
        layout.addWidget(self._scroll, 1)

        options = QHBoxLayout()
        remove_last = QCheckBox("默认去除最后一页")
        remove_last.setObjectName("removeLastCheckBox")
        remove_last.setChecked(True)
        remove_last.toggled.connect(self._update_hints)
        options.addWidget(remove_last)
        options.addStretch()
        layout.addLayout(options)

        footer = QFrame()
        footer.setObjectName("footerCard")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(18, 15, 18, 15)
        output_row = QHBoxLayout()
        choose_output = QPushButton("选择输出位置")
        choose_output.setObjectName("chooseOutputButton")
        choose_output.clicked.connect(self._choose_output)
        self._output_label = QLabel("每次处理前请选择输出位置")
        self._output_label.setObjectName("outputDirectoryLabel")
        output_row.addWidget(choose_output)
        output_row.addWidget(self._output_label, 1)
        self._process_button = QPushButton("开始处理")
        self._process_button.setObjectName("processButton")
        self._process_button.clicked.connect(self._process)
        output_row.addWidget(self._process_button)
        footer_layout.addLayout(output_row)
        self._progress = QProgressBar()
        self._progress.setObjectName("progressBar")
        self._progress.setTextVisible(False)
        self._progress.hide()
        footer_layout.addWidget(self._progress)
        self._status = QLabel("")
        self._status.setObjectName("statusLabel")
        self._status.hide()
        footer_layout.addWidget(self._status)
        layout.addWidget(footer)
        self._refresh_process_button()
        return content

    def _choose_files(self) -> None:
        selected, _ = QFileDialog.getOpenFileNames(self, "添加 PDF", "", "PDF 文件 (*.pdf)")
        self.add_inputs(tuple(Path(path) for path in selected))

    def _choose_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "添加文件夹")
        if selected:
            self.add_inputs((Path(selected),))

    def add_inputs(self, inputs: tuple[Path, ...]) -> DiscoveryResult:
        discovered = discover_pdfs(inputs)
        existing_paths = {str(entry.path).casefold() for entry in self.entries}
        existing_names = {entry.path.name.casefold() for entry in self.entries}
        repeated_paths = 0
        repeated_names: list[str] = []
        for path in discovered.files:
            if str(path).casefold() in existing_paths:
                repeated_paths += 1
                continue
            if path.name.casefold() in existing_names:
                repeated_names.append(path.name)
                continue
            try:
                reader = PdfReader(path)
                if reader.is_encrypted:
                    raise PageSelectionError("PDF 受密码保护")
                page_count = len(reader.pages)
            except Exception:
                page_count = 0
            self._add_entry(path, page_count)
            existing_paths.add(str(path).casefold())
            existing_names.add(path.name.casefold())
        self.entries.sort(key=lambda entry: natural_path_key(entry.path))
        self._rebuild_rows()
        notices: list[str] = []
        if discovered.ignored_non_pdf:
            notices.append(f"已忽略 {discovered.ignored_non_pdf} 个非 PDF 文件")
        duplicate_path_count = discovered.duplicate_paths + repeated_paths
        if duplicate_path_count:
            notices.append(f"已忽略 {duplicate_path_count} 个重复文件")
        duplicate_names = (*discovered.duplicate_names, *repeated_names)
        if duplicate_names:
            notices.append("已忽略同名文件：" + "、".join(duplicate_names))
        if notices:
            QMessageBox.information(self, "已完成添加", "\n".join(notices))
        return discovered

    def _add_entry(self, path: Path, page_count: int) -> None:
        row = QFrame()
        row.setObjectName("fileRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 12, 12, 12)
        name = ElidedLabel(path.name)
        name.setObjectName("fileName")
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        expression = QLineEdit()
        expression.setObjectName("pageExpressionEdit")
        expression.setFixedWidth(190)
        expression.setPlaceholderText(default_page_hint(page_count, self._remove_last()) if page_count else "无法读取")
        expression.textChanged.connect(self._validate_entries)
        remove = QPushButton("移除")
        remove.setProperty("kind", "quiet")
        remove.clicked.connect(lambda: self.remove_file(path))
        row_layout.addWidget(name, 1)
        row_layout.addWidget(expression)
        row_layout.addWidget(remove)
        self.entries.append(FileEntry(path, page_count, row, expression))

    def _rebuild_rows(self) -> None:
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        for entry in self.entries:
            self._list_layout.insertWidget(self._list_layout.count() - 1, entry.row)
        has_files = bool(self.entries)
        self._empty_state.setVisible(not has_files)
        self._scroll.setVisible(has_files)
        self._validate_entries()

    def remove_file(self, path: Path) -> None:
        self.entries = [entry for entry in self.entries if entry.path != path]
        self._rebuild_rows()

    def clear_files(self) -> None:
        self.entries.clear()
        self._rebuild_rows()

    def _clear_with_confirmation(self) -> None:
        if self.entries and QMessageBox.question(self, "清空列表", "确定移除全部文件吗？") == QMessageBox.StandardButton.Yes:
            self.clear_files()

    def _remove_last(self) -> bool:
        checkbox = self.findChild(QCheckBox, "removeLastCheckBox")
        return bool(checkbox.isChecked())

    def _update_hints(self) -> None:
        for entry in self.entries:
            if not entry.expression.text().strip() and entry.page_count:
                entry.expression.setPlaceholderText(default_page_hint(entry.page_count, self._remove_last()))
        self._validate_entries()

    def _validate_entries(self) -> None:
        valid_count = 0
        for entry in self.entries:
            try:
                resolve_pages(entry.expression.text(), entry.page_count, self._remove_last())
            except PageSelectionError as error:
                entry.expression.setProperty("invalid", True)
                entry.expression.setToolTip(str(error))
            else:
                entry.expression.setProperty("invalid", False)
                entry.expression.setToolTip("")
                valid_count += 1
            entry.expression.style().unpolish(entry.expression)
            entry.expression.style().polish(entry.expression)
        self._valid_count = valid_count
        self._refresh_process_button()

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输出位置")
        if selected:
            candidate = Path(selected)
            try:
                with NamedTemporaryFile(dir=candidate):
                    pass
            except OSError:
                self._output_root = None
                self._output_label.setText("输出位置不可写，请重新选择")
                QMessageBox.warning(self, "无法使用输出位置", "所选位置不可写，请重新选择")
            else:
                self._output_root = candidate
                self._output_label.setText(selected)
        self._refresh_process_button()

    def _refresh_process_button(self) -> None:
        if not hasattr(self, "_process_button"):
            return
        self._process_button.setEnabled(
            not self._processing and self._output_root is not None and getattr(self, "_valid_count", 0) > 0
        )

    def _process(self) -> None:
        if self._output_root is None:
            return
        requests = tuple(
            FileRequest(entry.path, page_expression=entry.expression.text(), remove_last=self._remove_last())
            for entry in self.entries
        )
        self._processing = True
        self._progress.setRange(0, len(requests))
        self._progress.show()
        self._status.show()
        self._status.setText("正在准备处理…")
        self._refresh_process_button()

        thread = QThread(self)
        worker = BatchWorker(BatchRequest(requests, self._output_root, True))
        self._worker_thread = thread
        self._worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._report_progress)
        worker.finished.connect(self._finish_processing)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._release_worker)
        thread.start()

    def _report_progress(self, done: int, total: int, name: str) -> None:
        self._progress.setMaximum(total)
        self._progress.setValue(done)
        self._status.setText(f"正在处理：{name}（{done}/{total}）")

    def _finish_processing(self, result: BatchResult) -> None:
        self._processing = False
        self._output_root = None
        self._output_label.setText("每次处理前请选择输出位置")
        self._status.setText("处理完成")
        self._refresh_process_button()
        problems = [item for item in result.files if not item.succeeded]
        if problems:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setWindowTitle("处理完成")
            dialog.setText(f"处理完成，但有 {len(problems)} 个文件未处理")
            dialog.setDetailedText("\n".join(f"{p.source.name}：{p.error}" for p in problems))
            dialog.exec()
        else:
            QMessageBox.information(self, "处理完成", "处理完成")

    def _release_worker(self) -> None:
        self._worker = None
        self._worker_thread = None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        self.add_inputs(tuple(Path(url.toLocalFile()) for url in event.mimeData().urls()))
        event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._processing:
            QMessageBox.information(self, "正在处理", "正在处理，请等待完成。")
            event.ignore()
        else:
            event.accept()


STYLESHEET = """
QWidget#canvas { background: #F6F7F9; color: #172033; font-family: "Segoe UI Variable", "Microsoft YaHei UI"; }
QLabel#eyebrow { color: #2F6BFF; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#title { color: #111827; font-size: 30px; font-weight: 700; line-height: 1.2; }
QLabel#subtitle, QLabel#dropHint, QLabel#outputDirectoryLabel, QLabel#statusLabel { color: #7A8496; font-size: 12px; }
QFrame#dropZone { background: #FFFFFF; border: 1px dashed #C9D2E3; border-radius: 18px; }
QLabel#dropGlyph { color: #2F6BFF; font-size: 34px; }
QLabel#dropTitle { color: #263246; font-size: 15px; font-weight: 600; }
QFrame#fileRow, QFrame#footerCard { background: #FFFFFF; border: 1px solid #E7EAF0; border-radius: 12px; }
QLabel#fileName { font-size: 13px; font-weight: 600; color: #263246; }
QPushButton { background: #FFFFFF; color: #263246; border: 1px solid #DDE2EA; border-radius: 9px; padding: 8px 14px; font-weight: 600; }
QPushButton:hover { background: #F1F5FF; border-color: #AFC3FF; }
QPushButton:disabled { color: #A6ADBA; background: #F0F2F5; border-color: #E5E7EB; }
QPushButton#processButton { background: #2F6BFF; color: white; border: none; padding: 10px 18px; }
QPushButton#processButton:hover { background: #2158DE; }
QPushButton[kind="quiet"] { border: none; color: #7A8496; background: transparent; }
QLineEdit { background: #F8FAFC; border: 1px solid #DDE2EA; border-radius: 8px; padding: 8px 10px; }
QLineEdit:focus { border: 1px solid #2F6BFF; background: white; }
QLineEdit[invalid="true"] { border: 1px solid #E5484D; background: #FFF7F7; }
QCheckBox { spacing: 8px; color: #4B5565; }
QProgressBar { height: 5px; border: none; background: #E9EDF4; border-radius: 2px; }
QProgressBar::chunk { background: #2F6BFF; border-radius: 2px; }
QScrollArea { background: transparent; }
"""


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("披露PDF缩放工具")
    window = MainWindow()
    window.show()
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(main())
