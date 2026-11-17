# 扩展市场目录

此目录是可独立发布的源目录：`polaris-source.json` 索引完整的 `packages/` 安装包，展示图标放在 `assets/`，说明放在 `docs/`。用户也可在扩展管理中添加其他 Git 源或本地目录。包代码来源及内容摘要记录在 `provenance.json`。

贡献条目时，先准备能独立安装的组件或应用包，并保留清单及运行所需资源。在索引 `packages` 中填写 `type`、包相对路径 `path`、`summary`、`author`、`icon`；可填写 `tags`、`description`、`readme`、`screenshots` 和 `upstream`。图标、截图及文档路径相对本目录，文件须放在包目录之外。推荐 256×256 的 PNG 或 WebP 图标。ID、名称、版本和入口以包清单为准，组件和应用分别使用 `manifest.json` 与 `polaris-application.json`。

修改包内容时更新包清单版本；仅修改索引、图标或文档不需要改包版本。提交前在仓库根目录运行：

```bash
python tools/validate_marketplace.py --base <目标分支的Git提交>
```

校验会读取目录和清单、检查身份与展示资源，并与明确的基准提交比较包内容及版本。新包无需基准版本。目录整体可以作为独立 Git 仓库发布；本目录不会自动发布或推送。完整协议见 [源格式](SOURCE_FORMAT.md)。
