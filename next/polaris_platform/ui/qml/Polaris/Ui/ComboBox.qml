import QtQuick
import QtQuick.Controls.Basic as Controls
import QtQuick.Layouts

Controls.ComboBox {
    id: control
    required property QtObject theme
    implicitHeight: theme.controlHeight
    leftPadding: theme.spaceMedium; rightPadding: 32
    font.pixelSize: theme.fontSizeBody
    palette.text: theme.ink; palette.buttonText: theme.ink; palette.base: theme.panel; palette.button: theme.panel
    contentItem: Text {
        text: control.displayText; font: control.font; textFormat: Text.PlainText
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        color: control.enabled ? control.theme.ink : control.theme.muted
    }
    indicator: Icon {
        theme: control.theme; kind: "down"
        x: control.width - width - 10; y: (control.height - height) / 2
        ink: control.enabled ? control.theme.muted : control.theme.quiet
    }
    background: Rectangle {
        radius: control.theme.radiusSmall; color: control.theme.panel
        opacity: control.enabled ? 1 : 0.55
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? control.theme.focus : control.theme.border
    }
    delegate: Controls.ItemDelegate {
        id: option
        required property var modelData
        required property int index
        width: control.width
        text: control.textRole ? modelData[control.textRole] : modelData
        highlighted: control.highlightedIndex === index
        contentItem: Text { text: option.text; textFormat: Text.PlainText; font: control.font; color: control.theme.ink; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        background: Rectangle { radius: control.theme.radiusSmall; color: option.highlighted || option.hovered ? control.theme.hover : "transparent" }
    }
    popup: Controls.Popup {
        y: control.height + 4; width: control.width; padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, 260)
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            Controls.ScrollIndicator.vertical: Controls.ScrollIndicator { }
        }
        background: Rectangle { radius: control.theme.radiusMedium; color: control.theme.card; border.color: control.theme.border }
    }
}
