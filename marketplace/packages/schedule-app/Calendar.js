.pragma library

function iso(d) { return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0') }
function date(day) { return new Date(day + 'T12:00:00') }
function shift(day, n) { var d=date(day); d.setDate(d.getDate()+n); return iso(d) }
function week(day) { var d=date(day); return shift(day, -(d.getDay()+6)%7) }
function days(day, count) { var a=[]; for(var i=0;i<count;i++) a.push(shift(day,i)); return a }
function month(day) { var d=date(day); d.setDate(1); return days(week(iso(d)),42) }
function changeMonth(day, n) { var d=date(day), number=d.getDate(); d.setDate(1); d.setMonth(d.getMonth()+n); var last=new Date(d.getFullYear(),d.getMonth()+1,0).getDate(); d.setDate(Math.min(number,last)); return iso(d) }
function clock(d) { return String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0') }
function minutes(time) { var v=time.split(':'); return Number(v[0])*60+Number(v[1]) }
function time(value) { value=Math.max(0,Math.min(1439,value)); return String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0') }
function validDate(day) { return /^\d{4}-\d{2}-\d{2}$/.test(day) && !isNaN(date(day)) && iso(date(day))===day }
function event(raw) {
    var e=Object.assign({},raw); e.googleEvent=true; e.allDay=!!e.start.date
    if(e.allDay) {
        e.first=e.start.date; e.last=shift(e.end.date,-1); e.time=''; e.timeLabel='全天'
        e.detailTime=e.first+(e.first!==e.last?' 至 '+e.last:'')+' · 全天'
    } else {
        var start=new Date(e.start.dateTime), end=new Date(e.end.dateTime)
        e.first=iso(start); e.last=iso(new Date(Math.max(start.getTime(),end.getTime()-1)))
        e.time=clock(start); e.timeLabel=clock(start)+'–'+clock(end)
        e.detailTime=iso(start)+' '+clock(start)+' 至 '+iso(end)+' '+clock(end)+' · 本机时间'
    }
    return e
}
function onDay(e,day) { return e.first<=day && e.last>=day }
function timed(events,tasks,day) {
    var result=[]
    events.forEach(function(e) {
        if(e.allDay || !onDay(e,day)) return
        var start=new Date(e.start.dateTime), end=new Date(e.end.dateTime)
        var a=iso(start)<day?0:start.getHours()*60+start.getMinutes()
        var b=iso(end)>day?1440:end.getHours()*60+end.getMinutes()
        result.push({item:e,start:a,end:b,visualEnd:Math.max(a+24,b)})
    })
    tasks.forEach(function(t) {
        if(t.date===day && t.time) {
            var a=minutes(t.time)
            // Layout footprint only: a task has an arranged instant, no invented duration.
            result.push({item:t,start:a,end:a,visualEnd:a+24})
        }
    })
    result.sort(function(a,b){return a.start-b.start || b.visualEnd-a.visualEnd})
    var group=[], ends=[], groupEnd=-1
    function finish() { group.forEach(function(e){e.columns=ends.length});group=[];ends=[] }
    result.forEach(function(e) {
        if(e.start>=groupEnd) { finish();groupEnd=-1 }
        var col=0;while(col<ends.length && ends[col]>e.start) col++
        e.column=col;ends[col]=e.visualEnd;group.push(e);groupEnd=Math.max(groupEnd,e.visualEnd)
    })
    finish(); return result
}
function untimed(events,tasks,day) {
    return events.filter(function(e){return e.allDay&&onDay(e,day)}).concat(tasks.filter(function(t){return t.date===day&&!t.time}))
}
function agenda(events,tasks,day) {
    return events.filter(function(e){return onDay(e,day)}).concat(tasks.filter(function(t){return t.date===day}))
        .sort(function(a,b){return (a.time||'00:00').localeCompare(b.time||'00:00')})
}
