# Shared implementation contract

Python >=3.10, synchronous component boundary. No old package imports.

- `Component` in `polaris_platform.component`: `describe()->dict`, `start(port: Client)->None`, `stop()->None`, `call(operation: str, params: dict, context: Context)->result` (the selected interface profile defines result types; stdio uses JSON values). Base implementation offers `operation(name, access='read', major=1, revision=1, interface=None)` decorator; handler signature `handler(params, context)`. Description keys: `operations` map name to metadata, `events` map, `views` list, `dependencies` list. May override methods without inheritance.
- `Context` in `protocol`: immutable opaque trusted request context. Contains `origin`, `origin_installation`, `caller`, `source`, `request_id`, `scope` (frozenset capability keys); runtime issues contexts. Nested calls preserve original origin/scope and replace caller with invoking component. Capability keys are `(installation_id, kind, name, major, access, revision)`. Public wire descriptions use JSON lists.
- `PlatformError(code, message, details=None)` in `protocol`, `.as_dict()`.
- `Runtime` in `runtime`: component itself; `install(manifest, factory, installation_id=None)->str`, `start_component(id)`, `stop_component(id)`, `client(id)->Client`, `snapshot()`. Constructor empty; bootstrap attaches collaboration and authorization using `connect(collaboration, authorization)`. Runtime keeps stable control methods available while component public lifecycle stopped, so trusted bootstrap can recover it.
- `Client`: bound to runtime-verified installation + instance. `call(target, operation, params=None, context=None)`, `bind(target, operation)->Handle`, `invoke(handle, params=None, context=None)`, `subscribe(target,event,callback,context=None)`, `publish(event,payload,context=None)`, `advertise()`. During handler use context argument; no-context calls are rejected inside active request. Independent background work must retain a trusted user-issued background context; Client.background_context refuses self-issuance (including delayed/queued requests).
- `Runtime.user_context(requester, targets=None)` is trusted bootstrap/user facade, freezes current explicit grants; never exposed in Client. `Runtime.grant(requester,target,name,kind='operation')` user action, exact current capability only. `Runtime.background_context(requester)` separate explicit background grants.
- `Client.remember_task(name, operations, context)` persists only the selected operations already authorized by both the supplied scope and current live grants. It preserves the original installation and `user`/`background` source. `Client.resume_task(name)` restores that limited authority outside an active handler; later calls still honor live revocation and cannot acquire newly granted capabilities. Existing records without a source are user-originated under the previous contract. `forget_task(name, context)` removes the delegation.
- Process adapter `ProcessComponent(manifest, directory)` in `transport.py`, same Component methods, optional `set_failure_callback(callback)`. `start(port)` retains authenticated Client. Adapter owns framing and child identity; child-supplied context/identity cannot become trusted. It forwards outbound child calls through `port` with the inbound context token resolved locally. `stop()` raises `PlatformError('stopping',...)` if child remains alive; optional `force_stop()`.
- SDK `Component` may reexport core Component, stdio `serve(component)` serves describe/start/call/stop with context represented only by opaque request tokens. Process adapter should call child `describe` before registration; capability description available before or immediately after start.
- Bootstrap `build(config: dict, base_dir: Path)->Runtime`, config roles mapping plus components list manifests/factories. Inprocess entry factory import string `module:callable`; process entry command JSON list. Core factory functions under `polaris_platform.builtins`.
- Desktop exports factories `create_window`, `create_canvas`, `create_pet` (optional Qt import only under desktop). All return same Component contract. Core never imports Qt. `Client` callable available to UI workers.


Legacy component dependencies still accept `{target: id}` or `{role: role}`, an optional interface and major, and kinds startup/capability/optional. Startup prerequisites apply to the component lifecycle. New plugins declare cooperation on the operation or event that actually requires it.

## Registered capability contracts

The optional `provides` field on an operation or event names its public contract, e.g. `notes.read@1`. Use a dotted namespace and positive major version matching the entry's `major`. The author documents parameter and result (or event payload) shapes and maintains their compatibility. Kind and access must match exactly. Each installation advertises at most one local endpoint for a given kind and contract. The ordinary operation name and grant key remain local to its installation. Change the major or authorization revision when changing the meaning of a granted operation. The runtime remembers the public contract associated with each concrete grant key, including across restarts. Registering a different contract under that same key fails validation; increment the revision to request fresh authorization.

