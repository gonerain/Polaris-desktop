# Polaris 组件平台首版

这里是独立实现的 `polaris_platform`，包含运行管理、协作、授权、可选桌面基础组件，以及便签、标签和计数器三个示例软件。核心运行仅需 Python 3.10+ 标准库。

## 运行

从仓库根目录执行：

```bash
PYTHONPATH=next python -m polaris_platform
PYTHONPATH=next python -m polaris_platform --config next/config.demo.json
PYTHONPATH=next python -m polaris_platform --state-dir /tmp/polaris-platform-demo
PYTHONPATH=next python -m unittest discover -s next/tests -v
```

前三条命令启动所选组件、打印状态，再合作停止并退出；它们不是常驻服务。`config.headless.json` 只装配三个基础组件；`config.demo.json` 另启两个独立进程示例并列出明确授权。

需要桌面时，使用已装有 PySide6-Essentials 的解释器：

```bash
PYTHONPATH=next .venv/bin/python -m polaris_platform --gui --config next/config.demo.json
```

也可在自己的环境安装 `python -m pip install -e './next[desktop]'`，之后使用 `polaris-platform --gui`。不带 `--gui` 时无界面。GUI 默认直接显示透明悬浮桌宠，组件管理默认隐藏，通过桌宠右键菜单的“组件管理”打开；左键打开画布。已有安装保留授权与自启动选择；桌宠或窗口承载已卸载时，显示组件管理作为恢复入口。桌宠已停用或显示权限不足时输出启动失败原因并以非零状态退出。画布收到首次指针进入后，离开会延迟收起并恢复桌宠；重新进入、打开菜单或拖动卡片会暂缓收起。管理窗口提供本地组件加载、生命周期、操作与事件授权、撤销和调用入口，并区分本机请求与后台授权。加载同 ID 目录可确认覆盖安装（适用于从组件目录加载的安装；内置组件由可信装配定义）；卸载移除安装记录，保留源码和组件数据；重新安装不会沿用旧安装授权。基础角色组件和正在运行的管理组件受保护。卸载记录会跨重启保留，已卸载的桌宠或画布不会被 GUI 启动静默装回。通用视图按钮可预览所需权限后显示或隐藏画布、桌宠。画布、桌宠、窗口承载各有独立实例；管理窗口不依赖窗口承载，无界面启动不需要 Qt。GUI 默认把安装身份、组件目录、自启动选择和授权保存在本机用户数据目录；`--state-dir PATH` 可指定位置。headless 默认仅用内存，指定该选项后也会持久化。桌宠拖放位置由桌宠自己的文件保存。画布在自己的组件数据目录保存窗口尺寸、已添加视图及每个实例的位置、尺寸和折叠状态；窗口位置继续使用展开时的锚点。重启后首次指针进入画布时，按当前公开视图声明和已有授权恢复；暂不可用或未获授权的布局保留，显式移除才删除。布局文件损坏时保留原文件并显示错误，不覆盖。无持久目录时布局仅保留在内存。业务数据仍由组件自己保存。

## 本地日程

使用 `PYTHONPATH=next .venv/bin/python -m polaris_platform --gui --config next/config.schedule.json` 启动日程装配。已有应用可在桌宠右键菜单打开“组件管理”，点击“加载组件”，选择 `next/components/schedule` 并启动日程；左键打开画布，在“添加组件”中选择“日程 · 日程”，审阅并确认所列权限即可挂载。任务自动保存在组件自己的用户数据目录，折叠或移除视图后仍然保留。[日程能力与本地数据说明](components/schedule/README.md)。

## 调用示例

下面的授权来自用户选定的配置。普通软件拿到的是绑定实例的 `Client`，不能取得这里的管理对象。

