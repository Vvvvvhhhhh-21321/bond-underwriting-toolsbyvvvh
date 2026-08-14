# 底稿 PDF 缩放打印工具

版本 1.0.2 支持批量添加 PDF、递归文件夹和拖放，为每份文件单独指定页码，并按 1、2、4、6、9 页版式自动拼排。所有处理在本机离线完成，源文件不会被修改。

## 本地运行

在 `source/` 目录中执行：

```powershell
D:\anaconda\python.exe -m venv .venv --system-site-packages
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m disclosure_pdf_scaler
```

构建安装包前安装构建依赖，并将官方 Inno Setup 编译器放在 `source/tools/inno/`：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
```

构建 Windows 应用和安装包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

构建产物不提交到仓库；正式安装包通过 GitHub Releases 发布。
