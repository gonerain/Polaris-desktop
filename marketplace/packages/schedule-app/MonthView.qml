import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import 'Calendar.js' as Cal
import '.'

ColumnLayout {
    id: month
    required property var host
    readonly property var colors: host.colors
    spacing: 0
    Row {
        Layout.fillWidth: true; Layout.preferredHeight: 32
        Repeater { model: ['一','二','三','四','五','六','日']; Text { required property string modelData; width: month.width/7; height: 32; text: modelData; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 11; color: month.colors.muted } }
    }
    Grid {
        Layout.fillWidth: true; Layout.fillHeight: true
        columns: 7
        Repeater {
            model: Cal.month(month.host.selectedDate)
            Rectangle {
                id: cell
                required property string modelData
                property var entries: Cal.agenda(month.host.events,month.host.visibleTasks,modelData)
                property int capacity: Math.max(0,Math.floor((height-40)/23)-1)
                width: month.width/7; height: (month.height-32)/6
                color: drop.containsDrag?month.colors.selected:modelData===month.host.selectedDate?month.colors.selected:month.colors.surface
                border.color: month.colors.grid
                opacity: modelData.slice(0,7)===month.host.selectedDate.slice(0,7)?1:.55
                MouseArea { anchors.fill: parent; onClicked: month.host.selectedDate=cell.modelData; onDoubleClicked: {month.host.selectedDate=cell.modelData;month.host.viewMode='日'} }
                Column {
                    anchors.fill: parent; anchors.margins: 5; spacing: 3
                    Rectangle { width: 25; height: 25; radius: 13; color: cell.modelData===month.host.today?month.colors.accent:'transparent'; Text { anchors.centerIn: parent; text: Number(cell.modelData.slice(8)); color: cell.modelData===month.host.today?month.colors.onAccent:month.colors.text; font.pixelSize: 12 } }
                    Repeater {
                        model: cell.entries.slice(0,cell.capacity)
                        Rectangle {
                            required property var modelData
                            width: parent.width; height: 20; radius: 4
                            color: modelData.googleEvent?month.colors.wash(modelData.color,.2):'transparent'
                            Rectangle { x: 2; y: 7; width: 5; height: 5; radius: 3; color: parent.modelData.googleEvent?parent.modelData.color:month.colors.accent }
                            Text { anchors.fill: parent; anchors.leftMargin: 11; verticalAlignment: Text.AlignVCenter; text: (parent.modelData.done?'✓ ':'')+(parent.modelData.time?parent.modelData.time+' ':'')+parent.modelData.title; textFormat: Text.PlainText; color: month.colors.text; font.pixelSize: 10; elide: Text.ElideRight }
                            MouseArea { anchors.fill: parent; onClicked: month.host.openItem(parent.modelData) }
                        }
                    }
                    Text { visible: cell.entries.length>cell.capacity; text: '+'+(cell.entries.length-cell.capacity)+' 项'; color: month.colors.accent; font.pixelSize: 10; MouseArea { anchors.fill: parent; onClicked: {month.host.selectedDate=cell.modelData;month.host.viewMode='计划'} } }
                }
                DropArea { id: drop; anchors.fill: parent; keys: ['schedule-app-task']; onDropped: function(drag) {month.host.schedule(drag.source.task,cell.modelData,drag.source.task.time||'');drag.acceptProposedAction()} }
            }
        }
    }
}
