import QtQuick
import "components"
import "components/Theme.js" as Theme

Window {
    id: window

    width: compactSize
    height: compactSize
    minimumWidth: compactSize
    minimumHeight: compactSize
    visible: true
    title: qsTr("悬浮日程")
    color: Theme.background
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    readonly property int compactSize: 64
    readonly property int expandedMinimumWidth: 528
    readonly property int expandedMinimumHeight: 300
    property bool compact: true
    property bool moving: false
    property bool applyingState: false
    property bool collapsing: false
    property real expandedWidth: 528
    property real expandedHeight: 300

    onWidthChanged: if (!compact && !applyingState) expandedWidth = width
    onHeightChanged: if (!compact && !applyingState) expandedHeight = height

    function expand() {
        if (!compact) {
            if (collapsing)
                cancelCollapse()
            return
        }
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

    Item {
        id: root
        anchors.fill: parent

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

            Rectangle {
                id: titleBar
                objectName: "titleBar"
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 44
                color: Theme.surface

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: Theme.border
                }

                Rectangle {
                    x: 14
                    y: 14
                    width: 3
                    height: 16
                    radius: 1.5
                    color: Theme.primary
                }

                Item {
                    objectName: "titleDragArea"
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: windowControls.left

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 24
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: window.title
                        color: Theme.ink
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }

                    DragHandler {
                        objectName: "windowMoveHandler"
                        target: null
                        acceptedButtons: Qt.LeftButton
                        onActiveChanged: {
                            window.moving = active
                            if (active) {
                                window.startSystemMove()
                            } else if (!windowHover.hovered && !window.compact && !window.collapsing) {
                                autoCollapse.restart()
                            }
                        }
                    }
                }

                Row {
                    id: windowControls
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 3

                    WindowButton {
                        objectName: "minimizeButton"
                        onClicked: window.showMinimized()
                    }

                    WindowButton {
                        objectName: "closeButton"
                        isCloseButton: true
                        onClicked: window.close()
                    }
                }
            }

            ComponentBoard {
                id: board
                objectName: "componentBoard"
                anchors.top: titleBar.bottom
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
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
            anchors.left: parent.left
            color: "transparent"
            visible: opacity > 0
            enabled: window.compact
            opacity: window.compact ? 1 : 0
            scale: window.compact ? 1 : 0.92
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("打开日程")

            Behavior on opacity {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Behavior on scale {
                NumberAnimation { duration: Theme.normal; easing.type: Easing.OutCubic }
            }

            Rectangle {
                id: compactButton
                anchors.centerIn: parent
                width: 52
                height: 52
                radius: 17
                color: compactHover.hovered ? Theme.primaryDark : Theme.primary
                scale: compactHover.hovered ? 1.03 : 1

                Behavior on color {
                    ColorAnimation { duration: Theme.fast }
                }

                Behavior on scale {
                    NumberAnimation { duration: Theme.fast; easing.type: Easing.OutCubic }
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: 18
                    height: 2
                    radius: 1
                    color: "white"
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: 2
                    height: 18
                    radius: 1
                    color: "white"
                }
            }

            HoverHandler {
                id: compactHover
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
        CalendarTasks { objectName: "calendarTasks" }
    }

    Component.onCompleted: {
        const calendar = board.request(calendarFactory, {cells: [[0, 0], [1, 0]]})
        if (!calendar.ok)
            console.error("初始化画板失败", calendar.error)
    }
}