`requires` maps local aliases to a contract string (a read operation by default) or to `{contract, kind, access, optional, group}`. An explicit legacy destination can be constrained with `target`. Matching group names within one capability require a common installation. Example: `{"note": "notes.read@1"}`. Authors register events with `component.event(...)` and remove entries with `withdraw_operation` or `withdraw_event`. SDK registration validates and advertises immediately. Handwritten descriptions can still publish through `port.advertise()`.

The collaboration operation `providers({contract, kind?, access?})` lists matching installations and local names. The normal directory and runtime snapshot expose resolved `bindings`, per-alias candidates and endpoint or issue. Required dependency failures propagate to dependent operations and events; optional failures remain on their alias. Incompatible versions and required cycles carry diagnostic details. These are availability results independent of any user's grants.

A unique compatible provider is resolved automatically and pinned on first use. Discovery alone does not make startup order a permanent choice. Multiple usable installations require selection in the component manager. Trusted management uses `select_provider(target, kind, name, alias, installation, consumer_installation)`. Choices are per consumer installation, capability and alias, persisted in `capability-bindings.json` whenever a state directory is configured. An offline or reinstalled selection stays unavailable until it returns or the user selects another installation.

Both SDK profiles offer `ctx.call_required(alias, params)` and `ctx.subscribe_required(alias, callback)`. Requests and callbacks use pinned endpoints, instance-bound handles, and the existing live authorization checks. Explicit `ctx.call(target, operation, params)` and legacy grants keep their existing semantics. Withdrawn endpoints invalidate existing handles/subscriptions even when republished by the same instance.

The desktop uses three contracts from one provider. `polaris.canvas.show@1` is a write operation taking `{sessionId, anchor:{x,y}}`; successful presentation returns the session ID and visible state. `polaris.canvas.status@1` reads `{}` and returns at least `{sessionId, visible}`. `polaris.canvas.dismissed@1` is a read event with `{sessionId, reason}`. Session IDs identify a single presentation. Implementations may expose additional fields.


Stable control facade is Runtime's direct Python management methods, handed only to trusted bootstrap/manager. Ordinary components receive only Client. Public runtime operations go through normal grants. Authorization implementations expose check/scope/grant/revoke/export_records/import_records; replacement migrates grant records through those public methods. Collaboration implementations expose advertise/withdraw/discover/describe_target/watch/bind/invoke/subscribe/unsubscribe/publish and `runtime` control injection. Both start/stop their actual services; new role instances reconnect via Runtime.connect.

Trusted management updates use `runtime.replace_component(component_id, manifest, factory)` (no `_records` access): stops old service, preserves installation ID, constructs and reconnects the replacement. Runtime manager implementation replacement explicitly raises restart_required; bootstrap selects managerFactory. `export_installations()` and `import_installations(records, factory_resolver)` migrate manager-owned installation records via public contracts. Authorization exposes export_records/import_records for its own records.

## Optional local records

`build(config, base_dir=None, state_dir=None)` and `from_file(path, state_dir=None)` restore local JSON records only when explicitly selected. CLI `--state-dir` enables this in headless mode; GUI defaults to the local user's application data directory. Runtime owns installations.json (manifest, directory, stable installationId, desired autostart); Authorization owns authorization.json. Each owner reads/writes through its public record methods; writes use fsync plus atomic replace. Component data is not part of these files.

Authorization `bind_identity(component_id, installation_id)` receives only bootstrap/runtime-confirmed identity. Grants bind both the requesting installation and exact target capability semantic key. `decisions()` returns human component ID plus requesterInstallation. No record lacking requesterInstallation is trusted on import. Application restarts preserve identities and grants; new operations and changed authorization semantics still require explicit grants. Use `stop_component(id, persist=False)` only for application shutdown so shutdown does not disable next launch's desired components. Manifest entry `defer` skips bootstrap startup until an explicitly selected adapter is ready (desktop initializes Qt first).

