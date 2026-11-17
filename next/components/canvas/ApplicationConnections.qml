import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Polaris.Ui 1.0 as Ui

Popup {
    id: dialog
    objectName: 'applicationConnectionsDialog'
    required property var applicationHost
    required property var manager
    required property QtObject theme
    signal holdChanged(string reason, bool active)
    property string stage: 'connections'
    property string requester: ''
    property string subject: ''
    property string resultMessage: ''
    property var permissions: []
    readonly property var application: applicationHost ? JSON.parse(applicationHost.selectedJson) : ({})
    readonly property var connections: applicationHost ? JSON.parse(applicationHost.connectionsJson) : []
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(680, parent.width - 32)
    height: Math.min(stage === 'connections' ? Math.max(280, Math.min(640, connections.length * 90 + 180)) : stage === 'approval' || stage === 'granting' ? Math.max(300, Math.min(580, permissions.length * 28 + 200)) : 300, parent.height - 32)
    padding: 20; modal: true; focus: true
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { radius: 12; color: dialog.theme.card; border.color: dialog.theme.border }

    function openConnections() {
        stage = 'connections'
        resultMessage = ''
        applicationHost.refreshConnections()
        open()
    }
    function showAuthorization() {
        stage = 'approval'
        requester = manager.planRequester
        subject = manager.planSubject
        permissions = JSON.parse(manager.planJson)
        resultMessage = ''
        open()
    }
    function restorePresentation() {
        if (manager && manager.authorizationPending && manager.planType === 'application') showAuthorization()
    }
    onOpened: holdChanged('application-connections', true)
    onClosed: {
        holdChanged('application-connections', false)
        if (stage === 'approval' && manager && manager.authorizationPending && manager.planRequester === requester) manager.cancelView()
        if (applicationHost && (stage === 'connections' || stage === 'approval' || stage === 'failed')) applicationHost.dismissMessage()
    }
    Connections {
        target: dialog.manager
        function onPlanReady() { if (dialog.manager.planType === 'application') dialog.showAuthorization() }
        function onPlanCancelled() { if (dialog.stage === 'approval') dialog.close() }
        function onApplicationPermissionFinished(applicationId, status, message) {
            if (applicationId !== dialog.requester || dialog.stage !== 'granting') return
            dialog.stage = status === 'confirmed' ? 'confirmed' : 'failed'
            dialog.resultMessage = message
            if (status === 'failed') dialog.applicationHost.dismissMessage()
        }
    }
    ColumnLayout {
        anchors.fill: parent; spacing: 14
        RowLayout {
            Layout.fillWidth: true; Layout.preferredHeight: 34; Layout.maximumHeight: 34
            Text { Layout.fillWidth: true; text: dialog.stage === 'connections' ? '组件连接 / 权限' : '应用授权'; color: dialog.theme.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
            Ui.Button { theme: dialog.theme; glyph: 'close'; hint: '关闭'; objectName: 'closeApplicationConnections'; onClicked: dialog.close() }
        }
        Text { Layout.fillWidth: true; text: dialog.stage === 'connections' ? (dialog.application.title || '') : dialog.subject; textFormat: Text.PlainText; color: dialog.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
        ScrollView {
            id: connectionScroll
            objectName: 'applicationConnections'
            visible: dialog.stage === 'connections'
            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
            ScrollBar.vertical: Ui.ScrollBar { theme: dialog.theme }
            ColumnLayout {
                width: connectionScroll.availableWidth; spacing: 14
                Text { Layout.fillWidth: true; visible: !!text; text: dialog.applicationHost.messageError || dialog.applicationHost.feedback; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: dialog.applicationHost.messageError ? dialog.theme.error : dialog.theme.muted; font.pixelSize: 12 }
                Repeater {
                    model: dialog.connections
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true; spacing: 6
                        Text {
                            Layout.fillWidth: true; text: modelData.label; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: dialog.theme.ink; font.pixelSize: 13
                            ToolTip.visible: labelHover.hovered && !!modelData.contract
                            ToolTip.text: modelData.contract
                            HoverHandler { id: labelHover }
                        }
                        Ui.ComboBox {
                            theme: dialog.theme; objectName: 'applicationBinding_' + modelData.alias
                            Layout.fillWidth: true; textRole: 'label'
                            model: [{label: modelData.issue || '选择组件实例', instanceId: ''}].concat(modelData.candidates)
                            currentIndex: modelData.selected + 1
                            onActivated: function(index) { if (index > 0) dialog.applicationHost.bindInstance(modelData.alias, modelData.candidates[index - 1].instanceId, modelData.candidates[index - 1].operation) }
                        }
                        Text { Layout.fillWidth: true; visible: !modelData.candidates.length; text: '请先安装并启动提供此能力的组件'; wrapMode: Text.Wrap; color: dialog.theme.muted; font.pixelSize: 12 }
                    }
                }
            }
        }
        ScrollView {
            id: approvalScroll
            visible: dialog.stage === 'approval' || dialog.stage === 'granting'
            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
            ScrollBar.vertical: Ui.ScrollBar { theme: dialog.theme }
            Column {
                id: approvalGroups; width: approvalScroll.availableWidth; spacing: 14
                Repeater {
                    model: {
                        var groups = []
                        for (var row of dialog.permissions) {
                            var group = groups.find(function(g) { return g.target === row.target })
                            if (!group) { group = {target: row.target, title: row.title, instanceId: row.instanceId, permissions: []}; groups.push(group) }
                            group.permissions.push(row)
                        }
                        return groups
                    }
                    Column {
                        required property var modelData
                        width: approvalGroups.width; spacing: 5
                        Text { width: parent.width; text: modelData.title; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: dialog.theme.ink; font.weight: Font.DemiBold }
                        Text { width: parent.width; visible: !!modelData.instanceId; text: '实例 ' + modelData.instanceId; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere; color: dialog.theme.quiet; font.pixelSize: 11 }
                        Repeater {
                            model: modelData.permissions
                            Text { required property var modelData; width: approvalGroups.width; text: modelData.name + ' · ' + (modelData.access === 'write' ? '操作' : '查看') + (modelData.authorized ? ' · 已授权' : ' · 将授予'); textFormat: Text.PlainText; wrapMode: Text.Wrap; color: dialog.theme.muted; font.pixelSize: 12 }
                        }
                    }
                }
            }
        }
        ColumnLayout {
            visible: dialog.stage === 'confirmed' || dialog.stage === 'failed'
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
            Text { Layout.alignment: Qt.AlignHCenter; text: dialog.stage === 'confirmed' ? '✓' : '!'; color: dialog.stage === 'confirmed' ? dialog.theme.accent : dialog.theme.error; font.pixelSize: 38 }
            Text { Layout.fillWidth: true; objectName: 'applicationPermissionResult'; text: dialog.resultMessage; textFormat: Text.PlainText; wrapMode: Text.Wrap; horizontalAlignment: Text.AlignHCenter; color: dialog.stage === 'failed' ? dialog.theme.error : dialog.theme.ink; font.pixelSize: 14 }
        }
        Text { objectName: 'applicationBusyMessage'; Layout.fillWidth: true; text: dialog.stage === 'granting' ? '正在确认权限…' : dialog.stage === 'connections' && dialog.applicationHost.busy ? '应用正在处理请求…' : ''; visible: text.length > 0; color: dialog.theme.muted; font.pixelSize: 12; wrapMode: Text.Wrap }
        Flow {
            Layout.fillWidth: true; Layout.preferredHeight: implicitHeight; Layout.maximumHeight: implicitHeight; spacing: 8
            Ui.Button { visible: dialog.stage === 'connections'; theme: dialog.theme; text: '刷新连接'; glyph: 'right'; onClicked: dialog.applicationHost.refreshConnections() }
            Ui.Button { visible: dialog.stage === 'connections'; theme: dialog.theme; text: '撤销应用授权'; glyph: 'close'; objectName: 'revokePackagedApplication'; onClicked: dialog.applicationHost.revoke() }
            Ui.Button { visible: dialog.stage === 'approval'; theme: dialog.theme; text: '取消'; objectName: 'cancelApplicationPermission'; onClicked: dialog.close() }
            Ui.Button { visible: dialog.stage === 'approval'; theme: dialog.theme; text: '确认并执行'; primary: true; objectName: 'confirmApplicationPermission'; enabled: dialog.manager && !dialog.manager.busy; onClicked: { dialog.stage = 'granting'; dialog.manager.confirmView() } }
            Ui.Button { visible: dialog.stage === 'confirmed' || dialog.stage === 'failed'; theme: dialog.theme; text: '完成'; primary: true; objectName: 'finishApplicationPermission'; onClicked: dialog.close() }
        }
    }
}
