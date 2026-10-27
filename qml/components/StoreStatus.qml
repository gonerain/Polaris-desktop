pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    objectName: "storeStatus"
    required property var taskStore
    readonly property bool hasError: !!taskStore.storageError
    readonly property bool hasNotice: !!taskStore.storageNotice
    visible: hasError || hasNotice || taskStore.canUndoDelete
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
                : root.taskStore.canUndoDelete ? qsTr("已删除任务") : ""
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
    }
}
