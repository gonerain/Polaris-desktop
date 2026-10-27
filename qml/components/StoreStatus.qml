pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    required property var taskStore
    property bool showSavedHint: false
    readonly property bool hasError: !!taskStore.storageError
    readonly property bool hasNotice: !!taskStore.storageNotice
    visible: hasError || hasNotice || taskStore.canUndoDelete || showSavedHint
    implicitHeight: visible ? row.implicitHeight + 12 : 0
    color: hasError ? "#FFF1F0" : Theme.background
    radius: 8

    RowLayout {
        id: row
        anchors.fill: parent
        anchors.margins: 6
        spacing: 8
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: root.hasError ? root.taskStore.storageError
                : root.hasNotice ? root.taskStore.storageNotice
                : root.taskStore.canUndoDelete ? qsTr("已删除任务")
                : root.taskStore.storagePath ? qsTr("已自动保存到本机") : qsTr("本次会话")
            color: root.hasError ? Theme.danger : Theme.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        IconButton {
            visible: root.hasError
            text: qsTr("重试")
            buttonSize: 30
            textSize: 10
            accessibleName: qsTr("重试保存")
            onClicked: root.taskStore.retrySave()
        }
        IconButton {
            objectName: "undoDeleteButton"
            visible: root.taskStore.canUndoDelete
            text: qsTr("撤销")
            textSize: 10
            buttonSize: 30
            accessibleName: qsTr("撤销删除任务")
            onClicked: root.taskStore.undoDelete()
        }
        IconButton {
            visible: root.showSavedHint && !!root.taskStore.storagePath
            text: "…"
            buttonSize: 26
            accessibleName: qsTr("打开数据文件夹")
            tooltip: qsTr("打开数据文件夹，可复制日程文件备份")
            onClicked: Qt.openUrlExternally(root.taskStore.storageDirectoryUrl)
        }
    }
}