```python
from polaris_platform.bootstrap import from_file

runtime = from_file('next/config.demo.json')
try:
    requester = 'org.example.labeler'
    client = runtime.client(requester)
    context = runtime.user_context(requester)
    note = client.call('org.example.notes', 'create',
                       {'title': 'Reading architecture', 'body': 'Portable components'},
                       context=context)
    result = client.call('org.example.labeler', 'label',
                         {'note_id': note['id']}, context=context)
    print(result)
finally:
    for row in reversed(runtime.snapshot()):
        if row['state'] == 'running':
            runtime.stop_component(row['id'])
```

标签软件通过 `ctx.call` 读取便签，再维护自己的标签。把便签的配置入口改为 `{"mode":"inprocess","factory":"examples.notes.main:create"}`，并使 `next` 在 Python 导入路径中，标签处理器无需改动。示例数据仅保存在各自内存中，停止后丢失。

## 本地软件接入

一个目录包含 `manifest.json` 和入口文件即可。可从管理窗口加载目录，或在可信装配代码中执行 `runtime.install_directory(path)`，再执行 `runtime.start_component(component_id)`。加载不会自动授予业务权限。

```json
{
  "id": "org.example.hello",
  "name": "Hello",
  "version": "0.1.0",
  "platformApi": 1,
  "entry": {"mode": "process", "command": ["{python}", "main.py"]}
}
```

```python
from polaris_platform.sdk import Component

component = Component()

@component.operation('hello', access='read')
def hello(name):
    if not isinstance(name, str):
        raise ValueError('name must be text')
    return {'message': f'Hello, {name}'}

component.run()
```

`{python}` 使用平台当前解释器；命令参数数组直接启动，工作目录为组件目录。SDK 安装到所选解释器，开发时也可使用 `PYTHONPATH=next`。第三方依赖由软件作者自己的运行环境提供。

操作声明支持 `read`、`write`、接口主版本与授权修订号。SDK 接受普通函数；需要协作时添加 `ctx` 参数并使用 `ctx.call(target, operation, params)`。业务字段及规则由处理器校验。stdio 参数和结果须可表示为 JSON，stdout 专供协议，诊断写 stderr。同进程的本机接口可按自身公开契约使用 Python/Qt 对象。

声明存放于 `component.describe()` 的 `operations/events/views/dependencies`。组件可以修改自己的声明，再通过 `component.port.advertise()` 发布；目录与授权选项随之变化。新增能力须单独授权。当前轻量帮助类没有声明编辑器，撤回时删除对应声明项后重新发布。

在线事件可声明于 `component.events`，在处理器中使用 `ctx.subscribe(target, event, callback)`、`ctx.publish(event, payload)`、`ctx.unsubscribe(token)`。回调签名为 `callback(payload, ctx)`。订阅须有目标事件的明确授权；事件触发的后续调用沿用发布者与订阅者权限范围的交集。退订或组件退出会清理订阅。事件不持久化，不重放，也不保证跨组件全局顺序。

用户管理代码可执行 `runtime.grant(requester, target, name, kind='operation')` 与 `runtime.revoke(...)`；事件使用 `kind='event'`。稳定授权绑定安装身份和具体能力语义，运行句柄绑定实例。重启后需重新绑定；新增操作、授权修订变化、接口不兼容或读变写不会沿用原授权。后台权限须另行使用 `background=True` 授予；当前 stdio SDK 只转交活跃请求与事件的上下文，没有独立后台上下文获取入口。

## 在画布挂载软件自己的视图

从组件管理加载 `next/examples/counter` 并启动计数器。在画布点击“添加组件”，选择计数器后，管理窗口会列出这次展示所需的具体权限；确认后才授权并挂载。审批对话框打开时画布保持展开；取消不授权，取消或执行完成后才结束这次等待。审批绑定发起组件的当前实例，旧审批不能作用于替换后的实例。计数器自己的 QML 按钮调用自己的公开操作，撤销 `increment` 后，已显示的按钮也不能修改计数。

