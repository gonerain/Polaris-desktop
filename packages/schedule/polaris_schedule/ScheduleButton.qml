import QtQuick
import QtQuick.Controls.Basic
Button {
    id: control
    property var appearance: null
    SchedulePalette { id: fallback }
    readonly property var colors: appearance || fallback
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    property bool selected: false
    implicitHeight: 28
    implicitWidth: Math.max(28, label.implicitWidth + 16)
    padding: 6
    contentItem: Text {
        id: label
        text: control.text
        textFormat: Text.PlainText
        color: !control.enabled ? colors.muted : control.selected ? colors.accent : colors.text
        font.pixelSize: 12
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 7
        color: control.down ? colors.selected : control.selected ? colors.selected : control.hovered ? colors.hover : 'transparent'
        opacity: control.enabled ? 1 : 0.45
        border.width: control.visualFocus ? 2 : 0
        border.color: colors.accent
    }
}
