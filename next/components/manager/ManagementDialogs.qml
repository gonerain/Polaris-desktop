import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Polaris.Ui 1.0 as Ui

Item {
    id: root
    required property var manager
    required property QtObject theme
    signal holdChanged(string reason, bool active)
    function restorePresentation() {
        if (!manager) return
        if (manager.authorizationPending && manager.planType !== 'application') {
            permissionDialog.open()
            root.holdChanged('management-permission', true)
        }
        if (manager.installationPrompt.length) {
            installationDialog.open()
            root.holdChanged('management-installation', true)
        }
    }
    Connections {
        target: root.manager
        function onPlanReady() { if (root.manager.planType !== 'application') permissionDialog.open() }
        function onPlanCancelled() { permissionDialog.close() }
        function onInstallationReady() { installationDialog.open() }
        function onInstallationCancelled() { installationDialog.close() }
    }
    Popup {
        id: permissionDialog; objectName: 'viewPermissionDialog'
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(580, parent.width - 32)
        height: Math.min(permissionContent.implicitHeight + 40, parent.height - 32)
        padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        onOpened: root.holdChanged('management-permission', true)
        onClosed: { root.holdChanged('management-permission', false); if (root.manager) root.manager.cancelView() }
        contentItem: ColumnLayout {
            id: permissionContent; spacing: 12
            Text { text: '确认能力权限'; color: root.theme.ink; font.pixelSize: 18; font.weight: Font.DemiBold; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Text { textFormat: Text.PlainText; text: root.manager ? root.manager.planSubject : ''; color: root.theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
            ScrollView {
                id: permissionScroll; Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 0
                Layout.preferredHeight: Math.min(permissionGroups.implicitHeight, 300)
                clip: true; contentWidth: availableWidth
                ScrollBar.vertical: Ui.ScrollBar { theme: root.theme }
                Column {
                    id: permissionGroups; width: permissionScroll.availableWidth; spacing: 12
                    Repeater {
                        model: {
                            var groups = []
                            var permissions = JSON.parse(root.manager ? root.manager.planJson : '[]')
                            for (var row of permissions) {
                                var group = groups.find(function(g) { return g.target === row.target })
                                if (!group) { group = {target: row.target, title: row.title, instanceId: row.instanceId, permissions: []}; groups.push(group) }
                                group.permissions.push(row)
                            }
                            return groups
                        }
                        Column {
                            required property var modelData
                            width: permissionGroups.width; spacing: 5
                            Text { width: parent.width; textFormat: Text.PlainText; text: modelData.title; color: root.theme.ink; wrapMode: Text.Wrap; font.weight: Font.DemiBold }
                            Text { width: parent.width; textFormat: Text.PlainText; text: modelData.instanceId ? '实例 ' + modelData.instanceId : ''; visible: text.length > 0; color: root.theme.quiet; wrapMode: Text.WrapAnywhere; font.pixelSize: 11 }
                            Repeater {
                                model: modelData.permissions
                                Text { required property var modelData; width: permissionGroups.width; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: root.theme.muted; font.pixelSize: 12
                                    text: modelData.name + ' · ' + (modelData.access === 'write' ? '操作' : '查看') + (modelData.authorized ? ' · 已授权' : ' · 将授予') }
                            }
                        }
                    }
                }
            }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; objectName: 'cancelPermission'; text: '取消'; onClicked: permissionDialog.close() }
                Ui.Button { theme: root.theme; objectName: 'confirmPermission'; text: '确认并执行'; primary: true; enabled: root.manager && !root.manager.busy; onClicked: { root.manager.confirmView(); permissionDialog.close() } }
            }
        }
    }
    Popup {
        id: installationDialog; objectName: 'installationDialog'
        parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(440, parent.width - 32); padding: 20; modal: true; focus: true
        background: Rectangle { radius: 12; color: root.theme.card; border.color: root.theme.border }
        onOpened: root.holdChanged('management-installation', true)
        onClosed: { root.holdChanged('management-installation', false); if (root.manager) root.manager.cancelInstallation() }
        contentItem: ColumnLayout {
            spacing: 14
            Text { text: '确认操作'; color: root.theme.ink; font.pixelSize: 18 }
            Text { text: root.manager ? root.manager.installationPrompt : ''; textFormat: Text.PlainText; wrapMode: Text.Wrap; Layout.fillWidth: true; color: root.theme.muted }
            Flow {
                Layout.fillWidth: true; spacing: 8
                Ui.Button { theme: root.theme; objectName: 'cancelInstallation'; text: '取消'; onClicked: installationDialog.close() }
                Ui.Button { theme: root.theme; objectName: 'confirmInstallation'; text: '确认'; primary: true; enabled: root.manager && !root.manager.busy; onClicked: root.manager.confirmInstallation() }
            }
        }
    }
}
