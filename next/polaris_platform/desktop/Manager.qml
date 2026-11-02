import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
Pane {
    id: root
    padding: 0
    background: Rectangle { color: '#f3f5fa' }
    palette.window: '#ffffff'; palette.base: '#ffffff'; palette.text: '#243450'; palette.windowText: '#243450'
    palette.button: '#edf1f7'; palette.buttonText: '#40516a'; palette.highlight: '#dce7fb'; palette.highlightedText: '#243450'
    property bool showSystemComponents: false
    property var visibleRecords: records.filter(function(row) { return showSystemComponents || ['authorization','collaboration','runtime','window','canvas','pet','manager','sources'].indexOf(row.id) < 0 })
    property var records: JSON.parse(manager ? manager.dataJson : '[]')
    property var decisions: JSON.parse(manager ? manager.permissionsJson : '[]')
    property bool customPermissions: false
    property string expandedCapability: ''
    onSelectedIdChanged: { customPermissions = false; expandedCapability = '' }
    property string selectedId: ''
    property string subjectId: 'canvas'
    property var current: records.find(item => item.id === selectedId) || visibleRecords[0] || ({})
    component SettingsButton: Button {
        id: button
        implicitHeight: 34; leftPadding: 14; rightPadding: 14
        contentItem: Text { text: button.text; font.pixelSize: 12; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; color: !button.enabled ? '#97a3b6' : button.checked ? '#254f91' : '#40516a' }
        background: Rectangle { radius: 8; color: button.checked ? '#dfeafb' : button.down ? '#dce4f0' : button.hovered ? '#e6edf7' : button.flat ? 'transparent' : '#edf1f7'; opacity: button.enabled ? 1 : 0.6 }
    }
    function permissionMode() {
        var capabilities = rows(current)
        if (!capabilities.length || capabilities.every(function(row) { return !hasGrant(current, row, false) })) return 'none'
        if (capabilities.every(function(row) { return hasGrant(current, row, false) })) return 'all'
        if (capabilities.every(function(row) { return hasGrant(current, row, false) === (row.metadata.access !== 'write') })) return 'read'
        return 'custom'
    }
    function description(item) { return item.description || ({}) }
    function stateText(state) { return ({installed:'已安装', starting:'启动中', running:'运行中', stopping:'停止中', stopped:'已停止', failed:'异常'})[state] || state || '' }
    function rows(item) {
        let result = []
        for (let kind of ['operation', 'event']) {
            let source = description(item)[kind === 'operation' ? 'operations' : 'events'] || ({})
            for (let name of Object.keys(source)) result.push({name:name, kind:kind, metadata:source[name]})
        }
        return result
    }
    function viewActions(item) {
        let result = []
        for (let view of description(item).views || [])
            for (let action of view.actions || []) result.push(action)
        return result
    }
    function hasGrant(item, capability, background) {
        let m = capability.metadata
        let key = [item.installation, capability.kind, capability.name, m.major || 1, m.access || 'read', m.revision || 1]
        return decisions.some(record => record.requesterInstallation === (records.find(item => item.id === subjectId)?.installation || '') && record.background === background && record.scope.some(scope => JSON.stringify(scope) === JSON.stringify(key)))
    }
    Dialog {
        id: aboutDialog; objectName: 'aboutDialog'; title: '关于'; modal: true
        anchors.centerIn: parent; width: Math.min(520, root.width - 48)
        standardButtons: Dialog.Close
        onOpened: standardButton(Dialog.Close).text = '关闭'
        property var info: JSON.parse(manager ? manager.aboutJson : '{}')
        contentItem: ColumnLayout {
            spacing: 12
            Label { text: aboutDialog.info.APP_NAME || ''; font.pixelSize: 20 }
            Label { text: aboutDialog.info.DISPLAY_VERSION || '' }
            Label { text: '作者：' + (aboutDialog.info.AUTHOR || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: aboutDialog.info.PROJECT_URL || ''; color: '#345f9c'; wrapMode: Text.Wrap; Layout.fillWidth: true
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally(aboutDialog.info.PROJECT_URL) }
            }
            Label { text: '代码许可：' + (aboutDialog.info.CODE_LICENSE || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: '素材许可：' + (aboutDialog.info.ARTWORK_LICENSE || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: '素材作者：' + (aboutDialog.info.ARTWORK_CREDIT || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: aboutDialog.info.ARTWORK_URL || ''; color: '#345f9c'; wrapMode: Text.Wrap; Layout.fillWidth: true
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally(aboutDialog.info.ARTWORK_URL) }
            }
        }
    }
    Dialog {
        id: sourceDialog; objectName: 'sourceDialog'; title: '插件源'; modal: true
        anchors.centerIn: parent; width: Math.min(760, root.width - 48); height: Math.min(570, root.height - 48)
        contentItem: ColumnLayout {
            RowLayout {
                TextField { id: sourceLocation; objectName: 'sourceLocation'; placeholderText: 'Git 仓库地址或本地仓库目录'; Layout.fillWidth: true; enabled: manager && !manager.busy }
                SettingsButton { objectName: 'addSource'; text: '添加'; enabled: manager && !manager.busy && sourceLocation.text.trim().length > 0; onClicked: manager.addSource(sourceLocation.text) }
            }
            Label { text: manager && manager.busy ? '处理中…' : '选择插件安装；已有同 ID 插件需确认更新。'; color: '#61718b' }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                ColumnLayout {
                    width: sourceDialog.availableWidth
                    Repeater {
                        model: JSON.parse(manager ? manager.sourcesJson : '[]')
                        ColumnLayout {
                            id: sourceRow; required property var modelData; Layout.fillWidth: true
                            RowLayout {
                                Label { text: sourceRow.modelData.name || sourceRow.modelData.location; Layout.fillWidth: true; elide: Text.ElideRight }
                                SettingsButton { text: '检查更新'; enabled: manager && !manager.busy; onClicked: manager.refreshSource(sourceRow.modelData.id) }
                            }
                            Repeater {
                                model: sourceRow.modelData.components || []
                                RowLayout {
                                    required property var modelData; Layout.fillWidth: true
                                    Label { text: modelData.manifest.name + ' · ' + modelData.manifest.version; Layout.fillWidth: true }
                                    SettingsButton { objectName: 'installSource_' + modelData.manifest.id; text: root.records.some(row => row.id === modelData.manifest.id) ? '更新 / 替换' : '安装'; enabled: manager && !manager.busy
                                        onClicked: manager.installSource(sourceRow.modelData.id, modelData.manifest.id) }
                                }
                            }
                        }
                    }
                }
            }
            Label { text: manager ? manager.notice : ''; wrapMode: Text.Wrap; Layout.fillWidth: true }
            SettingsButton { text: '关闭'; Layout.alignment: Qt.AlignRight; onClicked: sourceDialog.close() }
        }
    }
    FolderDialog { id: folder; title: '选择组件目录'; onAccepted: manager.loadDirectory(selectedFolder.toString()) }
    Connections { target: manager; function onPlanReady() { viewPlan.open() } function onPlanCancelled() { viewPlan.close() } }
    Dialog {
        id: viewPlan; objectName: 'viewPermissionDialog'; title: '确认展示权限'; modal: true; anchors.centerIn: parent; width: Math.min(580, root.width - 48)
        onClosed: { if (manager) manager.cancelView() }
        property var permissions: JSON.parse(manager ? manager.planJson : '[]')
        contentItem: ColumnLayout {
            spacing: 12
            Label { text: '授权使用者：' + (manager ? manager.planSubject : ''); font.pixelSize: 15 }
            Label { text: '将使用以下组件'; color: '#61718b' }
            ScrollView {
                Layout.fillWidth: true; Layout.preferredHeight: Math.min(permissionGroups.implicitHeight, 320); clip: true
                Column {
                    id: permissionGroups; width: parent.width; spacing: 8
                    Repeater {
                        model: {
                            var groups = []
                            for (var row of viewPlan.permissions) {
                                var group = groups.find(function(g) { return g.target === row.target })
                                if (!group) { group = {target: row.target, title: row.title, permissions: []}; groups.push(group) }
                                group.permissions.push(row)
                            }
                            return groups
                        }
                        Column {
                            id: permissionGroup; required property var modelData
                            width: permissionGroups.width; property bool expanded: false; spacing: 4
                            RowLayout {
                                width: parent.width
                                Label { text: permissionGroup.modelData.title; font.bold: true; color: '#243450'; Layout.fillWidth: true }
                                Label { text: permissionGroup.modelData.permissions.some(function(p) { return p.access === 'write' }) ? '查看与操作' : '查看'; color: '#61718b' }
                                SettingsButton { text: permissionGroup.expanded ? '收起 ▴' : '详情 ▾'; flat: true; onClicked: permissionGroup.expanded = !permissionGroup.expanded }
                            }
                            Repeater {
                                model: permissionGroup.expanded ? permissionGroup.modelData.permissions : []
                                Label { required property var modelData; width: permissionGroup.width; wrapMode: Text.Wrap; color: '#61718b'; font.pixelSize: 12
                                    text: '  ' + modelData.name + (modelData.authorized ? ' · 已授权' : ' · 将授予') }
                            }
                        }
                    }
                }
            }
            RowLayout { Layout.alignment: Qt.AlignRight
                SettingsButton { objectName: 'cancelPermission'; text: '取消'; onClicked: viewPlan.close() }
                SettingsButton { objectName: 'confirmPermission'; text: '确认并执行'; enabled: manager && !manager.busy; onClicked: { manager.confirmView(); viewPlan.close() } }
            }
        }
    }
    Connections { target: manager
        function onInstallationReady() { installationDialog.open() }
        function onInstallationCancelled() { installationDialog.close() }
    }
    Dialog {
        id: installationDialog; objectName: 'installationDialog'; title: '确认操作'
        modal: true; anchors.centerIn: parent; width: Math.min(440, root.width - 48)
        onRejected: manager.cancelInstallation()
        contentItem: ColumnLayout {
            Label { text: manager ? manager.installationPrompt : ''; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout { Layout.alignment: Qt.AlignRight
                SettingsButton { objectName: 'cancelInstallation'; text: '取消'; onClicked: manager.cancelInstallation() }
                SettingsButton { objectName: 'confirmInstallation'; text: '确认'; onClicked: manager.confirmInstallation() }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 16
        RowLayout {
            Layout.fillWidth: true
            Column { spacing: 5
                Text { text: 'Polaris'; font.pixelSize: 28; font.bold: true; color: '#20304d' }
                Text { text: '组件管理'; color: '#6b7891'; font.pixelSize: 14 }
            }
            Item { Layout.fillWidth: true }
            BusyIndicator { running: manager && manager.busy; implicitWidth: 32; implicitHeight: 32 }
            SettingsButton { text: '关于'; objectName: 'aboutButton'; onClicked: aboutDialog.open() }
            SettingsButton { text: '刷新'; onClicked: manager.refresh() }
            SettingsButton { objectName: 'sourceButton'; text: '插件源'; enabled: manager && !manager.busy; onClicked: sourceDialog.open() }
            SettingsButton { text: '加载组件'; onClicked: folder.open() }
            SettingsButton { text: '退出'; onClicked: manager.quit() }
        }
        RowLayout {
            Label { text: '权限使用者'; color: '#61718b' }
            ComboBox {
                Layout.preferredWidth: 260; model: root.records; textRole: 'name'
                currentIndex: root.records.findIndex(item => item.id === root.subjectId)
                onActivated: root.subjectId = root.records[currentIndex].id
            }

        }
        SplitView {
            Layout.fillWidth: true; Layout.fillHeight: true
            Rectangle {
                SplitView.preferredWidth: 270; color: 'white'; radius: 14
                ListView {
                    anchors.fill: parent; anchors.margins: 12; anchors.bottomMargin: 58; spacing: 8; clip: true
                    model: root.visibleRecords
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width; height: 76; radius: 10
                        color: root.current.id === modelData.id ? '#eaf0ff' : '#fafbfe'
                        Column { anchors.fill: parent; anchors.margins: 12; spacing: 6
                            Text { text: modelData.name; font.bold: true; color: '#243450'; elide: Text.ElideRight; width: parent.width }
                            Text { text: root.stateText(modelData.state); color: '#6d7c94'; font.pixelSize: 12 }
                        }
                        MouseArea { anchors.fill: parent; onClicked: root.selectedId = modelData.id }
                    }
                }
                SettingsButton { anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottomMargin: 12; text: root.showSystemComponents ? '收起系统组件 ▴' : '系统组件 ▾'; flat: true; onClicked: { root.showSystemComponents = !root.showSystemComponents; root.selectedId = '' } }
            }
            ScrollView {
                id: detailPane; SplitView.fillWidth: true; clip: true
                ColumnLayout {
                    width: detailPane.availableWidth; spacing: 16
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: header.implicitHeight + 40; color: 'white'; radius: 14
                        ColumnLayout { id: header; anchors.fill: parent; anchors.margins: 20; spacing: 10
                            Text { text: root.current.name || '选择组件'; font.pixelSize: 22; font.bold: true; color: '#243450' }
                            Text { visible: root.customPermissions; text: root.current.id || ''; color: '#738098'; font.pixelSize: 12 }
                            Text { visible: !!root.description(root.current).view_state; text: root.description(root.current).view_state?.visible ? '视图已显示' : '视图已隐藏'; color: '#738098'; font.pixelSize: 12 }
                            RowLayout {
                                SettingsButton { text: '启动'; enabled: !!root.current.id && manager && !manager.busy; onClicked: manager.lifecycle(root.current.id, 'start') }
                                SettingsButton { objectName: 'uninstallComponent'; text: '卸载'; enabled: !!root.current.id && root.current.manageable && manager && !manager.busy; onClicked: manager.prepareUninstall(root.current.id) }
                                SettingsButton { text: '停止'; enabled: !!root.current.id && manager && !manager.busy; onClicked: manager.lifecycle(root.current.id, 'stop') }
                                Repeater { model: root.viewActions(root.current)
                                    SettingsButton { required property var modelData; text: modelData.label; enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.prepareView(root.subjectId, root.current.id, modelData.operation) }
                                }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: permissionSummary.implicitHeight + 32; color: 'white'; radius: 12
                        ColumnLayout {
                            id: permissionSummary; anchors.fill: parent; anchors.margins: 16; spacing: 8
                            Label { text: '组件权限'; font.pixelSize: 17; font.bold: true; color: '#243450' }
                            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; color: '#738098'; text: '设置当前使用者的本机访问范围，后台权限在自定义中调整。' }
                            RowLayout {
                                Layout.fillWidth: true
                                Repeater { model: [{id:'none',title:'禁止'}, {id:'read',title:'只读'}, {id:'all',title:'允许全部'}]
                                    SettingsButton { required property var modelData; objectName: 'componentPermission_' + modelData.id
                                        text: modelData.title; checked: root.permissionMode() === modelData.id; enabled: !!root.subjectId && root.rows(root.current).length > 0 && manager && !manager.busy
                                        onClicked: manager.componentPermission(root.subjectId, root.current.id, modelData.id) }
                                }
                                Item { Layout.fillWidth: true }
                                SettingsButton { objectName: 'customPermissions'; text: root.customPermissions ? '收起 ▴' : '自定义 ▾'; flat: true; onClicked: root.customPermissions = !root.customPermissions }
                            }
                            Label { color: '#738098'; font.pixelSize: 12; text: {
                                var rows = root.rows(root.current)
                                var count = rows.filter(function(row) { return root.hasGrant(root.current, row, false) }).length
                                return count === 0 ? '未授权' : count === rows.length ? '已允许全部当前能力' : '已自定义 · ' + count + ' / ' + rows.length + ' 项'
                            } }
                        }
                    }
                    Repeater {
                        model: root.customPermissions ? root.rows(root.current) : []
                        Rectangle {
                            id: capabilityCard
                            required property var modelData
                            property string key: modelData.kind + ':' + modelData.name
                            property bool expanded: root.expandedCapability === key
                            Layout.fillWidth: true; implicitHeight: capabilityContent.implicitHeight + 24; radius: 10; color: 'white'
                            ColumnLayout {
                                id: capabilityContent; anchors.fill: parent; anchors.margins: 12; spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: capabilityCard.modelData.name; color: '#243450'; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Label { text: capabilityCard.modelData.kind === 'event' ? '订阅' : capabilityCard.modelData.metadata.access === 'write' ? '操作' : '查看'; color: '#738098'; font.pixelSize: 12 }
                                    Switch { objectName: 'capability_' + capabilityCard.modelData.name
                                        checked: root.hasGrant(root.current, capabilityCard.modelData, false); enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.permission(root.subjectId, root.current.id, capabilityCard.modelData.name, capabilityCard.modelData.kind, false, checked) }
                                    SettingsButton { text: capabilityCard.expanded ? '收起' : '高级'; flat: true; onClicked: root.expandedCapability = capabilityCard.expanded ? '' : capabilityCard.key }
                                }
                                RowLayout {
                                    visible: capabilityCard.expanded; Layout.fillWidth: true
                                    Label { text: '允许后台任务'; color: '#68768d'; Layout.fillWidth: true }
                                    Switch { checked: root.hasGrant(root.current, capabilityCard.modelData, true); enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.permission(root.subjectId, root.current.id, capabilityCard.modelData.name, capabilityCard.modelData.kind, true, checked) }
                                }
                                RowLayout {
                                    visible: capabilityCard.expanded && capabilityCard.modelData.kind === 'operation'
                                    TextField { id: args; text: '{}'; placeholderText: '调试参数 JSON'; Layout.fillWidth: true; selectByMouse: true; color: '#243450' }
                                    SettingsButton { text: '调试调用'; enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.invoke(root.subjectId, root.current.id, capabilityCard.modelData.name, args.text) }
                                }
                            }
                        }
                    }
                    Item { implicitHeight: 12 }
                }
            }
        }
        Rectangle {
            visible: !!manager && manager.notice.length > 0; Layout.fillWidth: true; implicitHeight: 64; radius: 10; color: '#e8edf7'
            ScrollView { anchors.fill: parent; anchors.margins: 12; clip: true
                TextArea { text: (manager ? manager.notice : '') || '就绪'; readOnly: true; wrapMode: Text.Wrap; color: '#43536f'; background: null; selectByMouse: true }
            }
        }
    }
}
