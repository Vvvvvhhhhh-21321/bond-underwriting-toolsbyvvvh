# 工具目录约定

每个小工具使用一个独立目录：

```text
tools/
└─ <工具名称>/
   ├─ README.md
   └─ source/
```

工具目录中的 `README.md` 至少说明：

- 工具解决的问题和适用场景；
- 使用方法、输入和输出；
- Windows 运行要求；
- 当前版本和已知限制；
- 对应的 GitHub Release。

源码放在 `source/` 中。构建产物、测试输入、运行输出和项目底稿不放入仓库；可执行文件通过 GitHub Releases 发布。
