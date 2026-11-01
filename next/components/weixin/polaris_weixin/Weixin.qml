import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: "weixinRoot"
    color: "#f7f8f8"
    implicitWidth: 370
    implicitHeight: 220
    property var snapshot: JSON.parse(weixinModel.dataJson || "{}")
    property bool setupOpen: false
    property bool agentOpen: false
    property var agent: JSON.parse(weixinModel.agentJson || "{}")
    property var catalog: JSON.parse(weixinModel.catalogJson || "[]")
    property var allowedDraft: []
    property bool allowedInitialized: false
    function selected(target, operation) {
        return allowedDraft.some(function(row) { return row.target === target && row.operation === operation })
    }
    function selectOperation(target, operation, checked) {
        var values = allowedDraft.filter(function(row) { return row.target !== target || row.operation !== operation })
        if (checked) values.push({target:target, operation:operation})
        allowedDraft = values
    }
    function openAgent() {
        if (!allowedInitialized) { allowedDraft = agent.allowed || []; allowedInitialized = true }
        setupOpen = false; agentOpen = true; weixinModel.loadAgentCatalog()
    }
    property string confirmation: ""
    property bool online: snapshot.state === "connected"
    property bool canSend: snapshot.canSend === true
    property string statusNotice: weixinModel.lastError || snapshot.warning || (["error", "expired", "reconnecting"].indexOf(snapshot.state) >= 0 ? snapshot.detail : "") || ""
    function action(name, args) { return weixinModel.invoke(name, JSON.stringify(args || {})) }
    function stateText() {
        var labels = {"loading":"准备登录", "waiting":"等待扫码", "reconnecting":"重连中", "expired":"登录已过期", "offline":"离线", "connected":"在线", "connecting":"连接中", "verify":"等待配对", "error":"连接异常"}
        return labels[snapshot.state] || snapshot.state || "未连接"
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 7
        RowLayout {
            Layout.fillWidth: true
            spacing: 7
            Rectangle { width: 6; height: 6; radius: 3; color: root.online ? "#28a36b" : "#a0a7ac" }
            Label { text: root.stateText(); color: "#6c7479"; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
            Switch {
                objectName: "weixinAgentToggle"
                text: "自动回复"; font.pixelSize: 11; padding: 0; spacing: 3
                enabled: root.online && root.agent.hasKey === true
                checked: root.agent.enabled === true
                onClicked: {
                    root.action("configure_agent", {enabled: !root.agent.enabled})
                    // Controls toggle before clicked; restore the authoritative state after a denied write.
                    checked = Qt.binding(function() { return root.agent.enabled === true })
                }
            }
            WeixinButton { objectName: "weixinAgentSettings"; text: "设置"; flat: true; implicitWidth: 36; implicitHeight: 28; font.pixelSize: 11; onClicked: root.agentOpen ? root.agentOpen = false : root.openAgent() }
            WeixinButton { objectName: "weixinLoginToggle"; text: root.setupOpen ? "收起" : (root.snapshot.hasAccount ? "登录信息" : "扫码登录"); flat: true; font.pixelSize: 11; implicitHeight: 28; onClicked: { root.agentOpen = false; root.setupOpen = !root.setupOpen; if (root.setupOpen && !root.snapshot.hasAccount && !root.snapshot.qrImage) root.action("login") } }
            WeixinButton { objectName: "weixinOptions"; text: "⋯"; implicitWidth: 28; implicitHeight: 28; onClicked: options.open(); Menu {
                id: options
                MenuItem { text: "连接"; enabled: !!root.snapshot.hasAccount && !root.online; onTriggered: root.action("connect") }
                MenuItem { text: "断开"; enabled: !!root.snapshot.hasAccount; onTriggered: root.action("disconnect") }
                MenuSeparator {}
                MenuItem { text: "清空消息"; onTriggered: root.confirmation = "clear_messages" }
                MenuItem { text: "退出登录"; enabled: !!root.snapshot.hasAccount; onTriggered: root.confirmation = "logout" }
            } }
        }
        ColumnLayout {
            visible: root.agentOpen
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 3
            Label { text: "使用 DeepSeek，将发送新收到的文字及工具结果"; font.pixelSize: 10; wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#6c7479" }
            Label { objectName: "weixinAgentKeyNotice"; visible: !root.agent.hasKey; text: "缺少 DEEPSEEK_API_KEY，请配置后重启组件"; font.pixelSize: 10; color: "#88613e"; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ListView {
                objectName: "weixinAgentOperations"; Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                model: root.catalog
                ScrollBar.vertical: ScrollBar {}
                delegate: CheckBox {
                    required property var modelData
                    width: ListView.view.width; height: 30; font.pixelSize: 11
                    objectName: "weixinAgentOperation_" + modelData.target + "_" + modelData.operation
                    text: modelData.component + " · " + modelData.operation + " · " + (modelData.access === "write" ? "写入" : "读取")
                    checked: root.selected(modelData.target, modelData.operation)
                    onClicked: root.selectOperation(modelData.target, modelData.operation, checked)
                }
                Label { anchors.centerIn: parent; visible: root.catalog.length === 0; text: "暂无可选操作"; font.pixelSize: 11; color: "#92999c" }
            }
            RowLayout {
                Layout.fillWidth: true
                WeixinButton { objectName: "weixinAgentNewConversation"; text: "新对话"; implicitHeight: 26; onClicked: root.action("new_conversation") }
                Item { Layout.fillWidth: true }
                WeixinButton { objectName: "weixinAgentSave"; text: "保存"; primary: true; implicitHeight: 26; onClicked: if(root.action("configure_agent", {enabled:root.agent.enabled === true, allowed:root.allowedDraft})) root.agentOpen = false }
                WeixinButton { objectName: "weixinAgentClose"; text: "关闭"; implicitHeight: 26; onClicked: root.agentOpen = false }
            }
        }
        Label { objectName: "weixinAgentStatus"; visible: !!root.agent.busy || !!root.agent.error; text: root.agent.error || "自动回复中…"; Layout.fillWidth: true; font.pixelSize: 11; color: root.agent.error ? "#88613e" : "#258956"; maximumLineCount: 2; wrapMode: Text.Wrap; elide: Text.ElideRight }
        Rectangle {
            visible: root.confirmation !== ""
            Layout.fillWidth: true; implicitHeight: 38; color: "#ecefef"; radius: 7
            RowLayout { anchors.fill: parent; anchors.margins: 4
                Label { text: root.confirmation === "logout" ? "退出当前账号？" : "清空本地消息？"; Layout.fillWidth: true; font.pixelSize: 12 }
                WeixinButton { text: "取消"; implicitHeight: 28; onClicked: root.confirmation = "" }
                WeixinButton { text: "确定"; implicitHeight: 28; onClicked: { if(root.action(root.confirmation)) root.confirmation = "" } }
            }
        }
        ScrollView {
            visible: root.setupOpen
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: 8
                Label { text: root.snapshot.hasAccount ? "账号 · " + (root.snapshot.userId || root.snapshot.accountId || "已登录") : root.snapshot.state === "verify" ? "在微信中查看配对码并输入" : "用微信扫描二维码，按提示确认登录"; Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: 12; color: "#596268" }
                Image { source: root.snapshot.qrImage || ""; visible: root.snapshot.state !== "verify" && source.toString() !== ""; Layout.alignment: Qt.AlignHCenter; Layout.preferredWidth: 144; Layout.preferredHeight: 144; sourceSize.width: 432; sourceSize.height: 432; fillMode: Image.PreserveAspectFit }
                Label { visible: !!root.snapshot.qrError; text: root.snapshot.qrError || ""; wrapMode: Text.Wrap; Layout.fillWidth: true; color: "#885d36"; font.pixelSize: 12 }
                RowLayout {
                    visible: root.snapshot.state === "verify"
                    Layout.fillWidth: true
                    TextField { id: code; objectName: "weixinPairCode"; placeholderText: "输入 4–12 位配对码"; Layout.fillWidth: true; maximumLength: 12; selectByMouse: true; validator: RegularExpressionValidator { regularExpression: /[0-9]{4,12}/ } onAccepted: if(acceptableInput) root.action("verify", {code:text})
                        background: Rectangle { radius: 7; color: "white"; border.color: code.activeFocus ? "#6fa78b" : "#dce3df" }
                    }
                    WeixinButton { objectName: "weixinVerify"; primary: true; text: "确认"; enabled: code.acceptableInput; onClicked: root.action("verify", {code:code.text}) }
                }
                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    WeixinButton { objectName: "weixinRetryLogin"; text: "重试扫码"; visible: !root.snapshot.hasAccount; onClicked: root.action("login") }
                    WeixinButton { objectName: "weixinCloseLogin"; text: root.snapshot.hasAccount ? "关闭" : "取消"; onClicked: { if (!root.snapshot.hasAccount) root.action("disconnect"); root.setupOpen = false } }
                }
            }
        }
        Label { visible: root.statusNotice !== ""; text: root.statusNotice; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideRight; wrapMode: Text.Wrap; font.pixelSize: 11; color: "#88613e" }
        ListView {
            id: messages
            visible: !root.setupOpen && !root.agentOpen
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 9
            model: root.snapshot.messages || []
            onCountChanged: Qt.callLater(positionViewAtEnd)
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Label { anchors.centerIn: parent; visible: messages.count === 0; text: root.online && !root.canSend ? "先从微信发一条文字" : root.snapshot.hasAccount ? "消息会显示在这里" : "扫码登录，开始聊天"; color: "#92999c"; font.pixelSize: 12 }
            delegate: Column {
                required property var modelData
                width: messages.width
                spacing: 3
                Rectangle {
                    anchors.right: modelData.direction === "out" ? parent.right : undefined
                    width: Math.min(parent.width * 0.84, bubble.implicitWidth + 22)
                    height: bubble.height + 16; radius: 9
                    color: modelData.direction === "out" ? "#d7efde" : "#ffffff"
                    Text { id: bubble; x:11; y:8; width: Math.min(implicitWidth, messages.width * 0.84 - 22); text: modelData.text || ""; textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: 13; color: "#27312e" }
                }
                Text { anchors.right: modelData.direction === "out" ? parent.right : undefined; text: (modelData.time || "") + (modelData.direction === "out" ? " · " + (modelData.status || "") : ""); font.pixelSize: 10; color: "#92999c"; width: parent.width * 0.9; horizontalAlignment: modelData.direction === "out" ? Text.AlignRight : Text.AlignLeft; wrapMode: Text.Wrap }
            }
        }
        RowLayout {
            visible: !root.setupOpen && !root.agentOpen
            Layout.fillWidth: true; spacing: 7
            ScrollView { Layout.fillWidth: true; Layout.preferredHeight: 48; clip: true
                TextArea { id: draft; objectName: "weixinMessageInput"; placeholderText: root.canSend ? "输入消息" : root.online ? "先从微信发一条文字" : "连接后可发送"; wrapMode: TextEdit.Wrap; selectByMouse: true; font.pixelSize: 12; color: "#28312e"; background: Rectangle { color: "white"; radius: 7; border.color: "#e0e5e3" } }
            }
            WeixinButton { objectName: "weixinSend"; primary: true; text: "发送"; enabled: root.canSend && !root.snapshot.sending && draft.text.trim().length > 0 && draft.text.length <= 2000; implicitHeight: 40
                onClicked: if (root.action("send", {text:draft.text})) draft.clear()
            }
        }
        Label { visible: !root.setupOpen && !root.agentOpen && draft.text.length > 2000; text: "最多 2000 字"; font.pixelSize: 10; color: "#a35e38" }
    }
}
