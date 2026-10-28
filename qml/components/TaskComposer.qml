pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

Rectangle {
    id: composer
    required property var taskStore
    property bool opened: false
    readonly property bool editBoundary: true
    signal submitted(int entryId)
    implicitHeight: 50
    visible: opened
    radius: 11
    color: Theme.surface
    border.color: "#D9DFFC"
    border.width: 1

    function open() {
        opened = true
        Qt.callLater(function() { titleInput.forceActiveFocus() })
    }
    function dismissEditors() { opened = false }
    function submit() {
        if (!titleInput.text.trim()) {
            titleInput.forceActiveFocus()
            return
        }
        const entry = taskStore.addTask(titleInput.text, timeInput.text)
        if (!entry) return
        const identity = entry.entryId
        titleInput.clear()
        timeInput.clear()
        opened = false
        submitted(identity)
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 6
        spacing: 7
        TimeField {
            id: timeInput
            objectName: "newTaskTimeInput"
            Layout.preferredWidth: 54
            chip: true
            placeholderText: qsTr("全天")
            horizontalAlignment: TextInput.AlignHCenter
            font.pixelSize: 11
            onTimeSelected: function(value) { text = value }
        }
        InlineField {
            id: titleInput
            objectName: "newTaskInput"
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            bare: true
            placeholderText: qsTr("想做什么？输入后按回车")
            font.pixelSize: 13
            onAccepted: composer.submit()
        }
        IconButton {
            objectName: "addTaskButton"
            text: qsTr("添加")
            textSize: 11
            buttonSize: 32
            filled: true
            onClicked: composer.submit()
        }
    }
    Shortcut {
        sequence: "Escape"
        enabled: composer.opened && composer.visible
                 && !(composer.Window.window && composer.Window.window.editorPopupCount > 0)
        onActivated: composer.dismissEditors()
    }
}
