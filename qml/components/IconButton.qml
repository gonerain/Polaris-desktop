import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

AbstractButton {
    id: control

    property bool destructive: false
    property bool filled: false
    property int buttonSize: 26
    property int textSize: 14
    property string accessibleName: ""
    property string tooltip: ""

    implicitWidth: Math.max(buttonSize, label.implicitWidth + 12)
    implicitHeight: buttonSize
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    Accessible.name: control.accessibleName.length > 0 ? control.accessibleName : control.text
    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.text: tooltip
    ToolTip.delay: 600

    scale: down ? 0.93 : 1
    Behavior on scale {
        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
    }

    background: Rectangle {
        radius: 7
        color: control.filled
            ? (control.down ? Theme.primaryDark : (control.hovered ? Theme.primaryDark : Theme.primary))
            : control.down
                ? (control.destructive ? "#FDE8E8" : "#E8ECF7")
                : control.hovered
                    ? (control.destructive ? "#FEF2F2" : Theme.primarySoft)
                    : "transparent"

        Behavior on color {
            ColorAnimation { duration: Theme.fast }
        }
    }

    contentItem: Text {
        id: label
        text: control.text
        font.pixelSize: control.textSize
        font.weight: control.filled ? Font.DemiBold : Font.Medium
        color: control.filled
            ? "white"
            : control.destructive
                ? (control.hovered ? Theme.danger : Theme.muted)
                : (control.hovered ? Theme.primary : Theme.muted)
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter

        Behavior on color {
            ColorAnimation { duration: Theme.fast }
        }
    }
}
