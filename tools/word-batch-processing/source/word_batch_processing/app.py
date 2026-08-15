from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QApplication,
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
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .batch import BatchLifecycle, BatchState, BatchStateStore
from .models import OperationPreview, OperationResult, OperationStatus
from .processor import DocumentBatchProcessor
from .word_process import IsolatedWordProcessAdapter


class _TaskSignals(QObject):
    progress = Signal(str, int, int, object)
    finished = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, function: Callable[[], object]):
        super().__init__()
        self.function = function
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            self.signals.finished.emit(self.function())
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class WordBatchWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        app_data = Path(os.getenv("LOCALAPPDATA", Path.home())) / "WordBatchProcessing"
        self.lifecycle = BatchLifecycle(BatchStateStore(app_data / "batch-state.json"))
        self.checkpoint = app_data / "checkpoint"
        self.word = IsolatedWordProcessAdapter()
        self.processor: DocumentBatchProcessor | None = None
        self.state: BatchState | None = None
        self.pool = QThreadPool.globalInstance()
        self._task: _Task | None = None
        self._busy = False
        self._operation_buttons: list[QPushButton] = []

        self.setWindowTitle("Word 批量处理")
        self.resize(800, 620)
        self.setMinimumSize(660, 520)
        self._build_ui()
        self._apply_style()
        saved_state = self.lifecycle.store.load()
        resumed_state = self.lifecycle.resume()
        self._set_state(resumed_state)
        if saved_state is not None and resumed_state is None:
            self.status_label.setText("上次批次路径已不存在，请重新导入正确的工作文件夹。")

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)
        self.setCentralWidget(central)

        heading = QLabel("Word 批量处理")
        heading.setObjectName("heading")
        subtitle = QLabel("在独立 Word 进程中安全处理当前文档批次")
        subtitle.setObjectName("subtitle")
        root.addWidget(heading)
        root.addWidget(subtitle)

        self.batch_card = QFrame()
        self.batch_card.setObjectName("batchCard")
        batch_layout = QVBoxLayout(self.batch_card)
        batch_layout.setContentsMargins(16, 13, 16, 13)
        batch_layout.setSpacing(7)
        row = QHBoxLayout()
        batch_title = QLabel("当前批次")
        batch_title.setObjectName("cardTitle")
        row.addWidget(batch_title)
        row.addStretch()
        self.undo_button = QPushButton("撤销上一步")
        self.undo_button.setObjectName("secondaryButton")
        self.undo_button.clicked.connect(self._undo)
        self.import_button = QPushButton("导入新批次")
        self.import_button.clicked.connect(self._import_batch)
        row.addWidget(self.undo_button)
        row.addWidget(self.import_button)
        batch_layout.addLayout(row)
        self.workspace_label = self._path_label()
        self.backup_label = self._path_label()
        self.count_label = QLabel()
        self.count_label.setObjectName("muted")
        batch_layout.addWidget(self.workspace_label)
        batch_layout.addWidget(self.backup_label)
        batch_layout.addWidget(self.count_label)
        root.addWidget(self.batch_card)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._replace_tab(), "内容替换")
        self.tabs.addTab(self._clean_tab(), "文档清洁")
        self.tabs.addTab(self._search_tab(), "内容查找")
        root.addWidget(self.tabs, 1)

        status_row = QHBoxLayout()
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        status_row.addWidget(self.status_label, 1)
        self.retry_button = QPushButton("重试失败项")
        self.retry_button.setObjectName("secondaryButton")
        self.retry_button.clicked.connect(self._retry)
        self.retry_button.hide()
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        status_row.addWidget(self.retry_button)
        status_row.addWidget(self.cancel_button)
        root.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        self.progress.hide()
        root.addWidget(self.progress)

    def _replace_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 16, 4, 8)
        layout.setSpacing(14)

        replace_card, body = self._card(
            "替换文档内容", "覆盖正文、表格、页眉页脚和可访问文本框，可连续执行多次。"
        )
        self.find_edit = self._field(body, "查找内容")
        self.replace_edit = self._field(body, "替换为")
        self.track_changes = QPushButton()
        self.track_changes.setObjectName("revisionToggle")
        self.track_changes.setCheckable(True)
        self.track_changes.setChecked(True)
        self.track_changes.toggled.connect(self._update_revision_toggle)
        self._update_revision_toggle(True)
        body.addWidget(self.track_changes)
        replace_button = QPushButton("开始替换")
        replace_button.clicked.connect(self._replace_content)
        self._operation_buttons.append(replace_button)
        body.addWidget(replace_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(replace_card)

        rename_card, rename_body = self._card(
            "替换文件名", "只更改当前工作文件夹中的 .doc 和 .docx 文件名。"
        )
        self.filename_find_edit = self._field(rename_body, "文件名中查找")
        self.filename_replace_edit = self._field(rename_body, "替换为")
        rename_button = QPushButton("替换文件名")
        rename_button.clicked.connect(self._rename_files)
        self._operation_buttons.append(rename_button)
        rename_body.addWidget(rename_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(rename_card)
        layout.addStretch()
        return self._scroll(content)

    def _clean_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 16, 4, 8)
        layout.setSpacing(12)
        actions = (
            (
                "接受全部修订",
                "接受所有故事范围中的修订，并关闭结果文档的修订模式。",
                self._accept_revisions,
            ),
            (
                "删除全部批注",
                "删除普通批注、已解决批注及其回复，不改变正文和修订。",
                self._delete_comments,
            ),
            (
                "更新目录页码",
                "更新每份文档中所有目录的页码，不更新目录文字或层级。",
                self._update_toc,
            ),
        )
        for title, description, handler in actions:
            card, body = self._card(title, description)
            button = QPushButton(title)
            button.clicked.connect(handler)
            self._operation_buttons.append(button)
            body.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(card)
        layout.addStretch()
        return self._scroll(content)

    def _search_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 16, 4, 8)
        card, body = self._card(
            "查找文档内容", "仅搜索当前工作文件夹；查找不会修改文件或覆盖撤销点。"
        )
        self.search_edit = self._field(body, "查找内容")
        search_button = QPushButton("开始查找")
        search_button.clicked.connect(self._search)
        self._operation_buttons.append(search_button)
        body.addWidget(search_button, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(card)
        self.search_results = QTextBrowser()
        self.search_results.setPlaceholderText("命中文件将显示在这里")
        self.search_results.setMinimumHeight(150)
        layout.addWidget(self.search_results, 1)
        return self._scroll(content)

    def _card(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 15, 18, 15)
        body.setSpacing(9)
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        description_label = QLabel(description)
        description_label.setObjectName("muted")
        description_label.setWordWrap(True)
        body.addWidget(title_label)
        body.addWidget(description_label)
        return card, body

    def _field(self, layout: QVBoxLayout, label: str) -> QLineEdit:
        caption = QLabel(label)
        caption.setObjectName("fieldLabel")
        edit = QLineEdit()
        edit.setClearButtonEnabled(True)
        layout.addWidget(caption)
        layout.addWidget(edit)
        return edit

    def _path_label(self) -> QLabel:
        label = QLabel()
        label.setObjectName("pathLabel")
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _set_state(self, state: BatchState | None) -> None:
        self.state = state
        if state is None:
            self.workspace_label.setText("工作文件夹：尚未导入")
            self.backup_label.setText("备份文件夹：—")
            self.count_label.setText("请先导入一个本地文件夹")
            self.processor = None
        else:
            self.workspace_label.setText(f"工作文件夹：{state.workspace}")
            self.backup_label.setText(f"备份文件夹：{state.backup}")
            self.count_label.setText(f"Word 文件：{state.word_file_count} 个")
            self.processor = DocumentBatchProcessor(
                state.workspace,
                self.word,
                checkpoint_root=self.checkpoint,
                batch_id=state.batch_id or None,
            )
        self.tabs.setEnabled(True)
        for button in self._operation_buttons:
            button.setEnabled(state is not None)
        self.undo_button.setEnabled(
            self.processor is not None and self.processor.can_undo
        )

    def _import_batch(self) -> None:
        answer = QMessageBox.question(
            self,
            "导入新批次",
            "导入会把所选文件夹重命名为备份，再在原路径建立工作文件夹。\n\n"
            "请先保存并关闭该文件夹中的全部文件；其他 Word 文档无需关闭。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择要导入的本地文件夹")
        if folder:
            self._run_task(
                "正在建立安全备份…",
                lambda: self.lifecycle.import_folder(folder),
                self._on_batch_imported,
            )

    def _on_batch_imported(self, value: object) -> None:
        assert isinstance(value, BatchState)
        self._set_state(value)
        assert self.processor is not None
        self.processor.reset_undo_history()
        self.status_label.setText("新批次已导入，可以开始处理。")

    def _replace_content(self) -> None:
        if not self._require_text(self.find_edit, "请输入要查找的内容"):
            return
        assert self.processor is not None
        processor = self.processor
        self._run_operation(
            "正在替换文档内容…",
            lambda: processor.replace_text(
                self.find_edit.text(),
                self.replace_edit.text(),
                self.track_changes.isChecked(),
            ),
        )

    def _rename_files(self) -> None:
        if not self._require_text(self.filename_find_edit, "请输入文件名中的查找内容"):
            return
        assert self.processor is not None
        processor = self.processor
        self._run_operation(
            "正在替换文件名…",
            lambda: processor.rename_files(
                self.filename_find_edit.text(), self.filename_replace_edit.text()
            ),
        )

    def _accept_revisions(self) -> None:
        assert self.processor is not None
        self._preview_then_confirm(
            "接受全部修订",
            "修订",
            self.processor.preview_accept_revisions,
            self.processor.accept_all_revisions,
        )

    def _delete_comments(self) -> None:
        assert self.processor is not None
        self._preview_then_confirm(
            "删除全部批注",
            "批注",
            self.processor.preview_delete_comments,
            self.processor.delete_all_comments,
        )

    def _update_toc(self) -> None:
        assert self.processor is not None
        answer = QMessageBox.question(
            self,
            "更新目录页码",
            "将更新当前批次中所有目录的页码；目录文字和层级不会更新。是否继续？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_operation(
                "正在更新目录页码…", self.processor.update_toc_page_numbers
            )

    def _preview_then_confirm(
        self,
        title: str,
        unit: str,
        preview: Callable[[], OperationPreview],
        operation: Callable[[], OperationResult],
    ) -> None:
        def confirm(value: object) -> None:
            assert isinstance(value, OperationPreview)
            text = (
                f"将影响 {value.affected_files} 份文档，共 {value.affected_items} 项{unit}。"
                "\n是否继续？"
            )
            if QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes:
                self._run_operation(f"正在{title}…", operation)

        self._run_task("正在检查影响范围…", preview, confirm)

    def _search(self) -> None:
        if not self._require_text(self.search_edit, "请输入要查找的内容"):
            return
        assert self.processor is not None
        processor = self.processor
        self.search_results.clear()
        self._run_operation(
            "正在查找文档内容…", lambda: processor.search(self.search_edit.text())
        )

    def _undo(self) -> None:
        assert self.processor is not None
        if QMessageBox.question(
            self, "撤销上一步", "仅能撤销最近一次成功修改。是否继续？"
        ) == QMessageBox.StandardButton.Yes:
            self._run_operation("正在撤销上一步…", self.processor.undo_last)

    def _retry(self) -> None:
        assert self.processor is not None
        self._run_operation("正在重试失败项…", self.processor.retry_last)

    def _cancel(self) -> None:
        if self.processor is not None:
            self.processor.cancel()
            self.status_label.setText("正在安全结束当前文件…")
            self.cancel_button.setEnabled(False)

    def _run_operation(
        self, label: str, function: Callable[[], OperationResult]
    ) -> None:
        self._run_task(label, function, self._show_result, with_progress=True)

    def _run_task(
        self,
        label: str,
        function: Callable[[], object],
        completed: Callable[[Any], None],
        *,
        with_progress: bool = False,
    ) -> None:
        if self._busy:
            return
        self._busy = True
        self.tabs.setEnabled(False)
        self.import_button.setEnabled(False)
        self.undo_button.setEnabled(False)
        self.retry_button.hide()
        self.cancel_button.setVisible(with_progress)
        self.cancel_button.setEnabled(True)
        self.progress.setVisible(with_progress)
        self.progress.setValue(0)
        self.status_label.setText(label)

        task = _Task(function)
        self._task = task
        if self.processor is not None:
            self.processor.progress = task.signals.progress.emit
        task.signals.progress.connect(self._on_progress)

        def finish(value: object) -> None:
            self._finish_task()
            completed(value)

        task.signals.finished.connect(finish)
        task.signals.failed.connect(self._task_failed)
        self.pool.start(task)

    @Slot(str, int, int, object)
    def _on_progress(
        self, path: str, current: int, total: int, result: OperationResult
    ) -> None:
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(current)
        self.status_label.setText(
            f"{path}  ·  {current}/{total}  ·  成功 {result.succeeded}  "
            f"失败 {result.failed}  跳过 {result.skipped}"
        )

    def _finish_task(self) -> None:
        self._busy = False
        self._task = None
        self.tabs.setEnabled(True)
        for button in self._operation_buttons:
            button.setEnabled(self.state is not None)
        self.import_button.setEnabled(True)
        self.cancel_button.hide()
        self.progress.hide()
        self.undo_button.setEnabled(
            self.processor is not None and self.processor.can_undo
        )

    def _task_failed(self, message: str) -> None:
        self._finish_task()
        self.status_label.setText("任务未完成")
        QMessageBox.critical(self, "任务未完成", message)

    def _show_result(self, value: object) -> None:
        assert isinstance(value, OperationResult)
        labels = {
            OperationStatus.COMPLETED: "任务已完成",
            OperationStatus.PARTIAL: "任务部分完成",
            OperationStatus.FAILED: "任务未完成",
            OperationStatus.CANCELLED: "任务已取消",
        }
        self.status_label.setText(
            f"{labels[value.status]} · 成功 {value.succeeded} · "
            f"失败 {value.failed} · 跳过 {value.skipped}"
        )
        self.retry_button.setVisible(value.can_retry)
        self.undo_button.setEnabled(value.can_undo)
        if value.hits:
            self.search_results.setPlainText("\n".join(value.hits))
            self.tabs.setCurrentIndex(2)
        if value.items:
            details = "\n".join(f"{item.path}：{item.reason}" for item in value.items)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(labels[value.status])
            box.setText(f"失败 {value.failed} 项，跳过 {value.skipped} 项。")
            box.setInformativeText("展开“显示详细信息”可查看文件名和原因。")
            box.setDetailedText(details)
            box.exec()
        elif not value.hits and value.status is not OperationStatus.COMPLETED:
            QMessageBox.information(self, labels[value.status], self.status_label.text())

    def _require_text(self, edit: QLineEdit, message: str) -> bool:
        if edit.text():
            return True
        QMessageBox.information(self, "需要输入", message)
        edit.setFocus()
        return False

    def _update_revision_toggle(self, enabled: bool) -> None:
        self.track_changes.setText(
            "修订模式：开启" if enabled else "修订模式：关闭"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy:
            QMessageBox.information(self, "任务进行中", "请先取消或等待当前任务结束。")
            event.ignore()
            return
        self.word.close()
        event.accept()

    def _apply_style(self) -> None:
        self.setFont(QFont("Microsoft YaHei UI", 9))
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f5f5f7; color: #1d1d1f; }
            QLabel#heading { font-size: 24px; font-weight: 650; }
            QLabel#subtitle, QLabel#muted { color: #6e6e73; }
            QLabel#cardTitle { font-size: 14px; font-weight: 650; }
            QLabel#fieldLabel { color: #424245; font-weight: 550; }
            QLabel#pathLabel { color: #424245; }
            QFrame#batchCard { background: #e9f2ff; border: 1px solid #d2e4fa;
                               border-radius: 12px; }
            QFrame#card { background: white; border: 1px solid #e5e5e7;
                          border-radius: 12px; }
            QTabWidget::pane { border: 0; }
            QTabBar::tab { background: transparent; color: #6e6e73; padding: 9px 18px;
                           margin-right: 4px; border-radius: 8px; }
            QTabBar::tab:selected { background: white; color: #1d1d1f; font-weight: 600; }
            QLineEdit, QTextBrowser { background: white; border: 1px solid #d2d2d7;
                                      border-radius: 8px; padding: 8px 10px; }
            QLineEdit:focus, QTextBrowser:focus { border: 1px solid #0071e3; }
            QPushButton { background: #0071e3; color: white; border: 0;
                          border-radius: 8px; padding: 8px 15px; font-weight: 600; }
            QPushButton:hover { background: #0077ed; }
            QPushButton:disabled { background: #d2d2d7; color: #86868b; }
            QPushButton#secondaryButton { background: white; color: #0066cc;
                                          border: 1px solid #d2d2d7; }
            QPushButton#dangerButton { background: #fff; color: #d70015;
                                       border: 1px solid #d2d2d7; }
            QPushButton#revisionToggle { background: white; color: #424245;
                                         border: 1px solid #d2d2d7;
                                         text-align: left; padding: 9px 13px; }
            QPushButton#revisionToggle:checked { background: #e9f2ff;
                                                 color: #0066cc;
                                                 border: 1px solid #8fc2f5; }
            QProgressBar { border: 0; background: #e5e5e7; border-radius: 2px; }
            QProgressBar::chunk { background: #0071e3; border-radius: 2px; }
            QScrollArea { background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            """
        )


def run_app() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Word 批量处理")
    app.setApplicationVersion("2.0.1")
    app.setOrganizationName("WordBatchProcessing")
    window = WordBatchWindow()
    window.show()
    return app.exec()
