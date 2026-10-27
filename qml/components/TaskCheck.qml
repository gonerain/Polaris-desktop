import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

AbstractButton {
    id: control

    readonly property bool editBoundary: true
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

    contentItem: Item {
        // Vector strokes render consistently even when the system font lacks ✓.
        Rectangle {
            x: parent.width / 2 - 6
            y: parent.height / 2 - 1
            width: 5
            height: 2
            radius: 1
            color: "white"
            rotation: 45
            transformOrigin: Item.Left
        }
        Rectangle {
            x: parent.width / 2 - 2.5
            y: parent.height / 2 + 2.5
            width: 9
            height: 2
            radius: 1
            color: "white"
            rotation: -45
            transformOrigin: Item.Left
        }
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
