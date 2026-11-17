import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: popup
    required property var host
    property var event: ({})
    readonly property var colors: host.appearance
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(410, host.width - 16)
    height: Math.min(450, host.height - 16)
    padding: 14
    modal: true
    background: Rectangle { color: popup.colors.surface; radius: 12; border.color: popup.colors.border }
    function openEvent(value) { event = value; open() }
    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: parent.width
            spacing: 10
            Text { Layout.fillWidth: true; text: popup.event.title || ''; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.text; font.pixelSize: 17; font.weight: Font.DemiBold }
            Text { Layout.fillWidth: true; text: (popup.event.calendarTitle || '') + (popup.event.recurring ? ' · 重复事件' : ''); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.muted; font.pixelSize: 11 }
            Text { Layout.fillWidth: true; text: popup.event.detailTime || ''; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.text; font.pixelSize: 12 }
            Text { Layout.fillWidth: true; text: popup.event.location || ''; visible: text.length > 0; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.text; font.pixelSize: 12 }
            TextArea { Layout.fillWidth: true; text: popup.event.description || ''; visible: text.length > 0; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: popup.colors.text; font.pixelSize: 12; background: Item {} }
            ScheduleButton { appearance: popup.colors; text: '在 Google Calendar 中查看'; visible: !!popup.event.url; onClicked: Qt.openUrlExternally(popup.event.url) }
            Text { Layout.fillWidth: true; text: 'Google 日历事件 · 只读'; color: popup.colors.muted; font.pixelSize: 10 }
            ScheduleButton { appearance: popup.colors; text: '关闭'; onClicked: popup.close() }
        }
    }
}
