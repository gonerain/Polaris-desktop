# 组件画板

## 运行

项目使用 Python + PySide6 / Qt Quick，依赖 `PySide6-Essentials==6.8.3`，不需要 WebEngine。

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py
```

## 初始化与自适应

在 `qml` 目录内的 QML 文件中：

```qml
import QtQuick
import "components"

ComponentBoard {
    id: board
    panelSize: Qt.size(120, 80)
    panelCount: 12
    gap: 8
}
```

- `panelSize` 是一个基础逻辑 panel 的宽高，必须为有限正数。
- `panelCount` 是可分配的 panel **总数**，不是业务组件实例数，必须是正整数。
- `gap` 必须为有限非负数。相邻同属 panel 内部合并，不同组件之间保留间距。
- 默认列数为 `ceil(sqrt(panelCount))`，按行排列；最后一行不足的格子不可分配。
- `implicitWidth` / `implicitHeight` 是按基础 `panelSize` 计算的自然尺寸。
- 当画板被布局赋予实际宽高时，格子随画板伸展：

  ```text
  cellWidth  = (width  - (columns - 1) * gap) / columns
  cellHeight = (height - (rows    - 1) * gap) / rows
  ```

  画板未获得额外尺寸时，`cellWidth` / `cellHeight` 等于基础 `panelSize`。
- 只有全部组件释放后才能修改初始化参数；非法修改会被拒绝，保留原配置，原因在 `lastError`。
- 画板不强制绘制格线、背景或按钮。

主窗口启动时是 `180×180` 的透明鲸鱼娘悬浮立绘；点击后展开为 `528×300`（两个 `260×260` 的基础 panel 加 8 间距），或恢复上次展开尺寸。展开态没有全局标题栏，画板直接占满 `528×300`；放大窗口时日程与月历会一起变大，内容重排；缩小到 `528×300` 后停止。

## 悬浮框与自动缩回

- 启动时只显示透明背景的鲸鱼娘立绘，待机时眨眼和轻微上下浮动，鼠标进入会挥手；点击展开日程。
- 鼠标离开展开界面约 `400ms` 后开始缩回；内容淡出约 `180ms` 后再缩到 `180×180`。计时或淡出期间移回界面会取消缩回。
- 拖动悬浮框、日期头或月份头期间不会自动缩回。
- 展开态可以拖动边缘调整大小；缩回后再次点击，会恢复本次运行中上次的展开尺寸。
- 展开、拖动结束和缩放后，窗口会收回当前显示器的可用区域，避开任务栏。跨屏和工作区变化会更新边界；小屏幕不足 `528×300` 时降低最小尺寸，不强行撑出屏幕。移动和展开/返回动画进行中不强制纠正坐标，结束后再校正。
- 缩回只隐藏界面，不销毁任务数据；正常启动的任务数据自动保存到用户数据目录，详见 [日程设计与可靠性](schedule-design.md)。
- 展开态没有全局“悬浮日程”标题栏；日期头、月份头等由各自组件管理。没有最小化/关闭按钮，鼠标离开自动收起。悬浮框本身只响应点击展开、右键退出和拖动。

`main.py` 会在加载界面前调用 `polaris.qml.register_types()`。独立加载这些 QML 组件时，也必须先注册 Python 类型，并将 `qml` 目录加入引擎的导入路径。

## 桌宠式窗口

- 主窗口使用透明背景、`Qt.Tool`，并在 X11 下设置 `_NET_WM_STATE_SKIP_TASKBAR` 与 `_NET_WM_STATE_SKIP_PAGER`，不进入任务栏、分页器和 Alt+Tab 切换器。
- 展开后仍允许点击输入框取得键盘焦点；否则时间、任务名无法编辑。它不会作为普通应用窗口参与切换。
- 展开界面没有关闭/最小化按钮。右键任意位置弹出“退出”菜单；普通关闭请求（包括 Alt+F4）会被拦截，必须显式选择退出。
- 这些 X11 提示由 `polaris/x11_hints.py` 通过 EWMH 客户端消息设置；Wayland 下窗口切换器是否忽略 `Qt.Tool` 由 compositor 决定。
- 应用没有标题栏关闭按钮；右键菜单的“退出”是唯一的正常退出路径，避免把“关闭窗口”误认成“退出软件”。

### 日程与桌宠联动

日程组件的内存模型在增删任务、修改标题/时间/完成状态时发出 `scheduleChanged`；应用级 `InteractionCoordinator` 读取**全部日期**的任务（不依赖当前显示的日期），每 30 秒复查一次。运行期间，未完成的定时任务在开始前 10 分钟内提醒一次；新增或改时间后若落在窗口内会立即提醒，已过开始时间不补发，全天任务不提醒。任务 ID + 开始时间用于去重，删除或改时间后旧记录失效。

协调器只发出 `notification(kind, entryId, text)`，不直接操纵日程/桌宠界面。紧凑状态的鲸鱼娘在顶部展示约 6.5 秒的文字泡泡，期间透明窗口临时向上扩展 58px；展开日程时泡泡收起并恢复窗口位置。展开状态不展示泡泡（此时通知仍视为已发）。任务自动持久化；正常启动增加托盘原生通知。通知去重记录仍为内存状态，退出后无后台提醒。

## 拖动、交换与最小化

组件容器提供32px通用标题条，抓住标题条拖动即可按 cell 吸附，右侧 `−` 收起内容、`+` 恢复。
这由 `ComponentHost` / `ComponentBoard` 实现，不由日程或 Agent 各写一套。

- 拖到空位：保持原占格形状，原子移动；拖到一个组件：尝试交换双方原点。
- 只有双方原形状都放得下、且不覆盖第三个组件时才交换。越界、覆盖多个组件或形状不适配时回到原位，标题条短暂标红。
- 不旋转、不推挤、不自动排版，也不填充原位置留下的空 cell。
- 最小化仅隐藏内容，**保留原 cell 占用**及同一业务/界面实例，避免恢复时抢位；标题条仍能拖动。
- 输入框先失焦提交；弹出的编辑器、完整态过渡和拖动过程中禁止冲突操作。月历日期、未提交草稿与面板状态不会因最小化恢复而重置。
- 位置及最小化状态目前只在本次运行内保留，重启恢复默认布局，不写入日程 JSON。

调用方可用 `board.move(handle, column, row)` 和 `board.setMinimized(handle, bool)`。
底层 `PanelLayout.relocate` / `PanelAllocator.move` 一次提交所有受影响分配，失败不改变占用图或分配 ID。

## 申请与释放

```qml
Component {
    id: factory
    Rectangle {
        color: "lightblue"
        // 一个统一的局部坐标系；此对象始终只创建一个实例。
        readonly property var panels: parent.panelContext
    }
}

