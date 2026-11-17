import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: picker
    property var appearance: null
    SchedulePalette { id: fallback }
    readonly property var colors: appearance || fallback
    property string selectedDate: ''
    property string todayDate: ''
    property string draftDate: ''
    property int shownYear: 2000
    property int shownMonth: 1
    signal dateSelected(string value)

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(308, parent ? parent.width - 16 : 308)
    padding: 12
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { radius: 12; color: picker.colors.surface; border.color: picker.colors.border }
    Overlay.modal: Rectangle { color: '#66000000' }

    function dateObject(year, month, day) {
        var date = new Date(0)
        date.setHours(12, 0, 0, 0)
        date.setFullYear(year, month - 1, day)
        return date
    }
    function format(year, month, day) {
        return String(year).padStart(4, '0') + '-' + String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0')
    }
    function valid(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
        var parts = value.split('-'), year = Number(parts[0]), month = Number(parts[1]), day = Number(parts[2])
        if (year < 1 || month < 1 || month > 12 || day < 1) return false
        var date = dateObject(year, month, day)
        return date.getFullYear() === year && date.getMonth() + 1 === month && date.getDate() === day
    }
    function choose(value) {
        if (!valid(value)) return
        draftDate = value
        shownYear = Number(value.slice(0, 4))
        shownMonth = Number(value.slice(5, 7))
    }
    function moveMonth(offset) {
        var monthIndex = (shownYear - 1) * 12 + shownMonth - 1 + offset
        if (monthIndex < 0 || monthIndex >= 9999 * 12) return
        shownYear = Math.floor(monthIndex / 12) + 1
        shownMonth = monthIndex % 12 + 1
    }
    onOpened: {
        var initial = valid(selectedDate) ? selectedDate : todayDate
        draftDate = ''
        if (valid(initial)) choose(initial)
    }
    contentItem: ColumnLayout {
        spacing: 6
        RowLayout {
            Layout.fillWidth: true
            ScheduleButton { objectName: 'datePickerPreviousMonth'; appearance: picker.colors; text: '‹'; Accessible.name: '上个月'; onClicked: picker.moveMonth(-1) }
            Text { Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: picker.shownYear + ' 年 ' + picker.shownMonth + ' 月'; color: picker.colors.text; font.pixelSize: 14; font.weight: Font.DemiBold }
            ScheduleButton { objectName: 'datePickerNextMonth'; appearance: picker.colors; text: '›'; Accessible.name: '下个月'; onClicked: picker.moveMonth(1) }
        }
        GridLayout {
            Layout.fillWidth: true; columns: 7; columnSpacing: 1; rowSpacing: 1
            Repeater {
                model: ['一', '二', '三', '四', '五', '六', '日']
                Text { required property string modelData; Layout.fillWidth: true; horizontalAlignment: Text.AlignHCenter; text: modelData; color: picker.colors.muted; font.pixelSize: 11 }
            }
            Repeater {
                model: 42
                ScheduleButton {
                    required property int index
                    readonly property int offset: (picker.dateObject(picker.shownYear, picker.shownMonth, 1).getDay() + 6) % 7
                    readonly property int daysInMonth: picker.dateObject(picker.shownYear, picker.shownMonth + 1, 0).getDate()
                    readonly property int day: index - offset + 1
                    readonly property bool inMonth: day >= 1 && day <= daysInMonth
                    readonly property string dateValue: inMonth ? picker.format(picker.shownYear, picker.shownMonth, day) : ''
                    objectName: inMonth ? 'datePickerDay_' + dateValue : ''
                    appearance: picker.colors
                    Layout.fillWidth: true; Layout.preferredHeight: 28; implicitWidth: 0
                    text: inMonth ? String(day) : ''
                    enabled: inMonth
                    selected: dateValue !== '' && dateValue === picker.draftDate
                    Accessible.name: inMonth ? dateValue : ''
                    onClicked: picker.draftDate = dateValue
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            ScheduleButton { objectName: 'datePickerToday'; appearance: picker.colors; text: '今天'; enabled: picker.valid(picker.todayDate); onClicked: picker.choose(picker.todayDate) }
            Item { Layout.fillWidth: true }
            ScheduleButton { objectName: 'datePickerCancel'; appearance: picker.colors; text: '取消'; onClicked: picker.close() }
            ScheduleButton { objectName: 'datePickerConfirm'; appearance: picker.colors; text: '确定'; selected: true; enabled: picker.valid(picker.draftDate); onClicked: { picker.dateSelected(picker.draftDate); picker.close() } }
        }
    }
}