Context integrity is signed by the runtime over identity, source, request ID and scope. Ordinary dataclass replacements are rejected. Trusted `derive_context(context, caller=None, scope=None)` can change direct caller and narrow scope, and re-signs the result; neither Client nor transport exposes a general signing port. This maintains the API boundary, not a security sandbox for arbitrary same-process Python code.

Control-port references in inprocess kwargs are resolved only when `load_factory(..., trusted_bindings=True)` is selected by trusted assembly. Bootstrap reads `trustedBindings` from its component specification (outside manifest); directory installs default to false and reject requested runtime/component references. Runtime persists this explicit assembly decision alongside installation records.

## Stable component instances and application principals

A component type has at most one installation per platform state. Its legacy component ID addresses the default instance; that instance's stable `instanceId` equals the existing `installationId`, preserving existing grant keys, data paths and saved layouts. The existing `instance` field on `Client` and `Handle` remains the ephemeral run identifier; `status` additionally reports `componentType`, `installationId`, `instanceId`, `runId` and `isDefault`. `Handle.instanceId` is the stable identity in its capability key. Restart changes the run ID and invalidates existing handles without changing stable identity or grants.

A component may opt into extra instances with `instances:{mode:'multiple'}` in its manifest. The first version supports only in-process factories with persistent platform state for this profile. Every factory call for that profile, including the default instance, receives `instance_context:{instanceId,dataDir,config}`; `dataDir` is platform-assigned, `config` is a JSON object. The default keeps the existing component data path; additional instances use distinct `component-instances/<instanceId>` paths. Legacy manifests default to a single instance and retain their existing zero-argument factory behavior. Components must explicitly implement the isolation promised by this profile; separate instance IDs do not isolate resources inside an instance.

Trusted management can call `create_instance(componentType, config={})`, `list_instances(componentType=None)`, `start_instance(instanceId)`, `stop_instance(instanceId)` and `destroy_instance(instanceId)`. New instances start with no grants. Stopped instances preserve identity, config, data and grants across restarts. Destruction rejects live or application-referenced instances; it retires the ID and removes its grants but retains component data. The default instance is removed only with its installation. Additional instances must be stopped before installation replacement; compatible replacement and rollback retain their identities, configurations and data. Component instance records and application references are stored separately from existing installation records, and retirement is persisted before grant cleanup.

Applications may call only operations whose provider advertises `applicationBinding:'instance'` in the live operation metadata. This opt-in is the provider's assertion that its stable component instance fully identifies the intended resource boundary; missing or different declarations do not authorize Application use. Application definitions cannot declare this on a provider's behalf. The runtime checks the live metadata for every operation in an application-origin call chain, including nested calls; it does not change calls from non-application origins. Application-origin event subscriptions are not yet supported. Per-resource authorization is not supplied by this declaration.

Packaged applications may expose explicitly declared `callbacks` as ordinary, authorized, instance-bindable write operations. Each callback declares a `contract` and object `parameters` schema, requires a backend entry, and dispatches to that backend's `handle`; it does not gain host management authority. An unavailable backend returns `completion_not_ready`. Trusted management registers a durable application UUID with `register_application_principal(id)` and obtains its ordinary `application_client(id)` and explicitly scoped `application_context(id)`. New registration rejects IDs with prior grants; only restoration of a verified stored application uses `restore=True`. `register_application_bindings(id, instanceIds)` records references before a definition is installed, protecting instances from deletion. Unregistration revokes that application's grants and invalidates its clients and contexts. Application authority never uses canvas or runtime identity. Only user-authorized capability calls through that client's context are allowed.

