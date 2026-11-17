import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: editor
    component ThinScrollBar: ScrollBar {
        id: bar; padding: 3
        visible: size > 0 && size < 1
        contentItem: Rectangle { implicitWidth: 5; implicitHeight: 5; radius: 3; color: colors.muted; opacity: bar.pressed ? 0.8 : 0.35 }
        background: Item { }
    }
    component ScheduleField: TextField {
        id: field
        implicitHeight: 32; leftPadding: 10; rightPadding: 10
        color: colors.text; placeholderTextColor: colors.muted
        selectionColor: colors.accent; selectedTextColor: colors.onAccent
        background: Rectangle { radius: 7; color: colors.raised; border.width: field.activeFocus ? 2 : 1; border.color: field.activeFocus ? colors.accent : colors.border }
    }
    required property var host
    readonly property var colors: host.appearance
    property string identity: ''
    property var childDrafts: ({})
    property var childrenTasks: {
        var tasks = host.snapshot.tasks || []
        for (var i = 0; i < tasks.length; ++i) if (tasks[i].id === identity) return tasks[i].subtasks
        return []
    }
    function openTask(task) {
        identity = task.id
        childDrafts = ({})
        titleInput.text = task.title
        dateInput.text = task.date || ''
        timeInput.text = task.time || ''
        notesInput.text = task.notes || ''
        subInput.clear()
        open()
        titleInput.forceActiveFocus()
    }
    function save() {
        if (!host.call('update', {identity: identity, title: titleInput.text, date: dateInput.text.trim() || null, time: timeInput.text.trim(), notes: notesInput.text})) return
        for (var key in childDrafts) {
            if (!host.call('update_subtask', {parent_id: identity, subtask_id: key, title: childDrafts[key]})) return
        }
        close()
    }
    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(440, parent ? parent.width - 16 : 354)
    height: Math.min(560, parent ? parent.height - 16 : 204)
    modal: true
    padding: 12
    closePolicy: Popup.CloseOnEscape
    background: Rectangle { color: colors.surface; radius: 12; border.color: colors.border }
    ColumnLayout {
        anchors.fill: parent
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: '日程详情'; textFormat: Text.PlainText; font.pixelSize: 15; font.weight: Font.DemiBold; color: colors.text }
            ScheduleButton { appearance: editor.colors; objectName: 'closeEditor'; text: '×'; onClicked: editor.close() }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AlwaysOff }
            ScrollBar.vertical: ThinScrollBar { }
            ColumnLayout {
                width: parent.width
                spacing: 10
                ScheduleField { id: titleInput; objectName: 'taskTitle'; Layout.fillWidth: true; placeholderText: '标题'; selectByMouse: true; font.pixelSize: 14; onAccepted: editor.save() }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    ScheduleField { id: dateInput; objectName: 'taskDate'; Layout.fillWidth: true; Layout.minimumWidth: 88; placeholderText: 'YYYY-MM-DD'; selectByMouse: true; font.pixelSize: 12 }
                    ScheduleButton { appearance: editor.colors; objectName: 'openDatePicker'; text: '日期'; selected: true; Accessible.name: '选择日期'; onClicked: { datePicker.selectedDate = dateInput.text; datePicker.todayDate = host.currentDay(0); datePicker.open() } }
                    ScheduleField { id: timeInput; objectName: 'taskTime'; Layout.preferredWidth: 70; Layout.minimumWidth: 54; placeholderText: 'HH:mm'; selectByMouse: true; font.pixelSize: 12 }
                    ScheduleButton { appearance: editor.colors; objectName: 'openTimePicker'; text: '时间'; selected: true; Accessible.name: '选择时间'; onClicked: { timePicker.selectedTime = timeInput.text; timePicker.open() } }

                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    ScheduleButton { appearance: editor.colors; objectName: 'rescheduleToday'; text: '今天'; onClicked: { var day = host.currentDay(0); if (day) dateInput.text = day } }
                    ScheduleButton { appearance: editor.colors; objectName: 'rescheduleTomorrow'; text: '明天'; onClicked: { var day = host.currentDay(1); if (day) dateInput.text = day } }
                    ScheduleButton { appearance: editor.colors; objectName: 'rescheduleInbox'; text: '收集箱'; onClicked: { dateInput.clear(); timeInput.clear() } }
                    Item { Layout.fillWidth: true }
                }
                TextArea {
                    id: notesInput
                    objectName: 'taskNotes'
                    Layout.fillWidth: true
                    Layout.minimumHeight: 70
                    placeholderText: '笔记'
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    font.pixelSize: 13
                    color: colors.text; placeholderTextColor: colors.muted; selectionColor: colors.accent; selectedTextColor: colors.onAccent
                    background: Rectangle { color: colors.surface; radius: 7; border.color: colors.border }
                }
                Text { text: '子任务'; textFormat: Text.PlainText; color: colors.muted; font.pixelSize: 11 }
                Repeater {
                    model: editor.childrenTasks
                    delegate: RowLayout {
                        id: subRow
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        ScheduleButton { appearance: editor.colors; objectName: 'completeSubtask_' + subRow.index; text: subRow.modelData.done ? '✓' : '○'; selected: subRow.modelData.done; onClicked: host.call('update_subtask', {parent_id: editor.identity, subtask_id: subRow.modelData.id, done: !subRow.modelData.done}) }
                        ScheduleField { objectName: 'subtaskTitle_' + subRow.index; Layout.fillWidth: true; text: editor.childDrafts[subRow.modelData.id] !== undefined ? editor.childDrafts[subRow.modelData.id] : subRow.modelData.title; selectByMouse: true; font.pixelSize: 12; onTextEdited: editor.childDrafts[subRow.modelData.id] = text; onAccepted: host.call('update_subtask', {parent_id: editor.identity, subtask_id: subRow.modelData.id, title: text}) }
                        ScheduleButton { appearance: editor.colors; objectName: 'deleteSubtask_' + subRow.index; text: '×'; onClicked: { if (host.call('delete_subtask', {parent_id: editor.identity, subtask_id: subRow.modelData.id})) delete editor.childDrafts[subRow.modelData.id] } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ScheduleField { id: subInput; objectName: 'subtaskInput'; Layout.fillWidth: true; placeholderText: '添加子任务'; selectByMouse: true; font.pixelSize: 12; onAccepted: addSub.clicked() }
                    ScheduleButton { appearance: editor.colors; id: addSub; objectName: 'addSubtask'; text: '+'; selected: true; onClicked: { if (subInput.text.trim() && host.call('add_subtask', {identity: editor.identity, title: subInput.text})) subInput.clear() } }
                }
            }
        }
        Text { objectName: 'editorError'; Layout.fillWidth: true; visible: text.length > 0; text: scheduleModel.lastError; textFormat: Text.PlainText; color: colors.error; font.pixelSize: 11; wrapMode: Text.Wrap }
        RowLayout {
            Layout.fillWidth: true
            ScheduleButton { appearance: editor.colors; objectName: 'deleteTask'; text: '删除'; onClicked: { if (host.call('delete', {identity: editor.identity})) editor.close() } }
            Item { Layout.fillWidth: true }
            ScheduleButton { appearance: editor.colors; objectName: 'saveTask'; text: '保存'; selected: true; onClicked: editor.save() }
        }
    }
    ScheduleDatePicker {
        id: datePicker; objectName: 'scheduleDatePicker'
        appearance: editor.colors
        onDateSelected: function(value) { dateInput.text = value; if (!value) timeInput.clear() }
    }
    ScheduleTimePicker {
        id: timePicker; objectName: 'scheduleTimePicker'
        appearance: editor.colors
        onTimeSelected: function(value) { timeInput.text = value }
    }

}