// 单格。options/properties 可省略。
const single = board.request(factory)

// 占用两个横向 panel。
const doublePanel = board.request(factory, {cells: [[0, 0], [1, 0]]})

// L 形，缺角仍可被其他组件申请。
const irregular = board.request(factory, {cells: [[0, 0], [1, 0], [0, 1]]})

if (irregular.ok) {
    console.log(irregular.id, irregular.allocation.regions)
    board.release(irregular)
} else {
    console.warn(irregular.error)
}
```

`cells` 必须是非空、无重复的非负整数坐标集合，坐标会平移归一化。支持矩形、L/T 形、孔洞和不连通的格子集合，不包含任意曲线轮廓。

分配按从上到下、从左到右寻找第一个可用位置，不旋转形状、不挪动已有组件。空间不足或组件创建失败时，申请全部回滚，不保留部分占用。

成功返回 `{ok, id, item, allocation, host}`；失败返回 `{ok: false, error}`。`item` 是业务组件实例；`allocation` 包含局部格子、位置、包围尺寸和请求时的基础区域。`freePanelCount` 可查询剩余容量。画板尺寸变化后，以 `host` 和 `panelContext` 的实时几何为准。

第三个参数可传给组件的初始化属性，包括组件声明的 required 属性：

```qml
Component {
    id: labeledFactory
    Rectangle { required property string caption }
}
const handle = board.request(labeledFactory, {cells: [[0, 0]]}, {caption: "示例"})
```

必须用原始成功 handle 调用 `board.release(handle)`；重复释放或其他画板的 handle 返回 false。不要直接 destroy 组件或修改 handle 的标识、host 和分配数据。

## 容器与内部自由度

`ComponentHost` 管理通用标题条、移动/收起、外部边界和生命周期，不规定组件内部控件、数据结构、布局或动画。

业务组件的根对象必须是 QML `Item`。组件放在标题条下方，宽高随内容区绑定；最小化不重建或缩小内容实例，只隐藏它。其父对象提供 `panelContext`：

- `width` / `height`：当前统一局部坐标系的包围尺寸，随画板尺寸变化。
- `cells`：相对占用格子。
- `regions`：相对内容区原点的可绘制、交互矩形集合。
- `outerRegions` / `headerHeight`：容器外部形状及标题条高度。
- `minimized`：当前是否仅显示标题条。

矩形组件直接渲染。不规则组件使用同一个内容实例的实时 `ShaderEffectSource` 分片，按互不重叠的矩形覆盖显示，不复制业务实例，不用矩形 clip 冒充不规则裁剪，也不依赖 GPU ShaderEffect 遮罩。为兼容软件渲染的高 DPI 镜像行为，各分片从统一原点正向捕获完整内容，在显示节点恢复纵向方向，再通过各自的矩形视口裁剪；多个完整内容纹理会增加内存与渲染开销，软件模式不承诺任意复杂动画的帧率。

区域尺寸由画板当前 `cellWidth`、`cellHeight` 和 `gap` 重新计算；画板缩放时，不规则组件的显示区域和输入边界一起更新。输入边界与显示区域一致：初始点击、悬停和滚轮不能借包围框覆盖孔洞；在区域内开始的鼠标拖动仍能收到区域外的释放事件。容器会为不规则区域合并子项的命中 mask，保留原有形状及其 QML binding，并支持动态子项及嵌套容器。混合了区域外新触点的触控事件会保守拒绝，不拆分成跨组件手势。

这是受信任 QML 组件的布局协议，不是安全沙箱。自行创建顶层 Window/Popup 等越界内容不受画板裁剪保护。Qt 软件后端本身不支持所有 GPU 特效，画板不会解除这一限制。

## 组件完整视图（独立于画布）

组件可在画布内完成所有常用操作，再通过明确入口请求独立的完整视图；完整视图不参与 panel 分配，也不改变原有占用。原有组件无需改造即可继续使用。

窗口层创建 `FocusPresenter { targetWindow: window; availableGeometry: window.availableGeometry }`，并设置 `board.presenter`。`availableGeometry` 由窗口的 `WindowBounds` 控制器从 `QScreen.availableGeometry()` 更新，使用当前显示器的可用矩形（含任务栏偏移），而非整个虚拟桌面。打开接口：

```qml
// 省略尺寸：覆盖当前画布，窗口大小不变。
board.present(handle, fullViewFactory, {}, {model: sharedModel})
// 期望 6×4 个基础 panel 的大小，与画布容量无关。
board.present(handle, fullViewFactory, {span: Qt.size(6, 4)}, {model: sharedModel})
// 也可直接指定逻辑像素尺寸。
board.present(handle, fullViewFactory, {size: Qt.size(1000, 720)}, {model: sharedModel})
// 组件发出请求时，窗口也可用业务 Item 查找原 handle。
board.presentItem(componentItem, fullViewFactory, options, properties)
```

`span` 必须是正整数宽高，按基础 `panelSize` 与 `gap` 换算，优先于 `size`；省略 `size` 或尺寸为零时保留原窗口对应尺寸。实际尺寸会按屏幕空间与窗口最小尺寸约束。完整视图必须以 `Item` 为根，自动绑定展示区域宽高，通过 `parent.presentationContext.close()` 返回。工厂及其数据模型应由长生命周期组件持有，不要在完整视图内重新创建业务数据。

管理器只接受一个活动请求；`present()` 的 true 表示已接受异步截图请求，不代表视图已经创建成功，最终由 `opened` / `failed(reason)` 信号报告。活动请求期间不能释放来源 handle。视图创建失败会恢复空闲状态，不改变画布占用。

过渡使用来源组件快照、背景扩张、内容交叉淡入淡出及窗口几何插值（320ms），不是拉伸活的控件。返回沿原路径恢复原始窗口位置和尺寸；快照是打开瞬间的视觉占位，真实画布一直保留，返回后显示最新数据。完整视图在返回时销毁，业务数据不销毁。

主窗口在完整态冻结画布尺寸、暂停自动缩回并禁止边缘缩放。点击返回或按 Esc 退出；过渡期间阻止重复切换。完整视图内部仍可自由布局、编辑和导航。第一版完整态为矩形区域；画布态的不规则区域能力不变。桌面实际动画效果以运行界面为准。

日程右上角的 `↗` 打开独立的 `4×3` 总览（月历 + 当日日程），窄窗口改为上下排列；两个视图共用同一个 `CalendarTaskStore`，日期和任务实时一致。原 `2×1` 日程的添加、编辑、子任务和月历切换保留。

## 两格日程组件

`CalendarTasks.qml` 占两个横向 panel，但默认只显示一个全宽的日程视图；月历藏在“月历”按钮后面，不占默认空间。

- 默认显示日期、星期和日程列表；没有任务时不显示空状态文案或插图，只保留右上角加号。
- 点击加号才展开时间/名称输入条；添加成功或按 `Esc` 后收起输入条。
- 点击“月历”进入全宽月历；选择日期或点击返回箭头回到日程。
- 月份箭头切换月份，“今天”回到当前日期并返回日程。
- 日期格显示未完成任务圆点；选中日期实心，今天使用橙色描边；全部完成时显示绿色圆点。
- 任务支持可选 `HH:mm` 时间；空时间为全天任务，按“全天优先、时间升序”排序。
- 点击任务左侧勾选框切换完成状态；已完成任务保留原位置，标题变淡并加删除线。
- 子任务同样可以勾选完成；任务行显示 `已完成/总数`，可折叠展开子任务。点背景收起编辑区域和子任务，未添加草稿保留；点击控件不误收起。
- 名称行内编辑，按 Enter 或失去焦点提交；空白名称不接受。时间点选弹层的小时/分钟滚轮，支持全天，不要求键入格式。
- `×` 删除对应任务/子任务，删除任务也会删除其子任务。
- 任务行不画外框，使用更大的外边距、行距和悬停底色留白。
- 切换日期保留其他日期数据；正常启动自动保存，失败会明确提示；删除主任务可单步撤销。
- 月切换使用方向感滑入，日期切换、任务增删、完成勾选和子任务展开都有短动效；不使用依赖着色器的模糊或阴影，保证软件渲染可用。

默认画布容量为 **2×2 四个 cell**，与实际占用数量分开。日程通过 `board.request` 申请 `[[0,0],[1,0]]` 两格，Agent 申请 `[[0,0]]` 一格，由分配器 first-fit 放到下一行；第四格保持空闲，不自动补写字板，不缩小画布，也不改成顶栏分页。默认日程内容528×300、Agent内容260×300，每个容器额外有32px通用标题条，整张画布528×672（8px间距）。

`Workspace.qml` 只组合组件及其申请，不为 Agent 绕开 `ComponentHost` 单独定位。其他组件仍可申请剩余 cell、多 cell 或不规则形状，分配/回滚/释放规则不变；`Notepad.qml` 仍可按需申请，但不会自动占空格。Agent 的 `↗` 与日程一样通过 `ComponentBoard.present` 打开独立完整态，不改变其画布 cell 占用。

包含运行期提前提醒、任务自动保存、待办搜索和日期输入改期；不包含重复日程、远程同步或拖拽改期。详见 [日程设计与可靠性](schedule-design.md)。日程时间只精确到分钟，不包含结束时间、地点和参与人。

## 文件

- `polaris/panels.py`：纯 Python 分配与不规则区域计算。
- `polaris/qt_board.py`：Qt 配置接口、实时区域计算和区域输入过滤。
- `polaris/tasks.py`：日期、时间、完成状态、共享日程、子任务、改期与删除撤销。
- `polaris/storage.py`：版本化快照、原子写入、备份与损坏保护。
- `polaris/desktop.py`：可选托盘菜单及系统原生提醒通道。
- `qml/components/TaskOverview.qml`、`StoreStatus.qml`：跨日期待办搜索、改期与保存/撤销反馈。
- `polaris/x11_hints.py`：X11 下把窗口标记为跳过任务栏、分页器和 Alt+Tab。
- `qml/components/PetMascot.qml`：鲸鱼娘待机、眨眼、浮动和悬停挥手动画。
- `assets/whale/`：鲸鱼娘素材、CC BY 4.0 授权文本和署名说明。
- `qml/components/ComponentBoard.qml`、`ComponentHost.qml`：画板、自适应格子和单实例容器。
- `qml/components/CalendarTasks.qml`：两格日程组件入口和配色布局。
- `qml/components/CalendarMonthView.qml`、`CalendarDayCell.qml`：月历、日期状态和任务圆点。
- `qml/components/AgendaPanel.qml`、`TaskCard.qml`：当日议程、快速添加和任务卡。
- `qml/components/IconButton.qml`、`InlineField.qml`、`TaskCheck.qml`：通用按钮、输入框和勾选框。
- `qml/components/Theme.js`：颜色、圆角和动效时长。
- `qml/Main.qml`：悬浮框、展开/缩回状态、动效和展开尺寸记忆。
- `qml/components/Notepad.qml`：可选的单格写字板组件。
- `qml/Polaris/plugins.qmltypes`：Python 公开接口的静态工具描述，接口修改时应同步更新。
