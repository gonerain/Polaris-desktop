# 应用组件开发约定

`Application` 是有应用入口的 `Component`。它通过普通 Runtime 记录启动和停止，使用同一套客户端、能力目录与授权检查。`ApplicationDefinition` 保存应用实例的 UUID、连接、配置及包快照引用；应用的界面代码和业务代码由应用包提供。

## 类型、实例与界面

- 应用类型是包清单中的 `id`，例如 `org.example.text-studio`，描述一份实现。
- 应用实例拥有稳定 UUID。授权、连接和数据归属于这个 UUID；重启只更换 `runId`。
- 视图是应用实例的展示入口。关闭或切换当前应用会停止其会话；共享能力提供方保留自己的生命周期。

官方组件是默认实现。应用声明需要的能力契约，用户选择具体提供方实例。可选 `label` 指定连接行标题，未提供时显示别名；契约标识在悬浮提示中展示。`preferredComponentType` 只影响候选排序；满足契约的其他组件同样可以连接。

## 平台实例与管理入口

画布设置按外观、扩展管理和关于分层。扩展管理的市场页读取已配置 Git 源中的应用与组件目录，应用页集中管理已安装应用，组件页按组件包列出平台实例。浏览管理列表不启动、停止或切换应用；“打开应用”才进入该应用的界面。

组件实例由平台统一保存。`single` 和 `multiple` 只决定实例数量；应用连接已存在的实例，同一实例可被多个应用引用，各应用保留自己的授权。停用、卸载应用不销毁所连接的实例。显式删除实例仍校验运行状态与应用引用。配置入口打开组件已有的界面，不提供通用 JSON 编辑器。

市场安装停留在管理页，“打开应用”才展示应用界面。应用按验证后的包 ID 匹配安装记录，源更新使用明确的应用身份；本地安装不会被自动认作来自某个源。来源记录与应用代码快照、摘要和源 revision 一致时才展示，本地目录更新会清除旧来源记录。更新继续保留应用身份、数据、有效连接和已有授权。

应用通用连接、权限和可信授权确认由宿主承载。画布顶部“收起画布”旁的“组件连接 / 权限”打开独立弹窗，不占用应用内容区。需要新权限时在同一个弹窗中确认并展示结果；已有授权的普通调用直接复用权限，不重复打开弹窗或发布授权成功通知。弹窗等待用户确认不设总时限；关闭等待中的确认即取消该请求。申请授权不会为了打开管理页而切换当前应用。应用自有 QML 只收到应用能力及后台桥，不收到扩展管理或 Runtime 控制接口。

## Python 应用抽象

底层 `polaris_platform.application.Application` 的操作处理函数接收 `(params, context)`。SDK 入口 `polaris_platform.sdk.Application` 提供与 SDK 组件相同的关键字处理函数和可选 `ctx`：

```python
from polaris_platform.application import ApplicationDefinition
from polaris_platform.sdk import Application


class TextApplication(Application):
    def __init__(self, definition):
        super().__init__(definition=definition)
        self.event('changed')

        @self.operation('tidy', access='read', applicationBinding='instance')
        def tidy(text, ctx):
            result = ' '.join(text.split())
            ctx.publish('changed', {'text': result})
            return {'text': result}


definition = ApplicationDefinition('文本应用')
runtime.ensure_application(
    definition,
    factory=lambda: TextApplication(definition),
    component_type='org.example.text-application',
    version='1.0.0',
)
runtime.start_application(definition.id)
```

这里的 `runtime` 由可信宿主提供。应用操作进入普通能力目录，调用方仍需获得对应授权。应用通过 `ctx.call(...)` 或声明操作的 `requires` 后使用 `ctx.call_required(...)` 调用外部能力，调用链保留原始请求身份。应用可以声明和发布事件；当前应用来源的事件订阅仍返回 `application_binding_unsupported`。

覆写 `start(port)`、`stop()` 时应调用父类实现。`port` 是当前运行的普通组件客户端，停止或重启后旧客户端失效。`on_stop` 可通知宿主关闭视图和会话；通知回调不得再次调用 Runtime 停止自身。Qt 宿主应通过信号切回界面线程。

