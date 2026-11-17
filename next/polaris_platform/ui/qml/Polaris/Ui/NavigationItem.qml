import QtQuick
import QtQuick.Controls.Basic as Controls
import QtQuick.Layouts

Controls.ItemDelegate {
    id: control
    required property QtObject theme
    property string glyph: "board"
    property bool selected: false
    property bool compact: false
    property string hint: text
    implicitHeight: theme.navigationHeight
    implicitWidth: 192
    hoverEnabled: true; focusPolicy: Qt.StrongFocus
    leftPadding: theme.spaceMedium; rightPadding: 10
    Accessible.name: hint
    readonly property bool hintVisible: (hovered || visualFocus) && (compact || label.truncated)
    Controls.ToolTip {
        visible: control.hintVisible; delay: 650
        contentItem: Text { text: control.hint; textFormat: Text.PlainText; color: control.theme.ink }
        background: Rectangle { radius: control.theme.radiusSmall; color: control.theme.card; border.color: control.theme.border }
    }
    contentItem: RowLayout {
        opacity: control.enabled ? 1 : 0.42
        spacing: 10
        Icon { theme: control.theme; width: 17; height: 17; visible: control.glyph.length > 0; kind: control.glyph; ink: control.selected ? control.theme.selectedInk : control.theme.muted }
        Text {
            id: label
            Layout.fillWidth: true; visible: !control.compact
            text: control.text; textFormat: Text.PlainText; elide: Text.ElideRight
            color: control.selected ? control.theme.selectedInk : control.theme.muted
            font.pixelSize: control.theme.fontSizeBody; font.weight: control.selected ? Font.DemiBold : Font.Medium
        }
    }
    background: Rectangle {
        radius: control.theme.radiusSmall
        opacity: control.enabled ? 1 : 0.42
        color: control.selected ? control.theme.selected : control.down ? control.theme.pressed : control.hovered ? control.theme.hover : "transparent"
        border.width: control.visualFocus ? 1 : 0; border.color: control.theme.focus
    }
}
