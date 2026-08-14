# Vvvvvhhhhh-21321 开发工具

这是一个 Windows 工具集合仓库。每个工具拥有独立目录、说明、源码和版本节奏，互不混用测试数据、运行输出或发布文件。

## 工具清单

- [Word 批量处理](tools/word-batch-processing/README.md)：面向 Windows 桌面版 Microsoft Word 的本地批量文档处理工具，当前版本 `2.0.1`。

## 目录结构

```text
tools/
└─ word-batch-processing/
   ├─ README.md
   └─ source/
```

新增工具时，请在 `tools/` 下建立独立目录，并将该工具的使用说明放在自己的 `README.md` 中，源码放在自己的 `source/` 目录中。

## 发布约定

- 每个工具独立提交源码和使用说明。
- 可执行文件、安装包和校验文件通过对应工具的 GitHub Release 发布。
- 不提交客户文件、项目底稿、测试样本、运行输出、凭据或其他敏感业务资料。
