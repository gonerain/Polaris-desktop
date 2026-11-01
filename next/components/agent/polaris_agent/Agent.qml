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
    property string selectedId: ""
    property var sessions: (snapshot.sessions || []).slice().sort(function(a,b) { return Number(b.marked) - Number(a.marked) })
    property var selected: sessions.find(function(s) { return s.id === selectedId }) || null
    property var runs: selected ? selected.runs || [] : []
    property string chosenRunId: ""
    property var latestRun: runs.length ? runs[runs.length-1] : null
    property var run: runs.find(function(r) { return r.id === chosenRunId }) || (runs.length ? runs[runs.length-1] : null)
    property var deliveries: (snapshot.deliveries || []).filter(function(d) { return d.sessionId === selectedId })
    function state(r) { if (!r) return "暂无轮次"; return ({running:"进行中",completed:"已完成",failed:"失败",stopped:"已停止",unknown:"结束未确认"})[r.status] || r.status }
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
        contentItem: Text { text: control.displayText; color: "#4b5d73"; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight; leftPadding: 10; rightPadding: 24 }
        background: Rectangle { radius: 7; color: "#ffffff"; border.color: "#d6dfe9" }
    }
    function presence(s) { if (!s.online) return "离线"; return ({host:"在线",connection:"已连接",unverified:"未验证"})[s.liveness] || "未验证" }
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
            AgentButton { text: "刷新"; onClicked: agentModel.refresh() }
        }
        Label { visible: root.sessions.length === 0; text: "暂无会话"; color: "#737d8c"; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter }
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
                MouseArea { anchors.fill: parent; onClicked: root.selectedId = modelData.id }
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
                Label { text: root.state(root.run); color: "#48576a"; Layout.fillWidth: true; elide: Text.ElideRight }
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
            TextArea { id: input; objectName: "agentInput"; Layout.fillWidth: true; Layout.preferredHeight: 64; wrapMode: TextEdit.Wrap; placeholderText: "向此会话发送消息"; selectByMouse: true; background: Rectangle { color: "#ffffff"; radius: 6; border.color: "#d6dce5" } }
            RowLayout {
                Layout.fillWidth: true
                Label { Layout.fillWidth: true; text: root.selected && (!root.selected.marked || !root.selected.online || !root.selected.canSend) ? "当前会话不可发送" : ""; color: "#737d8c"; font.pixelSize: 11 }
                AgentButton { objectName: "agentSend"; text: sendMode.currentIndex === 1 ? "追加指导" : "发送新一轮"; enabled: !!root.selected && root.selected.marked && root.selected.online && root.selected.canSend && input.text.trim().length > 0; onClicked: { if (root.invoke("send",{session_id:root.selectedId,text:input.text,mode:sendMode.currentIndex === 1 ? "steer" : "start"})) input.clear() } }
            }
            Label { Layout.fillWidth: true; visible: root.deliveries.length > 0; wrapMode: Text.Wrap; text: { var d = root.deliveries.slice(-1)[0]; return d ? "发送回执：" + (({pending:"待接收",accepted:"已接收",rejected:"已拒绝",unknown:"结果未确认"})[d.status] || d.status) + (d.detail ? " · " + d.detail : "") : "" } color: "#697586"; font.pixelSize: 11 }
        }
        Label { Layout.fillWidth: true; visible: !!root.snapshot.storageNotice; text: root.snapshot.storageNotice || ""; wrapMode: Text.Wrap; color: "#a7652c" }
        Label { objectName: "agentError"; Layout.fillWidth: true; visible: !!agentModel.lastError; text: agentModel.lastError; wrapMode: Text.Wrap; color: "#b14343" }
        Item { Layout.fillHeight: true; visible: !root.selected }
    }
}
