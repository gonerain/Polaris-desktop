pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

EditorPopup {
    id: root
    required property var sync
    width: 340
    padding: 16
    background: Rectangle { color: Theme.surface; radius: 12; border.color: Theme.border }
    contentItem: ColumnLayout {
        spacing: 10
        Text { text: qsTr("OneDrive 日程同步 · 预览版"); color: Theme.ink; font.bold: true }
        Label {
            Layout.fillWidth: true
            text: qsTr("仅同步日程、任务与笔记，不同步聊天。云端暂为明文；并发编辑保留冲突副本。历史检查点暂不自动清理。")
            wrapMode: Text.Wrap
            color: Theme.muted
            font.pixelSize: 11
        }
        TextField {
            id: clientId
            Layout.fillWidth: true
            placeholderText: qsTr("微软应用 Client ID")
            text: root.sync ? root.sync.clientId : ""
            enabled: !!root.sync && !root.sync.busy && !root.sync.connected
            selectByMouse: true
        }
        Label {
            Layout.fillWidth: true
            text: qsTr("需注册自己的公共客户端应用并允许设备代码登录。凭证仅保留在内存，重启需重新登录。详见 docs/onedrive-sync.md。")
            wrapMode: Text.Wrap
            color: Theme.muted
            font.pixelSize: 11
        }
        Label {
            Layout.fillWidth: true
            text: root.sync ? root.sync.status : qsTr("尚未初始化本地存储")
            wrapMode: Text.Wrap
            color: Theme.ink
            font.pixelSize: 12
        }
        TextField {
            Layout.fillWidth: true
            visible: !!root.sync && root.sync.userCode.length > 0
            text: root.sync ? root.sync.userCode : ""
            readOnly: true
            selectByMouse: true
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 22
        }
        Button {
            visible: !!root.sync && root.sync.loginUrl.length > 0
            text: qsTr("打开微软登录页面")
            onClicked: Qt.openUrlExternally(root.sync.loginUrl)
        }
        CheckBox {
            text: qsTr("登录后每分钟自动同步")
            checked: !!root.sync && root.sync.autoSync
            enabled: !!root.sync && !root.sync.busy
            onToggled: root.sync.setAutoSync(checked)
        }
        RowLayout {
            Button {
                text: root.sync && root.sync.connected ? qsTr("立即同步") : qsTr("登录并允许同步")
                enabled: !!root.sync && !root.sync.busy
                onClicked: {
                    if (root.sync.connected) root.sync.syncNow()
                    else root.sync.connectAccount(clientId.text)
                }
            }
            Button {
                text: root.sync && root.sync.busy ? qsTr("取消") : qsTr("断开")
                enabled: !!root.sync && (root.sync.busy || root.sync.connected)
                onClicked: {
                    if (root.sync.busy) root.sync.cancel()
                    else root.sync.disconnectAccount()
                }
            }
        }
    }
}
