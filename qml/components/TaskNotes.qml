pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

TextArea {
    id: notes
    required property var entry
    property var editingTask: null
    readonly property bool editBoundary: true
    objectName: "taskNotesInput"
    implicitHeight: Math.max(96, contentHeight + topPadding + bottomPadding)
    padding: 10
    font.pixelSize: 12
    color: Theme.ink
    placeholderText: qsTr("下次从哪里继续？记一句下一步，或留下需要的资料。")
    placeholderTextColor: Theme.muted
    wrapMode: TextEdit.Wrap
    selectByMouse: true
    persistentSelection: false
    background: Rectangle {
        radius: 8
        color: "#F7F8FC"
        border.color: notes.activeFocus ? Theme.primary : Theme.border
    }
    function commit() {
        const task = editingTask
        editingTask = null
        if (task) task.setNotes(text)
    }
    onEntryChanged: { commit(); text = entry ? entry.notes : "" }
    onActiveFocusChanged: {
        if (activeFocus) editingTask = entry
        else commit()
    }
    Component.onCompleted: text = entry ? entry.notes : ""
    Component.onDestruction: commit()
    Connections {
        target: notes.entry
        function onNotesChanged() {
            if (!notes.activeFocus) notes.text = notes.entry ? notes.entry.notes : ""
        }
    }
}