## 桌面应用包

当前桌面安装器支持可信本机 Qt Quick 包。清单 `polaris-application.json` 指定入口和能力需求：

```json
{
  "id": "org.example.text-studio",
  "name": "文本工作室",
  "version": "1.0.0",
  "entry": {"adapter": "qt-quick", "file": "Main.qml"},
  "requires": {
    "tidy": {
      "label": "整理文本",
      "contract": "org.example.text.tidy@1",
      "access": "read",
      "preferredComponentType": "org.example.text-tools"
    }
  }
}
```

提供方操作通过 `provides` 声明相同契约，并声明 `applicationBinding='instance'`。候选匹配契约和访问级别；连接之后固定到提供方安装身份、实例身份及能力语义。替换连接会撤销旧授权，执行新连接时重新确认。契约中的主版本表达兼容边界；实现变动必须遵守能力版本规则。

安装器保存经过摘要校验的包快照。QML 通过宿主桥接调用已连接的别名。安装包以 `qt-quick` QML 为界面入口，可用 `entry.backend` 声明应用自身的 Python 后台服务。包快照摘要同时覆盖 QML 和 Python 源码。Python `Application` 子类仍可由可信宿主通过 `ensure_application(..., factory=...)` 注册；包后台服务不通过开发者提供 Runtime 工厂来获取宿主管理权限。

## 宿主接口与数据

```python
runtime.ensure_application(
    definition,
    factory=factory,
    entry_view=entry_metadata,
    restore=True,
    component_type=package_id,
    version=package_version,
    data_directory=existing_application_data_directory,
)
runtime.start_application(definition.id)
component = runtime.application_component(definition.id)
client = runtime.application_client(definition.id)
context = runtime.application_context(definition.id)
runtime.stop_application(definition.id)
```

`ensure_application` 登记实例，不启动它。`factory` 返回运行对象；没有传入工厂时创建基本 `Application`。`entry_view` 是可选视图声明。宿主恢复旧安装时传入原数据目录，继续使用已有的应用数据；独立宿主未指定目录时使用 Runtime 状态目录下的 `application-data/<UUID>`。

`start_application` 和 `stop_application` 复用 `start_component`、`stop_component`。从宿主停止应用也会清除应用上下文并触发 `on_stop`。撤销授权会清除授权和旧上下文，并通过普通生命周期更新运行身份；重新授权不会使旧上下文或旧客户端恢复有效。

应用定义由 `ApplicationStore` 保存和恢复。Runtime 不把应用记录再次写入组件安装清单或附加组件实例清单，避免双重恢复。

## 兼容与当前边界

旧 schema 1 流程定义和 schema 2 包引用继续读取。`Application(title, bindings, ...)`、`from_dict`、`save`、`open` 等旧入口保留；新存储与宿主代码使用 `ApplicationDefinition`。迁移保留应用 UUID、授权、连接和原数据目录。

当前不支持资源范围绑定、应用来源的事件订阅。后台服务使用应用自身的既有授权上下文，不取得额外的“后台权限”。应用包删除和替换须经过应用宿主，普通组件卸载入口会拒绝操作。普通组件原有的能力和实例协议继续适用。应用获得自身明确授权，宿主管理权限不会随调用下放给应用。

## 桌面包更新

本机宿主维护入口 `ApplicationHost.updateDirectory(location)` 更新当前选中的应用；先调用 `select(applicationId)` 选择已有应用。新包清单的 `id` 必须与旧包相同。它先复制并验证独立快照，保留应用 UUID、数据目录、配置及仍匹配当前能力的绑定。`package.snapshot` 是包快照 UUID，与应用 UUID 独立；旧安装的两者相同仍有效。导入定义不能引用另一个已安装应用的快照。

宿主关闭旧视图、停用旧 Session，并异步等待旧服务 `stop()` 完成，再原子保存指向新快照的应用定义。保存失败时保留旧定义、旧包及实例引用；提交后清理旧快照。原运行意图保留；依赖组件存在即可恢复后台，能力连接或授权问题以警告显示，实际调用仍严格校验。新增或变化的能力须另行连接和授权，更新不自动授予权限。维护调用的进度或错误通过宿主 `changed` 及现有提示状态返回。

