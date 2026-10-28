pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "Theme.js" as Theme

EditorPopup {
    id: review
    required property var taskStore
    property string reviewDate: ""
    property int completed: 0
    property string error: ""
    objectName: "dayReviewPopup"
    width: Math.min(620, anchorItem.Window.window ? anchorItem.Window.window.width - 16 : 620)
    height: Math.min(540, anchorItem.Window.window ? anchorItem.Window.window.height - 16 : 540)
    padding: 18
    background: Rectangle { radius: 12; color: Theme.surface; border.color: Theme.border }
    ListModel { id: choices; dynamicRoles: true }
    onAboutToShow: {
        reviewDate = taskStore.todayDate
        completed = 0
        error = ""
        choices.clear()
        for (const row of taskStore.allEntries) {
            if (row.date !== reviewDate) continue
            if (row.task.done) ++completed
            else choices.append({identity: row.task.entryId, task: row.task, choice: 0})
        }
    }
    function chooseAll(choice) {
        for (let i = 0; i < choices.count; ++i) choices.setProperty(i, "choice", choice)
    }
    function apply() {
        const decisions = []
        for (let i = 0; i < choices.count; ++i) {
            const row = choices.get(i)
            decisions.push({id: row.identity, action: ["keep", "tomorrow", "inbox"][row.choice]})
        }
        if (taskStore.finishDay(reviewDate, decisions)) close()
        else error = qsTr("任务状态已变化，请重新打开整理。没有修改任何任务。")
    }
    contentItem: ColumnLayout {
        spacing: 12
        Text { text: qsTr("整理今天"); font.pixelSize: 20; font.weight: Font.DemiBold; color: Theme.ink }
        Text {
            Layout.fillWidth: true
            text: review.reviewDate + qsTr(" · 已完成 ") + review.completed + qsTr(" 项，还有 ") + choices.count + qsTr(" 项未完成")
            color: Theme.muted
            font.pixelSize: 12
            wrapMode: Text.Wrap
        }
        Text {
            Layout.fillWidth: true
            text: qsTr("每件事重新决定一次。不选择就保留原安排，不会自动顺延。")
            color: Theme.muted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        RowLayout {
            visible: choices.count > 0
            Layout.fillWidth: true
            Text { text: qsTr("批量："); color: Theme.muted; font.pixelSize: 11 }
            IconButton { text: qsTr("保留"); textSize: 11; buttonSize: 28; onClicked: review.chooseAll(0) }
            IconButton { text: qsTr("明天"); textSize: 11; buttonSize: 28; onClicked: review.chooseAll(1) }
            IconButton { text: qsTr("收集箱"); textSize: 11; buttonSize: 28; onClicked: review.chooseAll(2) }
            Item { Layout.fillWidth: true }
        }
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 5
            model: choices
            boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                id: item
                required property var task
                required property int choice
                required property int index
                width: list.width
                height: 58
                radius: 8
                color: Theme.background
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 8
                    Text {
                        Layout.fillWidth: true
                        Layout.minimumWidth: 0
                        text: item.task ? item.task.title : qsTr("任务已移除")
                        color: Theme.ink
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                    ComboBox {
                        id: decisionBox
                        objectName: "reviewChoice" + (item.task ? item.task.entryId : 0)
                        Layout.preferredWidth: Math.min(142, list.width * 0.45)
                        model: [qsTr("保留今天"), qsTr("安排明天"), qsTr("放回收集箱")]
                        currentIndex: item.choice
                        font.pixelSize: 11
                        contentItem: Text {
                            text: decisionBox.displayText
                            leftPadding: 10
                            rightPadding: 24
                            verticalAlignment: Text.AlignVCenter
                            color: Theme.ink
                            font.pixelSize: 11
                            elide: Text.ElideRight
                        }
                        background: Rectangle {
                            radius: 7
                            color: Theme.surface
                            border.color: decisionBox.activeFocus ? Theme.primary : Theme.border
                        }
                        indicator: Canvas {
                            width: 12
                            height: 8
                            x: decisionBox.width - width - 9
                            y: (decisionBox.height - height) / 2
                            onPaint: {
                                const ctx = getContext("2d")
                                ctx.strokeStyle = Theme.muted
                                ctx.lineWidth = 1.5
                                ctx.beginPath(); ctx.moveTo(2, 2); ctx.lineTo(6, 6); ctx.lineTo(10, 2); ctx.stroke()
                            }
                        }
                        onActivated: function(index) { choices.setProperty(item.index, "choice", index) }
                    }
                }
            }
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Text {
                anchors.centerIn: parent
                visible: list.count === 0
                text: qsTr("今天的事项都完成了，可以安心收工。")
                color: Theme.muted
                font.pixelSize: 13
            }
        }
        Text { visible: !!review.error; text: review.error; color: Theme.danger; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                text: qsTr("完成记录保留；确认后统一保存。")
                color: Theme.muted
                font.pixelSize: 10
                elide: Text.ElideRight
            }
            IconButton { text: qsTr("取消"); textSize: 11; buttonSize: 32; onClicked: review.close() }
            IconButton {
                objectName: "applyDayReview"
                text: qsTr("确认整理")
                filled: true
                textSize: 11
                buttonSize: 32
                onClicked: review.apply()
            }
        }
    }
}
