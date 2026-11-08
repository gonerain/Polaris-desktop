import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Flickable {
    id: planner
    component ThinScrollBar: ScrollBar {
        id: bar; padding: 3
        visible: size > 0 && size < 1
        contentItem: Rectangle { implicitWidth: 5; implicitHeight: 5; radius: 3; color: colors.muted; opacity: bar.pressed ? 0.8 : 0.35 }
        background: Item { }
    }
    property var appearance: null
    SchedulePalette { id: fallback }
    readonly property var colors: appearance || fallback
    property string today: ""
    required property string date
    required property bool monthMode
    required property var tasks
    signal dayClicked(string date)
    signal taskClicked(var task)
    signal taskDropped(var task, string date)
    signal addRequested(string date)
    clip: true
    contentWidth: Math.max(width, 7 * 80)
    contentHeight: Math.max(height, monthMode ? 600 : 270)
    boundsBehavior: Flickable.StopAtBounds
    readonly property var days: {
        var start = new Date(date + 'T12:00:00')
        if (monthMode) start.setDate(1)
        start.setDate(start.getDate() - (start.getDay()+6)%7)
        var result = []
        for (var i=0; i<(monthMode ? 42 : 7); ++i) {
            var d = new Date(start); d.setDate(d.getDate()+i)
            result.push(d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'))
        }
        return result
    }
    Grid {
        width: planner.contentWidth
        columns: 7
        spacing: 4
        Repeater {
            model: planner.days
            delegate: Rectangle {
                id: day
                required property string modelData
                required property int index
                property var entries: planner.tasks.filter(function(t){ return t.date === day.modelData }).sort(function(a,b){ return (a.time || '24:00').localeCompare(b.time || '24:00') })
                width: (planner.contentWidth-24)/7
                height: planner.monthMode ? (planner.contentHeight-20)/6 : planner.contentHeight
                color: drop.containsDrag ? colors.selected : modelData === planner.date ? colors.selected : colors.surface
                border.width: modelData === planner.today || drop.containsDrag ? 1 : 0
                border.color: colors.accent
                DropArea {
                    id: drop
                    objectName: 'dropDay_' + day.modelData
                    anchors.fill: parent
                    keys: ['polaris-schedule-task']
                    onDropped: function(event) {
                        if (event.source && event.source.task) { planner.taskDropped(event.source.task, day.modelData); event.acceptProposedAction() }
                    }
                }
                radius: 7
                clip: true
                readonly property int capacity: Math.max(1, Math.floor((height - 42) / 20))
                readonly property int previewCount: entries.length > capacity ? Math.max(0, capacity - 1) : capacity
                Column {
                    anchors.fill: parent
                    anchors.margins: 5
                    spacing: 2
                    Row {
                        width: parent.width
                        ScheduleButton { appearance: planner.colors; width: parent.width - 24; padding: 2; text: ['一','二','三','四','五','六','日'][day.index%7] + ' ' + Number(day.modelData.slice(8)); selected: day.modelData === planner.date; onClicked: planner.dayClicked(day.modelData) }
                        ScheduleButton { appearance: planner.colors; objectName: 'addDay_' + day.modelData; width: 24; implicitWidth: 24; padding: 0; text: '+'; Accessible.name: '添加到 ' + day.modelData; onClicked: planner.addRequested(day.modelData) }
                    }
                    Repeater {
                        model: day.entries.slice(0, day.previewCount)
                        delegate: Text {
                            required property var modelData
                            width: parent.width
                            text: (modelData.done ? '✓ ' : '') + (modelData.time ? modelData.time + ' ' : '') + modelData.title
                            textFormat: Text.PlainText
                            font.pixelSize: 11
                            color: modelData.done ? colors.muted : colors.text
                            elide: Text.ElideRight
                            height: 18
                            MouseArea { anchors.fill: parent; onClicked: planner.taskClicked(parent.modelData) }
                        }
                    }
                    Text {
                        width: parent.width
                        height: 18
                        visible: day.entries.length > day.previewCount
                        text: '+' + (day.entries.length - day.previewCount) + '项'
                        textFormat: Text.PlainText
                        color: colors.accent; font.pixelSize: 11
                        MouseArea { anchors.fill: parent; onClicked: planner.dayClicked(day.modelData) }
                    }
                }
            }
        }
    }
    ScrollBar.horizontal: ThinScrollBar { }
    ScrollBar.vertical: ThinScrollBar { }
}
