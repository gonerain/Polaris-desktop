pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

Rectangle {
    id: settings
    required property var chat
    property bool expanded: false
    required property bool connected
    height: modelControls.height + 16
    radius: 8
    color: "#F3F5F8"
    Column {
        id: modelControls
        x: 8
        y: 8
        width: parent.width - 16
        spacing: 6
        Text {
            width: parent.width
            text: qsTr("DeepSeek V4.1 Flash · Polaris Agent")
            textFormat: Text.PlainText
            font.pixelSize: 12
            font.bold: true
            color: Theme.ink
        }
        Text {
            width: parent.width
            text: settings.chat ? settings.chat.notice : ""
            textFormat: Text.PlainText
            font.pixelSize: 11
            color: Theme.muted
            wrapMode: Text.Wrap
        }
        Flow {
            width: parent.width
            spacing: 4
            IconButton {
                objectName: "weixinAutoReplyButton"
                text: settings.chat && settings.chat.autoReply ? qsTr("关闭自动回复") : qsTr("开启自动回复")
                textSize: 11
                selected: settings.chat && settings.chat.autoReply
                enabled: !!settings.chat
                onClicked: settings.chat.setEnabled(!settings.chat.autoReply)
            }
            IconButton {
                text: qsTr("恢复自动回复")
                visible: settings.chat && settings.chat.autoReply && !settings.chat.enabled
                         && settings.connected
                enabled: settings.chat && settings.chat.hasKey && !settings.chat.busy
                textSize: 11
                onClicked: settings.chat.setEnabled(true)
            }
            IconButton {
                text: qsTr("新对话")
                textSize: 11
                onClicked: settings.chat.resetConversation()
            }
        }
        Text {
            width: parent.width
            text: qsTr("默认自动回复，开关会保存。新文字和最近最多6轮上下文会发给 DeepSeek并产生 API 费用；最近100条聊天保存在本机。关闭不会撤回已发出的请求或消息。")
            textFormat: Text.PlainText
            font.pixelSize: 11
            color: Theme.muted
            wrapMode: Text.Wrap
        }
        Text {
            width: parent.width
            visible: settings.chat && settings.chat.storageError.length > 0
            text: settings.chat ? settings.chat.storageError : ""
            textFormat: Text.PlainText
            font.pixelSize: 11
            color: Theme.danger
            wrapMode: Text.Wrap
        }
        Column {
            visible: settings.expanded || (settings.chat && !settings.chat.hasKey)
            width: parent.width
            spacing: 6
            Text {
                width: parent.width
                text: qsTr("读取授权仅本次微信连接有效。写操作按当前请求的完整计划判断风险；删除、覆盖等计划整份审批一次，批准不覆盖后续新增动作。")
                font.pixelSize: 11
                color: Theme.muted
                wrapMode: Text.Wrap
            }
            Repeater {
                model: settings.chat ? settings.chat.tools.components : []
                CheckBox {
                    required property var modelData
                    width: modelControls.width
                    text: qsTr("允许读取：") + modelData.name
                    checked: modelData.readAllowed
                    font.pixelSize: 11
                    onToggled: settings.chat.tools.setReadAllowed(modelData.id, checked)
                }
            }
            CheckBox {
                objectName: "weixinAutoLowRisk"
                width: modelControls.width
                text: qsTr("自动执行低风险计划（仅新增任务和子任务）")
                checked: settings.chat && settings.chat.autoLowRisk
                font.pixelSize: 11
                onToggled: settings.chat.setAutoLowRisk(checked)
            }
            Text {
                width: parent.width
                text: qsTr("官方地址：https://api.deepseek.com\n模型：deepseek-flash\n密钥来源：DEEPSEEK_API_KEY 环境变量（Windows / Linux）\n修改环境变量后，需从新环境重新启动 Polaris。")
                textFormat: Text.PlainText
                font.pixelSize: 11
                color: Theme.muted
                wrapMode: Text.Wrap
            }
            Text {
                text: qsTr("对话人设（最多6000字符）")
                font.pixelSize: 11
                color: Theme.ink
            }
            TextArea {
                id: personaEditor
                objectName: "weixinPersonaEditor"
                width: parent.width
                height: Math.max(130, Math.min(280, contentHeight + 16))
                text: settings.chat ? settings.chat.persona : ""
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.Wrap
                selectByMouse: true
                font.pixelSize: 12
                color: Theme.ink
                padding: 8
                background: Rectangle {
                    color: "white"
                    radius: 6
                    border.color: personaEditor.activeFocus ? Theme.primary : Theme.border
                }
            }
            Flow {
                width: parent.width
                spacing: 4
                IconButton {
                    text: qsTr("保存人设")
                    textSize: 11
                    onClicked: {
                        if (settings.chat.savePersona(personaEditor.text))
                            personaEditor.text = settings.chat.persona
                    }
                }
                IconButton {
                    text: qsTr("恢复默认鲸鱼娘")
                    textSize: 11
                    onClicked: {
                        settings.chat.restoreDefaultPersona()
                        personaEditor.text = settings.chat.persona
                    }
                }
            }
            Flow {
                width: parent.width
                spacing: 4
                IconButton {
                    text: qsTr("测试连接")
                    tooltip: qsTr("会调用一次 DeepSeek API 并产生少量费用")
                    textSize: 11
                    enabled: settings.chat && settings.chat.hasKey && !settings.chat.busy
                    onClicked: settings.chat.testConnection()
                }
            }
        }
    }
}
