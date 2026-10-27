import QtQuick
import "components"

Window {
    id: window
    width: compactSize
    height: compactSize
    minimumWidth: compactSize
    minimumHeight: compactSize
    visible: true
    title: qsTr("悬浮写字板")
    color: "white"
    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    readonly property int compactSize: 64
    readonly property int expandedMinimumWidth: 528
    readonly property int expandedMinimumHeight: 300
    property bool compact: true
    property bool moving: false
    property bool applyingState: false
    property real expandedWidth: 528
    property real expandedHeight: 300

    onWidthChanged: if (!compact && !applyingState) expandedWidth = width
    onHeightChanged: if (!compact && !applyingState) expandedHeight = height

    function expand() {
        if (!compact)
            return
        autoCollapse.stop()
        applyingState = true
        compact = false
        minimumWidth = expandedMinimumWidth
        minimumHeight = expandedMinimumHeight
        width = Math.max(expandedWidth, expandedMinimumWidth)
        height = Math.max(expandedHeight, expandedMinimumHeight)
        applyingState = false
    }

    function collapse() {
        if (compact)
            return
        autoCollapse.stop()
        applyingState = true
        expandedWidth = width
        expandedHeight = height
        compact = true
        minimumWidth = compactSize
        minimumHeight = compactSize
        width = compactSize
        height = compactSize
        applyingState = false
    }

    Item {
        id: root
        anchors.fill: parent

        // 覆盖整个窗口的被动悬停检测，不抢占日历和输入框的鼠标事件。
        HoverHandler {
            id: windowHover
            objectName: "windowHover"
            onHoveredChanged: {
                if (hovered) {
                    autoCollapse.stop()
                } else if (!window.compact && !window.moving) {
                    autoCollapse.restart()
                }
            }
        }

        Item {
            id: expandedContent
            objectName: "expandedContent"
            width: window.compact ? window.expandedWidth : window.width
            height: window.compact ? window.expandedHeight : window.height
            visible: !window.compact

            Rectangle {
                id: titleBar
                objectName: "titleBar"
                anchors.top: parent.top
                anchors.left: parent.left
                anchors.right: parent.right
                height: 40
                color: "#f4f6f9"

                Item {
                    objectName: "titleDragArea"
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.left: parent.left
                    anchors.right: windowControls.left

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 14
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: window.title
                        color: "#526075"
                        font.pixelSize: 13
                        font.weight: Font.Medium
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
                            } else if (!windowHover.hovered && !window.compact) {
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
                    spacing: 4

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
                anchors.fill: parent
                targetWindow: window
            }
        }

        Rectangle {
            id: compactBox
            objectName: "compactBox"
            anchors.fill: parent
            visible: window.compact
            color: "#648bc6"
            Accessible.role: Accessible.Button
            Accessible.name: qsTr("打开日程")

            Rectangle {
                anchors.fill: parent
                anchors.margins: 4
                radius: 10
                color: compactHover.hovered ? "#f1f6fe" : "white"
            }

            Column {
                anchors.centerIn: parent
                spacing: 0

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatDate(new Date(), "M月")
                    color: "#648bc6"
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Qt.formatDate(new Date(), "d")
                    color: "#334155"
                    font.pixelSize: 24
                    font.weight: Font.DemiBold
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
                if (!windowHover.hovered && !window.moving && !window.compact)
                    window.collapse()
            }
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
