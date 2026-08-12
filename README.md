# 披露 PDF 缩放工具

当前版本完成工单 01：选择一份 PDF、指定一个连续页码范围，并把 2 至 9 页直接拼排到一张 A4 纵向 PDF 中。源文件不会被修改；目标位置已有同名结果时会自动使用递增序号。

## 本地运行

```powershell
D:\anaconda\python.exe -m venv .venv --system-site-packages
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m disclosure_pdf_scaler
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m mypy
```
