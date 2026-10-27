import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

AbstractButton {
    id: control

    property bool isCloseButton: false
    readonly property bool highlighted: hovered || down || activeFocus
    readonly property color iconColor: isCloseButton && highlighted ? "white" : (highlighted ? Theme.ink : Theme.muted)

    implicitWidth: 28
    implicitHeight: 26
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    text: isCloseButton ? qsTr("关闭") : qsTr("最小化")
    Accessible.name: text
    ToolTip.visible: hovered
    ToolTip.delay: 600
    ToolTip.text: text

    scale: down ? 0.93 : 1
    Behavior on scale {
        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
    }

    background: Rectangle {
        radius: 7
        color: control.down
            ? (control.isCloseButton ? "#D93B45" : "#E8ECF7")
            : (control.highlighted
                ? (control.isCloseButton ? Theme.danger : Theme.primarySoft)
                : "transparent")

        Behavior on color {
            ColorAnimation { duration: Theme.fast }
        }
    }

    contentItem: Item {
        Rectangle {
            anchors.centerIn: parent
            width: 12
            height: 1.6
            radius: 0.8
            antialiasing: true
            color: control.iconColor
            rotation: control.isCloseButton ? 45 : 0
        }

        Rectangle {
            anchors.centerIn: parent
            visible: control.isCloseButton
            width: 12
            height: 1.6
            radius: 0.8
            antialiasing: true
            color: control.iconColor
            rotation: -45
        }
    }
}
