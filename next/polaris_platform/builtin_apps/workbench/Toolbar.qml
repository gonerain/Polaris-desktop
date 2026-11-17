import QtQuick
import QtQuick.Window
import Polaris.Ui 1.0 as Ui

Row {
    required property Item body
    readonly property var colors: workbenchTheme
    spacing: 5
    enabled: visible && workbenchActions.running
    Ui.Button { theme: colors; text: Window.window && Window.window.width < 760 ? '' : '整理布局'; hint: '整理布局'; glyph: 'board'; objectName: 'arrangeCanvas'; visible: !workbenchActions.empty; onClicked: workbenchActions.arrange(body.width) }
    Ui.Button { theme: colors; text: Window.window && Window.window.width < 760 ? '' : '添加组件'; hint: '添加组件'; glyph: 'plus'; objectName: 'chooseComponentView'; onClicked: workbenchActions.chooseView() }
}
