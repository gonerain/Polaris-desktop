pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

Rectangle {
    id: approvalCard
    objectName: "weixinApprovalCard"
    required property var tools
    required property var modelData
    property bool detailed: true
    signal detailsRequested()
    height: approvalContent.height + 16
    radius: 8
    color: "#FFF3DC"
    Column {
        id: approvalContent
        x: 8
        y: 8
        width: parent.width - 16
        spacing: 6
        Text {
            width: parent.width
            text: qsTr("等待批准 · 本机或微信审批码 · 2分钟有效")
            font.pixelSize: 12
            font.bold: true
            color: Theme.ink
            wrapMode: Text.Wrap
        }
        Text {
            width: parent.width
            text: approvalCard.modelData.component + " / " + approvalCard.modelData.operation
            textFormat: Text.PlainText
            font.pixelSize: 11
            color: Theme.ink
            wrapMode: Text.WrapAnywhere
        }
        Flickable {
            visible: approvalCard.detailed
            width: parent.width
            height: Math.min(160, detailText.height)
            contentHeight: detailText.height
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}
            Text {
                id: detailText
                width: parent.width
                text: approvalCard.modelData.description + "\n" + approvalCard.modelData.arguments
                textFormat: Text.PlainText
                font.pixelSize: 11
                color: Theme.ink
                wrapMode: Text.WrapAnywhere
            }
        }
        Row {
            spacing: 6
            IconButton {
                objectName: "weixinApproveWrite"
                visible: approvalCard.detailed
                text: qsTr("批准整份计划")
                textSize: 11
                onClicked: approvalCard.tools.approve(approvalCard.modelData.id)
            }
            IconButton {
                objectName: "weixinReviewWrite"
                visible: !approvalCard.detailed
                text: qsTr("查看并审批 ↗")
                textSize: 11
                onClicked: approvalCard.detailsRequested()
            }
            IconButton {
                objectName: "weixinRejectWrite"
                text: qsTr("拒绝")
                textSize: 11
                onClicked: approvalCard.tools.reject(approvalCard.modelData.id)
            }
        }
    }
}
