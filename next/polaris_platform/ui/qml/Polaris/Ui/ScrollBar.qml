import QtQuick
import QtQuick.Controls.Basic as Controls

Controls.ScrollBar {
    id: control
    required property QtObject theme
    padding: 3
    minimumSize: 0.12
    visible: policy === Controls.ScrollBar.AlwaysOn || (policy === Controls.ScrollBar.AsNeeded && size > 0 && size < 1)
    contentItem: Rectangle {
        implicitWidth: 6; implicitHeight: 6; radius: 3
        color: control.pressed ? control.theme.accent : control.theme.scrollThumb
        opacity: !control.enabled ? 0.35 : control.hovered || control.pressed ? 1 : 0.65
    }
    background: Rectangle { color: "transparent" }
}
