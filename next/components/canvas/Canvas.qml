import QtQuick
import QtQuick as Quick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs
import Polaris.Ui 1.0 as Ui
import "../manager" as Management

Rectangle {
    id: canvasRoot
    objectName: "canvasSurface"
    color: 'transparent'
    Ui.Theme { id: colors; mode: typeof canvasActions === 'undefined' ? 'dark' : canvasActions.theme }
    Rectangle {
        anchors.fill: parent; anchors.margins: 4
        radius: 12; color: colors.panel
    }
    readonly property var appHost: typeof applicationHost === 'undefined' ? null : applicationHost
    readonly property var applications: appHost ? JSON.parse(appHost.applicationsJson) : []
    readonly property var selectedApplication: appHost ? JSON.parse(appHost.selectedJson) : ({})
    readonly property bool compactNavigation: width < 620
    readonly property int navigationWidth: compactNavigation ? 68 : width < 900 ? 192 : 216
    property bool settingsOpen: false
    property string settingsSection: 'appearance'
    readonly property bool wideSettings: width >= 1000
    readonly property var managementBridge: canvasActions.managementBridge
    function showExtensionManagement() { settingsSection = 'extensions'; showSettings() }
    readonly property string pageTitle: settingsOpen ? '设置' : (selectedApplication.title || '')
    function showWorkspace() { showApplication('f3bcb2d1737d4f4e9c57c5ea63f68209') }
    function showApplication(identity) { if (settingsOpen || selectedApplication.applicationId !== identity) { applicationConnections.close(); if (managementBridge && !managementBridge.noticeIsError) managementBridge.dismissNotice() } settingsOpen = false; appHost.select(identity) }
    function showSettings() { applicationConnections.close(); if (!settingsOpen && appHost) appHost.dismissMessage(); settingsOpen = true; if (appHost) appHost.select('') }
    readonly property bool workbenchSelected: !!selectedApplication.builtin
    readonly property bool applicationSelected: !!selectedApplication.applicationId && !workbenchSelected
    property string lastError: ''
    readonly property string messageError: (appHost && !(applicationConnections.visible && applicationConnections.stage === 'connections') ? appHost.messageError : '') || (managementBridge && managementBridge.noticeIsError ? managementBridge.notice : '') || lastError
    readonly property string messageText: messageError || (managementBridge ? managementBridge.notice : '') || (appHost && !(applicationSelected && selectedApplication.package && !settingsOpen) ? appHost.feedback : '')
    readonly property real contentTop: messageBar.visible ? messageBar.y + messageBar.height + 12 : 90
    property var canvasWindow: Window.window
    onCanvasWindowChanged: if (typeof canvasActions !== 'undefined') canvasActions.bindWindow(canvasWindow)
    Component.onCompleted: { canvasActions.bindWindow(canvasWindow); if (appHost) { appHost.attachBuiltinHeader(builtinHeaderSurface); appHost.attachView(customApplicationSurface) } }
    HoverHandler {
        onHoveredChanged: {
            if (typeof canvasActions !== 'undefined') {
                if (hovered) canvasActions.pointerEntered()
                else canvasActions.pointerLeft()
            }
        }
    }
    Timer {
        objectName: 'canvasPointerOverlayTimer'
        interval: 80; repeat: true; running: !!canvasRoot.canvasWindow && canvasRoot.canvasWindow.visible
        onTriggered: {
            canvasActions.syncPointer()
            var overlay = Overlay.overlay
            var active = false
            if (overlay) {
                for (var i = 0; i < overlay.children.length; ++i) {
                    if (overlay.children[i].visible) { active = true; break }
                }
            }
            if (typeof canvasActions !== 'undefined') canvasActions.hold('overlay', active)
        }
    }
    Rectangle {
        x: 4; y: 4; width: canvasRoot.navigationWidth - 4; height: parent.height - 8
        radius: 10; color: colors.sidebar
    }
    Item {
        x: 12; y: 16; width: canvasRoot.navigationWidth - 24; height: 42
        Row {
            x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Ui.Icon { theme: colors; anchors.verticalCenter: parent.verticalCenter; width: 19; height: 19; kind: 'star'; ink: colors.ink }
            Text { visible: !canvasRoot.compactNavigation; text: 'Polaris'; color: colors.ink; font.pixelSize: 15; font.weight: Font.DemiBold; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    Flickable {
        id: applicationRail
        objectName: 'canvasApplicationRail'
        function reveal(item) {
            var top = item.mapToItem(railColumn, 0, 0).y
            contentY = Math.max(0, Math.min(contentHeight - height, Math.max(top + item.height - height, Math.min(contentY, top))))
        }
        x: 12; y: 76; z: 11; width: canvasRoot.navigationWidth - 24; height: Math.max(0, parent.height - 154)
        contentHeight: railColumn.implicitHeight; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: Ui.ScrollBar { theme: colors; policy: ScrollBar.AsNeeded }
        Column {
            id: railColumn; spacing: 4; width: parent.width
            Text { x: 12; height: 24; visible: !canvasRoot.compactNavigation; text: '应用'; color: colors.quiet; font.pixelSize: 11; font.weight: Font.Medium }
            Repeater {
                model: canvasRoot.applications
                Ui.NavigationItem { required property var modelData; theme: colors; compact: canvasRoot.compactNavigation; width: canvasRoot.navigationWidth - 24; text: modelData.title; glyph: modelData.builtin ? 'board' : 'apps'; objectName: modelData.builtin ? 'workspaceEntry' : 'applicationEntry_' + modelData.applicationId
                    selected: !canvasRoot.settingsOpen && canvasRoot.selectedApplication.applicationId === modelData.applicationId
                    onActiveFocusChanged: if (activeFocus) applicationRail.reveal(this)
                    onClicked: canvasRoot.showApplication(modelData.applicationId) }
            }
        }
    }
    Ui.NavigationItem { theme: colors; compact: canvasRoot.compactNavigation; width: canvasRoot.navigationWidth - 24; x: 12; y: parent.height - 58; z: 11; text: '设置'; glyph: 'settings'; objectName: 'canvasSettingsEntry'; selected: canvasRoot.settingsOpen; onClicked: canvasRoot.showSettings() }
    CanvasWindowHandle { objectName: 'canvasBrandMove'; x: 8; y: 8; width: canvasRoot.navigationWidth - 16; height: 48 }
    CanvasWindowHandle { objectName: 'canvasWindowMove'; x: canvasRoot.navigationWidth + 8; y: 8; width: Math.max(0, parent.width - canvasRoot.navigationWidth - 216); height: 48 }
    Item {
        id: toolbar
        x: canvasRoot.navigationWidth + 28; y: 18; width: parent.width - canvasRoot.navigationWidth - 52; height: 36; z: 10
        Text {
            id: pageTitleLabel; objectName: 'canvasPageTitle'; anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
            width: Math.max(0, parent.width - toolbarActions.width - 18); text: canvasRoot.pageTitle; textFormat: Text.PlainText
            elide: Text.ElideRight; color: colors.ink; font.pixelSize: 17; font.weight: Font.DemiBold
            HoverHandler { id: pageTitleHover }
            ToolTip {
                visible: pageTitleHover.hovered && pageTitleLabel.truncated; delay: 650
                contentItem: Text { text: pageTitleLabel.text; textFormat: Text.PlainText; color: colors.ink }
                background: Rectangle { radius: colors.radiusSmall; color: colors.card; border.color: colors.border }
            }
        }
        Row {
            id: toolbarActions; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
            Item { id: builtinHeaderSurface; objectName: 'builtinHeaderSurface'; width: visible ? childrenRect.width : 0; height: 34; visible: canvasRoot.workbenchSelected && !canvasRoot.settingsOpen }
            Ui.Button { theme: colors; text: canvasRoot.compactNavigation ? '' : '组件连接 / 权限'; glyph: 'settings'; hint: '组件连接 / 权限'; objectName: 'applicationConnectionsToggle'; visible: canvasRoot.applicationSelected && !!canvasRoot.selectedApplication.package && !canvasRoot.settingsOpen; onClicked: { if (applicationConnections.visible) applicationConnections.close(); else applicationConnections.openConnections() } }
            Ui.Button { theme: colors; glyph: 'down'; hint: '收起画布'; objectName: 'dismissCanvas'; onClicked: canvasActions.dismiss() }
        }
    }
    Rectangle { x: canvasRoot.navigationWidth + 28; y: 70; width: Math.max(0, parent.width - canvasRoot.navigationWidth - 52); height: 1; color: colors.border }
    Rectangle {
        id: messageBar; objectName: 'canvasMessageBar'
        x: canvasRoot.navigationWidth + 28; y: 84
        width: Math.max(0, parent.width - canvasRoot.navigationWidth - 52)
        height: visible ? Math.min(Math.max(messageLabel.implicitHeight + 24, 56), canvasRoot.height / 3) : 0
        visible: canvasRoot.messageText.length > 0; enabled: visible
        radius: 8; color: colors.card; border.color: colors.border
        ScrollView {
            id: messageScroll; objectName: 'canvasMessageScroll'
            anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
            anchors.margins: 12; anchors.right: closeMessage.left; anchors.rightMargin: 8
            clip: true; contentWidth: availableWidth
            Text {
                id: messageLabel; objectName: 'canvasMessageText'
                width: messageScroll.availableWidth; text: canvasRoot.messageText
                textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: canvasRoot.messageError.length ? colors.error : colors.muted; font.pixelSize: 13
            }
        }
        Ui.Button {
            id: closeMessage; objectName: 'canvasCloseMessage'; theme: colors
            glyph: 'close'; hint: '关闭消息'; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 12
            onClicked: { if (canvasRoot.appHost) canvasRoot.appHost.dismissMessage(); if (canvasRoot.managementBridge) canvasRoot.managementBridge.dismissNotice(); canvasRoot.lastError = '' }
        }
    }
    ScrollView {
        id: applicationPageScroll
        enabled: visible
        objectName: 'applicationPage'; visible: canvasRoot.applicationSelected && !canvasRoot.settingsOpen && !canvasRoot.selectedApplication.package
        anchors.fill: parent; anchors.topMargin: canvasRoot.contentTop; anchors.leftMargin: canvasRoot.navigationWidth + 28; anchors.rightMargin: 24; anchors.bottomMargin: 20
        clip: true
        ColumnLayout {
            width: applicationPageScroll.availableWidth; spacing: 16
            Repeater {
                model: canvasRoot.selectedApplication.pages || []
                Rectangle {
                    id: applicationForm
                    required property var modelData
                    property var values: ({})
                    Layout.fillWidth: true; implicitHeight: formColumn.implicitHeight + 40
                    radius: 12; color: colors.card; border.color: colors.border
                    ColumnLayout {
                        id: formColumn; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 20; spacing: 12
                        Text { textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; text: applicationForm.modelData.title || applicationForm.modelData.id; color: colors.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
                        Repeater {
                            model: applicationForm.modelData.inputs || []
                            ColumnLayout {
                                required property var modelData
                                Layout.fillWidth: true; spacing: 6
                                Text { textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; text: modelData.label; color: colors.ink; font.pixelSize: 13 }
                                Ui.TextField {
                                    theme: colors;
                                    objectName: 'applicationInput_' + modelData.name
                                    Layout.fillWidth: true; text: modelData.default || ''; color: colors.ink
                                    Component.onCompleted: applicationForm.values[modelData.name] = text
                                    onTextChanged: applicationForm.values[modelData.name] = text
                                }
                            }
                        }
                        Ui.Button {
                            theme: colors; text: '执行'; glyph: 'right'; primary: true; objectName: 'runApplication_' + applicationForm.modelData.id
                            enabled: canvasRoot.appHost && !canvasRoot.appHost.busy
                            onClicked: canvasRoot.appHost.run(applicationForm.modelData.action, JSON.stringify(applicationForm.values))
                        }
                    }
                }
            }
            RowLayout {
                Ui.Button { theme: colors; text: '撤销应用授权'; glyph: 'close'; objectName: 'revokeApplication'; onClicked: canvasRoot.appHost.revoke() }

            }
            Text { textFormat: Text.PlainText; text: canvasRoot.appHost && canvasRoot.appHost.busy ? '正在处理：' + canvasRoot.appHost.busyTitle : ''; color: colors.muted }
            Text { text: canvasRoot.appHost ? ({idle: '就绪', approval: '等待授权确认', running: '正在执行…', done: '执行完成', error: '执行失败'}[canvasRoot.appHost.state] || '') : ''; color: colors.muted }
            Text { Layout.fillWidth: true; text: canvasRoot.appHost ? canvasRoot.appHost.error : ''; color: colors.error; wrapMode: Text.Wrap; textFormat: Text.PlainText }
            TextArea { Layout.fillWidth: true; visible: text.length > 0; readOnly: true; textFormat: TextEdit.PlainText; selectByMouse: true; wrapMode: TextEdit.Wrap; text: canvasRoot.appHost ? canvasRoot.appHost.result : ''; color: colors.ink; background: Rectangle { color: colors.card; radius: 8 } }
        }
    }
    ApplicationConnections {
        id: applicationConnections
        applicationHost: canvasRoot.appHost; manager: canvasRoot.managementBridge; theme: colors
        onHoldChanged: function(reason, active) { canvasActions.hold(reason, active) }
    }
    Item {
        id: customApplicationSurface; objectName: 'customApplicationSurface'
        visible: !canvasRoot.settingsOpen; enabled: visible; clip: true
        x: canvasRoot.navigationWidth + (canvasRoot.workbenchSelected ? 20 : 28)
        y: canvasRoot.contentTop
        width: parent.width - x - (canvasRoot.workbenchSelected ? 12 : 24)
        height: Math.max(0, parent.height - y - (canvasRoot.workbenchSelected ? 12 : 38))
    }
    Item {
        id: settingsPage; objectName: 'canvasSettingsPage'; visible: canvasRoot.settingsOpen; enabled: visible
        x: canvasRoot.navigationWidth + 28; y: canvasRoot.contentTop + 4
        width: parent.width - x - 28; height: Math.max(0, parent.height - y - 24)
        Column {
            id: settingsNavigation; visible: canvasRoot.wideSettings
            width: 156; spacing: 4
            Repeater {
                model: [{key:'appearance',title:'外观'}, {key:'extensions',title:'扩展管理'}, {key:'about',title:'关于'}]
                Ui.NavigationItem { required property var modelData; theme: colors; width: parent.width; glyph: ''; text: modelData.title; selected: canvasRoot.settingsSection === modelData.key; objectName: 'canvasSettings_' + modelData.key; onClicked: canvasRoot.settingsSection = modelData.key }
            }
        }
        Ui.ComboBox {
            id: compactSettingsNavigation; objectName: 'canvasSettingsSectionPicker'; theme: colors
            visible: !canvasRoot.wideSettings; width: parent.width
            model: ['外观', '扩展管理', '关于']; currentIndex: ['appearance','extensions','about'].indexOf(canvasRoot.settingsSection)
            onActivated: function(index) { canvasRoot.settingsSection = ['appearance','extensions','about'][index] }
        }
        Item {
            id: settingsContent
            x: canvasRoot.wideSettings ? 180 : 0; y: canvasRoot.wideSettings ? 0 : compactSettingsNavigation.height + 16
            width: parent.width - x; height: Math.max(0, parent.height - y)
            ScrollView {
                id: appearancePage; objectName: 'canvasAppearancePage'; anchors.fill: parent
                visible: canvasRoot.settingsSection === 'appearance'; enabled: visible; clip: true; contentWidth: availableWidth
                ScrollBar.vertical: Ui.ScrollBar { theme: colors }
                ColumnLayout {
                    width: appearancePage.availableWidth; spacing: 14
                    Text { text: '外观'; color: colors.ink; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Text { text: '选择画布配色'; color: colors.muted; font.pixelSize: 13 }
                Flow {
                    Layout.fillWidth: true; spacing: 10
                    Repeater {
                        model: [{key:'dark',name:'石墨',background:'#1b1c20',sidebar:'#18191d',card:'#292b30'}, {key:'light',name:'雾白',background:'#f3f5f8',sidebar:'#ebedf1',card:'#ffffff'}, {key:'warm',name:'暖砂',background:'#f3eee6',sidebar:'#ebe5db',card:'#fffcf7'}]
                        ItemDelegate {
                            id: appearance; required property var modelData
                            objectName: 'canvasAppearance_' + modelData.key
                            onActiveFocusChanged: if (activeFocus) {
                                var flick = appearancePage.contentItem
                                var top = mapToItem(flick.contentItem, 0, 0).y
                                flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, height > flick.height ? top : Math.max(top + height - flick.height, Math.min(flick.contentY, top))))
                            }
                            width: 144; height: 114; padding: 9; focusPolicy: Qt.StrongFocus
                            Accessible.name: modelData.name; Accessible.role: Accessible.RadioButton; Accessible.checkable: true; Accessible.checked: canvasActions.theme === modelData.key
                            background: Rectangle { radius: 8; color: appearance.hovered || canvasActions.theme === appearance.modelData.key ? colors.hover : 'transparent'; border.color: appearance.visualFocus ? colors.focus : canvasActions.theme === appearance.modelData.key ? colors.muted : colors.border; border.width: appearance.visualFocus ? 2 : 1 }
                            contentItem: Column {
                                spacing: 9
                                Rectangle { width: parent.width; height: 64; radius: 5; color: appearance.modelData.background; clip: true
                                    Rectangle { x: 0; y: 0; width: 31; height: parent.height; color: appearance.modelData.sidebar }
                                    Rectangle { x: 40; y: 12; width: parent.width - 49; height: 11; radius: 3; color: appearance.modelData.card }
                                    Rectangle { x: 40; y: 30; width: parent.width - 49; height: 23; radius: 3; color: appearance.modelData.card }
                                }
                                Text { text: appearance.modelData.name + (canvasActions.theme === appearance.modelData.key ? '  ✓' : ''); color: colors.ink; font.pixelSize: 12 }
                            }
                            onClicked: canvasActions.setTheme(modelData.key)
                        }
                    }
                }

                }
            }
            Management.Manager {
                id: extensionManagement; anchors.fill: parent
                visible: canvasRoot.settingsSection === 'extensions'; enabled: visible
                theme: colors; manager: canvasRoot.managementBridge; applicationHost: canvasRoot.appHost
                onOpenApplication: function(identity) { canvasRoot.showApplication(identity) }
                onOpenComponentView: function(identity) { canvasRoot.showWorkspace(); canvasActions.openComponentView(identity) }
                onHoldChanged: function(reason, active) { canvasActions.hold(reason, active) }
            }
            ScrollView {
                id: aboutPage; objectName: 'canvasAboutPage'; anchors.fill: parent
                visible: canvasRoot.settingsSection === 'about'; enabled: visible; clip: true; contentWidth: availableWidth
                ColumnLayout {
                    width: aboutPage.availableWidth; spacing: 12
                    Text { text: '关于 Polaris'; color: colors.ink; font.pixelSize: 16; font.weight: Font.DemiBold }
                    Text { objectName: 'canvasAboutVersion'; text: 'Polaris  v' + canvasActions.applicationVersion; color: colors.muted; font.pixelSize: 13 }
                    Text { Layout.fillWidth: true; text: '你的应用与组件工作空间'; color: colors.muted; wrapMode: Text.Wrap; font.pixelSize: 13 }
                    Repeater {
                        model: {
                            var info = JSON.parse(canvasRoot.managementBridge ? canvasRoot.managementBridge.aboutJson : '{}')
                            return ['作者：' + (info.AUTHOR || ''), info.PROJECT_URL || '', '代码许可：' + (info.CODE_LICENSE || ''), '素材许可：' + (info.ARTWORK_LICENSE || ''), info.ARTWORK_CREDIT || '', info.ARTWORK_URL || '']
                        }
                        Text { required property string modelData; Layout.fillWidth: true; text: modelData; textFormat: Text.PlainText; color: colors.muted; wrapMode: Text.WrapAnywhere; font.pixelSize: 12 }
                    }
                }
            }
        }
    }
    Management.ManagementDialogs {
        id: managementDialogs
        anchors.fill: parent; manager: canvasRoot.managementBridge; theme: colors
        onHoldChanged: function(reason, active) { canvasActions.hold(reason, active) }
    }
    Connections {
        target: canvasRoot.canvasWindow
        function onVisibleChanged() { if (canvasRoot.canvasWindow.visible) { managementDialogs.restorePresentation(); applicationConnections.restorePresentation() } }
    }
    Repeater {
        model: [
            {n:'Top', e:Qt.TopEdge, x:16, y:0, w:canvasRoot.width-32, h:6},
            {n:'Bottom', e:Qt.BottomEdge, x:16, y:canvasRoot.height-6, w:canvasRoot.width-32, h:6},
            {n:'Left', e:Qt.LeftEdge, x:0, y:16, w:6, h:canvasRoot.height-32},
            {n:'Right', e:Qt.RightEdge, x:canvasRoot.width-6, y:16, w:6, h:canvasRoot.height-32},
            {n:'TopLeft', e:Qt.TopEdge|Qt.LeftEdge, x:4, y:4, w:12, h:12},
            {n:'TopRight', e:Qt.TopEdge|Qt.RightEdge, x:canvasRoot.width-16, y:4, w:12, h:12},
            {n:'BottomLeft', e:Qt.BottomEdge|Qt.LeftEdge, x:4, y:canvasRoot.height-16, w:12, h:12},
            {n:'BottomRight', e:Qt.BottomEdge|Qt.RightEdge, x:canvasRoot.width-16, y:canvasRoot.height-16, w:12, h:12}
        ]
        delegate: CanvasWindowHandle { objectName: 'canvasResize' + modelData.n; edges: modelData.e; x: modelData.x; y: modelData.y; width: modelData.w; height: modelData.h; z: 30 }
    }

}
