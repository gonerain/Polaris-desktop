import QtQuick
import QtQuick.Controls.Basic as Controls

Controls.TextField {
    id: control
    required property QtObject theme
    implicitHeight: theme.controlHeight
    leftPadding: theme.spaceMedium; rightPadding: theme.spaceMedium
    font.pixelSize: theme.fontSizeBody
    color: enabled ? theme.ink : theme.muted
    placeholderTextColor: theme.muted
    selectionColor: theme.accent; selectedTextColor: theme.accentInk
    background: Rectangle {
        radius: control.theme.radiusSmall; color: control.theme.panel
        opacity: control.enabled ? 1 : 0.55
        border.width: control.activeFocus ? 2 : 1
        border.color: control.activeFocus ? control.theme.focus : control.theme.border
    }
}
