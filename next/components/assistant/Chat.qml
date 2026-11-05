import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    implicitWidth: 640; implicitHeight: 496
    radius: 12; color: surface
    property bool busy: false
    readonly property bool compact: height < 180 || width < 300
    property var configuration: JSON.parse(assistantChat.configurationJson)
    // Optional public native-view container appearance; standalone views keep
    // their own graphite fallback and never inspect the host's internal items.
    readonly property var hostTheme: parent && parent.polarisTheme !== undefined ? parent.polarisTheme : null
    readonly property color surface: hostTheme && hostTheme.surface ? hostTheme.surface : "#202126"
    readonly property color raised: hostTheme && hostTheme.surfaceRaised ? hostTheme.surfaceRaised : "#292a30"
    readonly property color ink: hostTheme && hostTheme.text ? hostTheme.text : "#e9e9e5"
    readonly property color muted: hostTheme && hostTheme.muted ? hostTheme.muted : "#a1a29d"
    readonly property color accent: hostTheme && hostTheme.accent ? hostTheme.accent : "#afc7db"
    readonly property color line: hostTheme && hostTheme.border ? hostTheme.border : "#3b3c43"
    readonly property bool dark: surface.hslLightness < 0.5
    readonly property color faint: dark ? "#8e908e" : "#73766f"
    readonly property color onAccent: dark ? "#1c252e" : "#ffffff"
    readonly property color errorInk: dark ? "#e7aaa5" : "#a33e38"
    readonly property color errorSurface: dark ? "#392a2d" : "#fff0ef"
    readonly property color warningInk: dark ? "#d7b28a" : "#8b6040"
    function openSettings() { settingsDialog.open() }
    function sendDraft() {
        if (!send.enabled || root.busy || draft.inputMethodComposing) return
        root.busy = true
        conversation.append({speaker: "你", body: draft.text})
        assistantChat.submit(draft.text, tools.checked)
        draft.clear()
        list.positionViewAtEnd()
    }
    component ActionButton: Button {
        id: button
        property bool primary: false
        property bool outlined: false
        property int textSize: 12
        implicitHeight: 30
        implicitWidth: Math.max(48, label.implicitWidth + 22)
        leftPadding: 11; rightPadding: 11
        hoverEnabled: true; focusPolicy: Qt.StrongFocus
        contentItem: Text {
            id: label
            text: button.text; font.pixelSize: button.textSize; font.weight: Font.Medium
            color: !button.enabled ? root.faint : button.primary ? root.onAccent : root.ink
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 8
            color: button.primary ? (button.enabled ? root.accent : root.raised) : button.down || button.hovered ? root.raised : "transparent"
            opacity: button.primary && button.enabled && button.hovered ? 0.85 : 1
            border.width: button.visualFocus ? 2 : button.outlined ? 1 : 0
            border.color: button.visualFocus ? root.accent : root.line
        }
    }
    component InputField: TextField {
        id: field
        implicitHeight: root.compact ? 32 : 38; leftPadding: 12; rightPadding: 12
        color: root.ink; placeholderTextColor: root.faint; selectionColor: root.accent; selectedTextColor: root.onAccent
        font.pixelSize: 13
        background: Rectangle {
            radius: 8; color: root.raised
            border.width: field.activeFocus ? 2 : 1; border.color: field.activeFocus ? root.accent : root.line
        }
    }
    component ChatScrollBar: ScrollBar {
        id: bar; padding: 3
        visible: size > 0 && size < 1
        contentItem: Rectangle { implicitWidth: 5; implicitHeight: 5; radius: 3; color: root.muted; opacity: bar.pressed ? 0.8 : 0.35 }
        background: Item { }
    }
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
            settingsNotice.color = success ? root.accent : root.errorInk
            if (success) {
                apiKey.clear()
                provider.currentIndex = Math.max(0, root.configuration.providers.findIndex(function(p) { return p.id === root.configuration.savedProvider }))
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: root.compact ? 6 : 20; spacing: root.compact ? 3 : 12
        RowLayout {
            id: headerRow
            Layout.fillWidth: true; spacing: 6
            Text {
                objectName: "modelConfigurationStatus"; Layout.fillWidth: true; elide: Text.ElideRight
                text: root.configuration.ready ? "本地已配置 · " + root.configuration.model : "模型未设置"
                color: root.muted; font.pixelSize: root.compact ? 10 : 11
            }
            Item { id: compactToolsSlot; visible: root.compact; Layout.preferredWidth: 54; Layout.preferredHeight: 26 }
            ActionButton { objectName: "modelSettingsButton"; text: "设置"; implicitWidth: 48; implicitHeight: 26; onClicked: root.openSettings() }
        }
        ListView {
            id: list; objectName: "conversationList"; clip: true; spacing: 18
            Layout.fillWidth: true; Layout.fillHeight: true; model: conversation
            ScrollBar.vertical: ChatScrollBar { }
            delegate: Item {
                id: messageRow
                required property string speaker
                required property string body
                readonly property bool fromUser: speaker === "你"
                readonly property bool failed: speaker === "未完成"
                width: list.width; height: messageColumn.implicitHeight
                Column {
                    id: messageColumn; spacing: 7
                    width: messageRow.fromUser ? Math.min(messageRow.width - 8, Math.max(110, Math.min(440, messageText.implicitWidth + 28))) : messageRow.width - 8
                    anchors.right: messageRow.fromUser ? parent.right : undefined
                    anchors.left: messageRow.fromUser ? undefined : parent.left
                    Text { text: messageRow.speaker; color: messageRow.failed ? root.errorInk : root.faint; font.pixelSize: 11; anchors.right: messageRow.fromUser ? parent.right : undefined }
                    Rectangle {
                        width: parent.width; height: messageText.implicitHeight + 24; radius: 10
                        color: messageRow.failed ? root.errorSurface : messageRow.fromUser ? root.raised : "transparent"
                        Text {
                            id: messageText; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                            text: messageRow.body; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: messageRow.failed ? root.errorInk : root.ink
                            font.pixelSize: 13; lineHeight: 1.35
                        }
                    }
                }
            }
            Column {
                anchors.centerIn: parent; width: Math.max(0, parent.width - 20); spacing: 11
                visible: list.count === 0 && !root.compact
                Text { anchors.horizontalCenter: parent.horizontalCenter; text: "✳"; color: root.accent; font.pixelSize: 24 }
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: "今天想做点什么？"; color: root.ink; font.pixelSize: root.width > 450 ? 23 : 18; font.weight: Font.Medium; wrapMode: Text.Wrap }
                Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap; text: root.configuration.ready ? "从一个问题开始，或者整理你的想法。" : "先选择模型，保存你的 API 密钥。"; color: root.muted; font.pixelSize: 12 }
            }
        }
        Rectangle {
            id: composer; objectName: "chatComposer"
            Layout.fillWidth: true; Layout.preferredHeight: root.compact ? 32 : 108; Layout.minimumHeight: root.compact ? 32 : 108
            radius: root.compact ? 8 : 12; color: root.raised
            border.color: draft.activeFocus ? root.accent : root.line
            InputField {
                id: draft; objectName: "messageDraft"
                x: 1; y: root.compact ? 0 : 5
                width: parent.width - (root.compact ? send.width + 8 : 2); height: root.compact ? 32 : 42
                font.pixelSize: root.compact ? 13 : 14
                maximumLength: 8000; placeholderText: "输入消息…"; selectByMouse: true
                background: Item { }
                onAccepted: root.sendDraft()
            }
            RowLayout {
                id: composerControls
                visible: !root.compact; x: 11; y: parent.height - 41; height: 30; width: parent.width - send.width - 34; spacing: 8
                ActionButton {
                    objectName: "composerModelSettings"; outlined: true
                    Layout.maximumWidth: Math.max(72, root.width - 220); Layout.minimumWidth: 60
                    text: root.configuration.ready ? root.configuration.model : "选择模型"
                    onClicked: root.openSettings()
                }
                Item { id: normalToolsSlot; Layout.preferredWidth: 62; Layout.preferredHeight: 28 }
                Item { Layout.fillWidth: true }
                Text { visible: root.width > 470; text: "Enter 发送"; color: root.faint; font.pixelSize: 11 }
            }
            ActionButton {
                id: send; objectName: "sendMessage"; primary: true
                x: parent.width - width - (root.compact ? 3 : 11)
                y: root.compact ? (parent.height - height) / 2 : parent.height - height - 11
                width: root.compact ? 34 : 32; implicitWidth: 32; height: 28
                text: root.busy ? "···" : "↑"; textSize: root.busy ? 12 : 18
                Accessible.name: root.busy ? "正在回复" : "发送消息"
                enabled: !root.busy && root.configuration.ready && draft.text.trim().length > 0
                onClicked: root.sendDraft()
            }
        }
    }
    CheckBox {
        id: tools; objectName: "authorizedTools"
        parent: root.compact ? compactToolsSlot : normalToolsSlot
        anchors.fill: parent; text: "工具"; spacing: 6
        hoverEnabled: true; focusPolicy: Qt.StrongFocus
        ToolTip.visible: hovered; ToolTip.text: "使用已授权工具"
        indicator: Rectangle {
            implicitWidth: 14; implicitHeight: 14; x: tools.leftPadding; y: (tools.height - height) / 2
            radius: 4; color: tools.checked ? root.accent : "transparent"
            border.width: tools.visualFocus ? 2 : 1; border.color: tools.checked || tools.visualFocus ? root.accent : root.faint
            Text { anchors.centerIn: parent; text: tools.checked ? "✓" : ""; color: root.onAccent; font.pixelSize: 11; font.bold: true }
        }
        contentItem: Text { text: tools.text; leftPadding: tools.indicator.width + tools.spacing; color: tools.checked ? root.ink : root.muted; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
    }
    Dialog {
        id: settingsDialog; objectName: "modelSettingsDialog"; title: "模型设置"
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.max(0, Math.min(440, parent ? parent.width - 24 : 416))
        height: Math.max(0, Math.min(settingsContent.implicitHeight + 112, parent ? parent.height - 24 : 520))
        padding: 18; modal: true; focus: true
        background: Rectangle { radius: 14; color: root.surface; border.color: root.line }
        Overlay.modal: Rectangle { color: "#660f172a" }
        header: Item {
            implicitHeight: 54
            Text { x: 18; anchors.verticalCenter: parent.verticalCenter; text: "模型设置"; color: root.ink; font.pixelSize: 16; font.weight: Font.DemiBold }
        }
        onOpened: {
            assistantChat.refreshConfiguration()
            provider.currentIndex = Math.max(0, root.configuration.providers.findIndex(function(p) { return p.id === root.configuration.savedProvider }))
            apiKey.clear()
            settingsNotice.text = ""
        }
        onClosed: apiKey.clear()
        property var selected: root.configuration.providers[provider.currentIndex] || ({})
        contentItem: ScrollView {
            id: settingsScroll; objectName: "modelSettingsScroll"; clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }
            ScrollBar.vertical: ChatScrollBar { }
            ColumnLayout {
                id: settingsContent; width: settingsScroll.availableWidth; spacing: 10
                Text { text: "模型服务"; color: root.ink; font.pixelSize: 13; font.weight: Font.DemiBold }
                ComboBox {
                    id: provider; objectName: "modelProvider"; Layout.fillWidth: true; Layout.minimumWidth: 0
                    model: root.configuration.providers; textRole: "label"; implicitHeight: 38; leftPadding: 12; rightPadding: 30
                    contentItem: Text { text: provider.displayText; color: root.ink; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                    background: Rectangle { radius: 9; color: root.raised; border.width: provider.visualFocus ? 2 : 1; border.color: provider.visualFocus ? root.accent : root.line }
                    indicator: Text { x: provider.width - width - 12; anchors.verticalCenter: parent.verticalCenter; text: "⌄"; color: root.muted; font.pixelSize: 16 }
                    delegate: ItemDelegate {
                        required property var modelData
                        required property int index
                        width: provider.width; text: modelData.label; highlighted: provider.highlightedIndex === index
                        contentItem: Text { text: parent.text; color: root.ink; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; leftPadding: 8; elide: Text.ElideRight }
                        background: Rectangle { radius: 7; color: parent.highlighted || parent.hovered ? root.raised : "transparent" }
                    }
                    popup: Popup {
                        y: provider.height + 4; width: provider.width; padding: 5
                        implicitHeight: Math.min(contentItem.implicitHeight + 10, 200)
                        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: provider.popup.visible ? provider.delegateModel : null; currentIndex: provider.highlightedIndex; ScrollBar.vertical: ChatScrollBar {} }
                        background: Rectangle { radius: 10; color: root.surface; border.color: root.line }
                    }
                }
                Text { Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; wrapMode: Text.Wrap; color: root.muted; font.pixelSize: 12; text: "模型：" + (settingsDialog.selected.model || "") }
                Text {
                    visible: root.configuration.providerOverride; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; wrapMode: Text.Wrap; color: root.warningInk; font.pixelSize: 12
                    text: "启动环境变量 POLARIS_AGENT_MODEL_PROVIDER 优先指定当前服务" + (root.configuration.provider ? "（" + root.configuration.provider + "）" : "，且当前值无效") + "。本机选择会保留。"
                }
                Item { implicitHeight: 3 }
                Text { text: "API 密钥"; color: root.ink; font.pixelSize: 13; font.weight: Font.DemiBold }
                InputField {
                    id: apiKey; objectName: "modelApiKey"; Layout.fillWidth: true; Layout.minimumWidth: 0; echoMode: TextInput.Password
                    maximumLength: 4096; selectByMouse: true
                    placeholderText: settingsDialog.selected.keyStored ? "已保存密钥；留空保持" : settingsDialog.selected.keyOverride ? "环境变量已提供密钥；可留空" : "输入所选服务的 API 密钥"
                }
                Text {
                    visible: !!settingsDialog.selected.keyOverride; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; wrapMode: Text.Wrap; color: root.warningInk; font.pixelSize: 12
                    text: (settingsDialog.selected.keyEnv || "") + " 已提供密钥，优先于本机保存的密钥。"
                }
                Text { objectName: "modelSettingsPrivacyNotice"; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; wrapMode: Text.Wrap; color: root.muted; font.pixelSize: 12; text: "密钥仅保存在本机，不回显。保存只检查格式，不验证服务连接或账户权限。" }
                Text { visible: !root.configuration.ready && !root.configuration.providers.some(function(p) { return root.configuration.detail === '请配置有效的 ' + p.keyEnv && !p.keyStored && !p.keyOverride }); Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; wrapMode: Text.Wrap; color: root.errorInk; font.pixelSize: 12; text: root.configuration.detail || "" }
                Text { id: settingsNotice; objectName: "modelSettingsNotice"; Layout.fillWidth: true; Layout.minimumWidth: 0; Layout.preferredWidth: 0; wrapMode: Text.Wrap; visible: text.length > 0; font.pixelSize: 12 }
                Text { visible: root.busy; text: "回复完成后可保存设置"; color: root.muted; font.pixelSize: 12 }
            }
        }
        footer: Item {
            implicitHeight: 58
            Rectangle { width: parent.width; height: 1; color: root.line }
            Row {
                anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                ActionButton { text: "关闭"; onClicked: settingsDialog.close() }
                ActionButton { objectName: "saveModelSettings"; text: "保存"; primary: true; enabled: !root.busy; onClicked: assistantChat.saveModel(settingsDialog.selected.id || "", apiKey.text) }
            }
        }
    }
}
