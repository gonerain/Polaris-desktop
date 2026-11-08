import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: root
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
    objectName: 'scheduleView'
    SchedulePalette { id: colors; source: root.parent && root.parent.polarisTheme !== undefined ? root.parent.polarisTheme : null }
    property alias appearance: colors
    implicitWidth: 320
    implicitHeight: 316
    color: colors.surface
    radius: 12
    property var snapshot: JSON.parse(scheduleModel.dataJson)
    property string section: '我的一天'
    property var timeContext: JSON.parse(scheduleModel.timeJson)
    property string todayDate: ''
    property string selectedDate: ''
    onTimeContextChanged: if (timeContext.date) refreshToday(timeContext.date)
    Component.onCompleted: if (timeContext.date) refreshToday(timeContext.date)
    onWideChanged: if (!wide) presentation = '列表'
    property string query: ''
    readonly property var pending: (snapshot.tasks || []).filter(function(t) { return !t.done && (!t.date || t.date < todayDate) })
    function countSection(name) {
        return (snapshot.tasks || []).filter(function(t) {
            if (name === '我的一天') return !t.done && t.date === selectedDate
            if (name === '收集箱') return !t.done && !t.date
            if (name === '待重新安排') return !t.done && t.date && t.date < todayDate
            if (name === '已完成') return t.done
            return true
        }).length
    }
    function selectSection(name) { section = name; presentation = '列表' }
    function planTask(task, date) { return call('update', {identity: task.id, date: date}) }
    function reorderTask(task, direction) {
        var tasks = (snapshot.tasks || []).filter(function(t) { return t.date === task.date })
        var ids = tasks.map(function(t) { return t.id })
        var i = ids.indexOf(task.id), j = i + direction
        if (i < 0 || j < 0 || j >= ids.length) return
        ids.splice(i, 1); ids.splice(j, 0, task.id)
        call('reorder', {ids: ids, date: task.date})
    }
    Keys.onPressed: function(event) {
        if (!(event.modifiers & Qt.ControlModifier) || editor.visible || datePopup.visible) return
        if (event.key === Qt.Key_N) { quickAdd.forceActiveFocus(); event.accepted = true }
        if (event.key === Qt.Key_F) { search.visible = true; search.forceActiveFocus(); event.accepted = true }
        if (event.key === Qt.Key_Z && snapshot.canUndo) { call('undo_delete'); event.accepted = true }
    }

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
        var followToday = !selectedDate || selectedDate === todayDate
        todayDate = value
        if (followToday) selectedDate = value
    }
    Timer { interval: 1000; repeat: true; running: root.visible; onTriggered: scheduleModel.refreshTime() }
    onVisibleChanged: if (visible) scheduleModel.refreshTime()
    function currentDay(offset) {
        if (!scheduleModel.refreshTime() || !timeContext.date) return ''
        var d = new Date(timeContext.date + 'T12:00:00')
        d.setDate(d.getDate() + offset)
        return iso(d)
    }
    function selectToday() { var day = currentDay(0); if (day) selectedDate = day }
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
        if (call('add', {title: quickAdd.text, date: presentation !== '列表' || section === '我的一天' ? selectedDate : null})) { quickAdd.clear(); quickAdd.forceActiveFocus() }
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: root.width < 300 ? 8 : 14
        spacing: 7
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            ScheduleButton { appearance: root.appearance; objectName: 'scheduleSections'; text: root.section + ' ▾'; visible: !root.wide; selected: true; onClicked: sections.open() }
            Text { visible: root.wide; text: '日程'; color: colors.text; font.pixelSize: 18; font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            ScheduleButton { appearance: root.appearance; objectName: 'previousDay'; text: '‹'; onClicked: root.changePeriod(-1) }
            ScheduleButton { appearance: root.appearance; objectName: 'selectedDay'; text: root.presentation === '月' ? root.selectedDate.slice(0,7) : root.selectedDate.slice(5).replace('-', ' / '); onClicked: datePopup.open() }
            ScheduleButton { appearance: root.appearance; objectName: 'nextDay'; text: '›'; onClicked: root.changePeriod(1) }
            ScheduleButton { appearance: root.appearance; objectName: 'todayButton'; text: '今天'; visible: root.wide || root.selectedDate !== root.todayDate; onClicked: root.selectToday() }
            ScheduleButton { appearance: root.appearance; objectName: 'searchButton'; text: '⌕'; onClicked: { search.visible = !search.visible; if (search.visible) search.forceActiveFocus(); else { search.clear(); root.query = '' } } }
            ScheduleButton { appearance: root.appearance; objectName: 'scheduleModes'; text: root.presentation + ' ▾'; visible: false; onClicked: modes.open() }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 2
            Repeater {
                model: ['我的一天', '收集箱', '待重新安排', '全部', '已完成']
                ScheduleButton { appearance: root.appearance;
                    required property string modelData
                    objectName: 'nav_' + modelData
                    visible: root.wide || ['我的一天', '收集箱', '待重新安排'].indexOf(modelData) >= 0
                    text: (modelData === '待重新安排' && !root.wide ? '待安排' : modelData) + ' ' + root.countSection(modelData)
                    selected: root.section === modelData && root.presentation === '列表'
                    onClicked: root.selectSection(modelData)
                }
            }
            Item { Layout.fillWidth: true }
        }
        RowLayout {
            visible: root.wide
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: root.presentation === '列表' ? root.section : '计划 · 拖动任务到日期'; color: colors.muted; font.pixelSize: 11 }
            Repeater {
                model: ['列表', '周', '月']
                ScheduleButton { appearance: root.appearance;
                    required property string modelData
                    required property int index
                    objectName: 'mode_' + index
                    text: modelData === '周' ? '周计划' : modelData === '月' ? '月计划' : '任务列表'
                    selected: root.presentation === modelData
                    onClicked: { root.presentation = modelData; if (modelData !== '列表') root.section = '全部' }
                }
            }
        }
        ScheduleField {
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
            ScheduleField {
                id: quickAdd
                objectName: 'quickAdd'
                Layout.fillWidth: true
                Layout.preferredHeight: 30
                placeholderText: root.presentation !== '列表' || root.section === '我的一天' ? '＋ 添加到 ' + root.selectedDate + ' · 回车继续' : '＋ 收集一个任务 · 回车继续'
                font.pixelSize: 12
                selectByMouse: true
                onAccepted: root.addTask()
                background: Rectangle { color: colors.raised; radius: 8; border.color: quickAdd.activeFocus ? colors.accent : colors.border }
            }
            ScheduleButton { appearance: root.appearance; objectName: 'addTask'; text: '+'; selected: true; onClicked: root.addTask() }
        }
        Text {
            Layout.fillWidth: true
            visible: text.length > 0
            text: scheduleModel.lastError || root.snapshot.storageNotice || ''
            textFormat: Text.PlainText
            color: colors.error
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
            ScrollBar.vertical: ThinScrollBar { }
            delegate: ScheduleTaskRow {
                required property var modelData
                required property int index
                host: root
                task: modelData
                rowIndex: index
                width: taskList.width
            }
            Text { anchors.centerIn: parent; visible: taskList.count === 0; text: root.query ? '没有匹配的日程' : '暂无日程'; textFormat: Text.PlainText; color: colors.muted; font.pixelSize: 12 }
        }
        RowLayout {
            visible: root.wide && root.presentation !== '列表'
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 8
            Rectangle {
                Layout.preferredWidth: 180
                Layout.fillHeight: true
                color: colors.raised; radius: 8
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 7
                    Text { text: '待安排 · ' + root.pending.length; color: colors.text; font.pixelSize: 12; font.weight: Font.DemiBold }
                    Text { text: '拖到右侧日期，或点 ⋯ 改期'; color: colors.muted; font.pixelSize: 10 }
                    ListView {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        clip: true; spacing: 4
                        model: root.pending
                        ScrollBar.vertical: ThinScrollBar { }
                        delegate: ScheduleTaskRow {
                            required property var modelData
                            required property int index
                            host: root; task: modelData; rowIndex: index
                            prefix: 'pending_'; draggable: true
                            width: ListView.view.width
                        }
                        Text { anchors.centerIn: parent; visible: root.pending.length === 0; text: '全部安排好了'; color: colors.muted; font.pixelSize: 11 }
                    }
                }
            }
            SchedulePlanner { appearance: root.appearance;
                objectName: 'planner'
                Layout.fillWidth: true
                Layout.fillHeight: true
                date: root.selectedDate
                today: root.todayDate
                monthMode: root.presentation === '月'
                tasks: root.filtered
                onDayClicked: function(date) { root.selectedDate = date; root.section = '我的一天'; root.presentation = '列表' }
                onTaskClicked: function(task) { root.openTask(task) }
                onTaskDropped: function(task, date) { root.planTask(task, date) }
                onAddRequested: function(date) { root.selectedDate = date; quickAdd.forceActiveFocus() }
            }
        }
        RowLayout {
            visible: root.snapshot.canUndo || false
            Layout.fillWidth: true
            Text { text: '已删除'; textFormat: Text.PlainText; color: colors.muted; font.pixelSize: 11 }
            ScheduleButton { appearance: root.appearance; objectName: 'undoDelete'; text: '撤销'; onClicked: root.call('undo_delete') }
            Item { Layout.fillWidth: true }
        }
    }
    Menu {
        palette.window: colors.raised; palette.text: colors.text; palette.buttonText: colors.text; palette.highlight: colors.selected; palette.highlightedText: colors.text
        id: sections
        y: 40
        Repeater {
            model: ['我的一天', '收集箱', '全部', '已完成', '待重新安排']
            MenuItem {
                background: Rectangle { radius: 5; color: parent.highlighted || parent.hovered ? colors.selected : "transparent" }
 required property string modelData; required property int index; objectName: 'section_' + index; text: modelData; contentItem: Text { text: parent.text; textFormat: Text.PlainText; color: colors.text; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter } onTriggered: root.selectSection(modelData) }
        }
    }
    Menu {
        palette.window: colors.raised; palette.text: colors.text; palette.buttonText: colors.text; palette.highlight: colors.selected; palette.highlightedText: colors.text
        id: modes
        x: Math.max(0, root.width - width - 10)
        y: 40
        Repeater { model: ['列表', '周', '月']; MenuItem {
                background: Rectangle { radius: 5; color: parent.highlighted || parent.hovered ? colors.selected : "transparent" }
 required property string modelData; required property int index; objectName: 'legacyMode_' + index; text: modelData; contentItem: Text { text: parent.text; textFormat: Text.PlainText; color: colors.text; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter } onTriggered: { root.presentation = modelData; if (modelData !== '列表') root.section = '全部' } } }
    }
    Popup {
        id: datePopup
        property string error: ''
        parent: Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(300, root.width - 16)
        modal: true
        padding: 16
        background: Rectangle { color: colors.surface; radius: 12; border.color: colors.border }
        ColumnLayout {
            anchors.fill: parent
            Text { text: '选择日期'; textFormat: Text.PlainText; color: colors.text }
            ScheduleField { id: dayInput; objectName: 'dayInput'; Layout.fillWidth: true; text: root.selectedDate; placeholderText: 'YYYY-MM-DD'; selectByMouse: true; onAccepted: chooseDay.clicked() }
            Text { Layout.fillWidth: true; text: datePopup.error; visible: text.length > 0; textFormat: Text.PlainText; color: colors.error; font.pixelSize: 11 }
            RowLayout {
                ScheduleButton { appearance: root.appearance; text: '今天'; onClicked: { root.selectToday(); datePopup.close() } }
                Item { Layout.fillWidth: true }
                ScheduleButton { appearance: root.appearance; id: chooseDay; objectName: 'chooseDay'; text: '确定'; selected: true; onClicked: { if (root.validDay(dayInput.text)) { root.selectedDate = dayInput.text; datePopup.close() } else datePopup.error = '日期无效' } }
            }
        }
        onOpened: { datePopup.error = ''; dayInput.text = root.selectedDate; dayInput.forceActiveFocus() }
    }
    ScheduleEditor {
        id: editor
        host: root
    }
}
