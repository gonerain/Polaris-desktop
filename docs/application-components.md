# 应用组件开发约定

`Application` 是有应用入口的 `Component`。它通过普通 Runtime 记录启动和停止，使用同一套客户端、能力目录与授权检查。`ApplicationDefinition` 保存应用实例的 UUID、连接、配置及包快照引用；应用的界面代码和业务代码由应用包提供。

## 类型、实例与界面

- 应用类型是包清单中的 `id`，例如 `org.example.text-studio`，描述一份实现。
- 应用实例拥有稳定 UUID。授权、连接和数据归属于这个 UUID；重启只更换 `runId`。
- 视图是应用实例的展示入口。关闭或切换当前应用会停止其会话；共享能力提供方保留自己的生命周期。

官方组件是默认实现。应用声明需要的能力契约，用户选择具体提供方实例。可选 `label` 指定连接行标题，未提供时显示别名；契约标识在悬浮提示中展示。`preferredComponentType` 只影响候选排序；满足契约的其他组件同样可以连接。

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

安装器保存经过摘要校验的包快照。QML 通过宿主桥接调用已连接的别名。这个安装路径目前只支持 `qt-quick` QML 入口。Python 子类可由可信宿主通过 `ensure_application(..., factory=...)` 注册；桌面包安装器不支持以 Python 子类作为动态入口，本轮不承诺此能力。

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

`start_application` 和 `stop_application` 复用 `start_component`、`stop_component`。从组件管理入口停止应用也会清除应用上下文并触发 `on_stop`。撤销授权会清除授权和旧上下文，并通过普通生命周期更新运行身份；重新授权不会使旧上下文或旧客户端恢复有效。

应用定义由 `ApplicationStore` 保存和恢复。Runtime 不把应用记录再次写入组件安装清单或附加组件实例清单，避免双重恢复。

## 兼容与当前边界

旧 schema 1 流程定义和 schema 2 包引用继续读取。`Application(title, bindings, ...)`、`from_dict`、`save`、`open` 等旧入口保留；新存储与宿主代码使用 `ApplicationDefinition`。迁移保留应用 UUID、授权、连接和原数据目录。

当前不支持资源范围绑定及应用来源的事件订阅。应用包删除和替换须经过应用宿主，普通组件卸载入口会拒绝操作。普通组件原有的能力和实例协议继续适用。应用获得自身明确授权，宿主管理权限不会随调用下放给应用。

## 应用后台与回调

包可通过 `entry.backend` 指定现有相对 Python 文件。模块提供 `create(context)`，返回有 `start()`、`stop()`、`handle(command, params)` 的服务。上下文仅提供本应用的 `application_id`、`data_directory`、`bindings`、`stopped`、`call(alias, params)` 和 `publish(state)`，不提供 Runtime 管理权限。

后台由用户明确开启，切换或隐藏界面不停止。运行意图持久化，恢复时不自动授予权限；实际调用始终校验绑定及普通授权。依赖组件由可选 `dependencies` 组件类型 ID 数组声明：组件或已连接实例丢失时报错并停止，组件存在但能力不可用时仅警告。

应用包可声明 `callbacks` 映射，每项为 `{contract, parameters, label?}`，其中 `parameters` 是对象参数 schema。宿主将回调注册为应用自身普通、可实例绑定的写能力，调用经正常授权后转交后台 `handle`；后台停止或尚未就绪时返回 `completion_not_ready`。接收者应在持久化接管结果后才返回 `accepted: true`。

QML 的 `appBackend` 提供 `available/running/stopping/error/warningsJson/stateJson`，以及 `start()`、`stop()`、`call(command, params, requestId)`。结果通过 `completed`、`failed` 返回。界面隐藏后仍可接收获授权的回调。

`updateDirectory()` 更新当前应用包，保留应用 UUID、数据和运行意图。先停止并等待旧后台，再原子保存新快照引用；新增能力不自动连接或授权。未知投递结果由应用保留并交给用户核对，不自动重发。