Applications provide their own Qt Quick UI in a local directory. The first package manifest format has no `schemaVersion`: `polaris-application.json` declares `id`, `name`, `version`, `entry` (`adapter: "qt-quick"`, relative QML `file`) and `requires`, a map from aliases to `componentType`, `operation`, positive integer `major` and `access` (`read` or `write`). This developer manifest is distinct from the platform's schema 2 persisted application record. These are developer requirements, not grants; the user selects a stable component instance and authorizes each capability. The host validates live provider metadata and pins installation, instance and capability semantics. Each installation receives a new local application UUID, separate from the developer's type ID. The platform copies the package into a private snapshot, rejects symbolic links and path traversal, and verifies the snapshot before launch and capability calls. Removing a package removes its snapshot, while preserving application data; revocation and principal retirement are managed separately. A stopped or removed application does not destroy its referenced platform component instances. Multiple applications may reference the same instance while retaining separate grants; single/multiple policies determine instance count only. Extension management is embedded in Canvas settings, while capability approvals remain in a persistent trusted Canvas overlay.

The Qt Quick adapter runs trusted application QML/JavaScript in the desktop process; it is not a sandbox for untrusted code. Application capabilities use the application's ordinary Client and Context, never a Runtime management interface. Legacy schema 1 flow definitions remain readable for compatibility, but are not the normal application installation interface.

## Trusted local Qt item views

A provider may declare `views` entries using `{id, title, adapter:'qt-quick-item', create:'create_view', release:'release_view', permissions:[{name,access}]}`. This profile is for trusted inprocess Python/Qt components. The declared create/release operations carry `profile:'qt-native'`; their arguments and results may contain Qt objects and cannot cross the JSON stdio boundary.

`create_view({view, parent: QQuickItem}, context)` returns `{handle: str, item: QQuickItem}`. The provider owns its QML, model, interaction bridge and view resources. It sets both QObject and visual parent of its item to the supplied parent and performs Qt operations on the GUI thread (`polaris_platform.desktop.GuiDispatcher` is the public dispatcher helper). `release_view({handle}, context)` disposes this view and returns `{released: bool}`; a released or already destroyed handle is harmless. Provider stop disposes its own remaining views. Disposing a canvas container or provider view does not stop the provider's business component.

`canvas.mount({target, view:'main', descriptor?}, context)` invokes the provider's declared operations through its ordinary Client. It returns `{mountId, state:'pending'}`; attachment completes asynchronously and `canvas.status` exposes mount state. The canvas forwards the original caller context to its trusted built-in Workbench application, which owns the wrapper, geometry and collapsed state; Canvas remains the presentation host. `unmount({mountId})` releases a presentation, and `layout({mountId,x?,y?,width?,height?,collapsed?})` changes canvas placement. No provider-specific model or identifier belongs in the canvas.

A view descriptor may include `preferredSize:{width,height}` in logical pixels. Canvas clamps these values to 240–1600 by 130–1200 for new mounts; missing or invalid dimensions use 380 by 340. Saved geometry takes precedence. Canvas size/theme and Workbench view layouts remain in the existing canvas layout file without migration. The supplied parent may expose an optional `polarisTheme` object with `background`, `surface`, `surfaceRaised`, `border`, `text`, `muted`, and `accent` colors. Providers may bind to it and must supply their own fallback when absent.

A view descriptor may declare `instancePolicy:'single'` or `'multiple'`; missing means `multiple`. `single` is scoped to a stable component instance and view ID within the canvas. Reuse rechecks current permissions and requires the same origin, origin installation and source, with the previous scope contained in the current scope. Conflicting saved layouts remain intact and report a conflict. Removing a view releases its presentation and does not stop its component instance.

Provider view buttons retain the creating request context and invoke their provider's ordinary public operations through its Client. Declarative `permissions` describe the required controls; they do not grant access. Existing views must honor authorization revocation, and reopening a view cannot replace the original user scope with the provider's standing permissions.

## Transient desktop session

Pet initiates one canvas presentation session carrying its existing local user context and an opaque session ID. It hides only after the canvas has actually shown. Canvas reports dismissal by its public `dismissed` event with that session ID. First display does not start a leave timer until the pointer has entered; reentry cancels it, and active popups or layout dragging hold dismissal. A failed hide does not report the canvas hidden or finish the session.

Pet restores itself only for its own active session, using the retained authorization context. Canvas exit or window loss is observed as unavailable; a returning window instance may restore the pet without replaying business calls. Stopping the pet cancels its session/recovery and queued input, so later callbacks cannot revive it. Desktop startup grants only the exact configured initial capabilities for a new installation; existing installations retain user revocations. Pet owns its position file under its own component data directory.

