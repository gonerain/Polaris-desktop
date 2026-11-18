# 组件抽象层原型

这是早期调用原型，现有应用尚未接入。它验证组件拥有功能和规则、发起组件负责协作，但尚未把运行管理、协作和授权实现为可替换组件。后续平台设计以[由组件组成的软件平台](../../docs/component-platform-design.md)为准。

## 运行

在仓库根目录执行，使用 Python 3.10 或更新版本，无第三方依赖：

```bash
python -m prototypes.component_layer
python -m unittest discover -s tests -p 'test_component_layer.py'
```

示例先创建文档，再请求标签组件生成标签。标签组件通过 `documents.get` 读取标题，成功后保存自己的标签。缺少文档读取授权时调用失败；文档退出后，标签仍能查询已有数据。

## 职责

| 所属方 | 职责 |
| --- | --- |
| 文档组件 | 管理文档、校验参数、分配 ID、实现创建和改名 |
| 标签组件 | 组织“读取文档 → 创建标签”，处理依赖缺失，返回业务结果 |
| 公共层 | 发现接口、检查授权、路由调用、传递调用来源、撤销能力 |
| 宿主 | 创建组件实例、决定何时授权或撤销授权 |

标签组件只使用文档接口承诺的返回字段，不持有文档组件或其存储对象。公共层不解释文档和标签字段，也不决定业务步骤。

## 接口

组件实现两个成员：

- `spec: ComponentSpec`：组件 ID、名称和 `OperationSpec` 列表。操作声明名称、读写性质、版本以及参数和返回值说明。
- `call(operation, args, context)`：校验并执行自己的功能，通过 `ComponentError(code, message)` 返回可处理的错误。参数和返回值类型由各操作的公开契约定义。

公共层原样转交参数和结果，不解析业务字段、不限制数据类型，也不统一复制数据。组件负责校验参数，并约定数据的所有权和可变性；例如返回独立副本或公开定义的不可变对象。文档和标签示例都返回自身构造的副本，调用方修改结果不会改变内部状态。参数说明用于发现和 help，具体校验仍由组件实现。

新增组件可以定义自己的公开数据类型，无须修改公共层。如果以后通过 IPC 等传输接口访问组件，由传输适配层按接口契约处理序列化。

宿主的最小调用方式：

```python
from prototypes.component_layer import Registry
from prototypes.component_layer.examples import DocumentsComponent, LabelsComponent

registry = Registry()
registry.register(DocumentsComponent())
registry.register(LabelsComponent())

# 宿主已完成自己的授权判断，再明确授予所需操作。
grant = registry.issue_grant(
    principal="user", source="local-host",
    operations=[("documents", "create"), ("documents", "get"),
                ("labels", "create_for_document")],
)
request = registry.context(grant, request_id="request-1")
created = request.call("documents", "create", {"title": "设计记录"})
result = request.call("labels", "create_for_document", {
    "documentId": created["document"]["id"],
})
```

组件内部调用其他组件时使用 `context.call(...)`。原始主体、授权来源和请求 ID 保持不变，`call_chain` 追加当前组件和操作。`context.narrow(...)` 可以缩小后续调用的操作范围，不能扩大。授权 `labels.create_for_document` 不会隐式授权 `documents.get`。

`issue_grant` 只属于宿主接口；组件收到的上下文没有签发授权的方法。原型面向可信的同进程组件，Python 私有属性不是恶意代码隔离机制。

## 加入、退出与授权

- `register` 保存不可变接口快照。之后改动组件的原始声明，不会隐式发布新能力；`discover` 和 `help` 始终读取已登记的快照。
- `update` 显式替换一个组件的登记。该组件旧授权全部失效，包括未改名的操作；其他组件授权继续有效。需要保留哪些操作，由宿主重新授权。
- `unregister` 立即撤销公开能力，同 ID 再次注册也不会继承旧授权。它不销毁业务对象、不处理保存或视图。
- `revoke` 撤销整份授权，已创建的调用上下文也随之失效。

权限精确绑定组件、操作、操作版本与本次登记代号，没有“所有未来写操作”的隐式权限。`principal`、`source` 和请求 ID 用于记录来源，不能单凭这些字符串获得权限。

## 原型边界

原型同步执行调用，发现查询返回当前快照。组件退出影响之后的调用，不中断已经进入组件的执行。实例启停、依赖调度、界面、授权持久化和异步通知留给应用接入阶段。

授权覆盖操作，不绑定某一组参数，也不代表一次性审批；请求 ID 仅用于追踪。组件的完整功能应在自身接口中完成校验和执行。跨组件流程由发起方处理部分失败，公共层不自动重试、不提供事务或通用计划执行器。业务异常原样交给调用方；异常或无效返回值不能证明写入未发生。
