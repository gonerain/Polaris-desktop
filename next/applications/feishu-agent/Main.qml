import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "feishuAgentApplication"
    implicitWidth: 640; implicitHeight: 520
    color: "#202126"; radius: 12
    property var snapshot: appBackend ? JSON.parse(appBackend.stateJson || "{}") : ({})
    property string commandError: ""
    property bool settingsOpen: false
    readonly property bool running: appBackend && appBackend.running
    readonly property var attention: snapshot.attention || []
    readonly property var reminders: snapshot.reminders || ({})
    property bool remindersOpen: false
    function saveReminders(enabled, preferences) {
        commandError = ""
        appBackend.call("configure_reminders", {enabled: enabled, preferences: preferences}, "reminders:" + Date.now())
    }
    function localTime(value) { return value ? new Date(value).toLocaleString() : "尚无" }
    readonly property var warnings: appBackend ? JSON.parse(appBackend.warningsJson || "[]") : []
    readonly property color ink: "#e9e9e5"
    readonly property color muted: "#a1a29d"
    readonly property color accent: "#afc7db"
    readonly property color line: "#3b3c43"
    function command(name, item) {
        commandError = ""
        appBackend.call(name, item ? {kind: item.kind, id: item.id} : {}, name + ":" + Date.now())
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
            text: action.text; color: action.primary ? "#1c252e" : root.ink; font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter; horizontalAlignment: Text.AlignHCenter
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
        anchors.fill: parent; anchors.margins: root.width < 480 ? 16 : 24; spacing: 16
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true; spacing: 6
                Text { text: "飞书 Agent"; color: root.ink; font.pixelSize: 22; font.weight: Font.DemiBold }
                Label { text: "在飞书继续 Codex 的当前会话" }
            }
            Item { Layout.fillWidth: true }
            Action {
                objectName: "feishuAgentToggle"
                text: appBackend && appBackend.stopping ? "正在停止…" : root.running ? "停止" : "开始运行"
                primary: !root.running
                enabled: appBackend && appBackend.available && !appBackend.stopping
                onClicked: root.running ? appBackend.stop() : appBackend.start()
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.line }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 7
            Label {
                Layout.fillWidth: true; color: root.running ? "#a6c8b6" : root.muted
                text: !root.running ? "已停止" : root.snapshot.connected ? "飞书会话已连接" : "等待一条新的飞书消息建立连接"
            }
            Label {
                Layout.fillWidth: true
                text: root.snapshot.session ? "Codex · " + root.snapshot.session : "尚未连接 Codex 会话"
            }
            Label {
                visible: root.snapshot.pending > 0
                text: root.snapshot.pending + " 条消息待投递"
            }
        }
        Label {
            Layout.fillWidth: true; visible: !!text; color: "#e7aaa5"
            text: root.commandError || (appBackend && appBackend.error) || ""
        }
        RowLayout {
            Layout.fillWidth: true; visible: (root.snapshot.issues || []).length > 0
            Label { Layout.fillWidth: true; color: "#dbc38c"; text: "部分操作失败，处理原因后可继续。" }
            Action { text: "查看"; onClicked: root.settingsOpen = true }
            Action { objectName: "feishuAgentContinue"; text: "继续"; onClicked: root.command("continue") }
        }
        ColumnLayout {
            Layout.fillWidth: true; spacing: 8
            Label { Layout.fillWidth: true; text: "飞书内发送「面板」或「日程」，即可打开交互卡片。" }
            RowLayout {
                Layout.fillWidth: true; spacing: 8
                Action {
                    objectName: "feishuAgentSessionsCard"; text: "发送会话卡片"
                    enabled: root.running && root.snapshot.connected === true
                    onClicked: root.command("show_sessions")
                }
                Action {
                    objectName: "feishuAgentScheduleCard"; text: "发送日程卡片"
                    enabled: root.running && root.snapshot.connected === true
                    onClicked: root.command("show_schedule")
                }
            }
        }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: "日程提醒 · " + (root.reminders.enabled ? root.reminders.scheduled + " 条待发送 / " + root.reminders.pending + " 项待规划" : "未开启")
                    }
                    Action {
                        objectName: "feishuAgentReminders"
                        text: root.remindersOpen ? "收起提醒" : "提醒设置"
                        onClicked: root.remindersOpen = !root.remindersOpen
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; visible: root.remindersOpen; spacing: 8
                    Label {
                        Layout.fillWidth: true
                        text: "每小时仅将新增、变更及刚进入未来七天的事项交给 AI；包含有日期的未完成任务。到点校验后直接发飞书。取消、完成或改期会使旧提醒失效，以本机已同步数据为准。"
                    }
                    Action {
                        objectName: "feishuAgentRemindersToggle"
                        text: root.reminders.enabled ? "关闭日程提醒" : "开启日程提醒"
                        enabled: !!appBackend
                        onClicked: root.saveReminders(!root.reminders.enabled, root.reminders.preferences)
                    }
                    TextArea {
                        id: reminderPreferences
                        objectName: "feishuAgentReminderPreferences"
                        Layout.fillWidth: true; wrapMode: TextEdit.WrapAnywhere; selectByMouse: true
                        text: root.reminders.preferences || ""
                        color: root.ink; font.pixelSize: 12
                        background: Rectangle { radius: 6; color: "#292a30" }
                    }
                    Action {
                        text: "保存提醒偏好"
                        enabled: !!appBackend && reminderPreferences.text.trim().length > 0
                        onClicked: root.saveReminders(root.reminders.enabled === true, reminderPreferences.text)
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "最近检查：" + root.localTime(root.reminders.lastCheck) + "\n最近规划：" + root.localTime(root.reminders.lastPlanned) + "\n下次检查：" + root.localTime(root.reminders.nextCheck)
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "Google 最近同步：" + root.localTime(root.reminders.googleSync)
                              + (root.reminders.googleError ? "\n同步错误：" + root.reminders.googleError : "")
                    }
                    Label { Layout.fillWidth: true; text: "规划使用当前 Codex 会话的空闲回合；规划期间的新聊天暂存，完成后继续。停止应用时不检查、不发送，恢复后不补发过期提醒。" }
                    Repeater {
                        model: root.remindersOpen ? (root.reminders.plans || []).slice().reverse() : []
                        delegate: Label {
                            required property var modelData
                            Layout.fillWidth: true
                            text: ({scheduled: "待触发", queued: "待投递", sent: "已发送", cancelled: "已取消", expired: "已过期", failed: "失败", unknown: "结果未知", skipped: "已跳过"}[modelData.state] || modelData.state)
                                  + " · " + root.localTime(modelData.sendAt) + "\n" + modelData.text
                                  + (modelData.reason ? "\n" + modelData.reason : "")
                        }
                    }
                }
                Label { visible: root.attention.length > 0; text: "待处理 · " + root.attention.length; color: root.ink }
                Repeater {
                    model: root.attention
                    delegate: Rectangle {
                        id: entry
                        required property var modelData
                        property bool expanded: false
                        Layout.fillWidth: true; implicitHeight: content.implicitHeight + 24
                        color: "#292a30"; radius: 8
                        ColumnLayout {
                            id: content
                            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
                            spacing: 8
                            Label {
                                Layout.fillWidth: true; color: root.ink; maximumLineCount: entry.expanded ? 10000 : 2; elide: Text.ElideRight
                                text: entry.modelData.text
                            }
                            Label {
                                Layout.fillWidth: true; color: "#e7aaa5"; visible: entry.expanded
                                text: entry.modelData.error
                            }
                            Flow {
                                Layout.fillWidth: true; spacing: 6
                                Action { text: entry.expanded ? "收起原因" : entry.modelData.state === "unknown" ? "结果待核对" : "查看原因"; onClicked: entry.expanded = !entry.expanded }
                                Action {
                                    objectName: "feishuAgentRetry_" + entry.modelData.id
                                    visible: entry.modelData.kind !== "legacy"
                                    text: entry.modelData.state === "unknown" ? "确认未送达，重发" : "重试"
                                    onClicked: root.command("retry", entry.modelData)
                                }
                                Action {
                                    visible: entry.modelData.kind !== "legacy" && entry.modelData.state === "unknown"
                                    text: "已核对送达"; onClicked: root.command("confirm", entry.modelData)
                                }
                                Action {
                                    visible: entry.modelData.kind === "legacy" && entry.modelData.state !== "unknown" && entry.modelData.state !== "sending"
                                    text: "交给 Codex"; onClicked: root.command("transfer", entry.modelData)
                                }
                                Action { text: "跳过"; onClicked: root.command("skip", entry.modelData) }
                            }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true; visible: root.settingsOpen; spacing: 10
                    Label {
                        Layout.fillWidth: true
                        text: "飞书消息、卡片操作和卡片更新连接同一个机器人实例；会话列表和回复详情连接同一个 Agent Bridge 实例。首条新消息连接一个飞书会话。"
                    }
                    Label {
                        objectName: "feishuAgentWarnings"; Layout.fillWidth: true
                        visible: root.warnings.length > 0; color: "#dbc38c"; text: root.warnings.join("\n")
                    }
                    Label {
                        Layout.fillWidth: true; color: "#e7aaa5"
                        visible: (root.snapshot.issues || []).length > 0; text: (root.snapshot.issues || []).join("\n")
                    }
                    Label { text: "Bridge 回调地址 · on_complete" }
                    TextArea {
                        objectName: "feishuAgentCallback"; Layout.fillWidth: true
                        readOnly: true; selectByMouse: true; wrapMode: TextEdit.WrapAnywhere
                        text: JSON.stringify(root.snapshot.callback || {}, null, 2)
                        color: root.muted; font.pixelSize: 12
                        background: Rectangle { radius: 6; color: "#292a30" }
                    }
                }
            }
        }
        Button {
            id: settingsButton
            objectName: "feishuAgentSettings"
            text: root.settingsOpen ? "收起连接设置" : "连接设置"
            implicitHeight: 32; implicitWidth: contentItem.implicitWidth
            contentItem: Text { text: settingsButton.text; color: root.muted; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
            background: Item {}
            onClicked: root.settingsOpen = !root.settingsOpen
        }
    }
}
