import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import 'Calendar.js' as Cal
import '.'

Rectangle {
    id: root
    objectName: 'scheduleApplication'
    implicitWidth: 1220; implicitHeight: 780
    color: palette.background
    Palette { id: palette }
    readonly property var colors: palette
    property var snapshot: ({})
    property string selectedDate: Cal.iso(new Date())
    property string today: Cal.iso(new Date())
    property date now: new Date()
    property string viewMode: '周'
    property string section: '我的一天'
    property string query: ''
    property bool showSearch: false
    property bool readAgain: false
    property bool showTasks: true
    property bool showDone: false
    property var hiddenCalendars: []
    property bool sidebarVisible: width>=760
    readonly property bool narrow: width<760
    property bool ready: false
    property bool reading: false
    property bool saving: false
    property string error: ''
    property var requests: ({})
    property int serial: 0
    property var detail: null
    property var draft: ({})
    property bool dirty: false
    property var pendingDetail: null
    readonly property bool sideInspector: width>=1140
    readonly property var visibleTasks: showTasks?(snapshot.tasks||[]).filter(function(t){return (showDone||!t.done)&&(!query||(t.title+' '+t.notes+' '+(t.subtasks||[]).map(function(s){return s.title}).join(' ')).toLowerCase().indexOf(query.toLowerCase())>=0)}):[]
    readonly property var events: ((snapshot.google||{}).events||[]).filter(function(e){return hiddenCalendars.indexOf(e.calendarId)<0}).map(function(e){return Cal.event(e)}).filter(function(e){return !query||(e.title+' '+e.description+' '+e.location).toLowerCase().indexOf(query.toLowerCase())>=0})
    readonly property var inbox: (snapshot.tasks||[]).filter(function(t){return !t.date&&!t.done})
    readonly property var overdue: (snapshot.tasks||[]).filter(function(t){return t.date&&t.date<today&&!t.done})
    readonly property var displayDays: viewMode==='日'?[selectedDate]:Cal.days(Cal.week(selectedDate),7)
    readonly property string periodTitle: viewMode==='周'?Cal.week(selectedDate).slice(0,4)+' 年 '+Number(Cal.week(selectedDate).slice(5,7))+' 月 '+Number(Cal.week(selectedDate).slice(8))+' — '+Cal.shift(Cal.week(selectedDate),6).slice(5).replace('-',' / '):selectedDate.slice(0,4)+' 年 '+Number(selectedDate.slice(5,7))+' 月'+(viewMode==='月'?'':' '+Number(selectedDate.slice(8))+' 日')

    function refresh() {
        if(!appCapabilities.active) return
        if(reading){readAgain=true;return}
        reading=true
        var id='read-'+(++serial);requests[id]={operation:'get'}
        appCapabilities.call('get',{},id)
    }
    function write(operation,params,closeAfter) {
        error=''
        var id='write-'+(++serial);requests[id]={operation:operation,closeAfter:!!closeAfter}
        if(closeAfter)saving=true
        appCapabilities.call(operation,params,id)
    }
    function chooseSection(value) {section=value;viewMode='计划';query='';if(value==='我的一天')selectedDate=today}
    function openItem(item) {if(item.googleEvent)openDetail(item);else openTask(item)}
    function openTask(task) {openDetail(task)}
    function openDetail(item) {
        if(dirty){pendingDetail=item;discard.open();return}
        detail=item;draft=Object.assign({},item);dirty=false;error=''
        if(!sideInspector)detailPopup.open()
    }
    function closeDetail() {
        if(dirty){pendingDetail=null;discard.open();return}
        detail=null;draft=({});detailPopup.close()
    }
    function newTask(day,time) {openDetail({title:'',date:day,time:time||'',notes:'',important:false,done:false,subtasks:[]})}
    function changeDraft(key,value) {var next=Object.assign({},draft);next[key]=value;if(key==='date'&&!value)next.time='';draft=next;dirty=true}
    function tomorrowDraft() {changeDraft('date',Cal.shift(today,1))}
    function saveDetail() {
        if(!draft.title.trim()){error='请输入任务标题';return}
        if(draft.date&&!Cal.validDate(draft.date)){error='日期需要为有效的 YYYY-MM-DD';return}
        if(draft.time&&!/^([01][0-9]|2[0-3]):[0-5][0-9]$/.test(draft.time)){error='时间需要为 HH:mm';return}
        var params={title:draft.title,date:draft.date||null,time:draft.date?draft.time||'':'',notes:draft.notes,important:draft.important}
        if(detail.id){params.identity=detail.id;params.done=draft.done}
        write(detail.id?'update':'add',params,true)
    }
    function confirmDelete() {deleteConfirm.open()}
    function schedule(task,day,time) {write('update',{identity:task.id,date:day,time:time||''})}
    function movePeriod(n) {selectedDate=viewMode==='月'?Cal.changeMonth(selectedDate,n):Cal.shift(selectedDate,n*(viewMode==='周'?7:1))}
    function toggleCalendar(id) {var a=hiddenCalendars.filter(function(x){return x!==id});if(a.length===hiddenCalendars.length)a.push(id);hiddenCalendars=a}
    function selectView(value) {viewMode=value;query='';search.clear();compactSearch.clear();section='我的一天'}
    Keys.onPressed: function(event) {
        if(event.modifiers&Qt.ControlModifier) {
            if(event.key===Qt.Key_N){newTask(selectedDate,'');event.accepted=true}
            if(event.key===Qt.Key_F){if(width>=1380)search.forceActiveFocus();else{showSearch=true;compactSearch.forceActiveFocus()}event.accepted=true}
            if(event.key===Qt.Key_Z&&snapshot.canUndo){write('undo_delete',{});event.accepted=true}
        }
    }
    Component.onCompleted: if(appCapabilities.active)refresh()
    Timer { interval: 15000; repeat: true; running: appCapabilities.active&&root.ready; onTriggered: root.refresh() }
    Timer { interval: 30000; repeat: true; running: appCapabilities.active; onTriggered: root.now=new Date() }
    Connections {
        target: appCapabilities
        function onChanged() {
            if(appCapabilities.active)root.refresh()
            else {root.reading=false;root.saving=false;root.requests=({});root.ready=false;root.snapshot=({});root.readAgain=false}
        }
        function onCompleted(id,resultJson) {
            var request=root.requests[id];if(!request)return;delete root.requests[id]
            if(request.operation==='get') {
                var data=JSON.parse(resultJson),follow=root.selectedDate===root.today
                root.snapshot=data;root.today=data.timeContext.date;root.now=new Date(data.timeContext.now)
                if(follow)root.selectedDate=root.today
                root.reading=false;root.ready=true
                if(root.detail&&root.detail.id&&!root.detail.googleEvent) {
                    var task=data.tasks.filter(function(t){return t.id===root.detail.id})[0]
                    if(task){root.detail=task;if(!root.dirty)root.draft=Object.assign({},task)}
                }
                if(root.readAgain){root.readAgain=false;root.refresh()}
            } else {
                if(request.closeAfter){root.saving=false;root.dirty=false;root.closeDetail()}
                root.refresh()
            }
        }
        function onFailed(id,message) {
            var request=root.requests[id];if(!request)return;delete root.requests[id]
            root.error=message
            if(request.operation==='get'){root.reading=false;root.ready=false;root.readAgain=false;root.snapshot=({})}
            if(request.closeAfter)root.saving=false
        }
    }

    ColumnLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            id: header
            objectName: 'scheduleAppHeader'
            Layout.fillWidth: true; Layout.preferredHeight: root.narrow||root.showSearch?96:62; color: palette.surface
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 12; spacing: 4
                RowLayout {
                    id: headerRow
                    Layout.fillWidth: true; spacing: root.narrow?3:6
                    Action { colors: root.colors; text: '☰'; onClicked: root.sidebarVisible=!root.sidebarVisible }
                    Rectangle { visible: !root.narrow; width: 28; height: 30; radius: 7; color: palette.accent; Text { anchors.centerIn: parent; text: Number(root.today.slice(8)); color: palette.onAccent; font.pixelSize: 16; font.weight: Font.DemiBold } }
                    Text { text: '日程'; color: palette.text; font.pixelSize: 20; font.weight: Font.DemiBold }
                    Action { colors: root.colors; text: '今天'; onClicked: root.selectedDate=root.today }
                    Action { colors: root.colors; text: '‹'; onClicked: root.movePeriod(-1) }
                    Action { colors: root.colors; text: '›'; onClicked: root.movePeriod(1) }
                    Text { visible: !root.narrow; Layout.fillWidth: true; Layout.minimumWidth: 45; text: root.periodTitle; color: palette.text; font.pixelSize: 13; font.weight: Font.Medium; elide: Text.ElideRight }
                    Item { visible: root.narrow; Layout.fillWidth: true }
                    RowLayout {
                        visible: root.width>=980; spacing: 2
                        Repeater { model: ['日','周','月','计划']; Action { required property string modelData; colors: root.colors; objectName: 'view_'+modelData; text: modelData==='计划'?'每日计划':modelData; selected: root.viewMode===modelData; onClicked: root.selectView(modelData) } }
                    }
                    ComboBox {
                        id: compactView; objectName: 'scheduleAppCompactView'
                        visible: root.width<980; Layout.preferredWidth: 92; implicitHeight: 34
                        model: ['日','周','月','每日计划']; currentIndex: ['日','周','月','计划'].indexOf(root.viewMode)
                        onActivated: function(index) {root.selectView(['日','周','月','计划'][index])}
                        palette.buttonText: root.colors.text; palette.text: root.colors.text; palette.window: root.colors.surface; palette.highlight: root.colors.selected; palette.highlightedText: root.colors.text
                        contentItem: Text { leftPadding: 10; rightPadding: 22; text: compactView.displayText; color: root.colors.text; font.pixelSize: 12; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                        background: Rectangle { color: root.colors.raised; radius: 7 }
                    }
                    Action { colors: root.colors; objectName: 'showCompleted'; text: root.showDone?'✓ 显示完成':'显示完成'; selected: root.showDone; onClicked: root.showDone=!root.showDone }
                    Action { colors: root.colors; objectName: 'createTask'; text: root.width>=1180?'＋ 新任务':'＋'; primary: true; onClicked: root.newTask(root.viewMode==='计划'&&root.section==='收集箱'?null:root.selectedDate,'') }
                    Field { id: search; colors: root.colors; objectName: 'scheduleAppSearch'; Layout.preferredWidth: 140; visible: root.width>=1380; placeholderText: '⌕ 搜索日程'; onTextChanged: {root.query=text;if(text)root.viewMode='计划'} }
                    Action { colors: root.colors; text: '⌕'; visible: root.width<1380; onClicked: {root.showSearch=!root.showSearch;if(root.showSearch)compactSearch.forceActiveFocus();else{compactSearch.clear();root.query=''}} }
                    Action { colors: root.colors; text: root.colors.dark?'☀':'☾'; onClicked: root.colors.dark=!root.colors.dark }
                    Action { colors: root.colors; text: '↻'; enabled: !root.reading; onClicked: {root.refresh();if((root.snapshot.google||{}).connected&&!(root.snapshot.google||{}).busy)root.write('google_sync',{})} }
                }
                RowLayout {
                    visible: root.narrow||root.showSearch; Layout.fillWidth: true
                    Text { visible: !root.showSearch; Layout.fillWidth: true; text: root.periodTitle; color: root.colors.muted; font.pixelSize: 12; elide: Text.ElideRight }
                    Field { id: compactSearch; colors: root.colors; visible: root.showSearch; Layout.fillWidth: true; placeholderText: '搜索任务和日历'; onTextChanged: {root.query=text;if(text)root.viewMode='计划'} }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: palette.line }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                visible: root.sidebarVisible; Layout.preferredWidth: root.narrow?180:214; Layout.fillHeight: true
                color: palette.sidebar
                ScrollView {
                    id: sidebarScroll
                    anchors.fill: parent; anchors.margins: 15; contentWidth: availableWidth; clip: true
                    ColumnLayout {
                        width: parent.width; spacing: 15
                        MiniMonth { colors: palette; Layout.fillWidth: true; date: root.selectedDate; today: root.today; onChosen: function(day){root.selectedDate=day} }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 3
                            Repeater { model: ['我的一天','收集箱','待重新安排','已完成']; Action { required property string modelData; colors: root.colors; Layout.fillWidth: true; text: modelData+(modelData==='收集箱'?'   '+root.inbox.length:modelData==='待重新安排'?'   '+root.overdue.length:''); selected: root.section===modelData&&root.viewMode==='计划'&&!root.query; onClicked: root.chooseSection(modelData) } }
                        }
                        Rectangle { Layout.fillWidth: true; height: 1; color: palette.line }
                        RowLayout { Layout.fillWidth: true; Text { Layout.fillWidth: true; text: '我的日历'; color: palette.muted; font.pixelSize: 10; font.weight: Font.DemiBold } Action { colors: root.colors; text: '⚙'; onClicked: google.open() } }
                        Action { colors: root.colors; Layout.fillWidth: true; text: (root.showTasks?'☑':'☐')+'  本地任务'; selected: root.showTasks; onClicked: root.showTasks=!root.showTasks }
                        Repeater {
                            model: (root.snapshot.google||{}).calendars||[]
                            RowLayout {
                                required property var modelData
                                Layout.fillWidth: true
                                Rectangle { width: 9; height: 9; radius: 3; color: parent.modelData.color }
                                Action { colors: root.colors; Layout.fillWidth: true; text: (root.hiddenCalendars.indexOf(parent.modelData.id)<0?'☑ ':'☐ ')+parent.modelData.title; enabled: ((root.snapshot.google||{}).selected||[]).indexOf(parent.modelData.id)>=0; onClicked: root.toggleCalendar(parent.modelData.id) }
                            }
                        }
                        Action { colors: root.colors; text: (root.snapshot.google||{}).connected?'管理 Google 日历':'＋ 连接 Google'; Layout.fillWidth: true; onClicked: google.open() }
                        Text { Layout.fillWidth: true; text: (root.snapshot.google||{}).busy?'Google 同步中…':(root.snapshot.google||{}).error?'Google 同步失败':(root.snapshot.google||{}).lastSync?'同步于 '+new Date(root.snapshot.google.lastSync).toLocaleTimeString(Qt.locale(),'HH:mm'):''; color: (root.snapshot.google||{}).error?palette.error:palette.muted; font.pixelSize: 9; wrapMode: Text.Wrap }
                        Rectangle { Layout.fillWidth: true; height: 1; color: palette.line }
                        RowLayout { Layout.fillWidth: true; Text { Layout.fillWidth: true; text: '待安排  '+root.inbox.length; color: palette.text; font.pixelSize: 11; font.weight: Font.DemiBold } Action { colors: root.colors; text: '＋'; onClicked: root.newTask(null,'') } }
                        Text { Layout.fillWidth: true; text: '拖动右侧把手到日期或时间'; color: palette.muted; font.pixelSize: 9; wrapMode: Text.Wrap }
                        Repeater { model: root.inbox; TaskRow { required property var modelData; host: root; task: modelData; draggable: true; Layout.fillWidth: true } }
                        Text { visible: !root.inbox.length; text: '收集箱已清空'; color: palette.muted; font.pixelSize: 11 }
                    }
                }
            }
            Rectangle { visible: root.sidebarVisible; width: 1; Layout.fillHeight: true; color: palette.line }
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumWidth: 210; spacing: 0
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: notice.implicitHeight+18; visible: !!root.error||!!root.snapshot.storageNotice; color: palette.surface
                    RowLayout { anchors.fill: parent; anchors.margins: 8; Text { id: notice; Layout.fillWidth: true; text: root.error||root.snapshot.storageNotice||''; textFormat: Text.PlainText; wrapMode: Text.Wrap; color: palette.error; font.pixelSize: 11 } Action { colors: root.colors; text: '重新读取'; enabled: !root.reading; onClicked: root.refresh() } }
                }
                Loader {
                    id: content
                    Layout.fillWidth: true; Layout.fillHeight: true
                    sourceComponent: !root.ready?welcome:root.viewMode==='月'?month:root.viewMode==='计划'||root.query?agenda:timegrid
                    Component { id: timegrid; TimeGrid { host: root; days: root.displayDays } }
                    Component { id: month; MonthView { host: root } }
                    Component { id: agenda; Rectangle { color: root.colors.background; Agenda { host: root; anchors.fill: parent; anchors.margins: root.narrow?12:25 } } }
                    Component {
                        id: welcome
                        Item { Column { anchors.centerIn: parent; spacing: 14; width: Math.min(parent.width-30,400)
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.reading?'正在读取日程…':'让每一天，井然有序'; color: palette.text; font.pixelSize: 23; wrapMode: Text.Wrap; width: parent.width; horizontalAlignment: Text.AlignHCenter }
                            Text { text: '连接日程组件后，在一个地方安排任务、查看日历。首次读取与修改会由平台确认权限。'; color: root.colors.muted; font.pixelSize: 12; wrapMode: Text.Wrap; width: parent.width; horizontalAlignment: Text.AlignHCenter }
                            Action { anchors.horizontalCenter: parent.horizontalCenter; colors: root.colors; text: '读取日程'; primary: true; enabled: !root.reading; onClicked: root.refresh() }
                        } }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true; Layout.margins: 8
                    Text { Layout.fillWidth: true; text: root.viewMode==='周'||root.viewMode==='日'?'双击时间创建任务 · 拖入任务安排时间':'日历安排与每日任务'; color: palette.muted; font.pixelSize: 9; elide: Text.ElideRight }
                    Action { colors: root.colors; text: '撤销删除'; visible: root.snapshot.canUndo||false; onClicked: root.write('undo_delete',{}) }
                }
            }
            Rectangle { visible: root.sideInspector&&!!root.detail; width: 1; Layout.fillHeight: true; color: palette.line }
            Loader { Layout.preferredWidth: 310; Layout.fillHeight: true; visible: root.sideInspector&&!!root.detail; active: visible; sourceComponent: inspectorComponent }
        }
    }
    Component { id: inspectorComponent; Inspector { host: root } }
    Popup {
        id: detailPopup; parent: Overlay.overlay; anchors.centerIn: parent
        width: Math.min(370,root.width-20); height: root.height-20; padding: 0; modal: true
        closePolicy: Popup.NoAutoClose
        background: Rectangle { color: palette.surface; radius: 12; border.color: palette.line }
        Loader { anchors.fill: parent; active: !!root.detail&&!root.sideInspector; sourceComponent: inspectorComponent }
    }
    onSideInspectorChanged: {if(detail){if(sideInspector)detailPopup.close();else detailPopup.open()}}
    Dialog {
        id: discard; parent: Overlay.overlay; anchors.centerIn: parent; title: '放弃未保存的修改？'; modal: true
        standardButtons: Dialog.Discard|Dialog.Cancel
        background: Rectangle { color: palette.surface; radius: 10; border.color: palette.line }
        palette.windowText: root.colors.text; palette.buttonText: root.colors.text; palette.button: root.colors.raised
        onDiscarded: {root.dirty=false;var item=root.pendingDetail;root.pendingDetail=null;if(item)root.openDetail(item);else root.closeDetail()}
    }
    Dialog {
        id: deleteConfirm; parent: Overlay.overlay; anchors.centerIn: parent; title: '删除此任务？'; modal: true
        standardButtons: Dialog.Yes|Dialog.No
        background: Rectangle { color: palette.surface; radius: 10; border.color: palette.line }
        palette.windowText: root.colors.text; palette.buttonText: root.colors.text; palette.button: root.colors.raised
        onAccepted: root.write('delete',{identity:root.detail.id},true)
    }
    GoogleSettings { id: google; host: root }
}
