import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "feishuAgentApplication"
    implicitWidth: 840; implicitHeight: 680
    color: "#202126"; radius: 12
    property var snapshot: appBackend ? JSON.parse(appBackend.stateJson || "{}") : ({})
    property string commandError: ""
    readonly property bool running: appBackend && appBackend.running
    readonly property color ink: "#e9e9e5"
    readonly property color muted: "#a1a29d"
    readonly property color accent: "#afc7db"
    readonly property color line: "#3b3c43"
    readonly property var requests: snapshot.tasks || []
    function command(name, taskId) {
        commandError = ""
        appBackend.call(name, {taskId: taskId || ""}, name + ":" + Date.now())
    }
    component Label: Text {
        color: root.muted; font.pixelSize: 12; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
    }
    component Action: Button {
        id: action
        property bool primary: false
        implicitHeight: 34; implicitWidth: Math.max(54, contentItem.implicitWidth + 22)
        leftPadding: 11; rightPadding: 11
        contentItem: Text {
            text: action.text; color: action.primary ? "#1c252e" : root.ink
            font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
        }
        background: Rectangle {
            radius: 7; color: action.primary ? root.accent : action.hovered ? "#32333a" : "transparent"
            border.color: action.visualFocus ? root.accent : root.line; opacity: action.enabled ? 1 : 0.5
        }
    }
    Connections {
        target: appBackend
        function onFailed(requestId, error) { root.commandError = error }
        function onCompleted(requestId, resultJson) { root.commandError = "" }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: root.width < 480 ? 14 : 22; spacing: 14
        RowLayout {
            Layout.fillWidth: true; spacing: 12
            ColumnLayout {
                Layout.fillWidth: true; spacing: 5
                Text { text: "飞书 Agent"; color: root.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
                Label { Layout.fillWidth: true; text: "飞书文字消息 → Polaris Agent → 原消息回复" }
            }
            Action { objectName: "feishuAgentToggle"; text: appBackend && appBackend.stopping ? "正在停止…" : root.running ? "停止运行" : "开始运行"; primary: !root.running; enabled: appBackend && appBackend.available && !appBackend.stopping; onClicked: root.running ? appBackend.stop() : appBackend.start() }
        }
        Label { Layout.fillWidth: true; text: root.running ? "后台运行中 · 切换页面后继续处理新消息" : "已停止 · 开始运行后接收新消息"; color: root.running ? "#a6c8b6" : root.muted }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: identities.implicitHeight + 26
            color: "#292a30"; radius: 9; border.color: root.line
            ColumnLayout {
                id: identities; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 13; spacing: 7
                Label { Layout.fillWidth: true; color: root.ink; text: "飞书机器人 · " + ((root.snapshot.feishu || {}).instanceName || "待连接") + " · " + ((root.snapshot.feishu || {}).connectionState === "connected" ? "已连接" : (root.snapshot.feishu || {}).connectionState === "connecting" ? "连接中" : "未连接") }
                Label { Layout.fillWidth: true; text: "实例：" + (root.snapshot.feishuInstance || "请在应用连接中选择同一个飞书实例") }
                Label { Layout.fillWidth: true; color: root.ink; text: "Polaris Agent · " + ((root.snapshot.agent || {}).model || "待连接") + " · " + ((root.snapshot.agent || {}).ready ? "已就绪" : "未就绪") }
                Label { Layout.fillWidth: true; text: "实例：" + (root.snapshot.agentInstance || "请在应用连接中选择同一个 Agent 实例") }
                Repeater {
                    model: root.snapshot.toolGroups || []
                    delegate: ColumnLayout {
                        id: tools
                        objectName: "feishuAgentTools_" + modelData.title
                        required property var modelData
                        Layout.fillWidth: true; spacing: 4
                        Label { Layout.fillWidth: true; color: root.ink; text: tools.modelData.title + " · " + (tools.modelData.instanceId ? "已接入" : "待连接") + " · " + tools.modelData.labels.length + " 项工具" }
                        Label { Layout.fillWidth: true; text: "实例：" + (tools.modelData.instanceId || "请选择同一组工具的组件实例") }
                        Label { Layout.fillWidth: true; text: tools.modelData.labels.join("、") }
                    }
                }
            }
        }
        Label { Layout.fillWidth: true; text: "处理文字和富文本中的正文，每条最多 8000 字。附件不会送给模型。首次开启从当前消息开始。" }
        Rectangle {
            Layout.fillWidth: true; implicitHeight: errorContent.implicitHeight + 20
            visible: !!root.commandError || !!root.snapshot.error || !!(appBackend && appBackend.error); radius: 7; color: "#292a30"; border.color: "#d7a09b"
            ColumnLayout {
                id: errorContent; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 10; spacing: 8
                Label { Layout.fillWidth: true; color: "#e7aaa5"; text: root.commandError || (appBackend && appBackend.error) || root.snapshot.error || "" }
                Action { objectName: "feishuAgentContinue"; text: "处理后继续"; enabled: root.running; onClicked: root.command("continue", "") }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text { text: "最近请求"; color: root.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            Label { text: "最近 40 条与待处理请求" }
        }
        ListView {
            id: history; objectName: "feishuAgentRequests"
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 10
            model: root.requests
            delegate: Rectangle {
                id: request
                required property var modelData
                width: history.width; implicitHeight: taskBody.implicitHeight + 24
                radius: 9; color: "#292a30"; border.color: root.line
                ColumnLayout {
                    id: taskBody; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12; spacing: 9
                    RowLayout {
                        Layout.fillWidth: true
                        Label { Layout.fillWidth: true; text: request.modelData.chatId + (request.modelData.threadId ? " · 话题" : ""); elide: Text.ElideMiddle; maximumLineCount: 1 }
                        Label { text: ({pending:"等待处理", generating:"生成中", ready:"等待发送", sending:"发送中", done:"已回复", skipped:"已跳过", failed:"生成未完成", send_failed:"发送被拒绝", unknown:"待核对发送"})[request.modelData.state] || request.modelData.state; color: request.modelData.state === "done" ? "#a6c8b6" : root.accent }
                    }
                    Label { Layout.fillWidth: true; color: root.ink; text: request.modelData.text; font.pixelSize: 13 }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.line; visible: !!request.modelData.answer }
                    Label { Layout.fillWidth: true; text: request.modelData.answer || ""; visible: !!text; color: root.ink; font.pixelSize: 13 }
                    Label { Layout.fillWidth: true; text: request.modelData.error || ""; visible: !!text; color: "#e7aaa5" }
                    Flow {
                        Layout.fillWidth: true; spacing: 7
                        Action { objectName: "feishuAgentRetry_" + request.modelData.id; text: "重新生成"; visible: request.modelData.state === "failed"; enabled: root.running; onClicked: root.command("retry", request.modelData.id) }
                        Action { text: "跳过此请求"; visible: request.modelData.state === "failed"; enabled: root.running; onClicked: root.command("skip", request.modelData.id) }
                        Action { text: "重新发送原回答"; visible: request.modelData.state === "send_failed"; enabled: root.running; onClicked: root.command("resend", request.modelData.id) }
                        Action { text: "已在飞书确认发出"; visible: request.modelData.state === "unknown"; enabled: root.running; onClicked: root.command("confirm_sent", request.modelData.id) }
                        Action { text: "确认未发出，重新发送"; visible: request.modelData.state === "unknown"; enabled: root.running; onClicked: root.command("resend", request.modelData.id) }
                    }
                }
            }
            Label { anchors.fill: parent; anchors.margins: 20; visible: !root.requests.length; text: "开始运行后，向已连接的飞书机器人发送一条文字消息。请求和回答将显示在这里。" }
            ScrollBar.vertical: ScrollBar { }
        }
    }
}
