# 组件画板

## 运行与验证

项目使用 Python + PySide6 / Qt Quick。依赖固定为已通过退出回归测试的 `PySide6-Essentials==6.8.3`，不需要 WebEngine。

```bash
.venv/bin/python -m pip install -r requirements.txt
QT_QUICK_BACKEND=software .venv/bin/python main.py
```

当前桌面驱动曾发生过故障，暂用软件渲染运行；自动测试不得连接真实桌面或注入全局鼠标事件。

```bash
.venv/bin/python -m unittest -v
.venv/bin/pyside6-qmllint -I qml qml/Main.qml qml/components/*.qml
```

GUI 测试入口强制 `offscreen`、软件渲染并清除显示服务环境变量。离屏事件测试不等于真实窗口管理器的拖动、缩放验证。

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

主窗口启动时是 `180×180` 的透明鲸鱼娘悬浮立绘；点击后展开为 `528×300`（两个 `260×260` 的基础 panel 加 8 间距），或恢复上次展开尺寸。展开态标题栏高 `44px`，画板内容高 `256px`；放大窗口时日程与月历会一起变大，内容重排；缩小到 `528×300` 后停止。

## 悬浮框与自动缩回

- 启动时只显示透明背景的鲸鱼娘立绘，待机时眨眼和轻微上下浮动，鼠标进入会挥手；点击展开日程。
- 鼠标离开展开界面约 `400ms` 后开始缩回；内容淡出约 `180ms` 后再缩到 `180×180`。计时或淡出期间移回界面会取消缩回。
- 拖动悬浮框或展开态标题栏期间不会自动缩回。
- 展开态可以拖动边缘调整大小；缩回后再次点击，会恢复本次运行中上次的展开尺寸。
- 缩回只隐藏界面，不销毁任务数据；再次展开仍能看到本次运行中的任务。关闭应用后数据仍不保留。
- 展开态标题栏不再提供最小化/关闭按钮；鼠标离开自动收起。悬浮框本身只响应点击展开、右键退出和拖动。

`main.py` 会在加载界面前调用 `polaris.qml.register_types()`。独立加载这些 QML 组件时，也必须先注册 Python 类型，并将 `qml` 目录加入引擎的导入路径。

## 桌宠式窗口

- 主窗口使用透明背景、`Qt.Tool`，并在 X11 下设置 `_NET_WM_STATE_SKIP_TASKBAR` 与 `_NET_WM_STATE_SKIP_PAGER`，不进入任务栏、分页器和 Alt+Tab 切换器。
- 展开后仍允许点击输入框取得键盘焦点；否则时间、任务名无法编辑。它不会作为普通应用窗口参与切换。
- 标题栏没有关闭/最小化按钮。右键任意位置弹出“退出”菜单；普通关闭请求（包括 Alt+F4）会被拦截，必须显式选择退出。
- 这些 X11 提示由 `polaris/x11_hints.py` 通过 EWMH 客户端消息设置；Wayland 下窗口切换器是否忽略 `Qt.Tool` 由 compositor 决定。
- 应用没有标题栏关闭按钮；右键菜单的“退出”是唯一的正常退出路径，避免把“关闭窗口”误认成“退出软件”。

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

`ComponentHost` 只管理位置、外部边界和生命周期，不规定组件内部控件、数据结构、布局或动画。

业务组件的根对象必须是 QML `Item`。初始位置为容器原点，宽高随容器绑定。其父对象提供 `panelContext`：

- `width` / `height`：当前统一局部坐标系的包围尺寸，随画板尺寸变化。
- `cells`：相对占用格子。
- `regions`：当前真正可绘制、交互的局部矩形集合。

矩形组件直接渲染。不规则组件使用同一个内容实例的实时 `ShaderEffectSource` 分片，按互不重叠的矩形覆盖显示，不复制业务实例，不用矩形 clip 冒充不规则裁剪，也不依赖 GPU ShaderEffect 遮罩。为兼容软件渲染的高 DPI 镜像行为，各分片从统一原点正向捕获完整内容，在显示节点恢复纵向方向，再通过各自的矩形视口裁剪；多个完整内容纹理会增加内存与渲染开销，软件模式不承诺任意复杂动画的帧率。

区域尺寸由画板当前 `cellWidth`、`cellHeight` 和 `gap` 重新计算；画板缩放时，不规则组件的显示区域和输入边界一起更新。输入边界与显示区域一致：初始点击、悬停和滚轮不能借包围框覆盖孔洞；在区域内开始的鼠标拖动仍能收到区域外的释放事件。容器会为不规则区域合并子项的命中 mask，保留原有形状及其 QML binding，并支持动态子项及嵌套容器。混合了区域外新触点的触控事件会保守拒绝，不拆分成跨组件手势。

这是受信任 QML 组件的布局协议，不是安全沙箱。自行创建顶层 Window/Popup 等越界内容不受画板裁剪保护。Qt 软件后端本身不支持所有 GPU 特效，画板不会解除这一限制。

## 两格日程组件

`CalendarTasks.qml` 占两个横向 panel，但默认只显示一个全宽的日程视图；月历藏在“月历”按钮后面，不占默认空间。

- 默认显示日期、星期和日程列表；没有任务时不显示空状态文案或插图，只保留右上角加号。
- 点击加号才展开时间/名称输入条；添加成功或按 `Esc` 后收起输入条。
- 点击“月历”进入全宽月历；选择日期或点击返回箭头回到日程。
- 月份箭头切换月份，“今天”回到当前日期并返回日程。
- 日期格显示未完成任务圆点；选中日期实心，今天使用橙色描边；全部完成时显示绿色圆点。
- 任务支持可选 `HH:mm` 时间；空时间为全天任务，按“全天优先、时间升序”排序。
- 点击任务左侧勾选框切换完成状态；已完成任务保留原位置，标题变淡并加删除线。
- 子任务同样可以勾选完成；任务行显示 `已完成/总数`，可折叠展开子任务。
- 直接编辑名称和时间，按 Enter 或失去焦点提交；空白名称不接受。
- `×` 删除对应任务/子任务，删除任务也会删除其子任务。
- 任务行不画外框，使用更大的外边距、行距和悬停底色留白。
- 切换日期保留其他日期的内存数据；关闭应用后数据不保留。
- 月切换使用方向感滑入，日期切换、任务增删、完成勾选和子任务展开都有短动效；不使用依赖着色器的模糊或阴影，保证软件渲染可用。

默认主窗口只申请 2 个 panel，全部给日程组件；不创建之前占位的写字板 panel，也不存在 2×2 网格里空出来的第 4 格。`Notepad.qml` 仍保留为可申请的单格组件，只是默认不占用画板。

不包含提醒、重复日程、保存、远程同步或拖拽改期。日程时间只精确到分钟，不包含结束时间、地点和参与人。

## 文件

- `polaris/panels.py`：纯 Python 分配与不规则区域计算。
- `polaris/qt_board.py`：Qt 配置接口、实时区域计算和区域输入过滤。
- `polaris/tasks.py`：日期、时间、完成状态、内存日程与子任务逻辑。
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
