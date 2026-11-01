import QtQuick
Rectangle {
    width: 320; height: 86
    radius: 10
    color: "#f4f6f9"
    border.color: "#cbd3df"
    property string noticeTitle: ""
    property string noticeState: ""
    Column {
        anchors.fill: parent; anchors.margins: 14; spacing: 7
        Text { width: parent.width; text: parent.parent.noticeTitle; elide: Text.ElideRight; font.bold: true; color: "#283447" }
        Text { text: parent.parent.noticeState; color: "#5c6d83" }
    }
}
