import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

Rectangle {
    id: root
    objectName: "feishuBotView"
    implicitWidth: 820; implicitHeight: 640
    radius: 12
    readonly property var hostTheme: parent && parent.polarisTheme !== undefined ? parent.polarisTheme : null
    readonly property color surface: hostTheme && hostTheme.surface ? hostTheme.surface : "#202126"
    readonly property color raised: hostTheme && hostTheme.surfaceRaised ? hostTheme.surfaceRaised : "#292a30"
    readonly property color ink: hostTheme && hostTheme.text ? hostTheme.text : "#e9e9e5"
    readonly property color muted: hostTheme && hostTheme.muted ? hostTheme.muted : "#a1a29d"
    readonly property color accent: hostTheme && hostTheme.accent ? hostTheme.accent : "#afc7db"
    readonly property color line: hostTheme && hostTheme.border ? hostTheme.border : "#3b3c43"
    readonly property color errorInk: surface.hslLightness < 0.5 ? "#e7aaa5" : "#a33e38"
    readonly property color onAccent: surface.hslLightness < 0.5 ? "#1c252e" : "#ffffff"
    readonly property bool narrow: width < 620
    property var snapshot: typeof feishuBot !== "undefined" && feishuBot ? JSON.parse(feishuBot.stateJson) : ({})
    property string selectedChatId: ""
    property string replyMessageId: ""
    property string replyPreview: ""
    property var savingResource: ({})
    readonly property bool streaming: !!snapshot.streamId
    readonly property string targetType: ["chat_id", "open_id", "email"][targetKind.currentIndex]
    readonly property var conversations: snapshot.conversations || []
    readonly property var messages: (snapshot.messages || []).filter(function(message) {
        return !!root.selectedChatId && message.chatId === root.selectedChatId
    })
    readonly property var registration: snapshot.registration || ({state: "idle"})
    readonly property bool registering: ["waiting", "scanned", "creating", "connecting"].indexOf(registration.state) >= 0
    readonly property string registrationLabel: ({idle: "扫码接入飞书", waiting: "等待扫码确认", scanned: "已扫码，请在飞书中确认", creating: "正在创建机器人", connecting: "已保存，正在连接", complete: "机器人已接入", expired: "二维码已过期，可手动刷新", cancelled: "已取消扫码", error: "扫码接入未完成"})[registration.state] || "扫码接入飞书"
    readonly property bool connected: snapshot.connectionState === "connected"
    readonly property bool busy: !!snapshot.busy
    color: surface

    function messageTime(value) {
        if (!value) return ""
        if (typeof value === "number") return Qt.formatDateTime(new Date(value), "MM-dd hh:mm")
        return String(value)
    }
    function chooseConversation(chatId) {
        selectedChatId = chatId
        targetKind.currentIndex = 0
        recipient.text = chatId
        replyMessageId = ""
        replyPreview = ""
        feishuBot.selectConversation(chatId)
    }
    function openSettings() {
        robotName.text = snapshot.instanceName || ""
        appId.text = snapshot.appId || ""
        secret.clear()
        settings.open()
    }
    function sendDraft() {
        if (!send.enabled || draft.inputMethodComposing) return
        if (root.streaming) feishuBot.updateStream(draft.text)
        else if (cardMode.checked) feishuBot.startStream(root.targetType, recipient.text.trim(), draft.text, replyMessageId, threadReply.checked)
        else feishuBot.sendDraft(root.targetType, recipient.text.trim(), draft.text, replyMessageId, threadReply.checked)
    }

    component ActionButton: Button {
        id: action
        property bool primary: false
        implicitHeight: 32; implicitWidth: Math.max(54, contentItem.implicitWidth + 22)
        leftPadding: 11; rightPadding: 11
        hoverEnabled: true
        contentItem: Text {
            text: action.text; textFormat: Text.PlainText; font.pixelSize: 12; font.weight: Font.Medium
            color: !action.enabled ? root.muted : action.primary ? root.onAccent : root.ink
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 7; opacity: action.enabled ? 1 : 0.5
            color: action.primary ? root.accent : action.hovered || action.down ? root.raised : "transparent"
            border.width: action.visualFocus ? 2 : 1
            border.color: action.visualFocus ? root.accent : root.line
        }
    }
    component Field: TextField {
        id: field
        implicitHeight: 36; leftPadding: 11; rightPadding: 11
        color: root.ink; placeholderTextColor: root.muted; font.pixelSize: 13
        selectionColor: root.accent; selectedTextColor: root.onAccent
        background: Rectangle {
            radius: 7; color: root.raised
            border.width: field.activeFocus ? 2 : 1
            border.color: field.activeFocus ? root.accent : root.line
        }
    }
    component OptionToggle: CheckBox {
        id: option
        implicitHeight: 32; spacing: 6; leftPadding: 0; rightPadding: 0
        indicator: Rectangle {
            implicitWidth: 15; implicitHeight: 15
            x: option.leftPadding; y: (option.height - height) / 2
            radius: 4; color: option.checked ? root.accent : root.raised
            border.color: option.visualFocus ? root.accent : root.line
            Text { anchors.centerIn: parent; text: option.checked ? "✓" : ""; color: root.onAccent; font.pixelSize: 12 }
        }
        contentItem: Text {
            text: option.text; color: option.enabled ? root.ink : root.muted; font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter; leftPadding: option.indicator.width + option.spacing
        }
    }
    component BodyLabel: Text {
        color: root.muted; font.pixelSize: 12; textFormat: Text.PlainText; wrapMode: Text.Wrap
    }

    Connections {
        target: feishuBot
        function onAttachmentSent() {
            root.replyMessageId = ""
            root.replyPreview = ""
        }
        function onMessageSent() {
            draft.clear()
            root.replyMessageId = ""
            root.replyPreview = ""
            cardMode.checked = false
        }
        function onChanged() {
            if (root.snapshot.selectedChatId && root.snapshot.selectedChatId !== root.selectedChatId) {
                root.selectedChatId = root.snapshot.selectedChatId
                if (targetKind.currentIndex === 0) recipient.text = root.selectedChatId
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent; anchors.margins: root.width < 400 ? 12 : 20; spacing: 12
        RowLayout {
            Layout.fillWidth: true; spacing: 10
            ColumnLayout {
                Layout.fillWidth: true; spacing: 4
                Text { objectName: "feishuIdentity"; Layout.fillWidth: true; text: root.snapshot.instanceName || "飞书机器人"; color: root.ink; textFormat: Text.PlainText; font.pixelSize: 19; font.weight: Font.DemiBold; elide: Text.ElideRight }
                BodyLabel { objectName: "feishuLocalConfiguration"; Layout.fillWidth: true; text: root.snapshot.configured ? "本地已配置" : "尚未配置机器人身份" }
            }
            ActionButton { objectName: "feishuConfigure"; text: root.snapshot.configured ? "配置" : "关联已有机器人"; enabled: !root.busy && !root.registering; onClicked: root.openSettings() }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Rectangle { width: 7; height: 7; radius: 4; color: root.connected ? "#a6c8b6" : root.snapshot.connectionState === "error" ? root.errorInk : root.muted }
            BodyLabel { objectName: "feishuConnectionState"; Layout.fillWidth: true; text: root.snapshot.connectionLabel || "未连接"; color: root.connected ? "#a6c8b6" : root.muted }
            ActionButton { objectName: "feishuCancelRegistration"; text: "取消扫码"; visible: root.registering; enabled: !root.busy; onClicked: feishuBot.cancelRegistration() }
            ActionButton { objectName: "feishuRefresh"; text: "刷新"; enabled: !root.busy; onClicked: feishuBot.refresh() }
            ActionButton { objectName: "feishuConnect"; visible: !root.registering; text: root.connected ? "断开" : "连接"; primary: !root.connected; enabled: !root.busy && !!root.snapshot.configured; onClicked: root.connected ? feishuBot.disconnectBot() : feishuBot.connectBot() }
        }
        Flow {
            Layout.fillWidth: true; spacing: 8; visible: !!root.snapshot.configured
            ActionButton { objectName: "feishuOpenChat"; text: "打开机器人私聊"; primary: true; onClicked: feishuBot.openChat() }
            ActionButton { objectName: "feishuShowChatQr"; text: "手机扫码进入"; onClicked: chatEntry.open() }
        }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: errorText.implicitHeight + 18
            visible: !!root.snapshot.lastError; color: root.raised; radius: 7; border.color: root.errorInk
            Text { id: errorText; objectName: "feishuError"; anchors.fill: parent; anchors.margins: 9; text: root.snapshot.lastError || ""; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; color: root.errorInk; font.pixelSize: 12 }
        }
        BodyLabel { objectName: "feishuNotice"; Layout.fillWidth: true; visible: !!root.snapshot.notice; text: root.snapshot.notice || ""; color: root.accent }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.line }
        ScrollView {
            objectName: "feishuOnboarding"; visible: !root.snapshot.configured
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 16
                Item { Layout.preferredHeight: 6 }
                Text { Layout.fillWidth: true; visible: !root.registering; text: "用飞书扫码，创建你的机器人"; textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: root.narrow ? 19 : 23; font.weight: Font.DemiBold; color: root.ink }
                BodyLabel { Layout.fillWidth: true; visible: !root.registering; text: "在飞书官方页面确认创建。完成后，凭据会保存到此实例并自动连接。" }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: onboardingContent.implicitHeight + 32
                    radius: 10; color: root.raised; border.color: root.line
                    ColumnLayout {
                        id: onboardingContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; spacing: 13
                        RowLayout {
                            Layout.fillWidth: true
                            Text { objectName: "feishuRegistrationState"; Layout.fillWidth: true; text: root.registrationLabel; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.ink; font.pixelSize: 15; font.weight: Font.DemiBold }
                        }
                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter; implicitWidth: Math.min(320, root.width - 64); implicitHeight: implicitWidth
                            visible: !!root.registration.qrImageSource; color: "white"; radius: 6
                            Image { objectName: "feishuRegistrationQr"; anchors.centerIn: parent; width: root.registration.qrModules ? root.registration.qrModules * Math.max(1, Math.floor((parent.width - 12) / root.registration.qrModules)) : parent.width - 12; height: width; sourceSize.width: width; sourceSize.height: height; source: root.registration.qrImageSource || ""; fillMode: Image.PreserveAspectFit; smooth: false; asynchronous: false }
                        }
                        BodyLabel { objectName: "feishuRegistrationMessage"; Layout.fillWidth: true; visible: !!root.registration.message; text: root.registration.message || ""; color: root.registration.state === "error" ? root.errorInk : root.muted }
                        BodyLabel { Layout.fillWidth: true; visible: root.registration.state === "waiting" || root.registration.state === "scanned"; text: "请使用手机飞书扫码，并在官方页面完成确认。" }
                        ActionButton { objectName: "feishuRegistrationBrowser"; text: "在浏览器中打开官方页面"; visible: !!root.registration.verificationUrl; enabled: !root.busy; onClicked: feishuBot.openRegistrationLink() }
                        Flow {
                            Layout.fillWidth: true; spacing: 9
                            ActionButton { objectName: "feishuRefreshRegistration"; text: "刷新二维码"; visible: root.registering && !!root.registration.qrImageSource; enabled: !root.busy; onClicked: feishuBot.startRegistration() }
                            ActionButton { objectName: "feishuStartRegistration"; text: root.registration.state === "expired" ? "刷新二维码" : ["error", "cancelled"].indexOf(root.registration.state) >= 0 ? "重新扫码" : "扫码创建机器人"; primary: true; visible: !root.registering; enabled: !root.busy; onClicked: feishuBot.startRegistration() }
                        }
                    }
                }
                BodyLabel { Layout.fillWidth: true; visible: !root.registering; text: "已有应用？使用右上角“关联已有机器人”填写 App ID 和 App Secret。" }
                Item { Layout.preferredHeight: 10 }
            }
        }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 14; visible: !!root.snapshot.configured
            ColumnLayout {
                Layout.preferredWidth: 178; Layout.fillHeight: true; visible: !root.narrow; spacing: 9
                Text { text: "最近会话"; color: root.ink; font.pixelSize: 13; font.weight: Font.DemiBold }
                ListView {
                    id: conversationList; objectName: "feishuConversations"
                    Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                    model: root.conversations
                    delegate: ItemDelegate {
                        id: conversationRow
                        required property var modelData
                        objectName: "feishuConversation_" + modelData.chatId
                        width: conversationList.width; height: 62
                        onClicked: root.chooseConversation(modelData.chatId)
                        background: Rectangle { radius: 7; color: conversationRow.modelData.chatId === root.selectedChatId || conversationRow.hovered ? root.raised : "transparent" }
                        contentItem: Column {
                            spacing: 6
                            Text { width: parent.width; text: conversationRow.modelData.title || conversationRow.modelData.chatId; textFormat: Text.PlainText; color: root.ink; font.pixelSize: 12; elide: Text.ElideRight }
                            Text { width: parent.width; text: conversationRow.modelData.lastText || "暂无消息"; textFormat: Text.PlainText; color: root.muted; font.pixelSize: 11; elide: Text.ElideRight }
                        }
                    }
                    BodyLabel { anchors.fill: parent; anchors.topMargin: 18; visible: !root.conversations.length; text: "收到消息后，会话会显示在这里。" }
                    ScrollBar.vertical: ScrollBar { }
                }
            }
            Rectangle { visible: !root.narrow; Layout.fillHeight: true; implicitWidth: 1; color: root.line }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 9
                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "消息"; color: root.ink; font.pixelSize: 13; font.weight: Font.DemiBold }
                    BodyLabel { Layout.fillWidth: true; horizontalAlignment: Text.AlignRight; text: root.messages.length ? "最近 " + root.messages.length + " 条" : "" }
                }
                ComboBox {
                    objectName: "feishuConversationPicker"; visible: root.narrow && root.conversations.length > 0
                    Layout.fillWidth: true; textRole: "title"; model: root.conversations
                    displayText: currentIndex >= 0 ? (root.conversations[currentIndex].title || root.conversations[currentIndex].chatId) : "选择会话"
                    currentIndex: root.conversations.findIndex(function(row) { return row.chatId === root.selectedChatId })
                    onActivated: function(index) { root.chooseConversation(root.conversations[index].chatId) }
                    palette.text: root.ink; palette.buttonText: root.ink; palette.base: root.raised; palette.button: root.raised
                }
                Repeater {
                    model: root.snapshot.activeStreams || []
                    delegate: RowLayout {
                        id: activeCard
                        required property var modelData
                        Layout.fillWidth: true
                        BodyLabel { Layout.fillWidth: true; text: "未完成卡片 · " + (activeCard.modelData.title || activeCard.modelData.text || "卡片"); maximumLineCount: 1; elide: Text.ElideRight }
                        ActionButton {
                            objectName: "feishuResumeStream_" + activeCard.modelData.stream_id
                            text: "继续编辑"; enabled: !root.busy
                            onClicked: {
                                targetKind.currentIndex = ["chat_id", "open_id", "email"].indexOf(activeCard.modelData.targetType || "chat_id")
                                recipient.text = activeCard.modelData.targetId || activeCard.modelData.chatId || ""
                                draft.text = activeCard.modelData.text || ""
                                cardMode.checked = true
                                feishuBot.resumeStream(activeCard.modelData.stream_id)
                            }
                        }
                    }
                }
                ListView {
                    id: messageList; objectName: "feishuMessages"
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 100; clip: true; spacing: 9
                    model: root.messages
                    delegate: Rectangle {
                        id: messageRow
                        required property var modelData
                        width: messageList.width; height: messageBody.implicitHeight + 20
                        radius: 8; color: root.raised
                        ColumnLayout {
                            id: messageBody; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 7
                            RowLayout {
                                Layout.fillWidth: true
                                BodyLabel { Layout.fillWidth: true; color: root.ink; text: ["outgoing", "outbound"].indexOf(messageRow.modelData.direction) >= 0 ? "机器人" : (messageRow.modelData.senderLabel || messageRow.modelData.sender || "收到消息") }
                                BodyLabel { text: root.messageTime(messageRow.modelData.createdAt); font.pixelSize: 10 }
                            }
                            Text { Layout.fillWidth: true; text: messageRow.modelData.text || ((messageRow.modelData.normalized || {}).content || {}).text || ""; visible: !!text; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; color: root.ink; font.pixelSize: 13 }
                            BodyLabel {
                                Layout.fillWidth: true
                                property var mentions: (messageRow.modelData.normalized || {}).mentions || []
                                visible: mentions.length > 0
                                text: mentions.map(function(mention) { return "@" + (mention.name || mention.open_id || mention.key) }).join("  ")
                                color: root.accent
                            }
                            BodyLabel {
                                Layout.fillWidth: true
                                property var conversation: (messageRow.modelData.normalized || {}).conversation || {}
                                property var reply: (messageRow.modelData.normalized || {}).reply || {}
                                visible: !!conversation.thread_id || !!messageRow.modelData.replyMessageId || !!reply.message_id
                                text: (conversation.thread_id ? "话题消息" : "") + ((messageRow.modelData.replyMessageId || reply.message_id) ? (conversation.thread_id ? " · " : "") + "引用：" + (reply.text || messageRow.modelData.replyMessageId || reply.message_id) : "")
                            }
                            Repeater {
                                model: (messageRow.modelData.normalized || {}).resources || []
                                delegate: RowLayout {
                                    id: attachmentRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    BodyLabel { Layout.fillWidth: true; color: root.ink; text: attachmentRow.modelData.file_name || (attachmentRow.modelData.type === "image" ? "图片" : "附件") }
                                    ActionButton {
                                        objectName: "feishuSaveAttachment_" + messageRow.modelData.messageId
                                        text: "保存"; enabled: !root.busy && root.snapshot.readable !== false
                                        onClicked: {
                                            root.savingResource = {key: attachmentRow.modelData.file_key || attachmentRow.modelData.image_key, messageId: messageRow.modelData.messageId, type: attachmentRow.modelData.type, name: attachmentRow.modelData.file_name || ""}
                                            saveAttachment.open()
                                        }
                                    }
                                }
                            }
                            ActionButton { objectName: "feishuReply_" + messageRow.modelData.messageId; text: "引用回复"; visible: !!messageRow.modelData.messageId; enabled: !root.busy; onClicked: { root.chooseConversation(messageRow.modelData.chatId); root.replyMessageId = messageRow.modelData.messageId; root.replyPreview = messageRow.modelData.text || "附件消息"; threadReply.checked = !!(((messageRow.modelData.normalized || {}).conversation || {}).thread_id); draft.forceActiveFocus() } }
                        }
                    }
                    BodyLabel { anchors.fill: parent; anchors.margins: 14; visible: !root.messages.length; text: root.selectedChatId ? "此会话暂无已记录消息。" : "选择最近会话，或指定发送目标。" }
                    ScrollBar.vertical: ScrollBar { }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 7
                    ComboBox {
                        id: targetKind; objectName: "feishuTargetType"; Layout.preferredWidth: 88
                        model: ["会话", "用户", "邮箱"]; enabled: !root.busy && !root.streaming
                        palette.text: root.ink; palette.buttonText: root.ink; palette.base: root.raised; palette.button: root.raised
                        onActivated: { recipient.clear(); root.replyMessageId = ""; root.replyPreview = "" }
                    }
                    Field {
                        id: recipient; objectName: "feishuRecipient"; Layout.fillWidth: true
                        placeholderText: ["会话 ID（oc_…）", "用户 Open ID（ou_…）", "收件人邮箱"][targetKind.currentIndex]
                        enabled: !root.busy && !root.streaming
                        onTextEdited: { if (targetKind.currentIndex === 0) root.selectedChatId = text.trim(); root.replyMessageId = ""; root.replyPreview = "" }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: replyText.implicitHeight + 16; visible: !!root.replyMessageId; radius: 7; color: root.raised
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 8
                        Text { id: replyText; objectName: "feishuReplyPreview"; Layout.fillWidth: true; text: "引用：" + root.replyPreview; textFormat: Text.PlainText; color: root.muted; font.pixelSize: 12; maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.WrapAnywhere }
                        OptionToggle { id: threadReply; objectName: "feishuReplyInThread"; text: "话题回复"; palette.windowText: root.ink; enabled: !root.streaming }
                        ActionButton { objectName: "feishuCancelReply"; text: "取消"; onClicked: { root.replyMessageId = ""; root.replyPreview = "" } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    visible: !!root.snapshot.attachment
                    BodyLabel { Layout.fillWidth: true; color: root.ink; text: root.snapshot.attachment ? "附件：" + root.snapshot.attachment.name : "" }
                    ActionButton { objectName: "feishuRemoveAttachment"; text: "移除"; enabled: !root.busy; onClicked: feishuBot.clearAttachment() }
                }
                BodyLabel {
                    Layout.fillWidth: true
                    visible: !!root.snapshot.attachment && root.snapshot.attachment.kind === "file" && !!draft.text.trim()
                    text: "文件将单独发送，正文保留为下一条消息。"
                }
                ScrollView {
                    Layout.fillWidth: true; Layout.preferredHeight: root.height < 560 ? 66 : 88; clip: true
                    TextArea {
                        id: draft; objectName: "feishuDraft"; placeholderText: "输入要发送的消息"; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; selectByMouse: true
                        color: root.ink; placeholderTextColor: root.muted; font.pixelSize: 13; padding: 11
                        background: Rectangle { radius: 7; color: root.raised; border.color: draft.activeFocus ? root.accent : root.line }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ActionButton { objectName: "feishuAddAttachment"; text: "附件"; visible: !cardMode.checked && !root.streaming; enabled: root.connected && !root.busy && root.snapshot.readable !== false; onClicked: chooseAttachment.open() }
                    OptionToggle { id: cardMode; objectName: "feishuCardMode"; text: "持续更新卡片"; visible: !root.snapshot.attachment; enabled: !root.busy && !root.streaming; palette.windowText: root.ink }
                    Item { Layout.fillWidth: true }
                    ActionButton { objectName: "feishuFinishStream"; text: "完成卡片"; visible: root.streaming; enabled: !root.busy; onClicked: feishuBot.finishStream(draft.text) }
                    ActionButton { id: send; objectName: "feishuSend"; text: root.streaming ? "更新" : cardMode.checked ? "创建卡片" : root.replyMessageId ? "发送回复" : "发送"; primary: true; enabled: root.connected && root.snapshot.readable !== false && !root.busy && !!recipient.text.trim() && (!!draft.text.trim() || !!root.snapshot.attachment); onClicked: root.sendDraft() }
                }
            }
        }
    }

    FileDialog {
        id: chooseAttachment; objectName: "feishuChooseAttachmentDialog"
        title: "选择要发送的附件"; fileMode: FileDialog.OpenFile
        onAccepted: feishuBot.chooseAttachment(selectedFile.toString())
    }
    FileDialog {
        id: saveAttachment; objectName: "feishuSaveAttachmentDialog"
        title: "保存飞书附件"; fileMode: FileDialog.SaveFile
        onAccepted: feishuBot.saveResource(root.savingResource.key, root.savingResource.messageId, root.savingResource.type, root.savingResource.name, selectedFile.toString())
    }
    Dialog {
        id: chatEntry; objectName: "feishuChatEntryDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent; width: Math.min(360, root.width - 24)
        modal: true; padding: 20; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { color: root.surface; radius: 12; border.color: root.line }
        contentItem: ColumnLayout {
            spacing: 14
            Text { text: "手机扫码进入私聊"; color: root.ink; font.pixelSize: 17; font.weight: Font.DemiBold }
            Rectangle {
                Layout.alignment: Qt.AlignHCenter
                implicitWidth: Math.min(288, chatEntry.width - 40); implicitHeight: implicitWidth
                color: "white"; radius: 7
                Image {
                    objectName: "feishuChatQr"; anchors.centerIn: parent
                    width: root.snapshot.chatQrModules ? root.snapshot.chatQrModules * Math.max(1, Math.floor((parent.width - 12) / root.snapshot.chatQrModules)) : 0
                    height: width; sourceSize.width: width; sourceSize.height: height
                    source: root.snapshot.chatQrImageSource || ""; smooth: false; fillMode: Image.PreserveAspectFit
                }
            }
            BodyLabel { Layout.fillWidth: true; text: "用手机飞书扫码，打开此机器人的私聊。发送消息后，即可在这里查看和回复。" }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "feishuCloseChatQr"; text: "关闭"; onClicked: chatEntry.close() }
            }
        }
    }
    Dialog {
        id: settings; objectName: "feishuConfigurationDialog"
        parent: Overlay.overlay
        anchors.centerIn: parent; width: Math.min(450, root.width - 24)
        modal: true; padding: 20; closePolicy: Popup.CloseOnEscape
        background: Rectangle { color: root.surface; radius: 12; border.color: root.line }
        onClosed: secret.clear()
        contentItem: ColumnLayout {
            spacing: 12
            Text { text: "机器人身份"; color: root.ink; font.pixelSize: 17; font.weight: Font.DemiBold }
            BodyLabel { Layout.fillWidth: true; text: "填写飞书应用的凭据，保存后再连接机器人。" }
            BodyLabel { text: "显示名称" }
            Field { id: robotName; objectName: "feishuRobotName"; Layout.fillWidth: true; placeholderText: "例如：项目通知机器人" }
            BodyLabel { text: "App ID" }
            Field { id: appId; objectName: "feishuAppId"; Layout.fillWidth: true; placeholderText: "cli_…"; readOnly: !!root.snapshot.appId }
            BodyLabel { Layout.fillWidth: true; visible: !!root.snapshot.appId; text: "此实例已绑定应用。配置其他机器人时，请创建新实例。" }
            BodyLabel { text: "App Secret" }
            Field { id: secret; objectName: "feishuAppSecret"; Layout.fillWidth: true; echoMode: TextInput.Password; placeholderText: root.snapshot.hasSecret ? "已保存；留空保留现有凭据" : "输入应用密钥" }
            BodyLabel { Layout.fillWidth: true; text: "凭据保存在此机器人实例的本地配置中。连接成功后才会显示在线状态。" }
            RowLayout {
                Layout.fillWidth: true; Layout.topMargin: 5
                Item { Layout.fillWidth: true }
                ActionButton { objectName: "feishuCancelConfiguration"; text: "取消"; onClicked: settings.close() }
                ActionButton { objectName: "feishuSaveConfiguration"; text: "保存"; primary: true; enabled: !root.busy && !!robotName.text.trim() && !!appId.text.trim() && (!!secret.text || !!root.snapshot.hasSecret); onClicked: { feishuBot.saveConfiguration(robotName.text.trim(), appId.text.trim(), secret.text); secret.clear(); settings.close() } }
            }
        }
    }
}
