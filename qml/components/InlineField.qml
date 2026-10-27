import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

TextField {
    id: field

    readonly property bool editBoundary: true
    readonly property bool editing: activeFocus && !readOnly
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
            ? (field.editing ? Theme.surface : "#F4F6FB")
            : field.bare
                ? (field.editing ? Theme.surface : (field.hovered ? "#F7F8FC" : Theme.clearSurface))
                : (field.editing || field.hovered ? Theme.surface : Theme.clearSurface)
        border.width: field.error || field.editing ? 1 : 0
        border.color: field.error ? Theme.danger : Theme.primary

        Behavior on color {
            ColorAnimation { duration: Theme.fast }
        }
    }
}
