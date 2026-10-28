pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    required property var hub
    required property var components
    color: Theme.surface
    radius: 12
    border.color: Theme.border
    clip: true
    onVisibleChanged: if (visible && hub) hub.markRead()
    Connections {
        target: root.hub
        function onChanged() { if (root.visible) root.hub.markRead() }
    }

    function stateLabel(state) {
        return state === "running" ? qsTr("执行中") : state === "disconnected" ? qsTr("连接断开") : qsTr("空闲")
    }
    function outcomeLabel(outcome) {
        return ({ended: qsTr("本轮已结束"), failed: qsTr("本轮失败"), cancelled: qsTr("已取消"), unknown: qsTr("结果未知")})[outcome] || ""
    }

    ListView {
        id: list
        objectName: "agentSessionList"
        anchors.fill: parent
        anchors.margins: 14
        spacing: 8
        clip: true
        model: root.hub ? root.hub.sessions : []
        ScrollBar.vertical: ScrollBar {}
        header: Column {
            width: list.width
            spacing: 8
            Text {
                text: qsTr("Agent 会话")
                font.pixelSize: 16
                font.bold: true
                color: Theme.ink
            }
            Text {
                width: parent.width
                text: qsTr("只显示已接入的会话；断连不代表完成。")
                font.pixelSize: 11
                color: Theme.muted
                wrapMode: Text.Wrap
            }
            Text {
                width: parent.width
                text: root.hub ? root.hub.connectionError : ""
                textFormat: Text.PlainText
                color: Theme.danger
                wrapMode: Text.Wrap
                visible: text.length > 0
                font.pixelSize: 12
            }
            Text {
                text: qsTr("暂无活跃会话，请加载接入插件。")
                color: Theme.muted
                font.pixelSize: 12
                visible: list.count === 0
            }
            Item { width: 1; height: 2 }
        }
        delegate: Rectangle {
            id: sessionRow
            required property var modelData
            width: list.width
            height: 78
            radius: 8
            color: Theme.calendarSurface
            border.color: Theme.border
            Column {
                anchors.fill: parent
                anchors.margins: 10
                spacing: 4
                RowLayout {
                    width: parent.width
                    Text {
                        Layout.fillWidth: true
                        text: sessionRow.modelData.source + " · " + sessionRow.modelData.name
                        textFormat: Text.PlainText
                        color: Theme.ink
                        font.pixelSize: 12
                        font.bold: true
                        elide: Text.ElideRight
                    }
                    Text {
                        text: root.stateLabel(sessionRow.modelData.state)
                        color: sessionRow.modelData.state === "running" ? Theme.primary : Theme.muted
                        font.pixelSize: 11
                    }
                }
                Text {
                    width: parent.width
                    text: sessionRow.modelData.project || qsTr("未提供项目")
                    textFormat: Text.PlainText
                    color: Theme.muted
                    font.pixelSize: 11
                    elide: Text.ElideMiddle
                }
                Text {
                    text: qsTr("连接 ") + sessionRow.modelData.instanceId.slice(0, 8)
                          + (sessionRow.modelData.outcome ? " · " + root.outcomeLabel(sessionRow.modelData.outcome) : "")
                    color: sessionRow.modelData.outcome === "failed" ? Theme.danger : Theme.muted
                    font.pixelSize: 10
                }
            }
        }
        footer: Column {
            width: list.width
            spacing: 10
            Item { width: 1; height: 4 }
            Text { text: qsTr("组件访问 · 当前连接有效"); color: Theme.ink; font.pixelSize: 12; font.bold: true }
            Text {
                width: parent.width
                text: qsTr("默认不允许读取或修改数据。只给你信任的连接授权。来源名称由客户端自报。")
                wrapMode: Text.Wrap
                color: Theme.muted
                font.pixelSize: 11
            }
            Repeater {
                model: root.hub ? root.hub.clients : []
                delegate: Column {
                    id: clientRow
                    required property var modelData
                    width: list.width
                    spacing: 4
                    Text {
                        width: parent.width
                        text: clientRow.modelData.name + " · " + clientRow.modelData.instanceId.slice(0, 8)
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        color: Theme.ink
                        font.pixelSize: 12
                    }
                    Repeater {
                        model: root.components ? root.components.components : []
                        delegate: RowLayout {
                            id: permissionRow
                            required property var modelData
                            width: clientRow.width
                            Text {
                                Layout.fillWidth: true
                                text: permissionRow.modelData.name
                                textFormat: Text.PlainText
                                font.pixelSize: 11
                                color: Theme.muted
                            }
                            ComboBox {
                                id: permissionControl
                                objectName: "agentPermissionControl"
                                readonly property string componentId: permissionRow.modelData.id
                                implicitWidth: 130
                                implicitHeight: 28
                                font.pixelSize: 11
                                model: permissionRow.modelData.writable
                                       ? [qsTr("未授权"), qsTr("只读"), qsTr("允许修改")]
                                       : [qsTr("未授权"), qsTr("只读")]
                                readonly property string level: clientRow.modelData.grants[permissionRow.modelData.id] || "none"
                                currentIndex: level === "write" && permissionRow.modelData.writable ? 2 : level !== "none" ? 1 : 0
                                onActivated: function(index) {
                                    root.hub.setPermission(clientRow.modelData.instanceId, permissionRow.modelData.id,
                                                           ["none", "read", "write"][index])
                                }
                                popup: EditorPopup {
                                    focus: false
                                    anchorItem: permissionControl
                                    width: permissionControl.width
                                    implicitHeight: contentItem.implicitHeight + 8
                                    padding: 4
                                    contentItem: ListView {
                                        clip: true
                                        implicitHeight: contentHeight
                                        model: permissionControl.popup.visible ? permissionControl.delegateModel : null
                                        currentIndex: permissionControl.highlightedIndex
                                    }
                                    background: Rectangle {
                                        color: Theme.surface
                                        border.color: Theme.border
                                        radius: 6
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Text { text: qsTr("最近结束 · 仅本次运行"); color: Theme.ink; font.pixelSize: 12; font.bold: true }
            Repeater {
                model: root.hub ? root.hub.results : []
                delegate: Text {
                    required property var modelData
                    width: list.width
                    text: modelData.time + "  " + modelData.text
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Theme.muted
                    font.pixelSize: 11
                }
            }
            Item { width: 1; height: 12 }
        }
    }
}
