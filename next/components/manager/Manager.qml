import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
Pane {
    id: root
    padding: 0
    background: Rectangle { color: '#17181b' }
    font.pixelSize: 13
    readonly property bool compact: width < 760
    readonly property color ink: '#eae8e4'
    readonly property color muted: '#a7a6a4'
    readonly property color accent: '#b4cde0'
    readonly property color line: '#36373d'
    palette.window: '#202126'; palette.base: '#202126'; palette.text: '#eae8e4'; palette.windowText: '#eae8e4'
    palette.button: '#27282e'; palette.buttonText: '#eae8e4'; palette.highlight: '#303943'; palette.highlightedText: '#eae8e4'
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
        property bool primary: false
        property bool danger: false
        implicitHeight: 34; leftPadding: 13; rightPadding: 13
        hoverEnabled: true; focusPolicy: Qt.StrongFocus
        contentItem: Text {
            text: button.text; font.pixelSize: 13; font.weight: button.primary || button.checked ? Font.Medium : Font.Normal
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            color: !button.enabled ? '#777b80' : button.primary ? '#17181b' : button.danger ? '#e3a5a1' : button.checked ? root.accent : root.ink
        }
        background: Rectangle {
            radius: 8
            color: !button.enabled ? '#27282e' : button.primary ? (button.down || button.hovered ? '#c8ddea' : root.accent) : button.checked ? '#303943' : button.down ? '#3a4048' : button.hovered ? '#30343b' : button.flat ? 'transparent' : '#27282e'
            border.width: button.visualFocus ? 2 : 0; border.color: root.accent
        }
    }
    component SettingsField: TextField {
        id: field
        implicitHeight: 38; leftPadding: 12; rightPadding: 12
        font.pixelSize: 13; color: root.ink; placeholderTextColor: '#85888b'
        selectionColor: root.accent; selectedTextColor: '#202126'; selectByMouse: true
        background: Rectangle { radius: 8; color: field.enabled ? '#202126' : '#27282e'; border.width: field.activeFocus ? 2 : 1; border.color: field.activeFocus ? root.accent : '#36373d' }
    }
    component SettingsSwitch: Switch {
        id: toggle
        implicitWidth: 44; implicitHeight: 30; padding: 4
        hoverEnabled: true; focusPolicy: Qt.StrongFocus
        indicator: Rectangle {
            implicitWidth: 36; implicitHeight: 20; x: 4; y: (toggle.height - height) / 2; radius: 10
            color: !toggle.enabled ? '#36373d' : toggle.checked ? root.accent : '#545a60'
            border.width: toggle.visualFocus ? 2 : 0; border.color: '#b4cde0'
            Rectangle { x: toggle.checked ? parent.width - width - 2 : 2; y: 2; width: 16; height: 16; radius: 8; color: '#202126' }
        }
        contentItem: Item { }
        background: Item { }
    }
    component SettingsScrollBar: ScrollBar {
        id: bar; padding: 3; minimumSize: 0.12
        visible: size > 0 && size < 1
        contentItem: Rectangle { implicitWidth: 6; implicitHeight: 6; radius: 3; color: bar.pressed ? root.accent : '#747a80'; opacity: bar.hovered || bar.pressed ? 1 : 0.65 }
        background: Item { }
    }
    component SettingsCombo: ComboBox {
        id: combo
        implicitHeight: 38; leftPadding: 12; rightPadding: 34
        font.pixelSize: 13; hoverEnabled: true
        contentItem: Text { text: combo.displayText; font: combo.font; color: combo.enabled ? root.ink : '#777b80'; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
        indicator: Text { text: '⌄'; color: root.muted; font.pixelSize: 17; x: combo.width - width - 13; y: (combo.height - height) / 2 }
        background: Rectangle { radius: 8; color: combo.enabled ? '#202126' : '#27282e'; border.width: combo.visualFocus ? 2 : 1; border.color: combo.visualFocus ? root.accent : combo.hovered ? '#747a80' : '#36373d' }
        delegate: ItemDelegate {
            id: option; width: combo.width - 12; height: 38
            text: combo.textRole ? modelData[combo.textRole] : modelData
            highlighted: combo.highlightedIndex === index
            contentItem: Text { text: option.text; color: root.ink; font.pixelSize: 13; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
            background: Rectangle { radius: 6; color: option.highlighted || option.hovered ? '#303943' : 'transparent' }
        }
        popup: Popup {
            y: combo.height + 6; width: combo.width; padding: 6
            implicitHeight: Math.min(contentItem.implicitHeight + 12, 280)
            contentItem: ListView { clip: true; implicitHeight: contentHeight; model: combo.popup.visible ? combo.delegateModel : null; currentIndex: combo.highlightedIndex; ScrollBar.vertical: SettingsScrollBar { } }
            background: Rectangle { radius: 10; color: '#202126'; border.color: root.line }
        }
    }
    component SettingsDialog: Dialog {
        id: dialog
        padding: 20; focus: true
        background: Rectangle { radius: 14; color: '#202126'; border.color: root.line }
        header: Label { text: dialog.title; color: root.ink; font.pixelSize: 18; font.weight: Font.DemiBold; leftPadding: 20; rightPadding: 20; topPadding: 18; bottomPadding: 4 }
        footer: DialogButtonBox { visible: count > 0; padding: 16; spacing: 8; delegate: SettingsButton { } background: Rectangle { color: '#202126'; radius: 14 } }
        Overlay.modal: Rectangle { color: '#490f172a' }
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
    function dependencyRows(row) {
        let bindings = row.metadata.bindings || {}, result = [], groups = new Set()
        for (let alias of Object.keys(bindings)) {
            let b = bindings[alias]
            if (b.group && groups.has(b.group)) continue
            groups.add(b.group)
            let members = b.group ? Object.values(bindings).filter(x => x.group === b.group) : [b]
            let problem = members.find(x => x.issue)
            let issue = problem ? problem.issue : null
            let labels = {missing_contract:'缺少能力', incompatible_version:'契约版本不兼容', no_common_provider:'需要同一提供方', selection_required:'请选择提供方', selected_provider_unavailable:'已选提供方不可用', dependency_cycle:'存在循环依赖'}
            let state = issue ? (labels[issue.code] || '依赖不可用') + (issue.contract ? ' · ' + issue.contract : '') : b.endpoint.target
            if (issue?.path) state += ' · ' + issue.path.map(n => n[0] + '.' + n[2]).join(' → ')
            if (issue?.offered) state += '（已提供 ' + issue.offered.join('、') + '）'
            result.push({alias:alias, label:b.group || alias, title:(b.group || alias) + ' · ' + state, candidates:b.candidates,
                         contracts:members.map(x => x.contract).join('、'), endpoint:b.endpoint})
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
    SettingsDialog {
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
            Label { text: aboutDialog.info.PROJECT_URL || ''; color: root.accent; wrapMode: Text.Wrap; Layout.fillWidth: true
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally(aboutDialog.info.PROJECT_URL) }
            }
            Label { text: '代码许可：' + (aboutDialog.info.CODE_LICENSE || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: '素材许可：' + (aboutDialog.info.ARTWORK_LICENSE || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: '素材作者：' + (aboutDialog.info.ARTWORK_CREDIT || ''); wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: aboutDialog.info.ARTWORK_URL || ''; color: root.accent; wrapMode: Text.Wrap; Layout.fillWidth: true
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: Qt.openUrlExternally(aboutDialog.info.ARTWORK_URL) }
            }
        }
    }
    SettingsDialog {
        id: sourceDialog; objectName: 'sourceDialog'; title: '插件源'; modal: true
        anchors.centerIn: parent; width: Math.min(760, root.width - 48); height: Math.min(570, root.height - 48)
        contentItem: ColumnLayout {
            RowLayout {
                SettingsField { id: sourceLocation; objectName: 'sourceLocation'; placeholderText: 'Git 仓库地址或本地仓库目录'; Layout.fillWidth: true; enabled: manager && !manager.busy }
                SettingsButton { objectName: 'addSource'; text: '添加'; primary: true; enabled: manager && !manager.busy && sourceLocation.text.trim().length > 0; onClicked: manager.addSource(sourceLocation.text) }
            }
            Label { text: manager && manager.busy ? '处理中…' : '选择插件安装；已有同 ID 插件需确认更新。'; color: root.muted }
            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                ScrollBar.vertical: SettingsScrollBar { }
                ColumnLayout {
                    width: sourceDialog.availableWidth
                    Repeater {
                        model: JSON.parse(manager ? manager.sourcesJson : '[]')
                        ColumnLayout {
                            id: sourceRow; required property var modelData; Layout.fillWidth: true
                            RowLayout {
                                Label { text: sourceRow.modelData.name || sourceRow.modelData.location; Layout.fillWidth: true; elide: Text.ElideRight }
                                SettingsButton { text: sourceRow.modelData.pending ? '正在安装…' : sourceRow.modelData.defaultError ? '重试安装' : '检查更新'
                                    enabled: manager && !manager.busy && !sourceRow.modelData.pending
                                    onClicked: sourceRow.modelData.defaultError ? manager.retryDefault(sourceRow.modelData.id) : manager.refreshSource(sourceRow.modelData.id) }
                            }
                            Label { text: sourceRow.modelData.location; Layout.fillWidth: true; elide: Text.ElideMiddle; color: root.muted }
                            Label { visible: !!sourceRow.modelData.defaultError; text: sourceRow.modelData.defaultError || ''; Layout.fillWidth: true; wrapMode: Text.Wrap; color: '#e3a5a1' }
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
    SettingsDialog {
        id: viewPlan; objectName: 'viewPermissionDialog'; title: '确认展示权限'; modal: true; anchors.centerIn: parent; width: Math.min(580, root.width - 48)
        onClosed: { if (manager) manager.cancelView() }
        property var permissions: JSON.parse(manager ? manager.planJson : '[]')
        contentItem: ColumnLayout {
            spacing: 12
            Label { text: '授权使用者：' + (manager ? manager.planSubject : ''); font.pixelSize: 15 }
            Label { text: '将使用以下组件'; color: root.muted }
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
                                Label { text: permissionGroup.modelData.title; font.bold: true; color: root.ink; Layout.fillWidth: true }
                                Label { text: permissionGroup.modelData.permissions.some(function(p) { return p.access === 'write' }) ? '查看与操作' : '查看'; color: root.muted }
                                SettingsButton { text: permissionGroup.expanded ? '收起 ▴' : '详情 ▾'; flat: true; onClicked: permissionGroup.expanded = !permissionGroup.expanded }
                            }
                            Repeater {
                                model: permissionGroup.expanded ? permissionGroup.modelData.permissions : []
                                Label { required property var modelData; width: permissionGroup.width; wrapMode: Text.Wrap; color: root.muted; font.pixelSize: 12
                                    text: '  ' + modelData.name + (modelData.authorized ? ' · 已授权' : ' · 将授予') }
                            }
                        }
                    }
                }
            }
            RowLayout { Layout.alignment: Qt.AlignRight
                SettingsButton { objectName: 'cancelPermission'; text: '取消'; onClicked: viewPlan.close() }
                SettingsButton { objectName: 'confirmPermission'; text: '确认并执行'; primary: true; enabled: manager && !manager.busy; onClicked: { manager.confirmView(); viewPlan.close() } }
            }
        }
    }
    Connections { target: manager
        function onInstallationReady() { installationDialog.open() }
        function onInstallationCancelled() { installationDialog.close() }
    }
    SettingsDialog {
        id: installationDialog; objectName: 'installationDialog'; title: '确认操作'
        modal: true; anchors.centerIn: parent; width: Math.min(440, root.width - 48)
        onRejected: manager.cancelInstallation()
        contentItem: ColumnLayout {
            Label { text: manager ? manager.installationPrompt : ''; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout { Layout.alignment: Qt.AlignRight
                SettingsButton { objectName: 'cancelInstallation'; text: '取消'; onClicked: manager.cancelInstallation() }
                SettingsButton { objectName: 'confirmInstallation'; text: '确认'; primary: true; onClicked: manager.confirmInstallation() }
            }
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: root.compact ? 16 : 24; spacing: 16
        RowLayout {
            Layout.fillWidth: true
            Column { spacing: 5
                Text { text: '组件管理'; font.pixelSize: 20; font.weight: Font.DemiBold; color: root.ink }
                Text { text: 'Polaris · 安装、运行与权限'; color: root.muted; font.pixelSize: 12 }
            }
            Item { Layout.fillWidth: true }
            Flow {
                Layout.fillWidth: true; Layout.preferredHeight: childrenRect.height; spacing: 8
                layoutDirection: Qt.RightToLeft
                SettingsButton { text: '加载组件'; primary: true; onClicked: folder.open() }
                SettingsButton { objectName: 'sourceButton'; text: '插件源'; enabled: manager && !manager.busy; onClicked: sourceDialog.open() }
                SettingsButton { text: '刷新'; flat: true; onClicked: manager.refresh() }
                SettingsButton { text: '关于'; flat: true; objectName: 'aboutButton'; onClicked: aboutDialog.open() }
                SettingsButton { text: '退出'; flat: true; onClicked: manager.quit() }
            }
        }
        RowLayout {
            Label { text: '权限使用者'; color: root.muted; font.pixelSize: 12 }
            SettingsCombo {
                Layout.preferredWidth: 240; Layout.maximumWidth: Math.max(120, root.width - 140); model: root.records; textRole: 'name'
                currentIndex: root.records.findIndex(item => item.id === root.subjectId)
                onActivated: root.subjectId = root.records[currentIndex].id
            }
            Label { visible: manager && manager.busy; text: '处理中…'; font.pixelSize: 12; color: root.muted }

        }
        SplitView {
            Layout.fillWidth: true; Layout.fillHeight: true
            orientation: root.compact ? Qt.Vertical : Qt.Horizontal
            handle: Rectangle { implicitWidth: 16; implicitHeight: 16; color: 'transparent' }
            Rectangle {
                SplitView.preferredWidth: 232; SplitView.minimumWidth: 190
                SplitView.preferredHeight: root.compact ? 124 : -1
                SplitView.minimumHeight: root.compact ? 124 : 100
                color: '#202126'; radius: 12
                ListView {
                    anchors.fill: parent; anchors.margins: 12; anchors.bottomMargin: 48; spacing: 6; clip: true
                    orientation: root.compact ? ListView.Horizontal : ListView.Vertical
                    ScrollBar.vertical: SettingsScrollBar { }
                    ScrollBar.horizontal: SettingsScrollBar { }
                    model: root.visibleRecords
                    delegate: Rectangle {
                        required property var modelData
                        width: root.compact ? 180 : ListView.view.width; height: 64; radius: 8
                        color: root.current.id === modelData.id ? '#303943' : 'transparent'
                        Rectangle { width: 3; height: 24; radius: 1.5; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; color: root.accent; visible: root.current.id === modelData.id }
                        Column { anchors.fill: parent; anchors.margins: 12; spacing: 6
                            Text { text: modelData.name; font.pixelSize: 14; font.weight: Font.Medium; color: root.ink; elide: Text.ElideRight; width: parent.width }
                            Text { text: root.stateText(modelData.state); color: root.muted; font.pixelSize: 12 }
                        }
                        MouseArea { anchors.fill: parent; onClicked: root.selectedId = modelData.id }
                    }
                }
                SettingsButton { anchors.bottom: parent.bottom; anchors.horizontalCenter: parent.horizontalCenter; anchors.bottomMargin: 12; text: root.showSystemComponents ? '收起系统组件 ▴' : '系统组件 ▾'; flat: true; onClicked: { root.showSystemComponents = !root.showSystemComponents; root.selectedId = '' } }
            }
            ScrollView {
                id: detailPane; SplitView.fillWidth: true; SplitView.fillHeight: true; clip: true
                ScrollBar.vertical: SettingsScrollBar { }
                ColumnLayout {
                    width: detailPane.availableWidth; spacing: 12
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: header.implicitHeight + 40; color: '#202126'; radius: 14
                        ColumnLayout { id: header; anchors.fill: parent; anchors.margins: 20; spacing: 10
                            Label { Layout.fillWidth: true; text: root.current.name || '选择组件'; font.pixelSize: 19; font.weight: Font.DemiBold; color: root.ink; elide: Text.ElideRight }
                            Label { text: root.stateText(root.current.state); font.pixelSize: 12; color: root.current.state === 'running' ? '#a6c8b6' : root.current.state === 'failed' ? '#e3a5a1' : root.muted }
                            Text { visible: root.customPermissions; text: root.current.id || ''; color: root.muted; font.pixelSize: 12 }
                            Text { visible: !!root.description(root.current).view_state; text: root.description(root.current).view_state?.visible ? '视图已显示' : '视图已隐藏'; color: root.muted; font.pixelSize: 12 }
                            Label {
                                Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; color: '#e3a5a1'
                                visible: root.current.state === 'failed' && !!root.current.error
                                text: visible ? '启动失败：' + (root.current.error.message || root.current.error) : ''
                            }
                            RowLayout {
                                SettingsButton { text: '启动'; primary: root.current.state !== 'running'; enabled: !!root.current.id && manager && !manager.busy; onClicked: manager.lifecycle(root.current.id, 'start') }
                                SettingsButton { objectName: 'uninstallComponent'; text: '卸载'; flat: true; danger: true; enabled: !!root.current.id && root.current.manageable && manager && !manager.busy; onClicked: manager.prepareUninstall(root.current.id) }
                                SettingsButton { text: '停止'; enabled: !!root.current.id && manager && !manager.busy; onClicked: manager.lifecycle(root.current.id, 'stop') }
                                Repeater { model: root.viewActions(root.current)
                                    SettingsButton { required property var modelData; text: modelData.label; enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.prepareView(root.subjectId, root.current.id, modelData.operation) }
                                }
                            }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; implicitHeight: permissionSummary.implicitHeight + 32; color: '#202126'; radius: 12
                        ColumnLayout {
                            id: permissionSummary; anchors.fill: parent; anchors.margins: 16; spacing: 8
                            Label { text: '访问权限'; font.pixelSize: 15; font.weight: Font.DemiBold; color: root.ink }
                            Label { Layout.fillWidth: true; wrapMode: Text.Wrap; color: root.muted; font.pixelSize: 12; text: '当前使用者的本机访问范围；后台权限可在自定义中调整。' }
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
                            Label { color: root.muted; font.pixelSize: 12; text: {
                                var rows = root.rows(root.current)
                                var count = rows.filter(function(row) { return root.hasGrant(root.current, row, false) }).length
                                return count === 0 ? '未授权' : count === rows.length ? '已允许全部当前能力' : '已自定义 · ' + count + ' / ' + rows.length + ' 项'
                            } }
                        }
                    }
                    Repeater {
                        model: root.rows(root.current).filter(row => row.metadata.requires && Object.keys(row.metadata.requires).length)
                        ColumnLayout {
                            id: dependencyCard
                            required property var modelData
                            property string key: 'deps:' + modelData.kind + ':' + modelData.name
                            Layout.fillWidth: true
                            SettingsButton {
                                objectName: 'dependencies_' + dependencyCard.modelData.name
                                text: dependencyCard.modelData.name + (dependencyCard.modelData.metadata.available === false ? ' · 依赖未就绪' : ' · 能力依赖') + (root.expandedCapability === dependencyCard.key ? ' ▴' : ' ▾')
                                onClicked: root.expandedCapability = root.expandedCapability === dependencyCard.key ? '' : dependencyCard.key
                            }
                            Repeater {
                                model: root.expandedCapability === dependencyCard.key ? root.dependencyRows(dependencyCard.modelData) : []
                                ColumnLayout {
                                    id: requirementRow
                                    required property var modelData
                                    Layout.fillWidth: true
                                    Label { text: requirementRow.modelData.title; color: root.ink }
                                    Label { text: requirementRow.modelData.contracts; wrapMode: Text.Wrap; Layout.fillWidth: true; color: root.muted }
                                    Repeater {
                                        model: requirementRow.modelData.candidates
                                        SettingsButton {
                                            required property var modelData
                                            objectName: 'provider_' + requirementRow.modelData.label + '_' + modelData.target
                                            text: root.records.find(r => r.id === modelData.target)?.name || modelData.target
                                            checked: requirementRow.modelData.endpoint?.installation === modelData.installation
                                            enabled: manager && !manager.busy
                                            onClicked: manager.selectProvider(root.current.id, dependencyCard.modelData.kind, dependencyCard.modelData.name,
                                                requirementRow.modelData.alias, modelData.installation, root.current.installation)
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Repeater {
                        model: root.customPermissions ? root.rows(root.current) : []
                        Rectangle {
                            id: capabilityCard
                            required property var modelData
                            property string key: modelData.kind + ':' + modelData.name
                            property bool expanded: root.expandedCapability === key
                            Layout.fillWidth: true; implicitHeight: capabilityContent.implicitHeight + 24; radius: 10; color: '#202126'
                            ColumnLayout {
                                id: capabilityContent; anchors.fill: parent; anchors.margins: 12; spacing: 6
                                RowLayout {
                                    Layout.fillWidth: true
                                    Label { text: capabilityCard.modelData.name; color: root.ink; Layout.fillWidth: true; elide: Text.ElideRight }
                                    Label { text: capabilityCard.modelData.kind === 'event' ? '订阅' : capabilityCard.modelData.metadata.access === 'write' ? '操作' : '查看'; color: root.muted; font.pixelSize: 12 }
                                    SettingsSwitch { objectName: 'capability_' + capabilityCard.modelData.name
                                        checked: root.hasGrant(root.current, capabilityCard.modelData, false); enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.permission(root.subjectId, root.current.id, capabilityCard.modelData.name, capabilityCard.modelData.kind, false, checked) }
                                    SettingsButton { text: capabilityCard.expanded ? '收起' : '高级'; flat: true; onClicked: root.expandedCapability = capabilityCard.expanded ? '' : capabilityCard.key }
                                }
                                RowLayout {
                                    visible: capabilityCard.expanded; Layout.fillWidth: true
                                    Label { text: '允许后台任务'; color: root.muted; Layout.fillWidth: true }
                                    SettingsSwitch { checked: root.hasGrant(root.current, capabilityCard.modelData, true); enabled: !!root.subjectId && manager && !manager.busy
                                        onClicked: manager.permission(root.subjectId, root.current.id, capabilityCard.modelData.name, capabilityCard.modelData.kind, true, checked) }
                                }
                                RowLayout {
                                    visible: capabilityCard.expanded && capabilityCard.modelData.kind === 'operation'
                                    SettingsField { id: args; text: '{}'; placeholderText: '调试参数 JSON'; Layout.fillWidth: true; selectByMouse: true; color: root.ink }
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
            visible: !!manager && manager.notice.length > 0; Layout.fillWidth: true; implicitHeight: 64; radius: 10; color: '#303943'
            ScrollView { anchors.fill: parent; anchors.margins: 12; clip: true
                TextArea { text: (manager ? manager.notice : '') || '就绪'; font.pixelSize: 13; readOnly: true; wrapMode: Text.Wrap; color: root.ink; background: null; selectByMouse: true }
            }
        }
    }
}
