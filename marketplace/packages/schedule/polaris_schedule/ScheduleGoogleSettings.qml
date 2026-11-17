import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Popup {
    id: popup
    required property var host
    readonly property var colors: host.appearance
    readonly property var google: host.snapshot.google || ({})
    property var selected: []
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(410, host.width - 16)
    height: Math.min(570, host.height - 16)
    modal: true
    padding: 14
    background: Rectangle { color: popup.colors.surface; radius: 12; border.color: popup.colors.border }
    onOpened: selected = (google.selected || []).slice()
    FileDialog {
        id: clientPicker
        title: '选择 Google 桌面 OAuth 客户端 JSON'
        nameFilters: ['JSON 文件 (*.json)']
        onAccepted: clientPath.text = selectedFile.toString()
    }
    ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth
        clip: true
        ColumnLayout {
            width: parent.width
            spacing: 9
            Text { text: 'Google Calendar'; color: popup.colors.text; font.pixelSize: 17; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: '只读同步所选日历，在当天、周和月视图查看安排。同步范围：过去 90 天至未来一年；有时间的事件按本机时区显示。'
                textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.muted; font.pixelSize: 11
            }
            Text {
                Layout.fillWidth: true
                text: '首次连接：在 Google Cloud 启用 Calendar API，配置 OAuth 同意屏幕，再创建“桌面应用”客户端并下载 JSON。测试模式下需把自己的 Google 账号加入测试用户。'
                textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.text; font.pixelSize: 11
            }
            ScheduleButton { appearance: popup.colors; text: '打开 Google Cloud 配置'; onClicked: Qt.openUrlExternally('https://console.cloud.google.com/apis/credentials') }
            RowLayout {
                Layout.fillWidth: true
                TextField {
                    id: clientPath; objectName: 'googleClientPath'; Layout.fillWidth: true
                    placeholderText: '桌面 OAuth JSON 路径'; selectByMouse: true
                    color: popup.colors.text; placeholderTextColor: popup.colors.muted
                    background: Rectangle { color: popup.colors.raised; radius: 5; border.color: popup.colors.border }
                }
                ScheduleButton { appearance: popup.colors; text: '选择'; enabled: !popup.google.busy; onClicked: clientPicker.open() }
            }
            RowLayout {
                ScheduleButton { appearance: popup.colors; objectName: 'googleConnect'; text: popup.google.connected ? '重新连接' : '连接 Google'; selected: true; enabled: !popup.google.busy; onClicked: popup.host.call('google_connect', {client_file: clientPath.text}) }
                ScheduleButton { appearance: popup.colors; objectName: 'googleCancel'; text: '取消授权'; visible: popup.google.authorizing || false; onClicked: popup.host.call('google_cancel') }
            }
            Text { Layout.fillWidth: true; visible: popup.google.authorizing || false; text: '请在浏览器中完成授权。你可以随时取消。'; color: popup.colors.muted; wrapMode: Text.Wrap; font.pixelSize: 11 }
            ScheduleButton { appearance: popup.colors; text: '再次打开授权页面'; visible: !!popup.google.authUrl; onClicked: Qt.openUrlExternally(popup.google.authUrl) }
            Text { Layout.fillWidth: true; text: popup.google.error || ''; visible: text.length > 0; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.error; font.pixelSize: 11 }
            Text { Layout.fillWidth: true; text: scheduleModel.lastError; visible: text.length > 0; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: popup.colors.error; font.pixelSize: 11 }
            Text { text: '选择要显示的日历'; visible: popup.google.connected || false; color: popup.colors.text; font.pixelSize: 12 }
            Repeater {
                model: popup.google.calendars || []
                CheckBox {
                    required property var modelData
                    Layout.fillWidth: true
                    enabled: !popup.google.busy
                    checked: popup.selected.indexOf(modelData.id) >= 0
                    onToggled: {
                        var ids = popup.selected.filter(function(id) { return id !== modelData.id })
                        if (checked) ids.push(modelData.id)
                        popup.selected = ids
                    }
                    contentItem: Text { text: parent.modelData.title; textFormat: Text.PlainText; leftPadding: 28; color: popup.colors.text; font.pixelSize: 12; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
                    indicator: Rectangle { x: 2; y: (parent.height-height)/2; width: 17; height: 17; radius: 4; color: parent.checked ? popup.colors.accent : popup.colors.raised; border.color: popup.colors.border; Text { anchors.centerIn: parent; text: '✓'; visible: parent.parent.checked; color: popup.colors.onAccent; font.pixelSize: 12 } }
                }
            }
            RowLayout {
                visible: popup.google.connected || false
                ScheduleButton { appearance: popup.colors; text: '保存选择'; enabled: !popup.google.busy; onClicked: popup.host.call('google_select', {calendar_ids: popup.selected}) }
                ScheduleButton { appearance: popup.colors; text: '刷新'; enabled: !popup.google.busy; onClicked: popup.host.call('google_sync') }
                ScheduleButton { appearance: popup.colors; text: '断开'; enabled: !popup.google.busy; onClicked: popup.host.call('google_disconnect') }
            }
            Text {
                Layout.fillWidth: true
                text: popup.google.busy ? '正在处理…' : popup.google.lastSync ? '上次同步：' + new Date(popup.google.lastSync).toLocaleString() : '尚未同步'
                wrapMode: Text.Wrap; color: popup.colors.muted; font.pixelSize: 10
            }
            Text { Layout.fillWidth: true; text: '运行期间每 5 分钟同步；离线时保留已缓存安排。断开会移除本机凭据和缓存；如需撤销授权，请前往 Google 账号的第三方应用设置。'; wrapMode: Text.Wrap; color: popup.colors.muted; font.pixelSize: 10 }
            ScheduleButton { appearance: popup.colors; text: '关闭'; onClicked: popup.close() }
        }
    }
}
