import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import '.'

Popup {
    id: settings
    required property var host
    readonly property var colors: host.colors
    readonly property var google: host.snapshot.google||({})
    property var selected: []
    parent: Overlay.overlay; anchors.centerIn: parent
    width: Math.min(440,host.width-24); height: Math.min(540,host.height-24)
    padding: 20; modal: true
    onOpened: selected=(google.selected||[]).slice()
    background: Rectangle { color: settings.colors.surface; radius: 14; border.color: settings.colors.line }
    FileDialog { id: picker; title: '选择桌面 OAuth 客户端 JSON'; nameFilters: ['JSON (*.json)']; onAccepted: clientPath.text=selectedFile.toString() }
    ScrollView {
        anchors.fill: parent; contentWidth: availableWidth; clip: true
        ColumnLayout {
            width: parent.width; spacing: 12
            RowLayout { Layout.fillWidth: true; Text { Layout.fillWidth: true; text: 'Google Calendar'; color: settings.colors.text; font.pixelSize: 19; font.weight: Font.DemiBold } Action { colors: settings.colors; text: '×'; onClicked: settings.close() } }
            Text { Layout.fillWidth: true; text: settings.google.authorizing?'等待浏览器授权，可随时取消':settings.google.busy?'正在同步…':settings.google.connected?'已连接 · 只读同步':'连接后在日历中查看 Google 安排'; wrapMode: Text.Wrap; color: settings.colors.accent; font.pixelSize: 12 }
            Text { Layout.fillWidth: true; text: settings.google.error||''; visible: !!text; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: settings.colors.error; font.pixelSize: 11 }
            Text { Layout.fillWidth: true; text: settings.host.error; visible: !!text; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: settings.colors.error; font.pixelSize: 11 }
            Field { id: clientPath; colors: settings.colors; Layout.fillWidth: true; placeholderText: 'Google 桌面客户端 JSON 路径' }
            RowLayout {
                Action { colors: settings.colors; text: '选择 JSON'; enabled: !settings.google.busy; onClicked: picker.open() }
                Action { colors: settings.colors; text: '连接'; primary: true; enabled: !settings.google.busy; onClicked: settings.host.write('google_connect',{client_file:clientPath.text}) }
                Action { colors: settings.colors; text: '取消授权'; visible: settings.google.authorizing||false; onClicked: settings.host.write('google_cancel',{}) }
            }
            Action { colors: settings.colors; text: '打开授权页面'; visible: !!settings.google.authUrl; onClicked: Qt.openUrlExternally(settings.google.authUrl) }
            Text { text: '同步的日历'; visible: settings.google.connected||false; color: settings.colors.muted; font.pixelSize: 11 }
            Repeater {
                model: settings.google.calendars||[]
                CheckBox {
                    required property var modelData
                    Layout.fillWidth: true; enabled: !settings.google.busy
                    checked: settings.selected.indexOf(modelData.id)>=0
                    onToggled: {var a=settings.selected.filter(function(id){return id!==modelData.id});if(checked)a.push(modelData.id);settings.selected=a}
                    contentItem: Text { text: parent.modelData.title; textFormat: Text.PlainText; leftPadding: 28; verticalAlignment: Text.AlignVCenter; color: settings.colors.text; font.pixelSize: 12; elide: Text.ElideRight }
                    indicator: Rectangle { x: 2; y: (parent.height-height)/2; width: 17; height: 17; radius: 4; color: parent.checked?settings.colors.accent:settings.colors.raised; border.color: settings.colors.line; Text { anchors.centerIn: parent; text: '✓'; visible: parent.parent.checked; color: settings.colors.onAccent; font.pixelSize: 11 } }
                }
            }
            RowLayout {
                visible: settings.google.connected||false
                Action { colors: settings.colors; text: '保存选择'; enabled: !settings.google.busy; onClicked: settings.host.write('google_select',{calendar_ids:settings.selected}) }
                Action { colors: settings.colors; text: '立即同步'; enabled: !settings.google.busy; onClicked: settings.host.write('google_sync',{}) }
                Action { colors: settings.colors; text: '断开'; enabled: !settings.google.busy; onClicked: settings.host.write('google_disconnect',{}) }
            }
            Text { Layout.fillWidth: true; text: settings.google.lastSync?'上次同步 '+new Date(settings.google.lastSync).toLocaleString():'尚未同步'; wrapMode: Text.Wrap; color: settings.colors.muted; font.pixelSize: 10 }
            Text { Layout.fillWidth: true; text: '同步过去 90 天至未来一年，运行时每 5 分钟刷新。首次连接需在 Google Cloud 启用 Calendar API，创建桌面 OAuth 客户端并下载 JSON；测试模式需加入测试用户。'; wrapMode: Text.Wrap; color: settings.colors.muted; font.pixelSize: 11 }
            Action { colors: settings.colors; text: 'Google Cloud 配置'; onClicked: Qt.openUrlExternally('https://console.cloud.google.com/apis/credentials') }
        }
    }
}
