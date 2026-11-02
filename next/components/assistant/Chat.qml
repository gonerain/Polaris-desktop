import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    implicitWidth: 380; implicitHeight: 300
    color: "#f6f8fa"; radius: 10
    property bool busy: false
    ListModel { id: conversation }
    Connections {
        target: assistantChat
        function onAnswered(reply, error) {
            conversation.append({speaker: error ? "未完成" : "Polaris Agent", body: error || reply})
            root.busy = false
            list.positionViewAtEnd()
        }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 12
        RowLayout {
            Label { Layout.fillWidth: true; text: "Polaris Agent"; color: "#253650"; font.bold: true }
            CheckBox { id: tools; text: "使用已授权工具" }
        }
        ListView {
            id: list; clip: true; spacing: 8
            Layout.fillWidth: true; Layout.fillHeight: true; model: conversation
            delegate: Label {
                required property string speaker
                required property string body
                width: list.width; textFormat: Text.PlainText; wrapMode: Text.Wrap
                color: "#283850"; text: speaker + "\n" + body
            }
            Label { visible: list.count === 0; anchors.centerIn: parent; text: "开始一段对话"; color: "#63748a" }
        }
        RowLayout {
            TextField { id: draft; Layout.fillWidth: true; maximumLength: 8000; placeholderText: "输入消息"; onAccepted: send.clicked() }
            Button {
                id: send; text: root.busy ? "回复中…" : "发送"; enabled: !root.busy && draft.text.trim().length > 0
                onClicked: {
                    if (!enabled) return
                    root.busy = true
                    conversation.append({speaker: "你", body: draft.text})
                    assistantChat.submit(draft.text, tools.checked)
                    draft.clear()
                    list.positionViewAtEnd()
                }
            }
        }
    }
}
