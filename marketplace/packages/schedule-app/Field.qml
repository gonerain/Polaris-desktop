import QtQuick
import QtQuick.Controls.Basic
TextField {
    id: field
    required property var colors
    implicitHeight: 36
    leftPadding: 10; rightPadding: 10
    color: colors.text; placeholderTextColor: colors.muted
    selectionColor: colors.accent; selectedTextColor: colors.onAccent
    selectByMouse: true
    font.pixelSize: 12
    background: Rectangle { radius: 7; color: field.colors.raised; border.width: field.activeFocus?2:1; border.color: field.activeFocus?field.colors.accent:field.colors.line }
}
