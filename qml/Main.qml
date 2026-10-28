pragma ComponentBehavior: Bound

import QtQuick
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
    property string pendingComponent: ""
    readonly property int compactSize: 180
    readonly property int canvasPadding: 12
    readonly property int canvasHeaderHeight: 32
    property real canvasZoom: 1
    property bool canvasSized: false
    property bool canvasMoving: false
    readonly property int bubbleHeight: 84
    property bool bubbleBelow: false
    property bool bubbleVisible: false
    property string bubbleText: ""
    // Updated from QScreen.availableGeometry(), including taskbar offsets.
    property rect availableGeometry: Qt.rect(0, 0, 0, 0)
    readonly property int expandedMinimumWidth: Math.min(528 * canvasZoom + 2 * canvasPadding, availableGeometry.width || 552)
    readonly property int expandedMinimumHeight: Math.min(672 * canvasZoom + canvasHeaderHeight + 2 * canvasPadding, availableGeometry.height || 728)
    // Supplied before creation by the host, based on the actual Qt platform.
    property bool windowPositioningSupported: true
    property bool nativeNotificationsAvailable: false
    property string inlineReminderText: ""
    property double speechExpiresAt: 0
    property bool compact: true
    property bool moving: false
    property bool applyingState: false
    property bool collapsing: false
    readonly property bool contextMenuVisible: popupLoader.item ? popupLoader.item.menuVisible : false
    readonly property bool quitConfirmationVisible: popupLoader.item ? popupLoader.item.quitVisible : false
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
    readonly property var calendarStore: calendarModel
    CalendarTaskStore {
        id: calendarModel
        objectName: "calendarTaskStore"
    }
    property real expandedWidth: 552
    property real expandedHeight: 728
    property real canvasLogicalWidth: 528
    property real canvasLogicalHeight: 672
    property int canvasTargetWidth: 552
    property int canvasTargetHeight: 728

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
            ensurePopups().confirmQuit()
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

    onWidthChanged: if (!compact && !applyingState && !focusPresenter.busy) {
        expandedWidth = width
        if (width !== canvasTargetWidth) {
            canvasLogicalWidth = Math.max(528, (width - 2 * canvasPadding) / canvasZoom)
            canvasTargetWidth = width
        }
    }
    onHeightChanged: if (!compact && !applyingState && !focusPresenter.busy) {
        expandedHeight = height
        if (height !== canvasTargetHeight) {
            canvasLogicalHeight = Math.max(672, (height - canvasHeaderHeight - 2 * canvasPadding) / canvasZoom)
            canvasTargetHeight = height
        }
    }

    function showComponent(identity) {
        if (identity !== "calendar" && identity !== "agents") return false
        if (focusPresenter.busy) {
            if (focusPresenter.transitioning) return false
            pendingComponent = identity
            focusPresenter.close()
            return true
        }
        root.forceActiveFocus()
        expand()
        if (identity === "agents") {
            Qt.callLater(function() {
                if (!window.compact && expandedContent.item && !focusPresenter.busy)
                    expandedContent.item.openAgentDetails()
            })
        }
        return true
    }

    function ensurePopups() {
        if (!popupLoader.source.toString())
            popupLoader.setSource("components/ShellPopups.qml", {shell: window, pet: petMascot, presenter: focusPresenter})
        return popupLoader.item
    }

    function pauseAutoCollapse() { autoCollapse.stop() }
    function resumeAutoCollapse() {
        if (!compact && !windowHover.hovered && !focusPresenter.busy) autoCollapse.restart()
    }

    function setWorkspaceMoving(active, nativeMove) {
        moving = active || canvasMoving
        if (active && nativeMove) startSystemMove()
        else if (!active && !windowHover.hovered && !compact) autoCollapse.restart()
    }

    function canZoomCanvas(value) {
        if (compact || moving || editorPopupCount || quitConfirmationVisible || focusPresenter.busy)
            return false
        const next = Math.round(value * 10) / 10
        if (next < 0.8 || next > 1.5) return false
        return Math.ceil(528 * next + 2 * canvasPadding) <= availableGeometry.width
            && Math.ceil(672 * next + canvasHeaderHeight + 2 * canvasPadding) <= availableGeometry.height
    }

    function zoomCanvas(value) {
        if (!canZoomCanvas(value)) return false
        const next = Math.round(value * 10) / 10
        applyingState = true
        const wantedWidth = Math.ceil(canvasLogicalWidth * next + 2 * canvasPadding)
        const wantedHeight = Math.ceil(canvasLogicalHeight * next + canvasHeaderHeight + 2 * canvasPadding)
        canvasTargetWidth = Math.min(wantedWidth, availableGeometry.width)
        canvasTargetHeight = Math.min(wantedHeight, availableGeometry.height)
        if (canvasTargetWidth < wantedWidth)
            canvasLogicalWidth = (canvasTargetWidth - 2 * canvasPadding) / next
        if (canvasTargetHeight < wantedHeight)
            canvasLogicalHeight = (canvasTargetHeight - canvasHeaderHeight - 2 * canvasPadding) / next
        canvasZoom = next
        width = canvasTargetWidth
        height = canvasTargetHeight
        expandedWidth = width
        expandedHeight = height
        applyingState = false
        return true
    }

    function expand() {
        if (!canvasSized) {
            const fit = Math.min(1, (availableGeometry.width - 2 * canvasPadding) / 528,
                                    (availableGeometry.height - canvasHeaderHeight - 2 * canvasPadding) / 672)
            canvasZoom = Math.max(0.8, Math.floor(fit * 10) / 10)
            expandedWidth = Math.ceil(528 * canvasZoom + 2 * canvasPadding)
            expandedHeight = Math.ceil(672 * canvasZoom + canvasHeaderHeight + 2 * canvasPadding)
            canvasSized = true
        }
        if (!expandedContent.source.toString()) {
            expandedContent.setSource("components/Workspace.qml", {
                shell: window, presenter: focusPresenter, taskStore: calendarStore,
                agentHub: agentHub, componentApi: componentApi
            })
        }
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
        canvasTargetWidth = Math.ceil(Math.max(expandedWidth, expandedMinimumWidth))
        canvasTargetHeight = Math.ceil(Math.max(expandedHeight, expandedMinimumHeight))
        width = canvasTargetWidth
        height = canvasTargetHeight
        applyingState = false
    }

    function collapse() {
        if (compact || collapsing || focusPresenter.busy || quitConfirmationVisible || editorPopupCount > 0)
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
            if (window.pendingComponent) {
                const identity = window.pendingComponent
                window.pendingComponent = ""
                window.showComponent(identity)
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
                window.ensurePopups().popup(eventPoint.position)
            }
        }

        Loader {
            id: popupLoader
            anchors.fill: parent
        }

        HoverHandler {
            id: windowHover
            objectName: "windowHover"
            onHoveredChanged: {
                if (hovered) {
                    autoCollapse.stop()
                    if (window.collapsing)
                        window.cancelCollapse()
                } else if (!window.compact && !window.moving && !window.collapsing && !window.contextMenuVisible && window.editorPopupCount === 0) {
                    autoCollapse.restart()
                }
            }
        }

        Loader {
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

}
