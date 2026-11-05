import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    implicitWidth: 380; implicitHeight: 300
    color: "#f6f8fa"; radius: 10
    property bool busy: false
    property var configuration: JSON.parse(assistantChat.configurationJson)
    ListModel { id: conversation }
    Connections {
        target: assistantChat
        function onAnswered(reply, error) {
            conversation.append({speaker: error ? "未完成" : "Polaris Agent", body: error || reply})
            root.busy = false
            assistantChat.refreshConfiguration()
            list.positionViewAtEnd()
        }
        function onSettingsSaved(success, message) {
            settingsNotice.text = message
            settingsNotice.color = success ? "#315c44" : "#a73a36"
            if (success) {
                apiKey.clear()
                provider.currentIndex = Math.max(0, root.configuration.providers.findIndex(function(p) { return p.id === root.configuration.savedProvider }))
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 10; spacing: 6
        RowLayout {
            Label { Layout.fillWidth: true; text: "Polaris Agent"; color: "#253650"; font.bold: true }
            CheckBox { id: tools; text: "授权工具"; font.pixelSize: 12; ToolTip.visible: hovered; ToolTip.text: "使用已授权工具" }
            Button { objectName: "modelSettingsButton"; text: "模型设置"; implicitHeight: 28; onClicked: settingsDialog.open() }
        }
        Label {
            objectName: "modelConfigurationStatus"; Layout.fillWidth: true; wrapMode: Text.Wrap
            text: root.configuration.ready ? "已配置，可发送 · " + root.configuration.model : "尚未就绪 · 请打开模型设置"
            color: root.configuration.ready ? "#506c5d" : "#8b6040"; font.pixelSize: 12
        }
        ListView {
            id: list; objectName: "conversationList"; clip: true; spacing: 8
            Layout.fillWidth: true; Layout.fillHeight: true; model: conversation
            delegate: Label {
                required property string speaker
                required property string body
                width: list.width; textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: "#283850"; text: speaker + "\n" + body
            }
            Label { visible: list.count === 0; anchors.centerIn: parent; text: root.configuration.ready ? "开始一段对话" : "先设置模型服务和 API 密钥"; color: "#63748a" }
        }
        RowLayout {
            TextField { id: draft; objectName: "messageDraft"; Layout.fillWidth: true; maximumLength: 8000; placeholderText: "输入消息"; onAccepted: send.clicked() }
            Button {
                id: send; objectName: "sendMessage"; text: root.busy ? "回复中…" : "发送"; enabled: !root.busy && root.configuration.ready && draft.text.trim().length > 0
                onClicked: {
                    if (!enabled) return
                    root.busy = true
                    conversation.append({speaker: "你", body: draft.text})
                    assistantChat.submit(draft.text, tools.checked)
                    draft.clear()
                    list.positionViewAtEnd()
                }
            }
        }
    }
    Dialog {
        id: settingsDialog; objectName: "modelSettingsDialog"; title: "模型设置"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(440, parent ? parent.width - 24 : 416)
        height: Math.min(settingsContent.implicitHeight + 112, parent ? parent.height - 24 : 520)
        modal: true; focus: true
        onOpened: {
            assistantChat.refreshConfiguration()
            provider.currentIndex = Math.max(0, root.configuration.providers.findIndex(function(p) { return p.id === root.configuration.savedProvider }))
            apiKey.clear()
            settingsNotice.text = ""
        }
        onClosed: apiKey.clear()
        property var selected: root.configuration.providers[provider.currentIndex] || ({})
        contentItem: ScrollView {
            id: settingsScroll; clip: true
            ColumnLayout {
            id: settingsContent; width: settingsScroll.availableWidth
            spacing: 10
            Label { text: "模型服务"; font.bold: true }
            ComboBox { id: provider; objectName: "modelProvider"; Layout.fillWidth: true; model: root.configuration.providers; textRole: "label" }
            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#61718b"; text: "模型：" + (settingsDialog.selected.model || "") }
            Label {
                visible: root.configuration.providerOverride; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#8b6040"
                text: "启动环境变量 POLARIS_AGENT_MODEL_PROVIDER 优先指定当前服务" + (root.configuration.provider ? "（" + root.configuration.provider + "）" : "，且当前值无效") + "。本机选择会保留。"
            }
            Label { text: "API 密钥"; font.bold: true }
            TextField {
                id: apiKey; objectName: "modelApiKey"; Layout.fillWidth: true; echoMode: TextInput.Password
                maximumLength: 4096; selectByMouse: true
                placeholderText: settingsDialog.selected.keyStored ? "已保存密钥；留空保持" : settingsDialog.selected.keyOverride ? "环境变量已提供密钥；可留空" : "输入所选服务的 API 密钥"
            }
            Label {
                visible: !!settingsDialog.selected.keyOverride; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#8b6040"
                text: (settingsDialog.selected.keyEnv || "") + " 已提供密钥，优先于本机保存的密钥。"
            }
            Label {
                Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#61718b"; font.pixelSize: 12
                text: "密钥仅保存在本机，不回显。保存只检查格式，不验证服务连接或账户权限。"
            }
            Label {
                visible: !root.configuration.ready; Layout.fillWidth: true; wrapMode: Text.Wrap; color: "#a73a36"
                text: root.configuration.detail || ""
            }
            Label { id: settingsNotice; objectName: "modelSettingsNotice"; Layout.fillWidth: true; wrapMode: Text.Wrap; visible: text.length > 0 }
            Label { visible: root.busy; text: "回复完成后可保存设置"; color: "#61718b" }
            }
        }
        footer: DialogButtonBox {
            Button { text: "关闭"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole; onClicked: settingsDialog.close() }
            Button {
                objectName: "saveModelSettings"; text: "保存"; DialogButtonBox.buttonRole: DialogButtonBox.ActionRole; enabled: !root.busy
                onClicked: assistantChat.saveModel(settingsDialog.selected.id || "", apiKey.text)
            }
        }
    }
}