该插件只使用 SDK 和公开 Qt 视图契约，不取得 Runtime。`qt-quick-item` 描述声明 create/release 操作，提供方在画布给出的父项内创建自己的 QQuickItem，拥有模型、校验和交互。画布只负责容器、拖动、缩放和折叠。折叠或卸下展示不停止软件，也不清空它的业务数据；提供方退出会使旧展示失效，重启后可以重新添加。此接入仅适用于可信同进程 Qt 软件，不能通过 stdio 发送 Qt 对象。完整示例见 [counter](examples/counter/README.md)。

## 边界与验收

| 设计原则 | 实现与验收证据 |
| --- | --- |
| 能力归组件所有 | notes/labeler 各自拥有业务状态；新增业务字段无需平台分支；业务校验位于处理器 |
| 能力与展示分开 | 组件可无视图运行；Qt 延迟导入；headless 测试阻止 Qt 导入仍能启动 |
| 协作有明确负责人 | labeler 发起读取并接收错误；协作组件只做目录、路由、事件；业务请求不自动重放 |
| 依赖与退出行为明确 | 必需能力依赖退出后拒绝调用，恢复后重新可用；可选依赖不关闭其余操作；启动失败回收已启动的子进程 |
| 自动发现与明确授权 | 运行中操作/事件增删更新目录；新能力拒绝；撤权立即约束旧上下文；嵌套调用不借被调用方长期权限 |

`tests/test_platform.py` 验证真实 Runtime 与真实子进程的调用、权限拒绝/撤销、便签进程内外替换、错误传播、兼容重启保留授权而旧句柄失效、操作与事件动态声明、stdio 事件订阅/发布/退订和退出清理。它还实际停止授权、协作、运行管理后检查调用结果，再启动新实例恢复；通过公开 `replace_component` 更换授权与协作实现并保留调用方代码。必需组件启动失败会回收先前启动的子进程；普通清单不能自填管理控制端口，只有可信装配可以注入。事件订阅者异常会返回本项错误并继续投递其他订阅者，订阅者后续撤销下游权限也会收窄事件上下文。

`tests/test_persistence.py` 在独立宿主进程间验证安装身份和既有授权保留、新能力未授权、旧句柄失效、同名新安装不继承来源授权、撤销配置初始授权后重启不复授，以及业务文件仍由组件自己维护。

`tests/test_transport.py` 验证真实进程握手、生命周期、超时、退出、上下文令牌失效、帧长限制和调用环拒绝。协议默认每帧含结尾换行最多 1 MiB，每端最多 32 个并发处理请求和 32 个待答请求。进程重入调用环立即返回 `call_cycle`；当前不支持循环协作。调用超时仅表示结果未知，令牌立即失效；该实例后续业务调用被拒绝，需停止并重启，平台不会重放写入。正常停止不成功时报告 `stopping`，由管理方明确选择强制结束。

独立进程提供故障和依赖隔离，不是操作系统沙箱。Python 同进程软件属于可信代码，无法承诺安全卸载任意线程、Qt 对象或阻止其访问宿主内部对象。

首版仍有这些限制：没有商店、自动依赖下载、签名发布、业务事务或离线事件。运行管理实现替换要求重启；授权与协作的运行中替换已做调用验收，不代表任意第三方实现都能无缝迁移私有状态。可信 QML 原生视图与外部窗口入口属于可选桌面能力；画布可挂载符合原生视图契约的插件，不支持把任意程序窗口嵌入画布。桌面自动验收使用独立 Qt offscreen 进程，覆盖视图显示/隐藏、窗口承载停止后管理入口仍在、更换窗口提供者后画布和桌宠重新绑定，以及两次 GUI 启动间安装身份、授权和本地插件恢复。新增 Qt 输入验收覆盖桌宠点击/拖放、画布进入离开与菜单/拖动、插件按钮的实时撤权，以及两次独立宿主间桌宠位置恢复。当前环境没有可连接的真实显示服务，截图来自 Qt offscreen 的真实窗口或原生项渲染；真实屏幕合成效果与跨平台体验仍需单独验证。
