import QtQuick
import QtQuick.Controls.Basic as Controls

Controls.Button {
    id: control
    required property QtObject theme
    property string glyph: ""
    property bool primary: false
    property bool truncateLabel: true
    property string hint: text
    implicitHeight: theme.controlHeight
    implicitWidth: text.length ? (glyph.length ? theme.iconSize + theme.spaceSmall : 0) + label.implicitWidth + 26 : 32
    padding: 0
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: hint.length ? hint : text
    readonly property bool hintVisible: hint.length > 0 && (hovered || (visualFocus && (!text.length || label.truncated)))
    Controls.ToolTip {
        visible: control.hintVisible; delay: 650
        contentItem: Text { text: control.hint; textFormat: Text.PlainText; color: control.theme.ink }
        background: Rectangle { radius: control.theme.radiusSmall; color: control.theme.card; border.color: control.theme.border }
    }
    contentItem: Item {
        opacity: control.enabled ? 1 : 0.42
        clip: true
        Row {
            spacing: control.theme.spaceSmall
            anchors.centerIn: parent
            Icon {
                visible: control.glyph.length > 0
                theme: control.theme; anchors.verticalCenter: parent.verticalCenter
                kind: control.glyph; ink: control.primary ? control.theme.accentInk : control.theme.muted
            }
            Text {
                id: label
                width: control.truncateLabel ? Math.min(implicitWidth, Math.max(0, control.width - (control.glyph.length ? control.theme.iconSize + control.theme.spaceSmall : 0) - 26)) : implicitWidth
                visible: control.text.length > 0
                text: control.text; textFormat: Text.PlainText; elide: Text.ElideRight
                anchors.verticalCenter: parent.verticalCenter
                color: control.primary ? control.theme.accentInk : control.theme.ink
                font.pixelSize: control.theme.fontSizeBody; font.weight: Font.Medium
            }
        }
    }
    background: Rectangle {
        radius: control.theme.radiusMedium
        opacity: control.enabled ? 1 : 0.45
        color: control.primary ? (control.down || control.hovered ? control.theme.accentHover : control.theme.accent) : control.down ? control.theme.pressed : control.hovered ? control.theme.hover : "transparent"
        border.width: control.visualFocus ? 2 : 0
        border.color: control.theme.focus
    }
}
