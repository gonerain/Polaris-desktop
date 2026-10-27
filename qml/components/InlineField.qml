import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

TextField {
    id: field

    readonly property bool editBoundary: true
    property bool chip: false
    property bool bare: false
    property bool error: false

    implicitHeight: 28
    font.pixelSize: 12
    color: Theme.ink
    placeholderTextColor: Theme.subtle
    selectByMouse: true
    hoverEnabled: true
    leftPadding: 6
    rightPadding: 6

    background: Rectangle {
        radius: 7
        color: field.chip
            ? (field.activeFocus ? Theme.surface : "#F4F6FB")
            : field.bare
                ? (field.activeFocus ? Theme.surface : (field.hovered ? "#F7F8FC" : "transparent"))
                : (field.activeFocus || field.hovered ? Theme.surface : "transparent")
        border.width: field.error || field.activeFocus ? 1 : 0
        border.color: field.error ? Theme.danger : Theme.primary

        Behavior on color {
            ColorAnimation { duration: Theme.fast }
        }
    }
}
