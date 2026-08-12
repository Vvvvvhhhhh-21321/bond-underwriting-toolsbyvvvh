from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfReader
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from disclosure_pdf_scaler.batch import BatchRequest, FileRequest, process_batch


class MainWindow(QMainWindow):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self._source: Path | None = None
        self._output_dir: Path | None = None
        self.setWindowTitle("披露PDF缩放工具")
        self.resize(640, 360)
        self.setCentralWidget(self._build_content())

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        title = QLabel("披露 PDF 缩放工具")
        title.setStyleSheet("font-size: 24px; font-weight: 600;")
        layout.addWidget(title)

        description = QLabel("选择一份 PDF 和参与缩放的连续页码，生成 A4 纵向拼版文件。")
        description.setWordWrap(True)
        layout.addWidget(description)

        file_row = QHBoxLayout()
        add_file = QPushButton("选择 PDF")
        add_file.setObjectName("addFileButton")
        add_file.clicked.connect(self._choose_pdf)
        file_row.addWidget(add_file)
        source_label = QLabel("尚未选择文件")
        source_label.setObjectName("sourceFileLabel")
        source_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        file_row.addWidget(source_label, 1)
        layout.addLayout(file_row)

        pages_form = QFormLayout()
        page_row = QHBoxLayout()
        start_page = QSpinBox()
        start_page.setObjectName("startPageSpinBox")
        start_page.setRange(1, 1)
        end_page = QSpinBox()
        end_page.setObjectName("endPageSpinBox")
        end_page.setRange(1, 1)
        page_row.addWidget(start_page)
        page_row.addWidget(QLabel("至"))
        page_row.addWidget(end_page)
        page_row.addStretch()
        pages_form.addRow("参与缩放的页面", page_row)
        layout.addLayout(pages_form)

        output_row = QHBoxLayout()
        choose_output = QPushButton("选择输出位置")
        choose_output.setObjectName("chooseOutputButton")
        choose_output.clicked.connect(self._choose_output)
        output_row.addWidget(choose_output)
        output_label = QLabel("尚未选择输出位置")
        output_label.setObjectName("outputDirectoryLabel")
        output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_row.addWidget(output_label, 1)
        layout.addLayout(output_row)

        process_button = QPushButton("开始处理")
        process_button.setObjectName("processButton")
        process_button.setEnabled(False)
        process_button.clicked.connect(self._process)
        process_button.setMinimumHeight(40)
        layout.addWidget(process_button)
        layout.addStretch()
        return content

    def _choose_pdf(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "选择 PDF",
            "",
            "PDF 文件 (*.pdf)",
        )
        if not selected:
            return
        source = Path(selected)
        try:
            page_count = len(PdfReader(source).pages)
        except Exception as error:
            QMessageBox.warning(self, "无法读取 PDF", str(error))
            return
        if page_count == 0:
            QMessageBox.warning(self, "无法读取 PDF", "PDF 中没有页面。")
            return

        self._source = source
        self.findChild(QLabel, "sourceFileLabel").setText(source.name)
        start = self.findChild(QSpinBox, "startPageSpinBox")
        end = self.findChild(QSpinBox, "endPageSpinBox")
        start.setRange(1, page_count)
        end.setRange(1, page_count)
        start.setValue(1)
        end.setValue(min(page_count, 9))
        self._refresh_process_button()

    def _choose_output(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择输出位置")
        if not selected:
            return
        self._output_dir = Path(selected)
        self.findChild(QLabel, "outputDirectoryLabel").setText(selected)
        self._refresh_process_button()

    def _refresh_process_button(self) -> None:
        button = self.findChild(QPushButton, "processButton")
        button.setEnabled(self._source is not None and self._output_dir is not None)

    def _process(self) -> None:
        if self._source is None or self._output_dir is None:
            return
        start = self.findChild(QSpinBox, "startPageSpinBox").value()
        end = self.findChild(QSpinBox, "endPageSpinBox").value()
        if start > end:
            QMessageBox.warning(self, "页码无效", "起始页不能大于结束页。")
            return

        result = process_batch(
            BatchRequest(
                files=(
                    FileRequest(
                        source=self._source,
                        pages=tuple(range(start, end + 1)),
                    ),
                ),
                output_dir=self._output_dir,
            )
        )
        file_result = result.files[0]
        if file_result.succeeded:
            QMessageBox.information(self, "处理完成", f"已生成：{file_result.output}")
        else:
            QMessageBox.warning(self, "处理失败", file_result.error or "未知错误")


def main() -> int:
    application = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return int(application.exec())


if __name__ == "__main__":
    raise SystemExit(main())
