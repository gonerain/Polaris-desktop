pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

EditorPopup {
    id: picker
    property string dateValue: ""
    property int shownYear: new Date().getFullYear()
    property int shownMonth: new Date().getMonth()
    signal dateSelected(string value)
    width: Math.min(280, anchorItem.Window.window ? anchorItem.Window.window.width - 16 : 280)
    height: Math.min(332, anchorItem.Window.window ? anchorItem.Window.window.height - 16 : 332)
    padding: 12
    onAboutToShow: {
        const parts = dateValue.split("-").map(Number)
        if (parts.length === 3) { shownYear = parts[0]; shownMonth = parts[1] - 1 }
    }
    function shiftMonth(delta) {
        const date = new Date()
        date.setFullYear(shownYear, shownMonth + delta, 1)
        shownYear = date.getFullYear()
        shownMonth = date.getMonth()
    }
    function pick(value) { close(); dateSelected(value) }
    background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.border }
    contentItem: ColumnLayout {
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            IconButton {
                text: "‹"
                buttonSize: 28
                enabled: picker.shownYear > 1 || picker.shownMonth > 0
                onClicked: picker.shiftMonth(-1)
            }
            Text {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: picker.shownYear + qsTr("年") + (picker.shownMonth + 1) + qsTr("月")
                font.pixelSize: 13
                font.weight: Font.DemiBold
                color: Theme.ink
            }
            IconButton {
                text: "›"
                buttonSize: 28
                enabled: picker.shownYear < 9999 || picker.shownMonth < 11
                onClicked: picker.shiftMonth(1)
            }
        }
        DayOfWeekRow {
            Layout.fillWidth: true
            locale: Qt.locale("zh_CN")
            font.pixelSize: 10
        }
        MonthGrid {
            id: grid
            Layout.fillWidth: true
            Layout.fillHeight: true
            month: picker.shownMonth
            year: picker.shownYear
            locale: Qt.locale("zh_CN")
            spacing: 2
            delegate: CalendarDayCell {
                required property var model
                objectName: "rescheduleDay" + modelData.date
                cellHeight: Math.max(18, grid.height / 6 - 2)
                modelData: ({date: Qt.formatDate(model.date, "yyyy-MM-dd"), day: model.day,
                    selected: Qt.formatDate(model.date, "yyyy-MM-dd") === picker.dateValue,
                    today: model.today, inMonth: model.month === grid.month, taskCount: 0, openCount: 0})
                onActivated: function(value) { picker.pick(value) }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            IconButton {
                text: qsTr("今天")
                textSize: 11
                buttonSize: 28
                selected: true
                onClicked: picker.pick(Qt.formatDate(new Date(), "yyyy-MM-dd"))
            }
            IconButton {
                text: qsTr("明天")
                textSize: 11
                buttonSize: 28
                onClicked: {
                    const date = new Date()
                    date.setDate(date.getDate() + 1)
                    picker.pick(Qt.formatDate(date, "yyyy-MM-dd"))
                }
            }
            Item { Layout.fillWidth: true }
            IconButton { text: qsTr("取消"); textSize: 11; buttonSize: 28; onClicked: picker.close() }
        }
    }
}