## 应用自身的后台服务

包清单的 `entry` 可写为：

```json
{"adapter":"qt-quick","file":"Main.qml","backend":"backend.py"}
```

`backend` 必须是包内现有的相对 `.py` 文件，不能越出包目录。入口在每次运行时使用独立模块名，从已校验快照源码装载，不在快照目录生成入口或相对导入辅助模块的字节码。运行数据写入 `context.data_directory`，不要修改包快照。

`backend.py` 导出 `create(context)`，返回提供 `start()`、`stop()`、`handle(command, params)` 的服务对象。`start()` 启动应用自己的工作线程后返回；轮询、游标、队列、会话映射和消息回传均属于应用。`stop()` 应让工作线程退出并等待其结束；宿主会在独立生命周期线程调用它，不会让等待模型回答阻塞界面。

context 只提供：

- `application_id`、`data_directory`：当前应用身份及独立数据目录。
- `bindings`：已声明绑定信息的副本；修改副本不会修改权限或真实绑定。
- `call(alias, params)`：仅经 `ApplicationSession` 调用已连接别名，每次校验实例身份与现行权限。
- `publish(state_dict)`：发布可 JSON 序列化的应用状态快照。
- `stopped`：停止事件。停止时立即置位并关闭 Session；旧工作即使稍后收到模型结果，也不能继续调用其他能力。

应用包可用 `dependencies` 字符串数组声明必需的组件类型 ID，与 `requires` 的能力别名声明分开。启动时检查依赖组件及已连接实例是否存在；运行期间组件丢失时报错并停止。组件已停止、能力未连接或能力变化仅产生启动警告；能力调用失败不终止后台，也不绕过调用授权。恢复时不会自动授予缺失权限。

包可声明 `callbacks` 操作映射，每项为 `{contract, parameters, label?}`；`parameters` 为对象参数 schema，且必须有后台入口。宿主将这些入口注册为应用自身的普通写能力，提供相应契约和实例绑定元数据。调用仍经过普通授权检查，宿主只将命令和参数交给后台 `handle`，不授予额外权限。后台停止或尚未就绪时返回 `completion_not_ready`，界面是否打开不影响回调。应用应在持久化接管结果后才返回 `accepted: true`。

QML 获得 `appBackend`：`available/running/stopping/error/warningsJson/stateJson` 属性；`start()`、`stop()` 运行开关；`call(command, params, requestId)` 调用应用服务的 handle，结果通过 `completed(requestId, resultJson)` 或 `failed(requestId, message)` 返回，状态通过 `changed` 通知。后台服务及其状态不依赖当前视图，界面隐藏后只停用视图桥接，不停止已明确启用的后台。

首次启动前，宿主为清单所需别名请求现有应用授权确认。显式启动意图单独保存，主程序退出会停止工作但保留该意图；下次恢复只检查原绑定和已有授权，缺失时报告错误，不自动批准权限。显式停止、撤销、删除或更换绑定会停用旧工作并清除运行意图。重新启动须等待上次 stop 完成，避免两个服务同时写同一应用数据目录。没有声明 backend 的旧应用继续保持原先的界面生命周期。

## 内置工作台

工作台是平台固定注册的内置应用，使用独立的应用身份参与应用导航；它不是可安装或可移除的本地应用包。切换到其他应用只隐藏工作台视图，已挂载的组件视图与布局继续保留；退出画布时释放展示资源，不停止业务组件。现有应用包、连接与授权继续按各自身份管理。

工作台视图使用一套独立 QML 引擎，页头与内容共用该引擎，工作台内的原生卡片也共享它；这会增加一个视图引擎，并不构成安全沙箱。工作台使用平台内部的可信本机展示接口来挂载组件视图，保留发起操作的本机用户上下文。普通应用仍使用自己的能力绑定和授权，不能通过该接口获取运行时管理权限。
