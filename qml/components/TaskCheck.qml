import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

AbstractButton {
    id: control

    property bool checkedState: false
    property string accessibleName: ""
    signal toggleRequested(bool next)

    implicitWidth: 20
    implicitHeight: 20
    hoverEnabled: true
    focusPolicy: Qt.TabFocus
    padding: 0
    Accessible.role: Accessible.CheckBox
    Accessible.name: control.accessibleName
    Accessible.checked: control.checkedState

    onClicked: control.toggleRequested(!control.checkedState)

    background: Rectangle {
        radius: 5
        color: control.checkedState
            ? (control.down ? Theme.primaryDark : Theme.primary)
            : (control.hovered || control.activeFocus ? Theme.primarySoft : Theme.surface)
        border.width: control.checkedState ? 0 : 1
        border.color: control.hovered || control.activeFocus ? Theme.primary : "#D9DFEA"

        Behavior on color {
            ColorAnimation { duration: Theme.fast }
        }
    }

    contentItem: Text {
        text: "✓"
        color: "white"
        font.pixelSize: 12
        font.weight: Font.Bold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        opacity: control.checkedState ? 1 : 0
        scale: control.checkedState ? 1 : 0.55

        Behavior on opacity {
            NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
        }
        Behavior on scale {
            NumberAnimation { duration: 160; easing.type: Easing.OutBack }
        }
    }
}
