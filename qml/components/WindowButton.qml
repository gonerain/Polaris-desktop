import QtQuick
import QtQuick.Controls.Basic

AbstractButton {
    id: control

    property bool isCloseButton: false
    readonly property bool highlighted: hovered || down || activeFocus
    readonly property color iconColor: isCloseButton && highlighted ? "white" : "#526075"

    implicitWidth: 30
    implicitHeight: 28
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    text: isCloseButton ? qsTr("关闭") : qsTr("最小化")
    Accessible.name: text
    ToolTip.visible: hovered
    ToolTip.delay: 600
    ToolTip.text: text

    background: Rectangle {
        radius: 6
        color: control.down
            ? (control.isCloseButton ? "#c83e47" : "#d6dce6")
            : (control.highlighted
                ? (control.isCloseButton ? "#e4525c" : "#e4e8ef")
                : "transparent")

        Behavior on color {
            ColorAnimation { duration: 100 }
        }
    }

    contentItem: Item {
        Rectangle {
            anchors.centerIn: parent
            width: 13
            height: 1.6
            radius: 0.8
            antialiasing: true
            color: control.iconColor
            rotation: control.isCloseButton ? 45 : 0
        }

        Rectangle {
            anchors.centerIn: parent
            visible: control.isCloseButton
            width: 13
            height: 1.6
            radius: 0.8
            antialiasing: true
            color: control.iconColor
            rotation: -45
        }
    }
}
