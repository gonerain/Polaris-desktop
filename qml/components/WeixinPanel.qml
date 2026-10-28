pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

Rectangle {
    id: panel
    required property var client
    property bool detailed: false
    property bool settingsVisible: false
    required property var chat
    readonly property bool hasApproval: !!(chat && chat.tools.pending.id)
    readonly property var presentation: detailed && parent ? parent.presentationContext : null
    signal expandRequested()
    color: Theme.surface
    radius: 12
    clip: true
    readonly property bool loggingIn: client && ["loading", "waiting", "verify"].indexOf(client.state) >= 0
    readonly property bool online: client && ["connecting", "connected", "reconnecting"].indexOf(client.state) >= 0

    Column {
        id: header
        objectName: "weixinFixedHeader"
        x: 10
        y: 8
        width: parent.width - 20
        spacing: 5
        Row {
            width: parent.width
            spacing: 4
            Text {
                width: parent.width - 48
                text: qsTr("微信 · ClawBot")
                color: Theme.ink
                font.pixelSize: 13
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
            }
            IconButton {
                text: panel.detailed ? qsTr("返回") : "↗"
                textSize: panel.detailed ? 11 : 14
                tooltip: panel.detailed ? qsTr("返回画布") : qsTr("打开微信完整视图")
                onClicked: {
                    if (panel.detailed && panel.presentation) panel.presentation.close()
                    else panel.expandRequested()
                }
            }
        }
        Text {
            width: parent.width
            text: panel.client ? panel.client.detail : qsTr("微信组件不可用")
            textFormat: Text.PlainText
            color: panel.client && panel.client.state === "connected" ? "#16834B" : Theme.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Text {
            width: parent.width
            visible: !panel.detailed && panel.chat !== null && !panel.hasApproval
            text: panel.chat ? (panel.chat.enabled ? qsTr("自动回复：开 · ") : panel.chat.autoReply
                ? qsTr("自动回复：等待或暂停 · ") : qsTr("自动回复：关 · "))
                + panel.chat.notice : ""
            textFormat: Text.PlainText
            color: panel.chat && panel.chat.enabled ? "#16834B" : Theme.muted
            font.pixelSize: 10
            maximumLineCount: 2
            elide: Text.ElideRight
            wrapMode: Text.Wrap
        }
        Flow {
            visible: !panel.hasApproval
            width: parent.width
            spacing: 4
            IconButton {
                text: panel.client && panel.client.hasAccount ? qsTr("连接") : qsTr("扫码绑定")
                visible: !panel.online && !panel.loggingIn
                enabled: !!panel.client && panel.client.state !== "expired"
                filled: true
                textSize: 11
                onClicked: panel.client.hasAccount ? panel.client.connectAccount() : panel.client.login()
            }
            IconButton {
                text: panel.loggingIn ? qsTr("取消") : qsTr("断开")
                visible: panel.online || panel.loggingIn
                textSize: 11
                onClicked: panel.client.disconnectAccount()
            }
            IconButton {
                text: qsTr("退出登录")
                visible: panel.client && panel.client.hasAccount
                destructive: true
                textSize: 11
                onClicked: logoutConfirm.visible = !logoutConfirm.visible
            }
            IconButton {
                text: qsTr("清空消息")
                visible: panel.detailed
                textSize: 11
                onClicked: panel.client.clearMessages()
            }
            IconButton {
                text: qsTr("模型设置")
                textSize: 11
                onClicked: {
                    if (panel.detailed) panel.settingsVisible = !panel.settingsVisible
                    else panel.expandRequested()
                }
            }
            IconButton {
                visible: !panel.detailed
                text: panel.chat && panel.chat.autoReply ? qsTr("关闭自动回复") : qsTr("开启自动回复")
                textSize: 11
                selected: panel.chat && panel.chat.autoReply
                enabled: !!panel.chat
                onClicked: panel.chat.setEnabled(!panel.chat.autoReply)
            }
        }
        Row {
            id: logoutConfirm
            visible: false
            spacing: 4
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("清除本机绑定？")
                color: Theme.danger
                font.pixelSize: 11
            }
            IconButton {
                text: qsTr("确认退出")
                destructive: true
                textSize: 11
                onClicked: { logoutConfirm.visible = false; panel.client.logout() }
            }
            IconButton { text: qsTr("取消"); textSize: 11; onClicked: logoutConfirm.visible = false }
        }
        Repeater {
            model: panel.chat && panel.chat.tools.pending.id ? [panel.chat.tools.pending] : []
            WeixinApproval {
                width: header.width
                tools: panel.chat.tools
                detailed: panel.detailed
                onDetailsRequested: panel.expandRequested()
            }
        }
    }

    Flickable {
        id: content
        objectName: "weixinTranscript"
        x: 10
        y: header.y + header.height + 8
        width: parent.width - 20
        height: Math.max(0, composer.y - y - 8)
        clip: true
        contentHeight: body.height
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        Column {
            id: body
            width: content.width
            spacing: 10
            WeixinSettings {
                visible: panel.detailed
                width: body.width
                chat: panel.chat
                expanded: panel.settingsVisible
                connected: panel.client && panel.client.state === "connected"
            }
            Rectangle {
                visible: panel.client && panel.client.qrImage.length > 0
                width: Math.min(parent.width, panel.detailed ? 240 : 160)
                height: width
                color: "white"
                anchors.horizontalCenter: parent.horizontalCenter
                Image {
                    objectName: "weixinQrImage"
                    anchors.fill: parent
                    source: panel.client ? panel.client.qrImage : ""
                    fillMode: Image.PreserveAspectFit
                    smooth: false
                    cache: false
                }
            }
            Row {
                visible: panel.client && panel.client.state === "verify"
                width: parent.width
                spacing: 4
                InlineField {
                    id: verifyCode
                    width: parent.width - verifyButton.width - 4
                    placeholderText: qsTr("手机显示的配对码")
                    maximumLength: 12
                    validator: RegularExpressionValidator { regularExpression: /[0-9]{4,12}/ }
                    onAccepted: { panel.client.verify(text); clear() }
                }
                IconButton {
                    id: verifyButton
                    text: qsTr("验证")
                    onClicked: { panel.client.verify(verifyCode.text); verifyCode.clear() }
                }
            }
            Text {
                width: parent.width
                visible: panel.client && panel.client.warning.length > 0
                text: panel.client ? panel.client.warning : ""
                textFormat: Text.PlainText
                color: Theme.danger
                font.pixelSize: 11
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                visible: panel.detailed && panel.client && panel.client.hasAccount
                text: panel.client ? qsTr("绑定者：") + panel.client.userId + "\n"
                    + (panel.client.persisted ? qsTr("Windows 加密保存绑定；聊天记录另存于本机")
                                              : qsTr("绑定当前仅在内存；人设与聊天记录另存于本机")) : ""
                textFormat: Text.PlainText
                font.pixelSize: 11
                color: Theme.muted
                wrapMode: Text.WrapAnywhere
            }
            Text {
                width: parent.width
                visible: panel.client && panel.client.messages.length === 0 && !panel.loggingIn
                text: qsTr("仅接收绑定者发给 ClawBot 的单聊。\n先从微信发一条文字，即可在这里手动回复。\n↗ 完整视图可配置 DeepSeek 自动回复。")
                textFormat: Text.PlainText
                font.pixelSize: 11
                color: Theme.muted
                wrapMode: Text.Wrap
            }
            Repeater {
                model: panel.client ? panel.client.messages : []
                Rectangle {
                    id: messageRow
                    required property var modelData
                    width: body.width
                    height: messageColumn.height + 16
                    radius: 8
                    color: modelData.direction === "out" ? Theme.primarySoft : "#F3F5F8"
                    Column {
                        id: messageColumn
                        x: 8
                        y: 8
                        width: parent.width - 16
                        spacing: 4
                        Text {
                            width: parent.width
                            text: (messageRow.modelData.direction === "out" ? qsTr("本机 → 微信") : qsTr("微信 → 本机"))
                                + " · " + messageRow.modelData.time + " · " + messageRow.modelData.status
                            textFormat: Text.PlainText
                            color: Theme.muted
                            font.pixelSize: 10
                            wrapMode: Text.Wrap
                        }
                        TextEdit {
                            width: parent.width
                            text: messageRow.modelData.text
                            textFormat: TextEdit.PlainText
                            readOnly: true
                            selectByMouse: true
                            wrapMode: TextEdit.WrapAnywhere
                            color: Theme.ink
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
    Row {
        id: composer
        x: 10
        y: parent.height - height - 10
        width: parent.width - 20
        spacing: 4
        InlineField {
            id: draft
            objectName: "weixinReplyField"
            width: parent.width - sendButton.width - 4
            placeholderText: qsTr("手动回复绑定者")
            maximumLength: 2000
            enabled: panel.client && panel.client.canSend
            onAccepted: send()
            function send() {
                if (panel.client.sendText(text)) clear()
            }
        }
        IconButton {
            id: sendButton
            text: panel.client && panel.client.sending ? qsTr("发送中") : qsTr("发送")
            filled: true
            textSize: 11
            enabled: panel.client && panel.client.canSend && draft.text.trim().length > 0
            onClicked: draft.send()
        }
    }
}
