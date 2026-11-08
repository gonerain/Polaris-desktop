import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: picker
    property var appearance: null
    SchedulePalette { id: fallback }
    readonly property var colors: appearance || fallback
    property string selectedTime: ''
    signal timeSelected(string value)
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(280, parent ? parent.width - 16 : 280)
    padding: 14; modal: true; focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { radius: 12; color: picker.colors.surface; border.color: picker.colors.border }
    Overlay.modal: Rectangle { color: '#66000000' }
    function pad(value) { return String(value).padStart(2, '0') }
    function validPart(text, maximum) { return /^\d{1,2}$/.test(text) && Number(text) <= maximum }
    onOpened: {
        var valid = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(selectedTime)
        var h = valid ? Number(selectedTime.slice(0, 2)) : 9
        var m = valid ? Number(selectedTime.slice(3, 5)) : 0
        hours.currentIndex = h; hours.editText = pad(h)
        minutes.currentIndex = m % 5 === 0 ? m / 5 : -1; minutes.editText = pad(m)
    }
    component TimePart: ComboBox {
        id: control
        property int maximum: 23
        editable: true; flat: true; selectTextByMouse: true
        implicitHeight: 36; font.pixelSize: 15
        leftPadding: 0; rightPadding: 27
        inputMethodHints: Qt.ImhDigitsOnly
        validator: IntValidator { bottom: 0; top: control.maximum }
        palette.text: picker.colors.text; palette.buttonText: picker.colors.text
        palette.highlight: picker.colors.accent; palette.highlightedText: picker.colors.onAccent
        background: Rectangle { radius: 8; color: picker.colors.raised; border.width: control.activeFocus ? 2 : 1; border.color: control.activeFocus ? picker.colors.accent : picker.colors.border }
        indicator: Text { x: control.width - width - 10; anchors.verticalCenter: parent.verticalCenter; text: '⌄'; color: picker.colors.muted; font.pixelSize: 16 }
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            objectName: control.objectName + 'Option_' + index
            width: control.width; height: 30
            highlighted: control.highlightedIndex === index
            contentItem: Text { text: modelData; color: picker.colors.text; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter }
            background: Rectangle { radius: 5; color: parent.highlighted || parent.hovered ? picker.colors.raised : 'transparent' }
        }
        popup: Popup {
            y: control.height + 3; width: control.width; padding: 4
            implicitHeight: Math.min(188, contentItem.implicitHeight + 8)
            onOpened: contentItem.positionViewAtIndex(Math.max(0, control.currentIndex), ListView.Center)
            contentItem: ListView {
                clip: true; implicitHeight: contentHeight
                model: control.popup.visible ? control.delegateModel : null
                currentIndex: control.highlightedIndex
                ScrollBar.vertical: ScrollBar {
                    id: bar; padding: 2; visible: size > 0 && size < 1
                    contentItem: Rectangle { implicitWidth: 4; radius: 2; color: picker.colors.muted; opacity: bar.pressed ? 0.8 : 0.4 }
                    background: Item { }
                }
            }
            background: Rectangle { radius: 9; color: picker.colors.surface; border.color: picker.colors.border }
        }
    }
    contentItem: ColumnLayout {
        spacing: 10
        Text { text: '选择时间'; color: picker.colors.text; font.pixelSize: 15; font.weight: Font.DemiBold }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            ColumnLayout {
                Layout.fillWidth: true; spacing: 5
                Text { text: '小时'; color: picker.colors.muted; font.pixelSize: 12 }
                TimePart { id: hours; objectName: 'timePickerHours'; Layout.fillWidth: true; model: Array.from({length:24}, function(_, i) { return picker.pad(i) }); Accessible.name: '小时' }
            }
            Text { text: ':'; color: picker.colors.muted; font.pixelSize: 18; Layout.topMargin: 18 }
            ColumnLayout {
                Layout.fillWidth: true; spacing: 5
                Text { text: '分钟'; color: picker.colors.muted; font.pixelSize: 12 }
                TimePart { id: minutes; objectName: 'timePickerMinutes'; maximum: 59; Layout.fillWidth: true; model: Array.from({length:12}, function(_, i) { return picker.pad(i * 5) }); Accessible.name: '分钟' }
            }
        }
        Text { Layout.fillWidth: true; wrapMode: Text.Wrap; text: '分钟可直接输入 0–59'; color: picker.colors.muted; font.pixelSize: 11 }
        RowLayout {
            Layout.fillWidth: true
            ScheduleButton { appearance: picker.colors; objectName: 'clearPickedTime'; text: '清除时间'; onClicked: { picker.timeSelected(''); picker.close() } }
            Item { Layout.fillWidth: true }
            ScheduleButton { appearance: picker.colors; objectName: 'cancelPickedTime'; text: '取消'; onClicked: picker.close() }
            ScheduleButton {
                appearance: picker.colors; objectName: 'applyPickedTime'; text: '设定'; selected: true
                enabled: picker.validPart(hours.editText, 23) && picker.validPart(minutes.editText, 59)
                onClicked: { picker.timeSelected(picker.pad(Number(hours.editText)) + ':' + picker.pad(Number(minutes.editText))); picker.close() }
            }
        }
    }
}
