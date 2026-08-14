# Word 批量处理

面向 Windows 桌面版 Microsoft Word 的本地批量文档工具。新版使用 PySide6 界面和独立 Word 工作进程，可在不接管、不关闭用户现有 Word 的情况下处理当前文档批次。

## 主要功能

- 内容替换：递归处理 `.doc`、`.docx` 的正文、表格、页眉页脚及可访问文本框；修订模式默认开启。
- 文件名替换：只更改当前工作副本中的 `.doc`、`.docx` 文件名，并预检冲突。
- 内容查找：只读搜索当前批次，不产生撤销点。
- 文档清洁：三个相互独立的任务——接受全部修订、删除全部批注、只更新目录页码。
- 批次安全：首次导入把原文件夹改名为“原名称_备份”，随后在原路径完整复制同名工作文件夹；重复导入当前工作文件夹会保存带时间后缀的阶段稿。
- 任务恢复：保存当前工作文件夹、备份文件夹和最近一次有效撤销点。
- 部分成功：单文件失败不会中断整批，可取消、只重试失败项，并撤销最近一次修改任务。

## 安全边界

- 界面进程不直接连接 Word；工作进程使用 `DispatchEx` 创建并记录自己的隐藏实例。
- 宏在打开文档前被强制禁用；`.docm`、`.dot`、`.dotm`、`.dotx` 不进入 Word 处理队列。
- 密码、限制编辑、信息权限、数字签名、正在使用或无法安全保存的文件会被跳过。
- 每份文件先在同目录临时副本中处理，保存成功后才替换工作副本。
- 软件只退出或终止由它创建且 PID/创建时间均匹配的 Word 实例；不按进程名清理 Word。
- `Normal.dotm` 不保存，关闭时显式走不保存模板改动路径。

## 运行

要求：Windows、桌面版 Microsoft Word、Python 3.11+。

```powershell
D:\anaconda\python.exe -m pip install -r source\requirements.txt
D:\anaconda\python.exe source\batch_word_replace.py
```

启动后先点“导入新批次”，之后三个标签始终作用于顶部显示的同一工作文件夹，无需重复选择文件。

## 安装版

Windows 11 已完成当前用户安装、启动、真实 Word 处理和卸载验收。安装包通过本仓库的 GitHub Releases 提供，当前版本为 `2.0.1`。

安装不需要管理员权限；默认安装到当前用户目录，并创建“Word 批量处理”开始菜单项。卸载默认保留批次状态，且始终不会删除业务备份、阶段稿或工作文件夹。

安装包尚未使用商业代码签名证书签名，因此 Windows 可能显示“未知发布者”。

## 结构

```text
source/batch_word_replace.py                    PySide6 启动入口
source/word_batch_processing/app.py             界面和后台任务编排
source/word_batch_processing/batch.py           批次导入、备份、恢复
source/word_batch_processing/processor.py       统一处理接口、重试、撤销、安全提交
source/word_batch_processing/word_process.py    独立 Word 工作进程
source/packaging/WordBatchProcessing.iss        安装包构建配置
```
