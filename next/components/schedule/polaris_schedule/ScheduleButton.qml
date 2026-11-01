import QtQuick
import QtQuick.Controls.Basic
Button {
    id: control
    property bool selected: false
    implicitHeight: 28
    implicitWidth: Math.max(28, label.implicitWidth + 16)
    padding: 6
    contentItem: Text {
        id: label
        text: control.text
        textFormat: Text.PlainText
        color: control.selected ? '#4167b0' : '#65738b'
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 7
        color: control.down ? '#d8e5fa' : control.selected ? '#e6edfc' : control.hovered ? '#edf1f8' : 'transparent'
        border.width: control.activeFocus ? 1 : 0
        border.color: '#7596cf'
    }
}
