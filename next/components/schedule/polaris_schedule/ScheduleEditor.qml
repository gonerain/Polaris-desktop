import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Popup {
    id: editor
    required property var host
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
    background: Rectangle { color: '#f8faff'; radius: 12; border.color: '#dce4f0' }
    ColumnLayout {
        anchors.fill: parent
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: '日程详情'; textFormat: Text.PlainText; font.pixelSize: 13; font.weight: Font.DemiBold; color: '#293951' }
            ScheduleButton { objectName: 'closeEditor'; text: '×'; onClicked: editor.close() }
        }
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: 8
                TextField { id: titleInput; objectName: 'taskTitle'; Layout.fillWidth: true; placeholderText: '标题'; selectByMouse: true; font.pixelSize: 14; onAccepted: editor.save() }
                RowLayout {
                    Layout.fillWidth: true
                    TextField { id: dateInput; objectName: 'taskDate'; Layout.fillWidth: true; placeholderText: 'YYYY-MM-DD'; selectByMouse: true; font.pixelSize: 12 }
                    TextField { id: timeInput; objectName: 'taskTime'; Layout.preferredWidth: 80; placeholderText: 'HH:mm'; selectByMouse: true; font.pixelSize: 12 }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    ScheduleButton { objectName: 'rescheduleToday'; text: '今天'; onClicked: dateInput.text = host.iso(new Date()) }
                    ScheduleButton { objectName: 'rescheduleTomorrow'; text: '明天'; onClicked: { var d = new Date(); d.setDate(d.getDate()+1); dateInput.text = host.iso(d) } }
                    ScheduleButton { objectName: 'rescheduleInbox'; text: '收集箱'; onClicked: { dateInput.clear(); timeInput.clear() } }
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
                    font.pixelSize: 12
                    background: Rectangle { color: '#ffffff'; radius: 7; border.color: '#e4eaf4' }
                }
                Text { text: '子任务'; textFormat: Text.PlainText; color: '#74839b'; font.pixelSize: 11 }
                Repeater {
                    model: editor.childrenTasks
                    delegate: RowLayout {
                        id: subRow
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        ScheduleButton { objectName: 'completeSubtask_' + subRow.index; text: subRow.modelData.done ? '✓' : '○'; selected: subRow.modelData.done; onClicked: host.call('update_subtask', {parent_id: editor.identity, subtask_id: subRow.modelData.id, done: !subRow.modelData.done}) }
                        TextField { objectName: 'subtaskTitle_' + subRow.index; Layout.fillWidth: true; text: editor.childDrafts[subRow.modelData.id] !== undefined ? editor.childDrafts[subRow.modelData.id] : subRow.modelData.title; selectByMouse: true; font.pixelSize: 12; onTextEdited: editor.childDrafts[subRow.modelData.id] = text; onAccepted: host.call('update_subtask', {parent_id: editor.identity, subtask_id: subRow.modelData.id, title: text}) }
                        ScheduleButton { objectName: 'deleteSubtask_' + subRow.index; text: '×'; onClicked: { if (host.call('delete_subtask', {parent_id: editor.identity, subtask_id: subRow.modelData.id})) delete editor.childDrafts[subRow.modelData.id] } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    TextField { id: subInput; objectName: 'subtaskInput'; Layout.fillWidth: true; placeholderText: '添加子任务'; selectByMouse: true; font.pixelSize: 12; onAccepted: addSub.clicked() }
                    ScheduleButton { id: addSub; objectName: 'addSubtask'; text: '+'; selected: true; onClicked: { if (subInput.text.trim() && host.call('add_subtask', {identity: editor.identity, title: subInput.text})) subInput.clear() } }
                }
            }
        }
        Text { objectName: 'editorError'; Layout.fillWidth: true; visible: text.length > 0; text: scheduleModel.lastError; textFormat: Text.PlainText; color: '#b74854'; font.pixelSize: 11; wrapMode: Text.Wrap }
        RowLayout {
            Layout.fillWidth: true
            ScheduleButton { objectName: 'deleteTask'; text: '删除'; onClicked: { if (host.call('delete', {identity: editor.identity})) editor.close() } }
            Item { Layout.fillWidth: true }
            ScheduleButton { objectName: 'saveTask'; text: '保存'; selected: true; onClicked: editor.save() }
        }
    }
}
