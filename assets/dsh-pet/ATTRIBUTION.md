# 当前桌宠素材：dsh-pet 女仆鲸鱼娘（非商业）

**本素材包不可用于商业用途，也不能因为项目代码采用 MIT 就把角色或动画当成 MIT 素材。**

## 作者与许可

- 动画来源与项目作者：[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，Copyright © 2026 PC2005-cloud。
- 固定来源提交：[`86181ce1660a57ab27336630bab5b344de71b28c`](https://github.com/PC2005-cloud/dsh-pet/tree/86181ce1660a57ab27336630bab5b344de71b28c)。
- 角色原型「溟月」作者：[上善无形](https://space.bilibili.com/4456176)。
- DeepSeek 女仆鲸鱼娘二次设计：[ZipZipPipe](https://space.bilibili.com/4168597)。
- 上游声明：动画等素材允许开源使用、禁止商用；公开衍生作品须注明上游 GitHub 地址。原文保留于 [UPSTREAM-NOTICE.md](./UPSTREAM-NOTICE.md)。
- 角色及本包转换后的美术素材遵守 **[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)**：署名、非商业、相同方式共享；不对这些素材施加额外限制或技术保护。完整文本见 [CC-BY-NC-SA-4.0.txt](./CC-BY-NC-SA-4.0.txt)（SPDX 文本镜像，官方条文链接见协议）。
- 上游代码为 MIT，保留全文于 [UPSTREAM-MIT.txt](./UPSTREAM-MIT.txt)。本次只选用其动画资源，不搬其 Electron / DSH 插件代码；此 MIT 许可不覆盖角色美术，也不自动改变 Polaris 其余代码的许可。
- 非 DeepSeek 官方形象，不表示得到官方或上述作者背书。素材原样提供，不保证无第三方权利主张；不授予商标权。免责声明见所附协议。

## 采用的十段动作

| 本地文件 | 原始视频（`dsh-pet/assets/webm/`） | 截取区间 |
| --- | --- | --- |
| `idle.webp` | 待机呼吸休闲.webm | 0–10 秒 |
| `wave.webp` | 点击回应-元气挥手.webm | 1.3–3.8 秒 |
| `drowsy.webp` | 哈欠连天.webm | 0.7–3.9 秒 |
| `sleep.webp` | 原地小憩沉眠.webm | 2.5–8.5 秒 |
| `wake.webp` | 打瞌睡被惊醒.webm | 4–6.2 秒 |
| `drag.webp` | 被鼠标拖拽悬空反馈.webm | 1–5 秒 |
| `complete.webp` | 工作状态-雀跃庆祝.webm | 1.5–4.5 秒 |
| `stretch.webp` | 超大伸懒腰.webm | 1–8 秒 |
| `puzzle.webp` | 原地专心玩魔方.webm | 0–8 秒 |
| `glance.webp` | 东张西望.webm | 0–5 秒 |

## 修改与复现

使用 FFmpeg 的 `libvpx-vp9` 解码原始 VP9-alpha（不是带绿底的 GIF 预览），
按上述区间截取、降低到 6–12 fps，使用全部选定动作共有的 alpha 包围框裁剪，
等比缩放并透明填充到 256×256，再以 `libwebp_anim` 编码为循环透明 WebP，无音轨。
`poster.webp` 是待机第一帧；拖拽倾斜与落定回弹由 Polaris 在运行时叠加。
没有改画角色，也没有重新生成服装。此前原视频的生成、抠像与编码属于上游的既有处理。

转换脚本为 `tools/import_dsh_pet.py`；固定提交、原视频与输出的 SHA-256、截取区间、
帧数、实际时长和共同裁剪位置见 [SOURCES.json](./SOURCES.json)。
转换后的素材仍以 CC BY-NC-SA 4.0 提供，后续分享须继续保留作者、来源、修改说明和相同许可。
FFmpeg 仅用于构建，不随运行程序加载；运行使用 Qt 自带的 AnimatedImage/WebP 解码器。
