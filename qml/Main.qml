pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import Polaris 1.0
import "components"
import "components/Theme.js" as Theme

Window {
    id: window

    width: compactSize
    height: compactSize
    minimumWidth: compact ? Math.min(compactSize, availableGeometry.width || compactSize)
                          : expandedMinimumWidth
    minimumHeight: compact ? Math.min(compactSize + (bubbleVisible ? bubbleHeight : 0),
                                      availableGeometry.height || compactSize + bubbleHeight)
                           : expandedMinimumHeight
    maximumWidth: availableGeometry.width > 0 ? availableGeometry.width : 16777215
    maximumHeight: availableGeometry.height > 0 ? availableGeometry.height : 16777215
    visible: true
    title: "Polaris"
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    required property var agentHub
    required property var componentApi
    property string selectedPage: "calendar"
    property string pendingPage: ""
    readonly property int navigationHeight: 32
    readonly property int compactSize: 180
    readonly property int bubbleHeight: 84
    property bool bubbleBelow: false
    property bool bubbleVisible: false
    property string bubbleText: ""
    // Updated from QScreen.availableGeometry(), including taskbar offsets.
    property rect availableGeometry: Qt.rect(0, 0, 0, 0)
    readonly property int expandedMinimumWidth: Math.min(528, availableGeometry.width || 528)
    readonly property int expandedMinimumHeight: Math.min(300 + navigationHeight, availableGeometry.height || 300 + navigationHeight)
    // Supplied before creation by the host, based on the actual Qt platform.
    property bool windowPositioningSupported: true
    property bool nativeNotificationsAvailable: false
    property string inlineReminderText: ""
    property double speechExpiresAt: 0
    property bool compact: true
    property bool moving: false
    property bool applyingState: false
    property bool collapsing: false
    property int editorPopupCount: 0
    onEditorPopupCountChanged: {
        if (editorPopupCount > 0) {
            autoCollapse.stop()
            cancelCollapse()
        } else if (!compact && !windowHover.hovered && !focusPresenter.busy) {
            autoCollapse.restart()
        }
    }
    property bool reducedPetMotion: false
    property real lastPetX: 0
    onXChanged: {
        if (compact && moving) petMascot.lean(x - lastPetX)
        lastPetX = x
    }
    property bool allowQuit: false
    property var calendarStore: null
    property real expandedWidth: 528
    property real expandedHeight: 300 + navigationHeight

    onClosing: function(close) {
        // Even a blocked close request must commit the currently edited field.
        root.forceActiveFocus()
        if (!window.allowQuit)
            close.accepted = false
    }

    function requestQuit() {
        // Commit active inline edits before stopping the event loop.
        root.forceActiveFocus()
        if (calendarStore && calendarStore.storageError && !calendarStore.retrySave()) {
            autoCollapse.stop()
            unsavedQuitDialog.open()
            return
        }
        finishQuit()
    }

    function finishQuit() {
        window.allowQuit = true
        window.close()
        // Tool windows and a live tray must not leave an invisible process behind.
        Qt.quit()
    }

    onWidthChanged: if (!compact && !applyingState && !focusPresenter.busy) expandedWidth = width
    onHeightChanged: if (!compact && !applyingState && !focusPresenter.busy) expandedHeight = height

    function showPage(page) {
        if (page !== "calendar" && page !== "agents") return false
        if (focusPresenter.busy) {
            if (focusPresenter.transitioning) return false
            if (page !== selectedPage) { pendingPage = page; focusPresenter.close() }
            return true
        }
        root.forceActiveFocus()
        selectedPage = page
        if (page === "agents") agentHub.markRead()
        expand()
        return true
    }

    function expand() {
        if (!compact) {
            if (collapsing)
                cancelCollapse()
            return
        }
        hideBubble()
        autoCollapse.stop()
        collapseTimer.stop()
        collapsing = false
        applyingState = true
        compact = false
        width = Math.max(expandedWidth, expandedMinimumWidth)
        height = Math.max(expandedHeight, expandedMinimumHeight)
        applyingState = false
    }

    function collapse() {
        if (compact || collapsing || focusPresenter.busy || unsavedQuitDialog.visible || editorPopupCount > 0)
            return
        autoCollapse.stop()
        root.forceActiveFocus()
        collapsing = true
        collapseTimer.restart()
    }

    function finishCollapse() {
        if (!collapsing)
            return
        applyingState = true
        expandedWidth = width
        expandedHeight = height
        compact = true
        collapsing = false
        width = compactSize
        height = compactSize
        applyingState = false
        if (inlineReminderTimer.running && speechExpiresAt > Date.now()) {
            inlineReminderTimer.stop()
            showBubble(inlineReminderText, Math.max(1, speechExpiresAt - Date.now()))
        }
    }

    function cancelCollapse() {
        if (!collapsing)
            return
        collapseTimer.stop()
        collapsing = false
    }

    function showSpeech(message, durationMs) {
        speechExpiresAt = Date.now() + durationMs
        if (compact) {
            showBubble(message, durationMs)
            return "bubble"
        }
        inlineReminderText = message
        inlineReminderTimer.interval = durationMs
        inlineReminderTimer.restart()
        return "inline"
    }

    function showBubble(message, durationMs) {
        if (!compact)
            return
        bubbleText = message
        if (!bubbleVisible) {
            applyingState = true
            // At the top edge, put the bubble below instead of moving the pet.
            // Wayland cannot reposition the window, so keep its local pet anchor.
            bubbleBelow = !windowPositioningSupported || y - availableGeometry.y < bubbleHeight
            bubbleVisible = true
            if (windowPositioningSupported && !bubbleBelow) y -= bubbleHeight
            height = compactSize + bubbleHeight
            applyingState = false
        }
        bubbleTimer.interval = durationMs === undefined ? 6500 : durationMs
        bubbleTimer.restart()
    }

    function hideBubble() {
        bubbleTimer.stop()
        if (!bubbleVisible)
            return
        applyingState = true
        bubbleVisible = false
        if (windowPositioningSupported && !bubbleBelow) y += bubbleHeight
        height = compactSize
        applyingState = false
    }

    InteractionCoordinator {
        id: interactionCoordinator
        objectName: "interactionCoordinator"
    }

    Connections {
        target: interactionCoordinator
        function onNotification(kind, entryId, text) {
            if (kind === "task.upcoming") {
                if (window.compact) window.showBubble(text)
                else if (!window.nativeNotificationsAvailable) {
                    window.showSpeech(text, 6500)
                }
            } else if (kind === "task.completed")
                petMascot.celebrate()
        }
    }

    Connections {
        target: window.agentHub
        function onCompleted(message) {
            // A lifecycle event, not a model tool call. Never steals focus or changes pages.
            window.showSpeech(message, 6500)
        }
    }

    Timer {
        id: bubbleTimer
        interval: 6500
        onTriggered: window.hideBubble()
    }

    // No tray/message service is common on Linux/WSLg. This fallback never
    // takes focus or mouse input, and also works above the independent full view.
    Rectangle {
        objectName: "inlineReminder"
        z: 200
        anchors.top: parent.top
        anchors.topMargin: 10
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.max(0, Math.min(360, parent.width - 24))
        height: 68
        radius: 10
        color: Theme.primarySoft
        border.color: Theme.border
        visible: inlineReminderTimer.running && !window.compact
        Text {
            id: inlineReminderLabel
            anchors.fill: parent
            anchors.margins: 12
            text: window.inlineReminderText
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            maximumLineCount: 3
            elide: Text.ElideRight
            font.pixelSize: 12
            color: Theme.ink
        }
    }
    Timer {
        id: inlineReminderTimer
        interval: 6500
    }

    FocusPresenter {
        id: focusPresenter
        objectName: "focusPresenter"
        anchors.fill: parent
        targetWindow: window
        availableGeometry: window.availableGeometry
        onOpened: {
            autoCollapse.stop()
            window.cancelCollapse()
        }
        onClosed: {
            if (window.pendingPage) {
                const page = window.pendingPage
                window.pendingPage = ""
                window.showPage(page)
            } else if (!windowHover.hovered)
                autoCollapse.restart()
        }
        onFailed: function(reason) { console.warn("完整视图打开失败", reason) }
    }

    Item {
        id: root
        anchors.fill: parent

        TapHandler {
            acceptedButtons: Qt.RightButton

            onSingleTapped: function(eventPoint, button) {
                contextMenu.popup(eventPoint.position)
            }
        }

        Dialog {
            id: unsavedQuitDialog
            objectName: "unsavedQuitDialog"
            anchors.centerIn: parent
            popupType: Popup.Window
            modal: true
            width: 360
            title: qsTr("日程尚未保存")
            standardButtons: Dialog.Discard | Dialog.Cancel
            onOpened: {
                standardButton(Dialog.Discard).text = qsTr("仍然退出")
                standardButton(Dialog.Cancel).text = qsTr("返回")
            }
            Label {
                width: parent.width
                text: qsTr("保存失败，退出会丢失尚未写入的修改。建议返回后重试保存或备份数据。")
                wrapMode: Text.Wrap
            }
            onDiscarded: window.finishQuit()
        }

        Menu {
            id: contextMenu
            objectName: "quitMenu"
            parent: root
            // A window popup cannot be clipped by the 180px transparent pet.
            popupType: Popup.Window
            // Custom backgrounds have no implicit size: explicitly size the menu,
            // otherwise the list can collapse to padding-only (8px) on Windows.
            implicitWidth: 152
            padding: 4
            onOpened: autoCollapse.stop()
            onClosed: {
                if (!window.compact && !windowHover.hovered && !focusPresenter.busy)
                    autoCollapse.restart()
            }

            background: Rectangle {
                color: Theme.surface
                radius: 8
                border.width: 1
                border.color: Theme.border
            }

            MenuItem {
                objectName: "agentPageMenuItem"
                text: qsTr("Agent 会话") + (window.agentHub && window.agentHub.unreadCount ? " · " + window.agentHub.unreadCount : "")
                font.pixelSize: 12
                enabled: !focusPresenter.transitioning
                onTriggered: window.showPage("agents")
            }
            MenuItem {
                text: qsTr("打开日程")
                font.pixelSize: 12
                enabled: !focusPresenter.transitioning
                onTriggered: window.showPage("calendar")
            }
            MenuSeparator {}
            MenuItem {
                objectName: "petGreetMenuItem"
                text: qsTr("打个招呼")
                font.pixelSize: 12
                enabled: window.compact
                onTriggered: {
                    window.showSpeech(qsTr("Hi！👋"), 6500)
                    if (!window.reducedPetMotion) petMascot.playWave(true)
                }
            }
            MenuItem {
                objectName: "petActivityMenuItem"
                text: qsTr("换个小动作")
                font.pixelSize: 12
                enabled: window.compact && !window.reducedPetMotion
                onTriggered: petMascot.playActivity(true)
            }
            MenuItem {
                objectName: "petRestMenuItem"
                text: qsTr("休息一下")
                font.pixelSize: 12
                enabled: window.compact && !window.reducedPetMotion
                onTriggered: petMascot.rest(true)
            }
            MenuItem {
                objectName: "petMotionMenuItem"
                text: qsTr("减少动态")
                font.pixelSize: 12
                checkable: true
                checked: window.reducedPetMotion
                onTriggered: window.reducedPetMotion = checked
            }
            MenuItem {
                text: qsTr("素材协议 · 非商用")
                font.pixelSize: 12
                onTriggered: Qt.openUrlExternally("https://github.com/PC2005-cloud/dsh-pet/blob/86181ce1660a57ab27336630bab5b344de71b28c/README.md#%E8%AE%B8%E5%8F%AF")
            }
            MenuSeparator {}
            MenuItem {
                id: quitItem
                objectName: "quitMenuItem"
                text: qsTr("退出")
                implicitWidth: 144
                implicitHeight: 30

                contentItem: Text {
                    text: quitItem.text
                    color: Theme.danger
                    font.pixelSize: 12
                    verticalAlignment: Text.AlignVCenter
                }

                background: Rectangle {
                    radius: 6
                    color: quitItem.hovered ? "#FEF2F2" : "transparent"
                }

                onTriggered: window.requestQuit()
            }
        }

        HoverHandler {
            id: windowHover
            objectName: "windowHover"
            onHoveredChanged: {
                if (hovered) {
                    autoCollapse.stop()
                    if (window.collapsing)
                        window.cancelCollapse()
                } else if (!window.compact && !window.moving && !window.collapsing && !contextMenu.visible && window.editorPopupCount === 0) {
                    autoCollapse.restart()
                }
            }
        }

        Item {
            id: expandedContent
            objectName: "expandedContent"
            width: window.compact ? window.expandedWidth : window.width
            height: window.compact ? window.expandedHeight : window.height
            visible: !window.compact || window.collapsing
            enabled: !window.compact && !window.collapsing && !focusPresenter.busy
            opacity: (window.compact || window.collapsing) ? 0 : 1 - focusPresenter.progress
            scale: (window.compact || window.collapsing) ? 0.985 : 1
            transformOrigin: Item.Center

            Behavior on opacity {
                enabled: !focusPresenter.busy
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Behavior on scale {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Rectangle {
                width: parent.width
                height: window.navigationHeight
                radius: 8
                color: Theme.surface
                border.color: Theme.border
                DragHandler {
                    objectName: "componentNavigationDrag"
                    target: null
                    acceptedButtons: Qt.LeftButton
                    onActiveChanged: {
                        window.moving = active
                        if (active) window.startSystemMove()
                        else if (!windowHover.hovered && !window.compact) autoCollapse.restart()
                    }
                }
            }
            Row {
                height: window.navigationHeight
                spacing: 4
                enabled: !focusPresenter.busy
                Button {
                    id: calendarNavigation
                    objectName: "calendarPageButton"
                    text: qsTr("日程")
                    height: window.navigationHeight - 2
                    width: 72
                    background: Rectangle { radius: 7; color: window.selectedPage === "calendar" ? Theme.primarySoft : Theme.surface }
                    contentItem: Text {
                        text: calendarNavigation.text
                        font.pixelSize: 12
                        color: window.selectedPage === "calendar" ? Theme.primary : Theme.muted
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    font.pixelSize: 12
                    onClicked: window.showPage("calendar")
                }
                Button {
                    id: agentNavigation
                    objectName: "agentPageButton"
                    text: qsTr("Agent") + (window.agentHub && window.agentHub.unreadCount ? " · " + window.agentHub.unreadCount : "")
                    height: window.navigationHeight - 2
                    width: 100
                    background: Rectangle { radius: 7; color: window.selectedPage === "agents" ? Theme.primarySoft : Theme.surface }
                    contentItem: Text {
                        text: agentNavigation.text
                        font.pixelSize: 12
                        color: window.selectedPage === "agents" ? Theme.primary : Theme.muted
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    font.pixelSize: 12
                    onClicked: window.showPage("agents")
                }
            }

            AgentPanel {
                objectName: "agentPanel"
                x: 0
                y: window.navigationHeight
                width: parent.width
                height: parent.height - window.navigationHeight
                visible: window.selectedPage === "agents"
                hub: window.agentHub
                components: window.componentApi
            }

            ComponentBoard {
                id: board
                objectName: "componentBoard"
                width: focusPresenter.busy ? focusPresenter.savedGeometry.width : parent.width
                y: window.navigationHeight
                height: (focusPresenter.busy ? focusPresenter.savedGeometry.height : parent.height) - window.navigationHeight
                visible: window.selectedPage === "calendar"
                presenter: focusPresenter
                panelSize: Qt.size(260, 260)
                panelCount: 2
                gap: 8
            }

            WindowResizeHandles {
                objectName: "resizeHandles"
                z: 10
                anchors.fill: parent
                targetWindow: window
                enabled: !window.collapsing && !focusPresenter.busy
            }
        }

        Rectangle {
            id: compactBox
            objectName: "compactBox"
            z: 2
            width: window.compactSize
            height: window.compactSize
            anchors.top: parent.top
            anchors.topMargin: window.bubbleVisible && !window.bubbleBelow ? window.bubbleHeight : 0
            anchors.left: parent.left
            color: "transparent"
            visible: opacity > 0
            enabled: window.compact
            opacity: window.compact ? 1 : 0
            scale: window.compact ? 1 : 0.92
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("打开")

            Behavior on opacity {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Behavior on scale {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            PetMascot {
                id: petMascot
                objectName: "petMascot"
                anchors.fill: parent
                active: window.compact && window.visible
                dragging: window.compact && window.moving
                reducedMotion: window.reducedPetMotion
            }

            Rectangle {
                objectName: "petSpeechBubble"
                anchors.left: parent.left
                anchors.right: parent.right
                y: window.bubbleBelow ? parent.height + 6 : -height - 6
                height: window.bubbleHeight - 6
                radius: 12
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                visible: window.bubbleVisible && window.compact
                enabled: false

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: window.bubbleBelow ? -4 : parent.height - 6
                    width: 10
                    height: 10
                    rotation: 45
                    z: -1
                    color: Theme.surface
                    border.color: Theme.border
                }

                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 12
                    color: Theme.ink
                    text: window.bubbleText
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
            }

            TapHandler {
                objectName: "compactTapHandler"
                onTapped: window.expand()
            }

            DragHandler {
                objectName: "compactDragHandler"
                target: null
                acceptedButtons: Qt.LeftButton
                onActiveChanged: {
                    window.moving = active
                    if (active)
                        window.startSystemMove()
                }
            }
        }

        Timer {
            id: autoCollapse
            objectName: "autoCollapseTimer"
            interval: 400
            repeat: false
            onTriggered: {
                if (!windowHover.hovered && !window.moving && !window.compact && !window.collapsing)
                    window.collapse()
            }
        }

        Timer {
            id: collapseTimer
            objectName: "collapseTimer"
            interval: Theme.collapse
            repeat: false
            onTriggered: window.finishCollapse()
        }
    }

    Component {
        id: calendarFactory
        CalendarTasks {
            objectName: "calendarTasks"

            onFocusRequested: function(factory, options, properties) {
                board.presentItem(this, factory, options, properties)
            }
            onDragActiveChanged: function(active) {
                window.moving = active
                if (!active && !windowHover.hovered && !window.compact && !window.collapsing)
                    autoCollapse.restart()
            }
        }
    }

    Component.onCompleted: {
        const calendar = board.request(calendarFactory, {cells: [[0, 0], [1, 0]]})
        if (!calendar.ok)
            console.error("初始化画板失败", calendar.error)
        else
            window.calendarStore = calendar.item.taskStore
    }
}
