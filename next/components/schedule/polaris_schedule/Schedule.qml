import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
    objectName: 'scheduleView'
    implicitWidth: 370
    implicitHeight: 220
    color: '#f8faff'
    radius: 12
    property var snapshot: JSON.parse(scheduleModel.dataJson)
    property string section: '我的一天'
    property string todayDate: iso(new Date())
    property string selectedDate: todayDate
    property string query: ''
    property string presentation: '列表'
    property bool wide: width >= 650 && height >= 360
    property var editing: null
    property var filtered: {
        var tasks = snapshot.tasks || []
        return tasks.filter(function(t) {
            if (!query && section === '我的一天' && (t.date !== selectedDate || t.done)) return false
            if (!query && section === '收集箱' && (t.date !== null || t.done)) return false
            if (!query && section === '已完成' && !t.done) return false
            if (!query && section === '待重新安排' && (t.done || t.date === null || t.date >= todayDate)) return false
            var hay = t.title + ' ' + t.notes + ' ' + (t.subtasks || []).map(function(s) { return s.title + ' ' + s.notes }).join(' ')
            return hay.toLowerCase().indexOf(query.toLowerCase()) >= 0
        })
    }
    function iso(d) { return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') }
    function refreshToday(value) {
        var followToday = selectedDate === todayDate
        todayDate = value
        if (followToday) selectedDate = value
    }
    Timer { interval: 1000; repeat: true; running: true; onTriggered: root.refreshToday(root.iso(new Date())) }
    onVisibleChanged: if (visible) refreshToday(iso(new Date()))
    function shiftDate(n) { var d = new Date(selectedDate + 'T12:00:00'); d.setDate(d.getDate()+n); selectedDate = iso(d) }
    function changePeriod(direction) {
        if (presentation !== '月') { shiftDate(direction * (presentation === '周' ? 7 : 1)); return }
        var d = new Date(selectedDate + 'T12:00:00'); var day = d.getDate()
        d.setDate(1); d.setMonth(d.getMonth()+direction)
        var last = new Date(d.getFullYear(), d.getMonth()+1, 0).getDate()
        d.setDate(Math.min(day, last)); selectedDate = iso(d)
    }
    function validDay(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
        var d = new Date(value + 'T12:00:00')
        return !isNaN(d) && iso(d) === value
    }
    function call(op, payload) { return scheduleModel.invoke(op, JSON.stringify(payload || {})) }
    function openTask(task) { editing = task; editor.openTask(task) }
    function addTask() {
        if (!quickAdd.text.trim()) return
        if (call('add', {title: quickAdd.text, date: section === '我的一天' ? selectedDate : null})) quickAdd.clear()
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            ScheduleButton { objectName: 'scheduleSections'; text: root.section + ' ▾'; selected: true; onClicked: sections.open() }
            Item { Layout.fillWidth: true }
            ScheduleButton { objectName: 'previousDay'; text: '‹'; onClicked: root.changePeriod(-1) }
            ScheduleButton { objectName: 'selectedDay'; text: root.presentation === '月' ? root.selectedDate.slice(0,7) : root.selectedDate.slice(5).replace('-', ' / '); onClicked: datePopup.open() }
            ScheduleButton { objectName: 'nextDay'; text: '›'; onClicked: root.changePeriod(1) }
            ScheduleButton { objectName: 'todayButton'; text: '今天'; visible: root.wide || root.selectedDate !== root.todayDate; onClicked: root.selectedDate = root.iso(new Date()) }
            ScheduleButton { objectName: 'searchButton'; text: '⌕'; onClicked: { search.visible = !search.visible; if (search.visible) search.forceActiveFocus(); else { search.clear(); root.query = '' } } }
            ScheduleButton { objectName: 'scheduleModes'; text: root.presentation + ' ▾'; visible: root.wide; onClicked: modes.open() }
        }
        TextField {
            id: search
            objectName: 'scheduleSearch'
            visible: false
            Layout.fillWidth: true
            Layout.preferredHeight: 28
            placeholderText: '搜索日程'
            font.pixelSize: 12
            selectByMouse: true
            onTextChanged: root.query = text
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            TextField {
                id: quickAdd
                objectName: 'quickAdd'
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                placeholderText: root.section === '我的一天' ? '添加到这一天' : '添加到收集箱'
                font.pixelSize: 12
                selectByMouse: true
                onAccepted: root.addTask()
                background: Rectangle { color: '#edf2fb'; radius: 8; border.color: quickAdd.activeFocus ? '#7b9bd0' : '#e5ebf5' }
            }
            ScheduleButton { objectName: 'addTask'; text: '+'; selected: true; onClicked: root.addTask() }
        }
        Text {
            Layout.fillWidth: true
            visible: text.length > 0
            text: scheduleModel.lastError || root.snapshot.storageNotice || ''
            textFormat: Text.PlainText
            color: '#b74854'
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        ListView {
            id: taskList
            objectName: 'taskList'
            visible: !root.wide || root.presentation === '列表'
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 3
            model: root.filtered
            ScrollBar.vertical: ScrollBar { }
            delegate: Rectangle {
                id: row
                required property var modelData
                required property int index
                width: taskList.width
                height: 40
                radius: 7
                color: mouse.containsMouse ? '#edf2fa' : '#ffffff'
                MouseArea { id: mouse; anchors.fill: parent; hoverEnabled: true; onClicked: root.openTask(row.modelData) }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 3
                    anchors.rightMargin: 5
                    spacing: 3
                    ScheduleButton { objectName: 'completeTask_' + row.index; text: row.modelData.done ? '✓' : '○'; selected: row.modelData.done; onClicked: root.call('update', {identity: row.modelData.id, done: !row.modelData.done}) }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Text { Layout.fillWidth: true; text: row.modelData.title; textFormat: Text.PlainText; font.pixelSize: 12; font.strikeout: row.modelData.done; color: row.modelData.done ? '#9aa4b3' : '#293951'; elide: Text.ElideRight }
                        Text { Layout.fillWidth: true; visible: text.length > 0; text: [row.modelData.time || '', root.section !== '我的一天' ? (row.modelData.date || '收集箱') : '', row.modelData.subtasks.length ? row.modelData.subtasks.filter(function(s){ return s.done }).length + '/' + row.modelData.subtasks.length : ''].filter(function(s){return s.length > 0}).join(' · '); textFormat: Text.PlainText; font.pixelSize: 10; color: '#8b98ad'; elide: Text.ElideRight }
                    }
                    ScheduleButton { objectName: 'importantTask_' + row.index; text: row.modelData.important ? '★' : '☆'; selected: row.modelData.important; onClicked: root.call('update', {identity: row.modelData.id, important: !row.modelData.important}) }
                }
            }
            Text { anchors.centerIn: parent; visible: taskList.count === 0; text: root.query ? '没有匹配的日程' : '暂无日程'; textFormat: Text.PlainText; color: '#9ca8bb'; font.pixelSize: 12 }
        }
        SchedulePlanner {
            visible: root.wide && root.presentation !== '列表'
            Layout.fillWidth: true
            Layout.fillHeight: true
            date: root.selectedDate
            monthMode: root.presentation === '月'
            tasks: root.filtered
            onDayClicked: function(date) { root.selectedDate = date; root.section = '我的一天'; root.presentation = '列表' }
            onTaskClicked: function(task) { root.openTask(task) }
        }
        RowLayout {
            visible: root.snapshot.canUndo || false
            Layout.fillWidth: true
            Text { text: '已删除'; textFormat: Text.PlainText; color: '#8290a7'; font.pixelSize: 11 }
            ScheduleButton { objectName: 'undoDelete'; text: '撤销'; onClicked: root.call('undo_delete') }
            Item { Layout.fillWidth: true }
        }
    }
    Menu {
        id: sections
        y: 40
        Repeater {
            model: ['我的一天', '收集箱', '全部', '已完成', '待重新安排']
            MenuItem { required property string modelData; required property int index; objectName: 'section_' + index; text: modelData; contentItem: Text { text: parent.text; textFormat: Text.PlainText; color: '#293951'; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter } onTriggered: root.section = modelData }
        }
    }
    Menu {
        id: modes
        x: Math.max(0, root.width - width - 10)
        y: 40
        Repeater { model: ['列表', '周', '月']; MenuItem { required property string modelData; required property int index; objectName: 'mode_' + index; text: modelData; contentItem: Text { text: parent.text; textFormat: Text.PlainText; color: '#293951'; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter } onTriggered: { root.presentation = modelData; if (modelData !== '列表') root.section = '全部' } } }
    }
    Popup {
        id: datePopup
        property string error: ''
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(300, root.width - 16)
        modal: true
        padding: 16
        background: Rectangle { color: '#f8faff'; radius: 12; border.color: '#dce4f0' }
        ColumnLayout {
            anchors.fill: parent
            Text { text: '选择日期'; textFormat: Text.PlainText; color: '#293951' }
            TextField { id: dayInput; objectName: 'dayInput'; Layout.fillWidth: true; text: root.selectedDate; placeholderText: 'YYYY-MM-DD'; selectByMouse: true; onAccepted: chooseDay.clicked() }
            Text { Layout.fillWidth: true; text: datePopup.error; visible: text.length > 0; textFormat: Text.PlainText; color: '#b74854'; font.pixelSize: 11 }
            RowLayout {
                ScheduleButton { text: '今天'; onClicked: { root.selectedDate = root.iso(new Date()); datePopup.close() } }
                Item { Layout.fillWidth: true }
                ScheduleButton { id: chooseDay; objectName: 'chooseDay'; text: '确定'; selected: true; onClicked: { if (root.validDay(dayInput.text)) { root.selectedDate = dayInput.text; datePopup.close() } else datePopup.error = '日期无效' } }
            }
        }
        onOpened: { datePopup.error = ''; dayInput.text = root.selectedDate; dayInput.forceActiveFocus() }
    }
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: { var day = root.iso(new Date()); if (day !== root.todayDate) { var follow = root.selectedDate === root.todayDate; root.todayDate = day; if (follow) root.selectedDate = day } }
    }
    ScheduleEditor {
        id: editor
        host: root
    }
}
