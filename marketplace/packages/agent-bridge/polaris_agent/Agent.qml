import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "agentView"
    implicitWidth: 410
    implicitHeight: 520
    radius: 12
    color: "#f7f8fa"
    property var snapshot: JSON.parse(agentModel.dataJson)
    property var plugin: JSON.parse(agentModel.pluginJson)
    property string selectedId: ""
    property var sessions: (snapshot.sessions || []).slice().sort(function(a,b) { return Number(b.marked) - Number(a.marked) })
    property var selected: sessions.find(function(s) { return s.id === selectedId }) || null
    property var runs: selected ? selected.runs || [] : []
    property string chosenRunId: ""
    property var latestRun: runs.length ? runs[runs.length-1] : null
    property var run: runs.find(function(r) { return r.id === chosenRunId }) || (runs.length ? runs[runs.length-1] : null)
    property var deliveries: (snapshot.deliveries || []).filter(function(d) { return d.sessionId === selectedId })
    onSessionsChanged: {
        if (!sessions.some(function(s) { return s.id === selectedId })) {
            var preferred = sessions.find(function(s) { return s.marked && s.online }) || sessions.find(function(s) { return s.online }) || sessions[0]
            selectedId = preferred ? preferred.id : ""
        }
    }
    onSelectedIdChanged: chosenRunId = ""
    function sendUnavailable() {
        if (!selected) return ""
        if (!selected.marked) return "先标记此会话，即可发送"
        if (!selected.online) return "会话离线，请打开原会话并确认插件已连接"
        if (!selected.canSend) return "当前宿主插件未提供发送能力"
        return ""
    }
    function state(r) { if (!r) return "暂无轮次"; if (r.status === "unknown") return r.reply ? "已收到回复" : "完成状态未知"; return ({running:"进行中",completed:"已完成",failed:"失败",stopped:"已停止"})[r.status] || r.status }
    function stateExplanation(s, r) {
        var lines = []
        if (s && s.online && s.liveness !== "host") lines.push("插件已连接，但尚不能确认原会话是否仍在线。")
        if (r && r.status === "unknown") lines.push(r.reply ? "已收到本轮回复，但尚未收到最终完成确认。" : "尚未收到本轮最终完成确认。")
        return lines.join("\n")
    }
    component AgentButton: Button {
        id: control
        implicitHeight: 30
        leftPadding: 12; rightPadding: 12
        contentItem: Text { text: control.text; font.pixelSize: 12; color: control.enabled ? "#40516a" : "#96a1b0"; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 7; color: control.down ? "#d9e1ec" : control.hovered ? "#e3e9f1" : "#edf1f6"; border.color: "#dce3ec"; opacity: control.enabled ? 1 : 0.6 }
    }
    component AgentCombo: ComboBox {
        id: control
        implicitHeight: 30
        palette.window: "#ffffff"
        palette.base: "#ffffff"
        palette.text: "#40516a"
        palette.buttonText: "#40516a"
        palette.highlight: "#e3e9f1"
        palette.highlightedText: "#263143"
        contentItem: Text { text: control.displayText; color: "#4b5d73"; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; leftPadding: 10; rightPadding: 24 }
        background: Rectangle { radius: 7; color: "#ffffff"; border.color: "#d6dfe9" }
        indicator: Text { x: control.width - width - 10; anchors.verticalCenter: parent.verticalCenter; text: "▾"; font.pixelSize: 14; color: "#697586" }
        delegate: ItemDelegate {
            required property int index
            width: control.width - 8
            implicitHeight: 32
            highlighted: control.highlightedIndex === index
            contentItem: Text { text: control.textAt(index); color: "#40516a"; font.pixelSize: 12; font.bold: control.currentIndex === index; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
            background: Rectangle { radius: 5; color: parent.highlighted || parent.hovered ? "#e3e9f1" : "#ffffff" }
        }
        popup: Popup {
            y: control.height + 4; width: control.width; padding: 4
            implicitHeight: Math.min(contentItem.implicitHeight + 8, 240)
            contentItem: ListView {
                clip: true; implicitHeight: contentHeight
                model: control.popup.visible ? control.delegateModel : null
                currentIndex: control.highlightedIndex
                ScrollIndicator.vertical: ScrollIndicator { }
            }
            background: Rectangle { color: "#ffffff"; radius: 7; border.color: "#d6dfe9" }
        }
    }
    function presence(s) { if (!s.online) return "离线"; return ({host:"在线",connection:"插件已连接",unverified:"在线状态未知"})[s.liveness] || "在线状态未知" }
    function invoke(op,p) { return agentModel.invoke(op,JSON.stringify(p)) }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Label { text: "会话"; font.bold: true; color: "#323a46" }
            Label { text: root.sessions.length; color: "#737d8c" }
            Item { Layout.fillWidth: true }
            AgentButton { objectName: "agentPluginSettings"; text: "Codex 插件"; onClicked: { pluginDialog.open(); agentModel.pluginAction(false) } }
            AgentButton { text: "刷新"; onClicked: agentModel.refresh() }
        }
        Label { visible: root.sessions.length === 0; text: "暂无接入会话。启用 Agent Bridge 插件后，在 Pi 或 Codex 中打开新会话。"; wrapMode: Text.Wrap; color: "#737d8c"; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
        ListView {
            id: list
            objectName: "agentSessions"
            Layout.fillWidth: true
            Layout.preferredHeight: root.sessions.length ? Math.min(180, root.sessions.length*62) : 0
            clip: true
            model: root.sessions
            spacing: 4
            delegate: Rectangle {
                required property var modelData
                width: list.width
                height: 58
                radius: 7
                color: root.selectedId === modelData.id ? "#e5eaf1" : "#ffffff"
                Column {
                    anchors.fill: parent; anchors.margins: 8; spacing: 3
                    Text { width: parent.width; text: (modelData.marked ? "★  " : "") + modelData.title; elide: Text.ElideRight; color: "#263143"; font.bold: true }
                    Text { width: parent.width; text: modelData.adapter + " · " + root.presence(modelData) + " · " + root.state((modelData.runs || []).slice(-1)[0]); elide: Text.ElideRight; color: "#697586"; font.pixelSize: 11 }
                }
                ToolTip.visible: sessionMouse.containsMouse && ToolTip.text.length > 0
                ToolTip.text: root.stateExplanation(modelData, (modelData.runs || []).slice(-1)[0])
                MouseArea { id: sessionMouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.selectedId = modelData.id }
            }
            ScrollBar.vertical: ScrollBar {}
        }
        ColumnLayout {
            visible: !!root.selected
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 7
            RowLayout {
                Layout.fillWidth: true
                Label { text: root.state(root.run); color: "#48576a"; Layout.fillWidth: true; elide: Text.ElideRight
                    ToolTip.visible: statusHover.hovered && ToolTip.text.length > 0
                    ToolTip.text: root.stateExplanation(root.selected, root.run)
                    HoverHandler { id: statusHover }
                }
                AgentButton { objectName: "agentMark"; text: root.selected && root.selected.marked ? "取消标记" : "标记"; onClicked: root.invoke(root.selected.marked ? "unmark" : "mark", {session_id:root.selectedId}) }
            }
            AgentCombo {
                Layout.fillWidth: true
                visible: root.runs.length > 1
                model: root.runs.map(function(r,i) { return "第 " + (i+1) + " 轮 · " + root.state(r) })
                displayText: root.run ? "第 " + (root.runs.findIndex(function(r) { return r.id === root.run.id })+1) + " 轮 · " + root.state(root.run) : ""
                currentIndex: root.run ? root.runs.findIndex(function(r) { return r.id === root.run.id }) : -1
                onActivated: root.chosenRunId = root.runs[currentIndex].id
            }
            TextField { objectName: "agentSessionId"; Layout.fillWidth: true; readOnly: true; selectByMouse: true; text: root.selected ? root.selected.sessionId : ""; color: "#697586"; font.pixelSize: 11; background: Rectangle { radius: 7; color: "#ffffff"; border.color: "#dce3ec" } }
            Label { visible: !!root.run && !!root.run.replyTruncated; text: "回复已截断"; color: "#a7652c"; font.pixelSize: 11 }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 65
                TextArea { objectName: "agentReply"; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; text: root.run && root.run.reply ? root.run.reply : (root.run && root.run.detail ? root.run.detail : "暂无回复"); color: "#303b4b"; background: Rectangle { color: "#ffffff"; radius: 6 } }
            }
            AgentCombo {
                id: sendMode
                objectName: "agentSendMode"
                Layout.fillWidth: true
                model: ["新一轮", "追加指导"]
                currentIndex: root.latestRun && root.latestRun.status === "running" ? 1 : 0
            }
            TextArea { id: input; objectName: "agentInput"; Layout.fillWidth: true; Layout.preferredHeight: 64; wrapMode: TextEdit.Wrap; color: "#303b4b"; placeholderTextColor: "#737d8c"; selectionColor: "#ccdafa"; selectedTextColor: "#263143"; placeholderText: "向此会话发送消息"; selectByMouse: true; background: Rectangle { color: "#ffffff"; radius: 6; border.color: "#d6dce5" } }
            RowLayout {
                Layout.fillWidth: true
                Label { objectName: "agentSendUnavailable"; Layout.fillWidth: true; text: root.sendUnavailable(); wrapMode: Text.Wrap; color: "#737d8c"; font.pixelSize: 11 }
                AgentButton { objectName: "agentSend"; text: sendMode.currentIndex === 1 ? "追加指导" : "发送新一轮"; enabled: !!root.selected && root.selected.marked && root.selected.online && root.selected.canSend && input.text.trim().length > 0; onClicked: { if (root.invoke("send",{session_id:root.selectedId,text:input.text,mode:sendMode.currentIndex === 1 ? "steer" : "start"})) input.clear() } }
            }
            Label { Layout.fillWidth: true; visible: root.deliveries.length > 0; wrapMode: Text.Wrap; text: { var d = root.deliveries.slice(-1)[0]; return d ? "发送回执：" + (({pending:"等待接收方确认",accepted:"接收方已接收",rejected:"接收方已拒绝",unknown:"是否送达未知"})[d.status] || d.status) + (d.detail ? " · " + d.detail : "") : "" } color: "#697586"; font.pixelSize: 11 }
        }
        Label { Layout.fillWidth: true; visible: !!root.snapshot.storageNotice; text: root.snapshot.storageNotice || ""; wrapMode: Text.Wrap; color: "#a7652c" }
        Label { objectName: "agentError"; Layout.fillWidth: true; visible: !!agentModel.lastError; text: agentModel.lastError; wrapMode: Text.Wrap; color: "#b14343" }
        Item { Layout.fillHeight: true; visible: !root.selected }
    }
    Dialog {
        id: pluginDialog
        objectName: "agentPluginDialog"
        title: "Codex 插件"
        anchors.centerIn: parent
        width: Math.min(root.width - 16, 390)
        modal: true
        footer: DialogButtonBox {
            AgentButton { text: "关闭"; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
            onRejected: pluginDialog.close()
        }
        contentItem: ColumnLayout {
            spacing: 10
            Label { text: agentModel.pluginBusy ? "正在检查或安装…" : (root.plugin.message || "尚未检查"); wrapMode: Text.Wrap; Layout.fillWidth: true; color: root.plugin.error || root.plugin.ok === false ? "#b14343" : "#40516a" }
            Label { visible: !!root.plugin.bundledVersion; text: "随包版本：" + (root.plugin.bundledVersion || "") + "\n安装版本：" + (root.plugin.installedVersion || "未安装"); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { visible: !agentModel.pluginBusy && !!root.plugin.bundledVersion; text: "Codex CLI：" + (root.plugin.codexAvailable ? "可用" : "未找到") + "\nNode.js 20+：" + (root.plugin.nodeAvailable ? "可用" : "未满足") + "\n插件启用：" + (root.plugin.installed ? (root.plugin.enabled ? "已启用" : "未启用") : "未安装"); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { visible: !!root.plugin.helpers; text: { var rows = (root.plugin.helpers || {}).results || []; return rows.map(function(row) { return ({update_available:"连接待更新",unavailable:"无法确认连接状态",legacy_requires_restart:"旧连接需重开会话",deferred:"投递完成后更新",restarting:"连接正在换代，等待确认"})[row.status] || "" }).filter(function(text) { return !!text }).filter(function(text, index, texts) { return texts.indexOf(text) === index }).join("；") } wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#a7652c" }
            Label { text: "安装后按 Codex 提示确认启用和 hooks 信任。"; wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#737d8c"; font.pixelSize: 11 }
            RowLayout {
                AgentButton { objectName: "agentPluginRefresh"; text: "检查状态"; enabled: !agentModel.pluginBusy; onClicked: agentModel.pluginAction(false) }
                AgentButton { objectName: "agentPluginInstall"; text: root.plugin.repairable ? "修复插件" : (root.plugin.installed ? (root.plugin.enabled ? "更新插件" : "更新并启用") : "安装到 Codex"); enabled: !agentModel.pluginBusy && !!root.plugin.codexAvailable && !!root.plugin.nodeAvailable && (!root.plugin.error || !!root.plugin.repairable); onClicked: agentModel.pluginAction(true) }
            }
        }
    }

}
