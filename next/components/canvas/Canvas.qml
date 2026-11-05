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
        x: 64; y: 8; width: 1; height: parent.height - 16; color: colors.border
    }
    Column {
        x: 12; y: 18; spacing: 14; z: 11
        Item { width: 40; height: 40; CanvasIcon { anchors.centerIn: parent; width: 20; height: 20; kind: 'star'; ink: colors.accent } }
        CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: 'plus'; hint: '添加组件'; onClicked: canvasRoot.chooseView() }
        CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: 'palette'; hint: '配色'; objectName: 'canvasThemePicker'; onClicked: themePicker.open() }
    }
    CanvasWindowHandle { objectName: 'canvasWindowMove'; x: 72; y: 8; width: Math.max(0, parent.width - 280); height: 48 }
    Item {
        id: toolbar
        x: 92; y: 12; width: parent.width - 112; height: 36; z: 10
        Row {
            anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter; spacing: 10
            Text { text: 'Polaris'; color: colors.ink; font.pixelSize: 18; font.weight: Font.DemiBold }
        }
        Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '整理布局'; glyph: 'board'; objectName: 'arrangeCanvas'; visible: !canvasRoot.empty; onClicked: canvasActions.arrange(viewport.width) }
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '添加组件'; glyph: "plus"; objectName: 'chooseComponentView'; onClicked: canvasRoot.chooseView() }
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: "down"; hint: "收起画布"; objectName: 'dismissCanvas'; onClicked: canvasActions.dismiss() }
        }
    }
    Text { x: 96; y: 68; text: '工作台'; color: colors.ink; font.pixelSize: 20; font.weight: Font.DemiBold }
    Rectangle { x: 92; y: 58; width: Math.max(0, parent.width - 112); height: 1; color: colors.border }
    Flickable {
        id: viewport
        objectName: 'canvasViewport'
        anchors.fill: parent; anchors.topMargin: 102; anchors.leftMargin: 84; anchors.rightMargin: 12; anchors.bottomMargin: 12
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
        anchors.centerIn: viewport; spacing: 12; visible: canvasRoot.empty
        width: Math.min(360, viewport.width - 32)
        Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 42; height: 42; radius: 12; color: colors.softAccent; CanvasIcon { anchors.centerIn: parent; kind: 'board'; ink: colors.accent; width: 22; height: 22 } }
        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: '把常用组件放到工作台'; color: colors.ink; font.pixelSize: 17; font.weight: Font.DemiBold; wrapMode: Text.Wrap }
        Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: '添加组件后，可以自由摆放、调整大小和折叠。\n布局会为你保留。'; color: colors.muted; font.pixelSize: 13; wrapMode: Text.Wrap; lineHeight: 1.35 }
        CanvasButton { canvasPalette: canvasRoot.paletteForControls; anchors.horizontalCenter: parent.horizontalCenter; text: '添加第一个组件'; primary: true; onClicked: canvasRoot.chooseView() }
    }
    Text { anchors.left: parent.left; anchors.bottom: parent.bottom; anchors.margins: 12; text: canvasRoot.lastError; color: colors.error; width: parent.width - 24; wrapMode: Text.Wrap }
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
