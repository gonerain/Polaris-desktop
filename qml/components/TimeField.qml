pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

// Display-only field: selecting a time never requires typing HH:mm.
InlineField {
    id: field
    readOnly: true
    selectByMouse: false
    horizontalAlignment: TextInput.AlignHCenter
    placeholderText: qsTr("全天")
    Accessible.name: qsTr("选择时间")
    signal timeSelected(string value)

    function openPicker() {
        const parts = text.split(":")
        const now = new Date()
        const selectedHour = parts.length === 2 ? Number(parts[0]) : now.getHours()
        const selectedMinute = parts.length === 2 ? Number(parts[1]) : 0
        picker.open()
        // Position after the popup's wheel view has received its final size.
        Qt.callLater(function() {
            if (!picker.visible) return
            hour.wheelRemainder = 0
            minute.wheelRemainder = 0
            hour.currentIndex = selectedHour
            minute.currentIndex = selectedMinute
            hour.positionViewAtIndex(selectedHour, Tumbler.Center)
            minute.positionViewAtIndex(selectedMinute, Tumbler.Center)
        })
    }
    function choose(value) {
        picker.close()
        field.timeSelected(value)
    }
    TapHandler {
        acceptedButtons: Qt.LeftButton
        onTapped: field.openPicker()
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    Keys.onReturnPressed: function(event) { field.openPicker(); event.accepted = true }
    Keys.onEnterPressed: function(event) { field.openPicker(); event.accepted = true }
    Keys.onSpacePressed: function(event) { field.openPicker(); event.accepted = true }
    Keys.onDownPressed: function(event) { field.openPicker(); event.accepted = true }

    EditorPopup {
        id: picker
        objectName: "timePicker"
        anchorItem: field
        width: 248
        padding: 14
        implicitHeight: content.implicitHeight + 28
        background: Rectangle {
            color: Theme.surface
            radius: 12
            border.color: Theme.border
        }
        ColumnLayout {
            id: content
            anchors.fill: parent
            spacing: 14
            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: qsTr("时间")
                    color: Theme.ink
                    font.pixelSize: 13
                    Layout.fillWidth: true
                }
                IconButton {
                    objectName: "timeAllDayButton"
                    text: qsTr("全天")
                    textSize: 11
                    buttonSize: 28
                    accessibleName: qsTr("设为全天")
                    onClicked: field.choose("")
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                TimeWheel {
                    id: hour
                    objectName: "timePickerHour"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    model: 24
                    Accessible.name: qsTr("小时")
                }
                Text { text: ":"; color: Theme.muted; font.pixelSize: 20 }
                TimeWheel {
                    id: minute
                    objectName: "timePickerMinute"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 150
                    model: 60
                    Accessible.name: qsTr("分钟")
                }
            }
            RowLayout {
                Layout.fillWidth: true
                IconButton {
                    text: qsTr("现在")
                    textSize: 11
                    buttonSize: 28
                    accessibleName: qsTr("选当前时间")
                    onClicked: {
                        const now = new Date()
                        hour.currentIndex = now.getHours()
                        minute.currentIndex = now.getMinutes()
                    }
                }
                Item { Layout.fillWidth: true }
                IconButton {
                    objectName: "timeConfirmButton"
                    text: qsTr("确定")
                    textSize: 12
                    buttonSize: 30
                    filled: true
                    accessibleName: qsTr("确定时间")
                    onClicked: field.choose(String(hour.currentIndex).padStart(2, "0")
                                           + ":" + String(minute.currentIndex).padStart(2, "0"))
                }
            }
        }
    }
}
