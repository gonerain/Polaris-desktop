import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
Rectangle {
    color: '#f5f7fb'
    implicitWidth: 500; implicitHeight: 340
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 28; spacing: 16
        Label { text: 'Polaris 软件更新'; font.pixelSize: 24; font.bold: true; color: '#25344a' }
        Label {
            Layout.fillWidth: true; Layout.fillHeight: true
            text: updates.message; textFormat: Text.PlainText
            wrapMode: Text.Wrap; font.pixelSize: 15; color: '#344762'
        }
        ProgressBar { Layout.fillWidth: true; visible: updates.busy; from: 0; to: 100; value: updates.progress; indeterminate: updates.progress === 0 }
        TextField {
            Layout.fillWidth: true; visible: updates.canInstall
            text: updates.installCommand; readOnly: true; selectByMouse: true
        }
        RowLayout {
            Button { text: '检查更新'; enabled: !updates.busy; onClicked: updates.check() }
            Button { text: '下载 deb'; visible: updates.canDownload; enabled: !updates.busy; onClicked: updates.download() }
            Button { text: '安装更新'; visible: updates.canInstall; enabled: !updates.busy; onClicked: updates.install() }
            Button { text: '打开文件夹'; visible: updates.canInstall; onClicked: updates.openFolder() }
        }
        Button { text: '查看 GitHub 发布页'; flat: true; onClicked: updates.releases() }
    }
}
