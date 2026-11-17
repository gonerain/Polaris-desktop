# Polaris 扩展源格式

源仓库根目录放置 `polaris-source.json`，并包含每个组件或应用完整的安装目录及其展示资源。支持的 v2 索引如下：

```json
{
  "schemaVersion": 2,
  "name": "示例目录",
  "packages": [
    {"type": "component", "path": "packages/tool", "summary": "文本工具", "author": "示例", "icon": "assets/tool.png", "tags": ["工具"]},
    {"type": "application", "path": "packages/editor", "summary": "文本编辑器", "author": "示例", "icon": "assets/editor.png"}
  ]
}
```

每项必须有 `type`（`component` 或 `application`）、`path`、`summary`、`author`、`icon`。`tags`、`description`、`readme`、`screenshots` 和 `upstream` 可选；标签与截图为字符串数组，其余为字符串。目录与展示资源路径相对源根目录，图标、截图及文档应在包目录外。建议图标使用 256×256 PNG 或 WebP。

组件目录包含 `manifest.json`，应用目录包含 `polaris-application.json`。ID、名称、版本和入口以包清单为准，同类包的 ID 在同一源中唯一。包目录应包括运行所需文件；展示资料单独保存，修改展示资料不会改变包内容摘要。更新包内容时应更新包的版本。

Polaris 也支持旧版 schemaVersion 1 的 `components` 和 `applications` 目录。添加 Git 源时可以指定分支、标签或提交；源的当前快照由用户手动刷新，安装与更新都需要用户选择。
