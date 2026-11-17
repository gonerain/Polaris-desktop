import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import 'Calendar.js' as Cal
import '.'

ColumnLayout {
    id: agenda
    required property var host
    readonly property var colors: host.colors
    readonly property var tasks: host.query?host.visibleTasks:host.section==='收集箱'?host.visibleTasks.filter(function(t){return !t.date&&!t.done}):host.section==='待重新安排'?host.visibleTasks.filter(function(t){return t.date&&t.date<host.today&&!t.done}):host.section==='已完成'?(host.snapshot.tasks||[]).filter(function(t){return t.done}):host.visibleTasks.filter(function(t){return t.date===host.selectedDate})
    readonly property var entries: (host.query?host.events:host.section==='我的一天'?host.events.filter(function(e){return Cal.onDay(e,host.selectedDate)}):[]).concat(tasks).sort(function(a,b){return (a.time||'00:00').localeCompare(b.time||'00:00')})
    spacing: 14
    RowLayout {
        Layout.fillWidth: true
        ColumnLayout { Layout.fillWidth: true; spacing: 5
            Text { text: agenda.host.query?'搜索结果':agenda.host.section; color: agenda.colors.text; font.pixelSize: 25; font.weight: Font.DemiBold }
            Text { text: agenda.host.query?'找到 '+agenda.entries.length+' 项':agenda.host.section==='我的一天'?agenda.host.selectedDate+' · '+agenda.tasks.filter(function(t){return !t.done}).length+' 个待办，'+(agenda.entries.length-agenda.tasks.length)+' 个日历安排':agenda.entries.length+' 项任务'; color: agenda.colors.muted; font.pixelSize: 12 }
        }
    }
    ListView {
        id: list
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; spacing: 6
        model: agenda.entries
        ScrollBar.vertical: ScrollBar { }
        delegate: Loader {
            id: entry
            required property var modelData
            width: list.width
            sourceComponent: modelData.googleEvent?google:task
            Component { id: task; TaskRow { host: agenda.host; task: entry.modelData; draggable: !entry.modelData.done } }
            Component {
                id: google
                Rectangle {
                    implicitHeight: 68; radius: 8; color: agenda.colors.surface
                    Rectangle { x: 0; y: 10; width: 3; height: parent.height-20; radius: 2; color: entry.modelData.color }
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 13; spacing: 15
                        Text { Layout.preferredWidth: 90; text: entry.modelData.allDay?'全天':entry.modelData.timeLabel.replace('–','\n'); color: agenda.colors.accent; font.pixelSize: 12; lineHeight: 1.4 }
                        ColumnLayout { Layout.fillWidth: true; spacing: 5
                            Text { Layout.fillWidth: true; text: entry.modelData.title; textFormat: Text.PlainText; color: agenda.colors.text; font.pixelSize: 13; elide: Text.ElideRight }
                            Text { Layout.fillWidth: true; text: entry.modelData.calendarTitle+(entry.modelData.location?' · '+entry.modelData.location:''); textFormat: Text.PlainText; color: agenda.colors.muted; font.pixelSize: 10; elide: Text.ElideRight }
                        }
                        Text { text: '日历'; color: agenda.colors.muted; font.pixelSize: 10 }
                    }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: agenda.host.openItem(entry.modelData) }
                }
            }
        }
        Column {
            anchors.centerIn: parent; spacing: 10; visible: list.count===0
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: '✓'; font.pixelSize: 40; color: agenda.colors.accent }
            Text { text: agenda.host.query?'没有匹配的日程':'留一点空间，给重要的事'; font.pixelSize: 16; color: agenda.colors.text }
            Text { anchors.horizontalCenter: parent.horizontalCenter; text: '添加任务，或切换到日历查看安排'; font.pixelSize: 11; color: agenda.colors.muted }
        }
    }
}
