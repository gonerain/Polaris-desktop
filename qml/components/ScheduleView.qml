pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

ColumnLayout {
    id: root
    required property var taskStore
    property bool weekMode: true
    property bool showCompleted: false
    signal dayActivated(string date, bool addTask)
    readonly property var days: {
        if (weekMode) return taskStore.weekCells
        const cells = taskStore.calendarCells
        let end = cells.length
        while (end > 28 && !cells[end - 7].inMonth) end -= 7
        return cells.slice(0, end)
    }
    readonly property int monthRows: Math.max(4, days.length / 7)
    readonly property var grouped: {
        const result = {}
        for (const row of taskStore.allEntries) {
            if (!root.showCompleted && row.task.done) continue
            if (!result[row.date]) result[row.date] = []
            result[row.date].push(row.task)
        }
        return result
    }
    spacing: 12
    RowLayout {
        Layout.fillWidth: true
        IconButton {
            objectName: "previousPeriod"
            text: "‹"
            textSize: 20
            buttonSize: 30
            accessibleName: root.weekMode ? qsTr("上一周") : qsTr("上一月")
            onClicked: root.weekMode ? root.taskStore.changeDay(-7) : root.taskStore.changeMonth(-1)
        }
        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: root.weekMode ? root.taskStore.weekLabel : root.taskStore.monthLabel
            font.pixelSize: 15
            font.weight: Font.DemiBold
            color: Theme.ink
            elide: Text.ElideRight
        }
        IconButton {
            objectName: "nextPeriod"
            text: "›"
            textSize: 20
            buttonSize: 30
            accessibleName: root.weekMode ? qsTr("下一周") : qsTr("下一月")
            onClicked: root.weekMode ? root.taskStore.changeDay(7) : root.taskStore.changeMonth(1)
        }
        IconButton {
            text: qsTr("今天")
            textSize: 11
            buttonSize: 30
            selected: true
            onClicked: root.taskStore.goToday()
        }
        IconButton {
            text: qsTr("已完成")
            textSize: 10
            buttonSize: 30
            selected: root.showCompleted
            onClicked: root.showCompleted = !root.showCompleted
        }
    }
    Flickable {
        id: viewport
        objectName: "scheduleViewport"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        contentWidth: Math.max(width, root.weekMode ? 7 * 130 + 48 : 7 * 90 + 48)
        contentHeight: Math.max(height, root.weekMode ? 280
            : root.monthRows * 82 + (root.monthRows - 1) * 8 + 24)
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.HorizontalAndVerticalFlick
        Row {
            visible: !root.weekMode
            width: viewport.contentWidth
            height: 24
            spacing: 8
            Repeater {
                model: ["一", "二", "三", "四", "五", "六", "日"]
                Text {
                    required property string modelData
                    width: (viewport.contentWidth - 48) / 7
                    text: modelData
                    horizontalAlignment: Text.AlignHCenter
                    color: Theme.muted
                    font.pixelSize: 11
                }
            }
        }
        Grid {
            id: grid
            y: root.weekMode ? 0 : 24
            columns: 7
            spacing: 8
            width: viewport.contentWidth
            Repeater {
                model: root.days
                delegate: Rectangle {
                    id: day
                    required property var modelData
                    required property int index
                    readonly property var entries: root.grouped[modelData.date] || []
                    readonly property int previewCount: root.weekMode ? entries.length
                        : Math.max(1, Math.floor((height - 60) / 23))
                    width: (grid.width - 48) / 7
                    height: root.weekMode ? viewport.contentHeight
                        : (viewport.contentHeight - (root.monthRows - 1) * 8 - 24) / root.monthRows
                    objectName: "scheduleDay" + modelData.date
                    radius: 10
                    color: modelData.today ? "#F2F4FF" : Theme.surface
                    border.color: modelData.selected ? Theme.primary : Theme.border
                    border.width: 1
                    opacity: root.weekMode || modelData.inMonth ? 1 : 0.48
                    HoverHandler { id: dayHover }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: root.weekMode ? 8 : 6
                        spacing: root.weekMode ? 6 : 3
                        Item {
                            Layout.fillWidth: true
                            implicitHeight: root.weekMode ? 48 : 21
                            Text {
                                anchors.left: parent.left
                                text: root.weekMode ? qsTr("周") + "一二三四五六日"[day.index]
                                    + "  " + day.modelData.day : day.modelData.day
                                color: day.modelData.today ? Theme.primary : Theme.ink
                                font.pixelSize: root.weekMode ? 15 : 13
                                font.weight: Font.DemiBold
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                text: day.modelData.today ? qsTr("今") : day.entries.length || ""
                                font.pixelSize: 10
                                color: day.modelData.today ? Theme.primary : Theme.muted
                            }
                            TapHandler {
                                onTapped: if (day.modelData.date) root.dayActivated(day.modelData.date, false)
                            }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                        ListView {
                            id: dayList
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: 5
                            interactive: root.weekMode
                            boundsBehavior: Flickable.StopAtBounds
                            model: day.entries.slice(0, day.previewCount)
                            delegate: Rectangle {
                                id: event
                                required property var modelData
                                width: dayList.width
                                height: root.weekMode ? (modelData.time ? 61 : 43) : 23
                                radius: 6
                                color: root.weekMode ? (modelData.done ? "#F4F5F8" : "#E9EDFF") : Theme.clearSurface
                                opacity: modelData.done ? 0.55 : 1
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.margins: root.weekMode ? 5 : 0
                                    spacing: 3
                                    TaskCheck {
                                        visible: root.weekMode
                                        objectName: "scheduleToggle" + event.modelData.entryId
                                        checkedState: event.modelData.done
                                        onToggleRequested: function(value) { event.modelData.setDone(value) }
                                    }
                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        Layout.minimumWidth: 0
                                        spacing: 2
                                        Text {
                                            visible: root.weekMode && !!event.modelData.time
                                            text: event.modelData.time
                                            color: Theme.primary
                                            font.pixelSize: 10
                                            font.weight: Font.Medium
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: (!root.weekMode && event.modelData.time ? event.modelData.time + " " : "")
                                                + event.modelData.title
                                            color: Theme.ink
                                            font.pixelSize: root.weekMode ? 11 : 10
                                            font.strikeout: event.modelData.done
                                            wrapMode: root.weekMode ? Text.Wrap : Text.NoWrap
                                            maximumLineCount: root.weekMode ? 2 : 1
                                            elide: Text.ElideRight
                                        }
                                        TapHandler { onTapped: root.dayActivated(day.modelData.date, false) }
                                    }
                                }
                            }
                            ScrollBar.vertical: ScrollBar { policy: root.weekMode ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff }
                        }
                        IconButton {
                            Layout.fillWidth: true
                            text: !root.weekMode && day.entries.length > day.previewCount
                                ? "+ " + (day.entries.length - day.previewCount) + qsTr(" 项") : qsTr("＋ 安排")
                            textSize: 10
                            buttonSize: root.weekMode ? 24 : 18
                            opacity: root.weekMode || day.entries.length > day.previewCount
                                || dayHover.hovered || day.modelData.selected || activeFocus ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                            enabled: !!day.modelData.date
                            onClicked: root.dayActivated(day.modelData.date,
                                root.weekMode || day.entries.length <= day.previewCount)
                        }
                    }
                }
            }
        }
        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    }
}
