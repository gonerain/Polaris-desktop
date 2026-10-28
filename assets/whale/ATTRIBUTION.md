# 鲸鱼娘桌宠素材与动画来源

- 作者与版权持有人：**Er1c0v0**。
- 来源：[Er1c0v0/dsh-whale-pet](https://github.com/Er1c0v0/dsh-whale-pet)。
- 本次新增素材固定到提交 [`2e10c80abecfb66e599dac82609295659c3657de`](https://github.com/Er1c0v0/dsh-whale-pet/tree/2e10c80abecfb66e599dac82609295659c3657de)。
- 原图及其处理后衍生帧：**[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)**，完整协议随包附于 [CC-BY-4.0.txt](./CC-BY-4.0.txt)。允许在遵守署名、标明修改等条件下复制、修改和再分发，并非“仅供个人使用”。
- 上游代码与参考动画时序：**MIT**，完整版权声明与许可见 [UPSTREAM-MIT.txt](./UPSTREAM-MIT.txt)。
- 上游的创作说明、原图 SHA-256 和此前处理记录保留于 [UPSTREAM-ARTWORK.md](./UPSTREAM-ARTWORK.md)；仅将其中的协议链接调整为本地位置。

## 使用范围

| 文件 | 用途 |
| --- | --- |
| `idle_pillow_awake.webp` | 原有清醒待机 |
| `idle_pillow_blink.webp` | 原有眨眼、落定反馈 |
| `idle_pillow_wave_1.webp`、`idle_pillow_wave_2.webp` | 原有挥手 |
| `idle_pillow_drowsy.webp` | 新增打盹过渡 |
| `idle_pillow_sleep.webp` | 新增抱枕睡眠 |
| `idle_pillow_startle.webp` | 新增惊醒、拖起表情 |
| `ready_0.webp`、`ready_1.webp`、`ready.webp`、`ready_3.webp`、`ready_4.webp` | 新增完成任务的短促庆祝 |

## 修改与构建说明

此前四帧继续保留。本次八帧从上述固定提交的 `character/*.png` 使用其原有
`scripts/build-assets.mjs`、`assets.config.json` 和 `idle-animation.json` 构建，
保留上游原图哈希校验、背景去除、透明边缘处理、角色尺寸/位置归一化及 WebP 编码。
构建使用 Node 24、sharp 0.34.4、gifenc 1.0.3；它们只是素材构建工具，不是 Polaris 运行依赖。

Polaris 将动画调度改写为 QML：延长安静等待时间、限制重复招呼、暂停隐藏时的动画、
合并短时间内的完成反馈，并在运行时添加轻微呼吸、拖动倾斜及落定形变。
没有重新绘制角色，也没有复制上游的聊天、模型、养成或应用感知系统。

上游注明素材含 AI 辅助生成，鲸鱼抱枕带有 DeepSeek 鲸鱼标志的视觉灵感；详情和此前修改
说明见上游署名文件。CC BY 不授予商标权，本项目不声称得到 DeepSeek 或原作者的官方背书。
素材按协议原样提供，不作额外权利或质量担保。本声明不将素材改授为 MIT。
