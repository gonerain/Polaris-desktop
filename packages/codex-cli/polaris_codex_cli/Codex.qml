import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    color: "#f4f6fa"
    property var snapshot: JSON.parse(codexBridge.stateJson)
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 14; spacing: 8
        RowLayout {
            Layout.fillWidth: true
            TextField { id: cwd; Layout.fillWidth: true; placeholderText: "工作目录（绝对路径）"; text: snapshot.cwd || "" }
            Button { text: "保存目录"; onClicked: codexBridge.action("configure", JSON.stringify({cwd: cwd.text})) }
        }
        Label { Layout.fillWidth: true; text: "状态：" + (snapshot.connection || "") + (snapshot.error ? " · " + snapshot.error : ""); wrapMode: Text.Wrap }
        Label { Layout.fillWidth: true; text: snapshot.notice || ""; color: "#b62e2e"; visible: text.length > 0; wrapMode: Text.Wrap }
        RowLayout {
            Button { text: "/new"; onClicked: codexBridge.action("new", "{}") }
            Button { text: "/compact"; onClicked: codexBridge.action("compact", "{}") }
            Button { text: "中断"; enabled: !!snapshot.activeTurnId; onClicked: codexBridge.action("interrupt", "{}") }
        }
        ScrollView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true
            ColumnLayout {
                width: parent.width
                Repeater {
                    model: snapshot.turns || []
                    delegate: Frame {
                        required property var modelData
                        Layout.fillWidth: true
                        ColumnLayout {
                            width: parent.width
                            Label { text: modelData.message || ""; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                            Label { text: modelData.status + " · " + modelData.turnId; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                            Label { text: modelData.reply || ""; wrapMode: Text.Wrap; Layout.fillWidth: true; textFormat: Text.PlainText }
                            Label { text: modelData.error ? JSON.stringify(modelData.error) : ""; color: "#b62e2e"; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
                Repeater {
                    model: snapshot.requests || []
                    delegate: Frame {
                        id: requestFrame
                        required property var modelData
                        Layout.fillWidth: true
                        ColumnLayout {
                            width: parent.width
                            Label { text: "Codex 请求：" + requestFrame.modelData.method; font.bold: true; Layout.fillWidth: true; wrapMode: Text.Wrap }
                            Label { text: JSON.stringify(requestFrame.modelData.params, null, 2); Layout.fillWidth: true; wrapMode: Text.WrapAnywhere; textFormat: Text.PlainText }
                            ColumnLayout {
                                id: answers
                                Layout.fillWidth: true
                                visible: requestFrame.modelData.method === "item/tool/requestUserInput"
                                Repeater {
                                    id: questions
                                    model: answers.visible ? requestFrame.modelData.params.questions : []
                                    delegate: ColumnLayout {
                                        required property var modelData
                                        property alias answer: input.text
                                        Layout.fillWidth: true
                                        Label { text: modelData.question; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        Label { text: modelData.options ? modelData.options.map(x => x.label + "：" + x.description).join("\n") : ""; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        TextField { id: input; Layout.fillWidth: true; echoMode: modelData.isSecret ? TextInput.Password : TextInput.Normal; placeholderText: "输入回答" }
                                    }
                                }
                            }
                            RowLayout {
                                Button { text: "批准"; visible: !answers.visible; onClicked: codexBridge.answer(String(requestFrame.modelData.id), "accept") }
                                Button { text: "拒绝"; visible: !answers.visible; onClicked: codexBridge.answer(String(requestFrame.modelData.id), "decline") }
                                Button { text: "提交回答"; visible: answers.visible; onClicked: { let result = {}; for (let i = 0; i < questions.count; i++) result[requestFrame.modelData.params.questions[i].id] = questions.itemAt(i).answer; codexBridge.answer(String(requestFrame.modelData.id), JSON.stringify(result)) } }
                            }
                        }
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            TextArea { id: message; Layout.fillWidth: true; placeholderText: "输入消息、/new 或 /compact"; wrapMode: TextEdit.Wrap; Layout.preferredHeight: 70 }
            ColumnLayout {
                Button { text: "发送"; onClicked: { if (codexBridge.action("send", JSON.stringify({text: message.text, mode: "start"}))) message.clear() } }
                Button { text: "补充指导"; enabled: !!snapshot.activeTurnId; onClicked: { if (codexBridge.action("send", JSON.stringify({text: message.text, mode: "steer"}))) message.clear() } }
            }
        }
    }
}
