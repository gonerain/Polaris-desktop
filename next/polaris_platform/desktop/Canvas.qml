import QtQuick
import QtQuick as Quick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: canvasRoot
    objectName: "canvasSurface"
    color: 'transparent'
    CanvasPalette { id: colors; theme: typeof canvasActions === 'undefined' ? 'light' : canvasActions.theme }
    Rectangle {
        anchors.fill: parent; anchors.margins: 4
        radius: 18; color: colors.panel; border.color: colors.border; border.width: 1
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
    CanvasWindowHandle { objectName: 'canvasWindowMove'; x: 10; y: 8; width: Math.max(0, parent.width - 178); height: 40 }
    Item {
        id: toolbar
        x: 12; y: 10; width: parent.width - 24; height: 34; z: 10
        Row {
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 5
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: 'palette'; hint: '配色'; objectName: 'canvasThemePicker'; onClicked: themePicker.open() }
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; text: '添加组件'; glyph: "plus"; objectName: 'chooseComponentView'; onClicked: canvasRoot.chooseView() }
            CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: "down"; hint: "收起画布"; objectName: 'dismissCanvas'; onClicked: canvasActions.dismiss() }
        }
    }
    Item { id: surface; anchors.fill: parent; anchors.topMargin: 56; anchors.leftMargin: 12; anchors.rightMargin: 12; anchors.bottomMargin: 12; clip: true }
    Column {
        anchors.centerIn: surface; spacing: 12; visible: canvasRoot.empty
        Text { anchors.horizontalCenter: parent.horizontalCenter; text: '暂无组件'; color: colors.muted; font.pixelSize: 14 }
        CanvasButton { canvasPalette: canvasRoot.paletteForControls; anchors.horizontalCenter: parent.horizontalCenter; text: '添加组件'; onClicked: canvasRoot.chooseView() }
    }
    Flow {
        x: 24; y: 64; width: parent.width - 48; spacing: 16
        Repeater {
            model: JSON.parse(cardsJson)
            Rectangle {
                width: 330; height: 160; radius: 10; clip: true; color: colors.card; border.color: colors.border
                Column { anchors.fill: parent; anchors.margins: 20; spacing: 12
                    Text { objectName: 'cardTitle'; textFormat: Text.PlainText; text: modelData.title; font.pixelSize: 15; font.weight: Font.DemiBold; color: colors.ink }
                    Text { objectName: 'cardBody'; textFormat: Text.PlainText; text: modelData.text; wrapMode: Text.Wrap; width: parent.width; color: colors.muted; font.pixelSize: 14 }
                }
            }
        }
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
        Overlay.modal: Rectangle { color: "#18000000" }
        onOpened: canvasActions.hold('view-picker', true)
        onClosed: canvasActions.hold('view-picker', false)
        ColumnLayout {
            anchors.fill: parent; spacing: 12
            RowLayout {
                Layout.fillWidth: true
                Text { text: '添加组件'; font.pixelSize: 16; font.weight: Font.DemiBold; color: colors.ink; Layout.fillWidth: true }
                CanvasButton { canvasPalette: canvasRoot.paletteForControls; glyph: "close"; hint: "关闭选择器"; onClicked: viewPicker.close() }
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: colors.border }
            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
                model: typeof canvasActions === 'undefined' ? [] : JSON.parse(canvasActions.viewsJson)
                ScrollBar.vertical: ScrollBar { }
                delegate: ItemDelegate {
                    id: choice
                    objectName: "componentViewChoice"
                    width: ListView.view.width; height: 64
                    hoverEnabled: true
                    Accessible.name: modelData.componentName + "，" + modelData.title
                    background: Rectangle { radius: 8; color: choice.down ? colors.pressed : choice.hovered || choice.visualFocus ? colors.hover : "transparent"; border.width: choice.visualFocus ? 1 : 0; border.color: colors.focus }
                    contentItem: RowLayout {
                        spacing: 12
                        Rectangle { width: 36; height: 36; radius: 9; color: colors.hover; CanvasIcon { anchors.centerIn: parent; kind: "board"; ink: colors.muted } }
                        Column {
                            Layout.fillWidth: true; spacing: 4
                            Text { width: parent.width; elide: Text.ElideRight; text: modelData.componentName; textFormat: Text.PlainText; font.pixelSize: 14; font.weight: Font.Medium; color: colors.ink }
                            Text { visible: modelData.title !== modelData.componentName; width: parent.width; elide: Text.ElideRight; text: modelData.title; textFormat: Text.PlainText; font.pixelSize: 12; color: colors.muted }
                        }
                        CanvasIcon { kind: "plus"; ink: choice.hovered ? colors.ink : colors.muted }
                    }
                    onClicked: { canvasActions.mountSelected(index); viewPicker.close() }
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
                model: [{ key: 'light', name: '雾白', swatch: '#f5f6f7' }, { key: 'dark', name: '石墨', swatch: '#25272c' }, { key: 'warm', name: '暖砂', swatch: '#f1e9dc' }]
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
            width: 370; height: collapsed ? 42 : expandedHeight
            radius: 12; color: colors.card; border.color: cardDrag.active ? colors.focus : colors.border; clip: true
            function saveLayout() { canvasActions.layout(mountId, x, y, width, expandedHeight, collapsed) }
            Rectangle {
                id: titleBar
                objectName: "canvasViewHeader"
                x: 1; y: 1; width: parent.width - 2; height: 40; color: colors.card; radius: 9
                HoverHandler { id: headerHover; cursorShape: cardDrag.active ? Qt.ClosedHandCursor : Qt.OpenHandCursor }
                CanvasIcon { x: 7; anchors.verticalCenter: parent.verticalCenter; kind: 'grip'; ink: headerHover.hovered ? colors.ink : colors.muted }
                Rectangle { x: 10; y: 39; width: parent.width - 20; height: 1; color: colors.border; visible: !viewCard.collapsed }
                Text { x: 31; anchors.verticalCenter: parent.verticalCenter; text: caption; textFormat: Text.PlainText; elide: Text.ElideRight; width: parent.width - 110; color: colors.ink; font.pixelSize: 13; font.weight: Font.Medium }
                DragHandler {
                    id: cardDrag; target: viewCard
                    xAxis.minimum: 0; xAxis.maximum: Math.max(0, surface.width - viewCard.width)
                    yAxis.minimum: 0; yAxis.maximum: Math.max(0, surface.height - 42)
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
                x: 1; y: 42; width: parent.width - 2; height: Math.max(0, parent.height - 43)
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
                x: record.layout.x, y: Math.max(0, record.layout.y),
                width: record.layout.width, expandedHeight: record.layout.height,
                collapsed: record.layout.collapsed
            })
            var next = Object.assign({}, canvasRoot.viewCards)
            next[record.mountId] = card
            canvasRoot.viewCards = next
        }
        function onArranged(mountId, layout) {
            var card = canvasRoot.viewCards[mountId]
            if (card) { card.x = layout.x; card.y = layout.y; card.width = layout.width; card.expandedHeight = layout.height; card.collapsed = layout.collapsed }
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
