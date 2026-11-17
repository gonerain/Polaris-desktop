import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import '.'

Rectangle {
    id: inspector
    required property var host
    readonly property var colors: host.colors
    readonly property var item: host.detail || ({})
    readonly property var draft: host.draft
    color: colors.surface
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 18; spacing: 12
        RowLayout {
            Layout.fillWidth: true
            Text { text: inspector.item.googleEvent?'日历事件':inspector.item.id?'任务详情':'新任务'; color: inspector.colors.muted; font.pixelSize: 11; Layout.fillWidth: true }
            Action { colors: inspector.colors; text: '×'; objectName: 'closeInspector'; onClicked: inspector.host.closeDetail() }
        }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; contentWidth: availableWidth; clip: true
            ColumnLayout {
                width: parent.width; spacing: 13
                Text { Layout.fillWidth: true; visible: !!inspector.item.googleEvent; text: inspector.item.title||''; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: inspector.colors.text; font.pixelSize: 21; font.weight: Font.DemiBold }
                Field { Layout.fillWidth: true; visible: !inspector.item.googleEvent; objectName: 'taskTitle'; colors: inspector.colors; text: inspector.draft.title||''; placeholderText: '要做什么？'; font.pixelSize: 17; onTextEdited: inspector.host.changeDraft('title',text) }
                Text { Layout.fillWidth: true; visible: !!inspector.item.googleEvent; text: inspector.item.detailTime||''; wrapMode: Text.Wrap; color: inspector.colors.accent; font.pixelSize: 12 }
                Text { Layout.fillWidth: true; visible: !!inspector.item.googleEvent; text: inspector.item.calendarTitle||''; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: inspector.colors.muted; font.pixelSize: 11 }
                Text { Layout.fillWidth: true; visible: !!inspector.item.location; text: inspector.item.location||''; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: inspector.colors.text; font.pixelSize: 12 }
                TextArea { Layout.fillWidth: true; visible: !!inspector.item.googleEvent && !!inspector.item.description; text: inspector.item.description||''; textFormat: TextEdit.PlainText; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; color: inspector.colors.text; font.pixelSize: 12; background: Item {} }
                Action { visible: !!inspector.item.googleEvent; colors: inspector.colors; text: '在 Google Calendar 中查看'; onClicked: Qt.openUrlExternally(inspector.item.url) }
                ColumnLayout {
                    visible: !inspector.item.googleEvent; Layout.fillWidth: true; spacing: 10
                    Text { text: '安排'; color: inspector.colors.muted; font.pixelSize: 11 }
                    Field { colors: inspector.colors; objectName: 'taskDate'; Layout.fillWidth: true; text: inspector.draft.date||''; placeholderText: '日期 YYYY-MM-DD · 留空放入收集箱'; onTextEdited: inspector.host.changeDraft('date',text||null) }
                    RowLayout {
                        Action { colors: inspector.colors; text: '今天'; onClicked: inspector.host.changeDraft('date',inspector.host.today) }
                        Action { colors: inspector.colors; text: '明天'; onClicked: inspector.host.tomorrowDraft() }
                        Action { colors: inspector.colors; text: '收集箱'; onClicked: {inspector.host.changeDraft('date',null);inspector.host.changeDraft('time','')} }
                    }
                    Field { colors: inspector.colors; objectName: 'taskTime'; Layout.fillWidth: true; text: inspector.draft.time||''; enabled: !!inspector.draft.date; placeholderText: '安排时间 HH:mm · 可不设置'; onTextEdited: inspector.host.changeDraft('time',text) }
                    RowLayout {
                        Action { colors: inspector.colors; text: inspector.draft.important?'★ 重点':'☆ 设为重点'; selected: !!inspector.draft.important; onClicked: inspector.host.changeDraft('important',!inspector.draft.important) }
                        Action { colors: inspector.colors; visible: !!inspector.item.id; text: inspector.draft.done?'✓ 已完成':'○ 未完成'; onClicked: inspector.host.changeDraft('done',!inspector.draft.done) }
                    }
                    Rectangle { Layout.fillWidth: true; height: 1; color: inspector.colors.line }
                    Text { text: '笔记'; color: inspector.colors.muted; font.pixelSize: 11 }
                    TextArea { Layout.fillWidth: true; objectName: 'taskNotes'; text: inspector.draft.notes||''; placeholderText: '记录细节、想法和下一步…'; placeholderTextColor: inspector.colors.muted; color: inspector.colors.text; textFormat: TextEdit.PlainText; wrapMode: TextEdit.Wrap; selectByMouse: true; implicitHeight: Math.max(100,contentHeight+20); background: Rectangle { color: inspector.colors.raised; radius: 7 } onTextChanged: if(activeFocus) inspector.host.changeDraft('notes',text) }
                    Text { text: '子任务'; color: inspector.colors.muted; font.pixelSize: 11; visible: !!inspector.item.id }
                    Repeater {
                        model: inspector.item.subtasks||[]
                        RowLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            Action { colors: inspector.colors; text: parent.modelData.done?'✓':'○'; onClicked: inspector.host.write('update_subtask',{parent_id:inspector.item.id,subtask_id:parent.modelData.id,done:!parent.modelData.done}) }
                            Text { Layout.fillWidth: true; text: parent.modelData.title; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: inspector.colors.text; font.pixelSize: 12; font.strikeout: parent.modelData.done }
                            Action { colors: inspector.colors; text: '×'; onClicked: inspector.host.write('delete_subtask',{parent_id:inspector.item.id,subtask_id:parent.modelData.id}) }
                        }
                    }
                    Field { colors: inspector.colors; Layout.fillWidth: true; visible: !!inspector.item.id; placeholderText: '＋ 子任务 · 回车保存'; onAccepted: {if(text.trim()) {inspector.host.write('add_subtask',{identity:inspector.item.id,title:text});clear()} } }
                }
            }
        }
        Text { Layout.fillWidth: true; text: inspector.host.error; visible: !!text; wrapMode: Text.Wrap; color: inspector.colors.error; font.pixelSize: 11; textFormat: Text.PlainText }
        RowLayout {
            visible: !inspector.item.googleEvent; Layout.fillWidth: true
            Action { colors: inspector.colors; objectName: 'saveTask'; text: inspector.host.saving?'保存中…':'保存'; primary: true; enabled: !inspector.host.saving; onClicked: inspector.host.saveDetail() }
            Item { Layout.fillWidth: true }
            Action { colors: inspector.colors; text: '删除'; visible: !!inspector.item.id; enabled: !inspector.host.saving; onClicked: inspector.host.confirmDelete() }
        }
        Text { visible: !!inspector.item.googleEvent; text: 'Google 日历 · 只读'; color: inspector.colors.muted; font.pixelSize: 10 }
    }
}
