# Polaris.Ui QML 控件

北极星托管的画布窗口与应用视图可使用 `import Polaris.Ui 1.0 as Ui`；平台会为现有引擎注册模块路径。自行创建 `QQmlEngine` 时，在加载 QML 前调用 Python 的 `polaris_platform.ui.configure_qml_engine(engine)`。模块版本 `1.0` 表示控件 API 版本，独立于北极星平台版本。应用也可以继续使用自己的 QML 和控件。

主题由每个视图显式创建和传入，不是跨视图的全局单例。各控件继承相应 Qt Quick Controls 的属性、键盘交互与信号，例如 `Button.clicked`、`TextField.accepted` 和 `ComboBox.activated`。

| 类型 | Polaris.Ui 增加的属性 |
| --- | --- |
| `Theme` | `mode`：`dark`、`warm` 或 `light`；提供颜色、字号、间距、圆角和控件高度 token。 |
| `Icon` | 必填 `theme`；`kind` 图标名，`ink` 颜色。 |
| `Button` | 必填 `theme`；`glyph` 图标名（默认空，不显示图标），`primary` 主按钮样式，`truncateLabel` 文本截断，`hint` 提示。 |
| `NavigationItem` | 必填 `theme`；`glyph`、`selected`、`compact`、`hint`。 |
| `ScrollBar`、`TextField`、`ComboBox` | 必填 `theme`；其余属性和信号沿用对应 Qt 控件。 |

`Theme` 常用 token 包括 `panel`、`card`、`ink`、`muted`、`accent`、`error`、`focus`，以及 `fontSizeSmall/Body/Title`、`spaceSmall/Medium/Large`、`radiusSmall/Medium/Large`、`controlHeight`、`navigationHeight` 和 `iconSize`。

```qml
import QtQuick
import QtQuick.Layouts
import Polaris.Ui 1.0 as Ui

Item {
    width: 360; height: 120
    Ui.Theme { id: colors; mode: "dark" }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12
        Ui.TextField { id: query; theme: colors; Layout.fillWidth: true; placeholderText: "输入内容" }
        RowLayout {
            Layout.fillWidth: true
            Ui.ComboBox { id: choice; theme: colors; Layout.fillWidth: true; model: ["今天", "明天"] }
            Ui.Button { theme: colors; text: "确定"; glyph: "plus"; primary: true
                onClicked: console.log(query.text, choice.currentText) }
        }
    }
}
```
