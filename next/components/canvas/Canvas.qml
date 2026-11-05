import QtQuick
import QtQuick as Quick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: canvasRoot
    objectName: "canvasSurface"
    color: 'transparent'
    CanvasPalette { id: colors; theme: typeof canvasActions === 'undefined' ? 'dark' : canvasActions.theme }
    component WorkspaceScrollBar: ScrollBar {
        id: bar
        padding: 3
        minimumSize: 0.12
        visible: size > 0 && size < 1
        contentItem: Rectangle { implicitWidth: 6; implicitHeight: 6; radius: 3; color: bar.pressed ? colors.accent : colors.scrollThumb; opacity: bar.hovered || bar.pressed ? 1 : 0.65 }
        background: Rectangle { color: 'transparent' }
    }
    Rectangle {
        anchors.fill: parent; anchors.margins: 4
        radius: 12; color: colors.panel; border.color: colors.border; border.width: 1
    }
    readonly property var paletteForControls: colors
    readonly property bool empty: Object.keys(viewCards).length === 0 && JSON.parse(cardsJson).length === 0
    function chooseView() { canvasActions.refreshViews(); viewPicker.open() }
    readonly property var appHost: typeof applicationHost === 'undefined' ? null : applicationHost
    readonly property var applications: appHost ? JSON.parse(appHost.applicationsJson) : []
    readonly property var selectedApplication: appHost ? JSON.parse(appHost.selectedJson) : ({})
    readonly property int navigationWidth: applications.length ? 172 : 64
    readonly property bool applicationSelected: !!selectedApplication.applicationId
    property string cardsJson: '[]'
    property var viewCards: ({})
    property string lastError: ''
    property var canvasWindow: Window.window
    onCanvasWindowChanged: if (typeof canvasActions !== 'undefined') canvasActions.bindWindow(canvasWindow)
    Component.onCompleted: canvasActions.bindWindow(canvasWindow)
    HoverHandler {
        onHoveredChanged: {
            if (typeof canvasActions !== 'undefined') {
                if (hovered) canvasActions.pointerEntered()
                else canvasActions.pointerLeft()
            }
        }
    }
    Timer {
        interval: 80; repeat: true; running: true
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
        x: canvasRoot.navigationWidth; y: 8; width: 1; height: parent.height - 16; color: colors.border
    }
    Flickable {
        x: 12; y: 18; z: 11; width: canvasRoot.navigationWidth - 24; height: parent.height - 36
        contentHeight: railColumn.implicitHeight; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: WorkspaceScrollBar { policy: ScrollBar.AsNeeded }
        Column {
        id: railColumn; spacing: 10; width: parent.width
        Item { width: canvasRoot.navigationWidth - 24; height: 40; CanvasIcon { anchors.centerIn: parent; width: 20; height: 20; kind: 'star'; ink: colors.accent } }
        CanvasButton { truncateLabel: true; width: canvasRoot.navigationWidth - 24; canvasPalette: canvasRoot.paletteForControls; text: canvasRoot.applications.length ? '工作台' : ''; hint: '工作台'; glyph: 'board'; objectName: 'workspaceEntry'; primary: !canvasRoot.applicationSelected; onClicked: if (canvasRoot.appHost) canvasRoot.appHost.select('') }
        Repeater {
            model: canvasRoot.applications
            CanvasButton { truncateLabel: true; width: canvasRoot.navigationWidth - 24; canvasPalette: canvasRoot.paletteForControls; text: modelData.title; hint: modelData.title; glyph: 'board'; objectName: 'applicationEntry_' + modelData.applicationId
                primary: canvasRoot.selectedApplication.applicationId === modelData.applicationId
                onClicked: canvasRoot.appHost.select(modelData.applicationId) }
        }
        Rectangle { width: canvasRoot.navigationWidth - 24; height: 1; color: colors.border }
        CanvasButton { truncateLabel: true; width: canvasRoot.navigationWidth - 24; canvasPalette: canvasRoot.paletteForControls; text: canvasRoot.applications.length ? '添加组件' : ''; hint: '添加组件'; glyph: 'plus'; onClicked: canvasRoot.chooseView() }
        CanvasButton { truncateLabel: true; width: canvasRoot.navigationWidth - 24; canvasPalette: canvasRoot.paletteForControls; text: canvasRoot.applications.length ? '配色' : ''; hint: '配色'; glyph: 'palette'; objectName: 'canvasThemePicker'; onClicked: themePicker.open() }
        CanvasButton { truncateLabel: true; width: canvasRoot.navigationWidth - 24; canvasPalette: canvasRoot.paletteForControls; text: canvasRoot.applications.length ? '导入应用 JSON' : ''; glyph: 'plus'; hint: '开发者：导入应用 JSON'; objectName: 'importApplication'; visible: !!canvasRoot.appHost; onClicked: applicationImport.open() }
    }
    }
    CanvasWindowHandle { objectName: 'canvasWindowMove'; x: canvasRoot.navigationWidth + 8; y: 8; width: Math.max(0, parent.width - canvasRoot.navigationWidth - 216); height: 48 }
    Item {
        id: toolbar
        x: canvasRoot.navigationWidth + 28; y: 12; width: parent.width - canvasRoot.navigationWidth - 48; height: 36; z: 10
        Row {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Text { text: 'Polaris'; color: colors.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
        }
        Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '整理布局'; glyph: 'board'; objectName: 'arrangeCanvas'; visible: !canvasRoot.applicationSelected && !canvasRoot.empty; onClicked: canvasActions.arrange(viewport.width) }
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '添加组件'; glyph: "plus"; objectName: 'chooseComponentView'; onClicked: canvasRoot.chooseView() }
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: "down"; hint: "收起画布"; objectName: 'dismissCanvas'; onClicked: canvasActions.dismiss() }
        }
    }
    Text { textFormat: Text.PlainText; width: parent.width - canvasRoot.navigationWidth - 56; elide: Text.ElideRight; x: canvasRoot.navigationWidth + 32; y: 68; text: canvasRoot.applicationSelected ? canvasRoot.selectedApplication.title : '工作台'; color: colors.ink; font.pixelSize: 20; font.weight: Font.DemiBold }
    Rectangle { x: canvasRoot.navigationWidth + 28; y: 58; width: Math.max(0, parent.width - canvasRoot.navigationWidth - 48); height: 1; color: colors.border }
    Flickable {
        id: viewport
        objectName: 'canvasViewport'
        visible: !canvasRoot.applicationSelected
        anchors.fill: parent; anchors.topMargin: 102; anchors.leftMargin: canvasRoot.navigationWidth + 20; anchors.rightMargin: 12; anchors.bottomMargin: 12
        clip: true
        // Native views own their gestures. Navigation uses the scrollbars or
        // wheel events that were not consumed by a component.
        interactive: false
        boundsBehavior: Flickable.StopAtBounds
        readonly property real originX: Math.min(0, surface.childrenRect.x)
        readonly property real originY: Math.min(0, surface.childrenRect.y)
        contentWidth: Math.max(width, surface.childrenRect.x + surface.childrenRect.width - originX + 12)
        contentHeight: Math.max(height, surface.childrenRect.y + surface.childrenRect.height - originY + 16)
        function scrollBy(dx, dy) {
            contentX = Math.max(0, Math.min(contentWidth - width, contentX + dx))
            contentY = Math.max(0, Math.min(contentHeight - height, contentY + dy))
        }
        function reveal(card) {
            var left = card.x - originX, top = card.y - originY
            var right = left + Math.min(card.width, Math.max(0, width - 16))
            var bottom = top + Math.min(card.height, Math.max(44, height - 16))
            if (left < contentX) contentX = left
            else if (right > contentX + width - 16) contentX = right - width + 16
            if (top < contentY) contentY = top
            else if (bottom > contentY + height - 16) contentY = bottom - height + 16
            scrollBy(0, 0)
        }
        ScrollBar.horizontal: WorkspaceScrollBar {
            objectName: 'canvasHorizontalScroll'; height: 12; z: 20
            policy: ScrollBar.AsNeeded; visible: viewport.contentWidth > viewport.width; active: visible
            onPressedChanged: canvasActions.hold('scroll-horizontal', pressed)
        }
        ScrollBar.vertical: WorkspaceScrollBar {
            objectName: 'canvasVerticalScroll'; width: 12; z: 20
            policy: ScrollBar.AsNeeded; visible: viewport.contentHeight > viewport.height; active: visible
            onPressedChanged: canvasActions.hold('scroll-vertical', pressed)
        }
        MouseArea {
            width: viewport.contentWidth; height: viewport.contentHeight; z: -1
            acceptedButtons: Qt.NoButton
            onWheel: function(wheel) {
                var dx = wheel.pixelDelta.x || wheel.angleDelta.x / 3
                var dy = wheel.pixelDelta.y || wheel.angleDelta.y / 3
                if (wheel.modifiers & Qt.ShiftModifier) { dx += dy; dy = 0 }
                viewport.scrollBy(-dx, -dy)
                wheel.accepted = true
            }
        }
        Item {
            id: surface
            x: -viewport.originX; y: -viewport.originY
            width: viewport.width; height: viewport.height
            Flow {
                x: 12; y: 8; width: Math.max(0, viewport.width - 32); spacing: 16
                visible: JSON.parse(cardsJson).length > 0
                Repeater {
                    model: JSON.parse(cardsJson)
                    Rectangle {
                        width: 330; height: 160; radius: 12; clip: true; color: colors.card
                        Column { anchors.fill: parent; anchors.margins: 20; spacing: 12
                            Text { objectName: 'cardTitle'; textFormat: Text.PlainText; text: modelData.title; font.pixelSize: 15; font.weight: Font.DemiBold; color: colors.ink }
                            Text { objectName: 'cardBody'; textFormat: Text.PlainText; text: modelData.text; wrapMode: Text.Wrap; width: parent.width; color: colors.muted; font.pixelSize: 14 }
                        }
                    }
                }
            }
        }
    }
    Column {
        anchors.centerIn: viewport; spacing: 12; visible: canvasRoot.empty && !canvasRoot.applicationSelected
        width: Math.min(360, viewport.width - 32)
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 42; height: 42; radius: 12; color: colors.softAccent; CanvasIcon { anchors.centerIn: parent; kind: 'board'; ink: colors.accent; width: 22; height: 22 } }
        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: '把常用组件放到工作台'; color: colors.ink; font.pixelSize: 17; font.weight: Font.DemiBold; wrapMode: Text.Wrap }
        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: '添加组件后，可以自由摆放、调整大小和折叠。\n布局会为你保留。'; color: colors.muted; font.pixelSize: 13; wrapMode: Text.Wrap; lineHeight: 1.35 }
        CanvasButton { canvasPalette: canvasRoot.paletteForControls; anchors.horizontalCenter: parent.horizontalCenter; text: '添加第一个组件'; primary: true; onClicked: canvasRoot.chooseView() }
    }
    ScrollView {
        id: applicationPageScroll
        objectName: 'applicationPage'; visible: canvasRoot.applicationSelected
        anchors.fill: parent; anchors.topMargin: 102; anchors.leftMargin: canvasRoot.navigationWidth + 28; anchors.rightMargin: 24; anchors.bottomMargin: 20
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
                                TextField {
                                    objectName: 'applicationInput_' + modelData.name
                                    Layout.fillWidth: true; text: modelData.default || ''; color: colors.ink
                                    background: Rectangle { radius: 6; color: colors.panel; border.color: colors.border }
                                    Component.onCompleted: applicationForm.values[modelData.name] = text
                                    onTextChanged: applicationForm.values[modelData.name] = text
                                }
                            }
                        }
                        CanvasButton {
                            canvasPalette: canvasRoot.paletteForControls; text: '执行'; glyph: 'right'; primary: true; objectName: 'runApplication_' + applicationForm.modelData.id
                            enabled: canvasRoot.appHost && !canvasRoot.appHost.busy
                            onClicked: canvasRoot.appHost.run(applicationForm.modelData.action, JSON.stringify(applicationForm.values))
                        }
                    }
                }
            }
            RowLayout {
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '撤销应用授权'; glyph: 'close'; objectName: 'revokeApplication'; onClicked: canvasRoot.appHost.revoke() }
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '移除应用'; glyph: 'close'; objectName: 'removeApplication'; onClicked: applicationRemoval.open() }
            }
            Text { textFormat: Text.PlainText; text: canvasRoot.appHost && canvasRoot.appHost.busy ? '正在处理：' + canvasRoot.appHost.busyTitle : ''; color: colors.muted }
            Text { text: canvasRoot.appHost ? ({idle: '就绪', approval: '等待授权确认', running: '正在执行…', done: '执行完成', error: '执行失败'}[canvasRoot.appHost.state] || '') : ''; color: colors.muted }
            Text { Layout.fillWidth: true; text: canvasRoot.appHost ? canvasRoot.appHost.error : ''; color: colors.error; wrapMode: Text.Wrap; textFormat: Text.PlainText }
            TextArea { Layout.fillWidth: true; visible: text.length > 0; readOnly: true; textFormat: TextEdit.PlainText; selectByMouse: true; wrapMode: TextEdit.Wrap; text: canvasRoot.appHost ? canvasRoot.appHost.result : ''; color: colors.ink; background: Rectangle { color: colors.card; radius: 8 } }
        }
    }
    Popup {
        id: applicationRemoval; objectName: 'applicationRemovalDialog'
        anchors.centerIn: parent; width: Math.min(440, parent.width - 40); padding: 20
        modal: true; focus: true
        background: Rectangle { radius: 12; color: colors.card; border.color: colors.border }
        onOpened: canvasActions.hold('application-removal', true)
        onClosed: canvasActions.hold('application-removal', false)
        contentItem: ColumnLayout {
            spacing: 14
            Text { textFormat: Text.PlainText; text: '移除应用：' + (canvasRoot.selectedApplication.title || ''); color: colors.ink; font.pixelSize: 18; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Text { text: '将停止该应用流程，并清除应用定义、授权和能力绑定。'; color: colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '取消'; onClicked: applicationRemoval.close() }
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '确认移除'; glyph: 'close'; primary: true; objectName: 'confirmApplicationRemoval'; onClicked: { canvasRoot.appHost.remove(); applicationRemoval.close() } }
            }
        }
    }
    Popup {
        id: applicationImport; objectName: 'applicationImportDialog'
        anchors.centerIn: parent; width: Math.min(640, parent.width - 40); height: Math.min(520, parent.height - 40)
        modal: true; focus: true; padding: 20
        background: Rectangle { radius: 12; color: colors.card; border.color: colors.border }
        onOpened: canvasActions.hold('application-import', true)
        onClosed: canvasActions.hold('application-import', false)
        ColumnLayout {
            anchors.fill: parent; spacing: 12
            Text { text: '开发者 · 导入应用定义 JSON'; color: colors.ink; font.pixelSize: 18 }
            Text { text: '粘贴本机应用定义。导入后，执行能力仍需单独授权。'; color: colors.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            ScrollView { Layout.fillWidth: true; Layout.fillHeight: true
                TextArea { id: applicationJson; objectName: 'applicationJsonInput'; color: colors.ink; selectByMouse: true; wrapMode: TextEdit.Wrap; placeholderText: 'Application schemaVersion: 1'; background: Rectangle { color: colors.panel; radius: 6 } }
            }
            Text { textFormat: Text.PlainText; text: canvasRoot.appHost ? canvasRoot.appHost.error : ''; color: colors.error; wrapMode: Text.Wrap; Layout.fillWidth: true }
            RowLayout {
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '取消'; onClicked: applicationImport.close() }
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '导入'; primary: true; objectName: 'confirmApplicationImport'; onClicked: { canvasRoot.appHost.importJson(applicationJson.text); if (!canvasRoot.appHost.error) { applicationJson.text = ''; applicationImport.close() } } }
            }
        }
    }
    Text { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 12; textFormat: Text.PlainText; text: canvasRoot.appHost ? (canvasRoot.appHost.feedback || canvasRoot.appHost.error || canvasRoot.lastError) : canvasRoot.lastError; color: canvasRoot.appHost && canvasRoot.appHost.feedback ? colors.muted : colors.error; width: parent.width - 24; wrapMode: Text.Wrap }
    Popup {
        id: viewPicker
        objectName: 'componentViewPicker'
        x: Math.max(12, (parent.width - width) / 2); y: Math.min(82, Math.max(12, (parent.height - height) / 2))
        width: Math.min(420, parent.width - 32); height: Math.min(360, parent.height - 32)
        padding: 16
        modal: true; focus: true; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 14; color: colors.card; border.color: colors.border }
        Overlay.modal: Rectangle { color: "#280f172a" }
        onOpened: canvasActions.hold('view-picker', true)
        onClosed: canvasActions.hold('view-picker', false)
        ColumnLayout {
            anchors.fill: parent; spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text { text: '添加到工作台'; font.pixelSize: 18; font.weight: Font.DemiBold; color: colors.ink; Layout.fillWidth: true }
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: "close"; hint: "关闭选择器"; onClicked: viewPicker.close() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: colors.border }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                model: {
                    var groups = []
                    var views = typeof canvasActions === 'undefined' ? [] : JSON.parse(canvasActions.viewsJson)
                    views.forEach(function(view, index) {
                        var group = groups.find(function(g) { return g.target === view.target })
                        if (!group) { group = {target: view.target, name: view.componentName, views: []}; groups.push(group) }
                        group.views.push({title: view.title, index: index})
                    })
                    return groups
                }
                ScrollBar.vertical: WorkspaceScrollBar { }
                delegate: Column {
                    id: componentChoice
                    required property var modelData
                    width: ListView.view.width
                    property bool expanded: false
                    ItemDelegate {
                        id: choice
                        objectName: "componentViewChoice"
                        width: parent.width; height: 56; hoverEnabled: true
                        Accessible.name: componentChoice.modelData.name
                        background: Rectangle { radius: 8; color: choice.down ? colors.pressed : choice.hovered || choice.visualFocus ? colors.hover : "transparent"; border.width: choice.visualFocus ? 1 : 0; border.color: colors.focus }
                        contentItem: RowLayout {
                            spacing: 12
                            Rectangle { width: 36; height: 36; radius: 10; color: colors.softAccent; CanvasIcon { anchors.centerIn: parent; kind: "board"; ink: colors.accent } }
                            Text { Layout.fillWidth: true; elide: Text.ElideRight; text: componentChoice.modelData.name; textFormat: Text.PlainText; font.pixelSize: 14; font.weight: Font.Medium; color: colors.ink }
                            CanvasIcon { kind: componentChoice.modelData.views.length === 1 ? "plus" : "down"; ink: choice.hovered ? colors.ink : colors.muted }
                        }
                        onClicked: {
                            if (componentChoice.modelData.views.length === 1) { canvasActions.mountSelected(componentChoice.modelData.views[0].index); viewPicker.close() }
                            else componentChoice.expanded = !componentChoice.expanded
                        }
                    }
                    Repeater {
                        model: componentChoice.expanded ? componentChoice.modelData.views : []
                        ItemDelegate {
                            id: subChoice; required property var modelData
                            width: componentChoice.width; height: 38; leftPadding: 56
                            contentItem: Text { text: subChoice.modelData.title; color: colors.ink; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter }
                            background: Rectangle { radius: 8; color: subChoice.hovered ? colors.hover : "transparent" }
                            onClicked: { canvasActions.mountSelected(subChoice.modelData.index); viewPicker.close() }
                        }
                    }
                }
                Label { anchors.centerIn: parent; visible: parent.count === 0; text: '暂无可添加的组件'; font.pixelSize: 13; color: colors.muted }
            }
        }
    }
    Popup {
        id: themePicker
        objectName: 'canvasThemePopup'
        x: Math.max(8, parent.width - width - 12); y: 48; width: 164; padding: 8
        modal: false; focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle { radius: 12; color: colors.card; border.color: colors.border }
        onOpened: canvasActions.hold('theme-picker', true)
        onClosed: canvasActions.hold('theme-picker', false)
        contentItem: Column {
            spacing: 3
            Repeater {
                model: [{ key: 'light', name: '雾白', swatch: '#f3f5f8' }, { key: 'dark', name: '石墨', swatch: '#242830' }, { key: 'warm', name: '暖砂', swatch: '#f3eee6' }]
                ItemDelegate {
                    id: themeChoice
                    width: 148; height: 36; hoverEnabled: true
                    Accessible.name: modelData.name
                    Accessible.role: Accessible.RadioButton
                    Accessible.checkable: true
                    Accessible.checked: canvasActions.theme === modelData.key
                    background: Rectangle { radius: 7; color: themeChoice.hovered || canvasActions.theme === modelData.key ? colors.hover : 'transparent'; border.width: themeChoice.visualFocus ? 1 : 0; border.color: colors.focus }
                    contentItem: Row {
                        spacing: 10
                        Rectangle { width: 20; height: 20; radius: 6; anchors.verticalCenter: parent.verticalCenter; color: modelData.swatch; border.color: colors.border }
                        Text { text: modelData.name; color: colors.ink; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                        Text { text: canvasActions.theme === modelData.key ? '✓' : ''; color: colors.ink; font.pixelSize: 13; anchors.verticalCenter: parent.verticalCenter }
                    }
                    onClicked: { canvasActions.setTheme(modelData.key); themePicker.close() }
                }
            }
        }
    }
    Component {
        id: viewCardFactory
        Rectangle {
            id: viewCard
            objectName: "canvasViewCard"
            property string mountId: ''
            property string caption: ''
            property bool collapsed: false
            property real expandedHeight: 220
            property string failure: ''
            width: 380; height: collapsed ? 44 : expandedHeight
            radius: 12; color: colors.card; border.width: 1; border.color: cardDrag.active ? colors.focus : colors.border; clip: true
            function saveLayout() { canvasActions.layout(mountId, x, y, width, expandedHeight, collapsed) }
            Rectangle {
                id: titleBar
                objectName: "canvasViewHeader"
                x: 1; y: 0; width: parent.width - 2; height: 44; color: colors.card; radius: 12
                HoverHandler { id: headerHover; cursorShape: cardDrag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor }
                CanvasIcon { x: 11; anchors.verticalCenter: parent.verticalCenter; kind: 'grip'; ink: headerHover.hovered ? colors.ink : colors.scrollThumb }
                Rectangle { x: 16; y: 43; width: parent.width - 32; height: 1; color: colors.border; visible: !viewCard.collapsed }
                Text { objectName: 'canvasViewCaption'; x: 37; anchors.verticalCenter: parent.verticalCenter; text: caption; textFormat: Text.PlainText; elide: Text.ElideRight; width: parent.width - 120; color: colors.ink; font.pixelSize: 14; font.weight: Font.DemiBold }
                DragHandler {
                    id: cardDrag; target: viewCard
                    xAxis.minimum: Math.min(0, viewCard.x); xAxis.maximum: Math.max(0, viewport.contentWidth + viewport.originX - viewCard.width)
                    yAxis.minimum: Math.min(0, viewCard.y); yAxis.maximum: Math.max(0, viewport.contentHeight + viewport.originY - 44)
                    onActiveChanged: { canvasActions.hold('move-' + mountId, active); if (!active) viewCard.saveLayout() }
                }
                Row {
                    anchors.right: parent.right; anchors.rightMargin: 5; anchors.verticalCenter: parent.verticalCenter; spacing: 2
                    CanvasButton { canvasPalette: canvasRoot.paletteForControls; objectName: 'canvasCollapseView'; glyph: collapsed ? 'down' : 'up'; hint: collapsed ? '展开视图' : '折叠视图'; onClicked: { collapsed = !collapsed; viewCard.saveLayout() } }
                    CanvasButton { canvasPalette: canvasRoot.paletteForControls; objectName: 'canvasUnmountView'; glyph: 'close'; hint: '移除视图'; onClicked: canvasActions.unmount(mountId) }
                }
            }
            Item {
                id: content
                objectName: 'componentViewContent'
                readonly property var polarisTheme: ({background: colors.panel, surface: colors.card, surfaceRaised: colors.theme === 'dark' ? '#27282e' : colors.hover, border: colors.border, text: colors.ink, muted: colors.muted, accent: colors.accent})
                x: 1; y: 44; width: parent.width - 2; height: Math.max(0, parent.height - 45)
                visible: !collapsed; clip: true
                Component.onCompleted: Qt.callLater(function() { canvasActions.attach(mountId, content) })
                Text { anchors.centerIn: parent; width: parent.width - 24; wrapMode: Text.Wrap; text: failure; color: colors.error; visible: failure.length > 0 }
            }
            Rectangle {
                visible: !collapsed; width: 18; height: 18; anchors.right: parent.right; anchors.bottom: parent.bottom
                color: 'transparent'
                HoverHandler { id: resizeHover; cursorShape: Qt.SizeFDiagCursor }
                CanvasIcon { anchors.fill: parent; kind: 'resize'; ink: resizeHover.hovered ? colors.ink : colors.muted }
                DragHandler {
                    id: resizeDrag; target: null
                    property real initialWidth: 0
                    property real initialHeight: 0
                    onActiveChanged: {
                        canvasActions.hold('resize-' + mountId, active)
                        if (active) { initialWidth = viewCard.width; initialHeight = viewCard.expandedHeight }
                        else viewCard.saveLayout()
                    }
                    onTranslationChanged: {
                        if (active) {
                            viewCard.width = Math.max(240, initialWidth + translation.x)
                            viewCard.expandedHeight = Math.max(130, initialHeight + translation.y)
                        }
                    }
                }
            }
        }
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
    Connections {
        target: typeof canvasActions === 'undefined' ? null : canvasActions
        function onAdded(record) {
            var card = viewCardFactory.createObject(surface, {
                mountId: record.mountId, caption: record.title,
                x: record.layout.x, y: record.layout.y,
                width: record.layout.width, expandedHeight: record.layout.height,
                collapsed: record.layout.collapsed
            })
            var next = Object.assign({}, canvasRoot.viewCards)
            next[record.mountId] = card
            canvasRoot.viewCards = next
            Qt.callLater(function() { if (canvasRoot.viewCards[record.mountId] === card) viewport.reveal(card) })
        }
        function onArranged(mountId, layout) {
            var card = canvasRoot.viewCards[mountId]
            if (card) {
                card.x = layout.x; card.y = layout.y; card.width = layout.width; card.expandedHeight = layout.height; card.collapsed = layout.collapsed
                Qt.callLater(function() { if (canvasRoot.viewCards[mountId] === card) viewport.reveal(card) })
            }
        }
        function onRemoved(mountId) {
            var card = canvasRoot.viewCards[mountId]
            if (card) card.destroy()
            var next = Object.assign({}, canvasRoot.viewCards)
            delete next[mountId]
            canvasRoot.viewCards = next
        }
        function onReset() {
            for (var identity in canvasRoot.viewCards) canvasRoot.viewCards[identity].destroy()
            canvasRoot.viewCards = ({})
        }
        function onFailed(mountId, message) {
            if (canvasRoot.viewCards[mountId]) canvasRoot.viewCards[mountId].failure = message
            else canvasRoot.lastError = message
        }
    }
}
