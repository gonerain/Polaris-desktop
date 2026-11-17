import QtQuick
import QtQuick.Layouts
import 'Calendar.js' as Cal
import '.'

Column {
    id: mini
    required property var colors
    required property string date
    property string today: ''
    property string page: date
    signal chosen(string day)
    spacing: 8
    onDateChanged: page=date
    RowLayout {
        width: parent.width
        Text { Layout.fillWidth: true; text: mini.page.slice(0,4)+' 年 '+Number(mini.page.slice(5,7))+' 月'; font.pixelSize: 12; font.weight: Font.DemiBold; color: mini.colors.text }
        Action { colors: mini.colors; text: '‹'; implicitHeight: 26; onClicked: mini.page=Cal.changeMonth(mini.page,-1) }
        Action { colors: mini.colors; text: '›'; implicitHeight: 26; onClicked: mini.page=Cal.changeMonth(mini.page,1) }
    }
    Grid {
        columns: 7; width: parent.width
        Repeater { model: ['一','二','三','四','五','六','日']; Text { required property string modelData; width: mini.width/7; height: 24; text: modelData; horizontalAlignment: Text.AlignHCenter; color: mini.colors.muted; font.pixelSize: 10 } }
        Repeater {
            model: Cal.month(mini.page)
            Rectangle {
                required property string modelData
                width: mini.width/7; height: 28; radius: 14
                color: modelData===mini.date?mini.colors.accent:modelData===mini.today?mini.colors.selected:'transparent'
                Text { anchors.centerIn: parent; text: Number(parent.modelData.slice(8)); color: parent.modelData===mini.date?mini.colors.onAccent:parent.modelData.slice(0,7)!==mini.page.slice(0,7)?mini.colors.muted:mini.colors.text; font.pixelSize: 11; opacity: parent.modelData.slice(0,7)===mini.page.slice(0,7)?1:.5 }
                MouseArea { anchors.fill: parent; onClicked: mini.chosen(parent.modelData) }
            }
        }
    }
}
