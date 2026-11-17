import QtQuick
import QtQuick.Controls.Basic
Button {
    id: button
    required property var colors
    property bool primary: false
    property bool selected: false
    implicitHeight: 34
    implicitWidth: Math.max(32, label.implicitWidth+22)
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    contentItem: Text { id: label; text: button.text; textFormat: Text.PlainText; font.pixelSize: 12; color: !button.enabled ? button.colors.muted : button.primary ? button.colors.onAccent : button.selected ? button.colors.accent : button.colors.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
    background: Rectangle { radius: 8; color: button.primary ? button.colors.accent : button.down ? button.colors.hover : button.selected ? button.colors.selected : button.hovered ? button.colors.hover : 'transparent'; border.width: button.visualFocus?2:0; border.color: button.colors.accent; opacity: button.enabled?1:.5 }
    Accessible.name: text
    ToolTip.visible: hovered && text.length>1
    ToolTip.text: text
}
