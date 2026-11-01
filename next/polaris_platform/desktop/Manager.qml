import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
Rectangle {
    id: root
    color: '#f3f5fa'
    property var records: JSON.parse(manager ? manager.dataJson : '[]')
    property var decisions: JSON.parse(manager ? manager.permissionsJson : '[]')
    property string selectedId: ''
    property string subjectId: 'manager'
    property var current: records.find(item => item.id === selectedId) || records[0] || ({})
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
    FolderDialog { id: folder; title: '选择组件目录'; onAccepted: manager.loadDirectory(selectedFolder.toString()) }
    Connections { target: manager; function onPlanReady() { viewPlan.open() } function onPlanCancelled() { viewPlan.close() } }
    Dialog {
        id: viewPlan; objectName: 'viewPermissionDialog'; title: '确认展示权限'; modal: true; anchors.centerIn: parent; width: Math.min(580, root.width - 48)
        onClosed: { if (manager) manager.cancelView() }
        property var permissions: JSON.parse(manager ? manager.planJson : '[]')
        contentItem: ColumnLayout {
            spacing: 12
            Label { text: '授权使用者：' + (manager ? manager.planSubject : ''); font.pixelSize: 15 }
            Label { text: '本机交互将使用以下操作'; color: '#61718b' }
            Repeater { model: viewPlan.permissions
                Label { required property var modelData; Layout.fillWidth: true; wrapMode: Text.Wrap
                    text: modelData.title + ' · ' + modelData.name + '（' + (modelData.kind === 'event' ? '订阅' : (modelData.access === 'write' ? '写入' : '读取')) + '）' + (modelData.authorized ? '  已授权' : '  将授予')
                    color: '#43536f'
                }
            }
            RowLayout { Layout.alignment: Qt.AlignRight
                Button { objectName: 'cancelPermission'; text: '取消'; onClicked: viewPlan.close() }
                Button { objectName: 'confirmPermission'; text: '确认并执行'; enabled: manager && !manager.busy; onClicked: { manager.confirmView(); viewPlan.close() } }
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
                Button { objectName: 'cancelInstallation'; text: '取消'; onClicked: manager.cancelInstallation() }
                Button { objectName: 'confirmInstallation'; text: '确认'; onClicked: manager.confirmInstallation() }
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
            Button { text: '刷新'; onClicked: manager.refresh() }
            Button { text: '加载组件'; onClicked: folder.open() }
            Button { text: '退出'; onClicked: manager.quit() }
        }
        RowLayout {
            Label { text: '权限使用者'; color: '#61718b' }
            ComboBox {
                Layout.preferredWidth: 260; model: root.records; textRole: 'name'
                currentIndex: root.records.findIndex(item => item.id === root.subjectId)
                onActivated: root.subjectId = root.records[currentIndex].id
            }
            Label { text: root.subjectId; color: '#8491a5'; font.pixelSize: 12 }
        }
        SplitView {
            Layout.fillWidth: true; Layout.fillHeight: true
            Rectangle {
                SplitView.preferredWidth: 270; color: 'white'; radius: 14
                ListView {
                    anchors.fill: parent; anchors.margins: 12; spacing: 8; clip: true
                    model: root.records
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
            }
            ScrollView {
                id: detailPane; SplitView.fillWidth: true; clip: true
                ColumnLayout {
                    width: detailPane.availableWidth; spacing: 16
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: header.implicitHeight + 40; color: 'white'; radius: 14
                        ColumnLayout { id: header; anchors.fill: parent; anchors.margins: 20; spacing: 10
                            Text { text: root.current.name || '选择组件'; font.pixelSize: 22; font.bold: true; color: '#243450' }
                            Text { text: root.current.id || ''; color: '#738098'; font.pixelSize: 12 }
                            Text { visible: !!root.description(root.current).view_state; text: root.description(root.current).view_state?.visible ? '视图已显示' : '视图已隐藏'; color: '#738098'; font.pixelSize: 12 }
                            RowLayout {
                                Button { text: '启动'; enabled: !!root.current.id && manager && !manager.busy; onClicked: manager.lifecycle(root.current.id, 'start') }
                                Button { objectName: 'uninstallComponent'; text: '卸载'; enabled: !!root.current.id && root.current.manageable && manager && !manager.busy; onClicked: manager.prepareUninstall(root.current.id) }
                                Button { text: '停止'; enabled: !!root.current.id && manager && !manager.busy; onClicked: manager.lifecycle(root.current.id, 'stop') }
                                Repeater { model: root.viewActions(root.current)
                                    Button { required property var modelData; text: modelData.label; enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.prepareView(root.subjectId, root.current.id, modelData.operation) }
                                }
                            }
                        }
                    }
                    Label { text: '能力与权限'; font.pixelSize: 18; font.bold: true; color: '#243450' }
                    Repeater {
                        model: root.rows(root.current)
                        Rectangle {
                            id: capabilityCard
                            required property var modelData
                            Layout.fillWidth: true; implicitHeight: modelData.kind === 'operation' ? 205 : 155; radius: 12; color: 'white'
                            ColumnLayout { anchors.fill: parent; anchors.margins: 16; spacing: 8
                                RowLayout { Layout.fillWidth: true
                                    Text { text: capabilityCard.modelData.name; font.bold: true; font.pixelSize: 16; color: '#243450' }
                                    Text { text: capabilityCard.modelData.kind === 'event' ? '事件订阅' : (capabilityCard.modelData.metadata.access === 'write' ? '写入' : '读取'); color: '#738098' }
                                }
                                Repeater { model: [false, true]
                                    RowLayout {
                                        required property bool modelData
                                        property bool granted: root.hasGrant(root.current, capabilityCard.modelData, modelData)
                                        Layout.fillWidth: true
                                        Label { text: modelData ? '后台任务' : '本机交互'; color: '#68768d'; Layout.preferredWidth: 90 }
                                        Label { text: parent.granted ? '已授权' : '未授权'; color: parent.granted ? '#397c68' : '#8491a5'; Layout.fillWidth: true }
                                        Button { text: parent.granted ? '撤销' : '授予此项'; enabled: !!root.subjectId && manager && !manager.busy
                                            onClicked: manager.permission(root.subjectId, root.current.id, capabilityCard.modelData.name, capabilityCard.modelData.kind, parent.modelData, !parent.granted) }
                                    }
                                }
                                RowLayout {
                                    visible: capabilityCard.modelData.kind === 'operation'
                                    TextField { id: args; text: '{}'; placeholderText: '参数 JSON'; Layout.fillWidth: true; selectByMouse: true }
                                    Button { text: '调用'; enabled: !!root.subjectId && manager && !manager.busy
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
            Layout.fillWidth: true; implicitHeight: 76; radius: 10; color: '#e8edf7'
            ScrollView { anchors.fill: parent; anchors.margins: 12; clip: true
                TextArea { text: (manager ? manager.notice : '') || '就绪'; readOnly: true; wrapMode: Text.Wrap; color: '#43536f'; background: null; selectByMouse: true }
            }
        }
    }
}
