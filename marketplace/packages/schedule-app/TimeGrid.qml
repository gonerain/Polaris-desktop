import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import 'Calendar.js' as Cal
import '.'

ColumnLayout {
    id: grid
    required property var host
    required property var days
    readonly property var colors: host.colors
    readonly property int gutter: 48
    readonly property int hourHeight: 64
    spacing: 0
    Row {
        Layout.fillWidth: true; Layout.preferredHeight: 66
        Item { width: grid.gutter; height: 66; Text { anchors.centerIn: parent; text: '本地\n时间'; font.pixelSize: 9; color: grid.colors.muted; lineHeight: 1.4 } }
        Repeater {
            model: grid.days
            Rectangle {
                required property string modelData
                width: (grid.width-grid.gutter)/grid.days.length; height: 66
                color: modelData===grid.host.selectedDate?grid.colors.selected:grid.colors.surface
                Column {
                    anchors.centerIn: parent; spacing: 4
                    Text { anchors.horizontalCenter: parent.horizontalCenter; text: ['日','一','二','三','四','五','六'][Cal.date(parent.parent.modelData).getDay()]; color: grid.colors.muted; font.pixelSize: 10 }
                    Rectangle { anchors.horizontalCenter: parent.horizontalCenter; width: 30; height: 30; radius: 15; color: parent.parent.modelData===grid.host.today?grid.colors.accent:'transparent'; Text { anchors.centerIn: parent; text: Number(parent.parent.parent.modelData.slice(8)); font.pixelSize: 18; color: parent.parent.parent.modelData===grid.host.today?grid.colors.onAccent:grid.colors.text } }
                }
                MouseArea { anchors.fill: parent; onClicked: grid.host.selectedDate=parent.modelData }
            }
        }
    }
    Row {
        Layout.fillWidth: true; Layout.preferredHeight: 76
        Item { width: grid.gutter; height: 76; Text { anchors.centerIn: parent; text: '全天\n待定'; color: grid.colors.muted; font.pixelSize: 9; lineHeight: 1.4 } }
        Repeater {
            model: grid.days
            Rectangle {
                id: allDay
                required property string modelData
                property var entries: Cal.untimed(grid.host.events,grid.host.visibleTasks,modelData)
                width: (grid.width-grid.gutter)/grid.days.length; height: 76
                color: grid.colors.surface; border.color: grid.colors.grid
                Column {
                    anchors.fill: parent; anchors.margins: 3; spacing: 3
                    Repeater {
                        model: allDay.entries.slice(0,2)
                        Rectangle {
                            required property var modelData
                            width: parent.width; height: 20; radius: 4
                            color: modelData.googleEvent?grid.colors.wash(modelData.color,.22):grid.colors.selected
                            Rectangle { width: 3; height: parent.height; radius: 1; color: parent.modelData.googleEvent?parent.modelData.color:grid.colors.accent }
                            Text { anchors.fill: parent; anchors.leftMargin: 6; verticalAlignment: Text.AlignVCenter; text: (parent.modelData.done?'✓ ':'')+parent.modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight; color: grid.colors.text; font.pixelSize: 10 }
                            MouseArea { anchors.fill: parent; onClicked: grid.host.openItem(parent.modelData) }
                        }
                    }
                    Text { visible: allDay.entries.length>2; text: '+'+(allDay.entries.length-2)+' 项'; color: grid.colors.accent; font.pixelSize: 10; MouseArea { anchors.fill: parent; onClicked: {grid.host.selectedDate=allDay.modelData;grid.host.viewMode='计划'} } }
                }
                DropArea { anchors.fill: parent; keys: ['schedule-app-task']; onDropped: function(drop) {grid.host.schedule(drop.source.task,allDay.modelData,'');drop.acceptProposedAction()} }
            }
        }
    }
    Flickable {
        id: scroll
        objectName: 'calendarTimeScroll'
        Layout.fillWidth: true; Layout.fillHeight: true
        clip: true; contentWidth: width; contentHeight: 24*grid.hourHeight
        boundsBehavior: Flickable.StopAtBounds
        Component.onCompleted: contentY=Math.min(7*grid.hourHeight,Math.max(0,contentHeight-height))
        ScrollBar.vertical: ScrollBar { }
        Column {
            width: grid.gutter
            Repeater {
                model: 24
                Item { required property int index; width: grid.gutter; height: grid.hourHeight; Text { x: 6; y: 4; text: String(parent.index).padStart(2,'0')+':00'; color: grid.colors.muted; font.pixelSize: 9 } }
            }
        }
        Row {
            x: grid.gutter; width: scroll.width-grid.gutter; height: scroll.contentHeight
            Repeater {
                model: grid.days
                Rectangle {
                    id: column
                    objectName: 'timeDay_'+modelData
                    required property string modelData
                    property var entries: Cal.timed(grid.host.events,grid.host.visibleTasks,modelData)
                    width: (scroll.width-grid.gutter)/grid.days.length; height: scroll.contentHeight
                    color: modelData===grid.host.today?grid.colors.wash(grid.colors.accent,.025):grid.colors.surface
                    Rectangle { width: 1; height: parent.height; color: grid.colors.grid }
                    Repeater { model: 48; Rectangle { required property int index; y: index*grid.hourHeight/2; width: column.width; height: 1; color: grid.colors.grid; opacity: index%2 ? 0.45 : 1 } }
                    MouseArea {
                        anchors.fill: parent
                        onClicked: grid.host.selectedDate=column.modelData
                        onDoubleClicked: function(mouse) {grid.host.newTask(column.modelData,Cal.time(Math.floor(mouse.y/grid.hourHeight*2)*30))}
                    }
                    Repeater {
                        model: column.entries
                        Rectangle {
                            id: block
                            required property var modelData
                            readonly property var item: modelData.item
                            x: modelData.column*(column.width-4)/modelData.columns+3
                            y: modelData.start/60*grid.hourHeight+1
                            width: Math.max(12,(column.width-4)/modelData.columns-3)
                            height: Math.max(24,(modelData.end-modelData.start)/60*grid.hourHeight-2)
                            radius: 5; clip: true
                            color: item.googleEvent?grid.colors.wash(item.color,.24):grid.colors.selected
                            border.width: grid.host.detail&&grid.host.detail.id===item.id?1:0
                            border.color: grid.colors.accent
                            opacity: item.done ? 0.55 : 1
                            Rectangle { width: 3; height: parent.height; color: block.item.googleEvent?block.item.color:grid.colors.accent }
                            Column {
                                anchors.fill: parent; anchors.margins: 5; spacing: 2
                                Text { width: parent.width; text: (block.item.done?'✓ ':'')+block.item.title; textFormat: Text.PlainText; elide: Text.ElideRight; color: grid.colors.text; font.pixelSize: 11; font.weight: Font.Medium }
                                Text { width: parent.width; visible: block.height>37; text: block.item.googleEvent?block.item.timeLabel:block.item.time+' · 任务'; elide: Text.ElideRight; color: grid.colors.muted; font.pixelSize: 9 }
                            }
                            MouseArea { id: blockMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: grid.host.openItem(block.item) }
                            ToolTip.visible: blockMouse.containsMouse
                            ToolTip.text: item.title+'\n'+(item.googleEvent?item.timeLabel:item.time+' · 任务')
                        }
                    }
                    Rectangle {
                        visible: column.modelData===grid.host.today
                        y: (grid.host.now.getHours()+grid.host.now.getMinutes()/60)*grid.hourHeight
                        width: parent.width; height: 1; color: '#ef827f'; z: 5
                        Rectangle { x: -3; y: -3; width: 7; height: 7; radius: 4; color: '#ef827f' }
                    }
                    Rectangle { visible: drop.containsDrag; y: Math.floor(drop.dragY/grid.hourHeight*2)*grid.hourHeight/2; width: parent.width; height: grid.hourHeight/2; color: grid.colors.wash(grid.colors.accent,.25); z: 6; Text { anchors.centerIn: parent; text: Cal.time(Math.min(1410,Math.floor(drop.dragY/grid.hourHeight*2)*30)); color: grid.colors.accent; font.pixelSize: 11 } }
                    DropArea {
                        id: drop; property real dragY: 0
                        anchors.fill: parent; keys: ['schedule-app-task']
                        onPositionChanged: function(drag) {dragY=drag.y}
                        onDropped: function(drag) {grid.host.schedule(drag.source.task,column.modelData,Cal.time(Math.min(1410,Math.floor(drag.y/grid.hourHeight*2)*30)));drag.acceptProposedAction()}
                    }
                }
            }
        }
    }
}
