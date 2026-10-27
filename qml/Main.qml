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
    minimumWidth: compactSize
    minimumHeight: compactSize
    visible: true
    title: "Polaris"
    color: "transparent"
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    readonly property int compactSize: 180
    readonly property int bubbleHeight: 58
    property bool bubbleVisible: false
    property string bubbleText: ""
    readonly property int expandedMinimumWidth: 528
    readonly property int expandedMinimumHeight: 300
    property bool compact: true
    property bool moving: false
    property bool applyingState: false
    property bool collapsing: false
    property bool allowQuit: false
    property real expandedWidth: 528
    property real expandedHeight: 300

    onClosing: function(close) {
        if (!window.allowQuit)
            close.accepted = false
    }

    function requestQuit() {
        window.allowQuit = true
        window.close()
    }

    onWidthChanged: if (!compact && !applyingState) expandedWidth = width
    onHeightChanged: if (!compact && !applyingState) expandedHeight = height

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
        minimumWidth = expandedMinimumWidth
        minimumHeight = expandedMinimumHeight
        width = Math.max(expandedWidth, expandedMinimumWidth)
        height = Math.max(expandedHeight, expandedMinimumHeight)
        applyingState = false
    }

    function collapse() {
        if (compact || collapsing)
            return
        autoCollapse.stop()
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
        minimumWidth = compactSize
        minimumHeight = compactSize
        width = compactSize
        height = compactSize
        applyingState = false
    }

    function cancelCollapse() {
        if (!collapsing)
            return
        collapseTimer.stop()
        collapsing = false
    }

    function showBubble(message) {
        if (!compact)
            return
        bubbleText = message
        if (!bubbleVisible) {
            bubbleVisible = true
            y -= bubbleHeight
            height = compactSize + bubbleHeight
            minimumHeight = height
        }
        bubbleTimer.restart()
    }

    function hideBubble() {
        bubbleTimer.stop()
        if (!bubbleVisible)
            return
        bubbleVisible = false
        y += bubbleHeight
        minimumHeight = compactSize
        height = compactSize
    }

    InteractionCoordinator {
        id: interactionCoordinator
        objectName: "interactionCoordinator"
    }

    Connections {
        target: interactionCoordinator
        function onNotification(kind, entryId, text) {
            if (kind === "task.upcoming")
                window.showBubble(text)
        }
    }

    Timer {
        id: bubbleTimer
        interval: 6500
        onTriggered: window.hideBubble()
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

        Menu {
            id: contextMenu
            objectName: "quitMenu"
            parent: root
            padding: 4

            background: Rectangle {
                color: Theme.surface
                radius: 8
                border.width: 1
                border.color: Theme.border
            }

            MenuItem {
                id: quitItem
                objectName: "quitMenuItem"
                text: qsTr("退出")
                implicitWidth: 112
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
                } else if (!window.compact && !window.moving && !window.collapsing) {
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
            enabled: !window.compact && !window.collapsing
            opacity: (window.compact || window.collapsing) ? 0 : 1
            scale: (window.compact || window.collapsing) ? 0.985 : 1
            transformOrigin: Item.Center

            Behavior on opacity {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Behavior on scale {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            ComponentBoard {
                id: board
                objectName: "componentBoard"
                anchors.fill: parent
                panelSize: Qt.size(260, 260)
                panelCount: 2
                gap: 8
            }

            WindowResizeHandles {
                objectName: "resizeHandles"
                z: 10
                anchors.fill: parent
                targetWindow: window
                enabled: !window.collapsing
            }
        }

        Rectangle {
            id: compactBox
            objectName: "compactBox"
            z: 2
            width: window.compactSize
            height: window.compactSize
            anchors.top: parent.top
            anchors.topMargin: window.bubbleVisible ? window.bubbleHeight : 0
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
                objectName: "petMascot"
                anchors.fill: parent
            }

            Rectangle {
                objectName: "petSpeechBubble"
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.top
                anchors.bottomMargin: 6
                height: 46
                radius: 12
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                visible: window.bubbleVisible && window.compact

                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 12
                    color: Theme.ink
                    text: window.bubbleText
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
    }
}
