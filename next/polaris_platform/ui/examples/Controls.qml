import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Polaris.Ui 1.0 as Ui

Rectangle {
    id: root
    implicitWidth: 800; implicitHeight: 620
    property alias mode: tokens.mode
    property int actionCount: 0
    color: tokens.panel
    Ui.Theme { id: tokens }
    RowLayout {
        anchors.fill: parent; anchors.margins: tokens.spaceLarge; spacing: tokens.spaceLarge
        Rectangle {
            Layout.preferredWidth: root.width < 640 ? 140 : 184; Layout.fillHeight: true
            color: tokens.sidebar; radius: tokens.radiusMedium
            ColumnLayout {
                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: tokens.spaceMedium; spacing: 6
                Text { text: 'Polaris Ui'; color: tokens.ink; font.pixelSize: tokens.fontSizeTitle; font.weight: Font.DemiBold; Layout.bottomMargin: 16 }
                Ui.NavigationItem { objectName: 'uiNavigation'; theme: tokens; Layout.fillWidth: true; text: '工作空间'; glyph: 'board'; selected: true }
                Ui.NavigationItem { theme: tokens; Layout.fillWidth: true; text: '一个名称较长的导航条目'; glyph: 'apps' }
                Ui.NavigationItem { objectName: 'uiDisabledNavigation'; theme: tokens; Layout.fillWidth: true; text: '不可用条目'; glyph: 'settings'; enabled: false }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
            Text { text: '基础控件'; color: tokens.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
            Text { text: '统一的色彩、间距与交互状态'; color: tokens.muted; font.pixelSize: tokens.fontSizeBody }
            Flow {
                Layout.fillWidth: true; spacing: 6
                Ui.Button { objectName: 'uiThemeDark'; theme: tokens; glyph: ''; text: '石墨'; onClicked: tokens.mode = 'dark' }
                Ui.Button { objectName: 'uiThemeLight'; theme: tokens; text: '雾白'; onClicked: tokens.mode = 'light' }
                Ui.Button { objectName: 'uiThemeWarm'; theme: tokens; glyph: ''; text: '暖砂'; onClicked: tokens.mode = 'warm' }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: tokens.border }
            Text { text: '文本输入'; color: tokens.ink; font.pixelSize: tokens.fontSizeBody }
            Ui.TextField { objectName: 'uiField'; theme: tokens; Layout.fillWidth: true; placeholderText: '输入名称' }
            Text { text: '选择'; color: tokens.ink; font.pixelSize: tokens.fontSizeBody }
            Ui.ComboBox { objectName: 'uiCombo'; theme: tokens; Layout.fillWidth: true; model: ['选项一', '选项二', '选项三'] }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Ui.Button { objectName: 'uiButton'; theme: tokens; text: '普通按钮'; glyph: 'plus'; onClicked: root.actionCount += 1 }
                Ui.Button { objectName: 'uiPrimary'; theme: tokens; text: '主要操作'; glyph: 'right'; primary: true; onClicked: root.actionCount += 1 }
                Ui.Button { objectName: 'uiDisabledButton'; theme: tokens; text: '不可用'; glyph: ''; enabled: false; onClicked: root.actionCount += 1 }
            }
            Ui.Button { objectName: 'uiTruncatedButton'; theme: tokens; width: Math.min(230, parent.width); text: '这是一段用于展示布局截断的较长按钮名称'; glyph: ''; hint: text }
            Flickable {
                objectName: 'uiScrollArea'; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 60
                contentHeight: 260; clip: true
                Column {
                    width: parent.width; spacing: 12
                    Repeater {
                        model: 6
                        Rectangle { required property int index; width: parent.width - 14; height: 36; radius: tokens.radiusSmall; color: tokens.card
                            Text { anchors.left: parent.left; anchors.leftMargin: 12; anchors.verticalCenter: parent.verticalCenter; text: '内容区域 ' + (index + 1); color: tokens.muted; font.pixelSize: tokens.fontSizeSmall }
                        }
                    }
                }
                ScrollBar.vertical: Ui.ScrollBar { objectName: 'uiScrollBar'; theme: tokens; policy: ScrollBar.AlwaysOn }
            }
        }
    }
}