A native picker opens an explicit management approval scoped to the requesting installation and current instance. The trusted approval overlay lives at the Canvas root and preserves the current application page. While it is pending, the initiating canvas session holds dismissal. Confirmation, cancellation, failure, or management closure resolves the token and releases the hold. Confirmation rechecks the requester instance and exact capability semantics before granting or invoking. Permission failures during status observation propagate as permission failures and do not manufacture a hidden-window state or finish a live session.

## 插件源

一个仓库可提供多个组件和应用。仓库根目录的 `polaris-source.json` 使用统一发布目录：

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

每个条目必须有 `type`（`component` 或 `application`）、`path`、`summary`、`author` 和 `icon`。可选 `tags`、`description`、`readme`、`screenshots` 和 `upstream`；标签和截图为字符串数组，其他字段为字符串。路径相对源根目录；图标、截图和文档须是包目录以外的文件。建议使用 256 像素 PNG 或 WebP 图标。条目的 ID、名称和版本只从包自身清单读取。应用包包含 `polaris-application.json`，组件包含 `manifest.json`。同类包 ID 在源内唯一，索引不会执行包代码。

目录须包含安装所需的完整包文件；将索引、包和展示资源提交到 Git 后，可添加该仓库 URL 并选择分支、标签或 commit。旧版 schemaVersion 1 的 `components` / `applications` 仍可读取并映射到统一目录。源目录每项含 `type`、`path`、`manifest`、`contentDigest` 及声明的展示元数据；组件和应用内容摘要基于各自包目录，而非整个源的 revision。修改目录说明或展示资源不会改变包内容摘要。

插件源组件通过公开只读操作 `sources`、`packages`、`catalog` 和 `application_catalog` 提供源、统一目录和原有分类目录。目录行包含 `sourceId`、`revision` 和上述包信息，添加源不自动安装包。

画布设置中的可信扩展管理界面通过组件实例的 `local_source_control()` 调用：

- `sources()`、`packages(source_id=None)`、`catalog(source_id=None)`、`application_catalog(source_id=None)`：读取源、统一包目录和分类目录。
- `application_path(source_id, application_id, expected_revision)`：取得指定源 revision 的应用包快照路径；revision 改变时拒绝，应用安装和更新使用现有应用包流程。
- `installation_origin(component_id)`：读取仍与当前安装身份及目录匹配的组件来源（含安装时 `contentDigest`），否则返回空值。
- `archive_sources(source_ids, migration)`：按迁移标识一次性将指定源标为历史，保留来源记录及安装快照；无指定源时的分类目录和统一目录不返回历史条目，显式传入源 ID 仍可读取。
- `add(location, ref=None)`：添加本地目录或 HTTPS / SSH Git 仓库。
- `refresh(source_id, ref=None)`：读取新快照；Git 的 `ref` 可以是分支、标签或 commit。
- `install(source_id, component_id, replace=False, expected_installation=None, expected_revision=None)`：安装选定插件。同 ID 默认拒绝；替换需明确选择，可携带确认时的安装身份和源 revision 防止选择变化。
- `update(component_id)`：使用已记录来源的当前快照更新。
- `rollback(component_id)`：切换到该安装保留的上一份代码。

写操作只能由可信本机控制接口发起，不能通过普通组件操作调用。`create_sources(runtime, state_dir=None)` 使用只暴露安装所需生命周期方法的控制对象；默认数据目录由运行管理分配给 `sources`。安装来源、精确 revision 和旧代码路径持久化在插件源组件的数据目录。

Git 仓库固定 commit 后复制成独立快照；本地目录也先复制快照，再安装。获取时不执行 hooks、不递归 submodules、不执行依赖安装脚本。组件启动时若缺少运行依赖，应明确报告缺失依赖。选择仓库并不保证其依赖已在宿主或组件自己的运行环境中安装。

更新保持现有安装身份、授权及自启动设置；正在运行的组件切换后恢复运行。失败时恢复旧代码和运行状态，回退失败明确报告错误。组件自己的业务数据和格式迁移仍由组件负责，代码回退不回退业务数据。
