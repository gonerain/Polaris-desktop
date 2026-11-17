import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Rectangle {
    id: studio
    objectName: 'textStudioApplication'
    color: '#1e2025'; radius: 14
    property string output: ''
    property string status: '粘贴文字，先写作，再整理。'
    property string request: ''
    property bool pending: false
    readonly property int characters: editor.text.length
    readonly property int lines: editor.text.length ? editor.text.split('\n').length : 0
    function process(alias) {
        if (pending) return
        pending = true
        request = alias + '-' + Date.now()
        status = '等待组件响应…'
        appCapabilities.call(alias, {text: editor.text}, request)
    }
    component StudioButton: Button {
        id: button
        property bool accent: false
        implicitHeight: 36; implicitWidth: label.implicitWidth + 28
        contentItem: Text { id: label; text: button.text; textFormat: Text.PlainText; color: button.accent ? '#18212c' : '#e6e8ed'; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13 }
        background: Rectangle { radius: 7; color: button.accent ? '#c0d9ee' : button.hovered ? '#3a3f49' : '#30343d'; opacity: button.enabled ? 1 : .4 }
    }
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 18
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                spacing: 6
                Text { text: 'TEXT STUDIO'; color: '#9ab1c9'; font.pixelSize: 11; font.letterSpacing: 2 }
                Text { text: '让文字，更清晰'; color: '#f1f2f5'; font.pixelSize: 26; font.weight: Font.DemiBold }
            }
            Item { Layout.fillWidth: true }
            Rectangle { implicitWidth: 78; implicitHeight: 25; radius: 12; color: '#303947'; Text { anchors.centerIn: parent; text: '示例应用'; color: '#bdd1e6'; font.pixelSize: 11 } }
        }
        Text { text: '左侧自由编辑，右侧接收组件处理结果。字符统计与编辑操作由应用自己完成。'; color: '#9ba1ad'; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 16
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true; color: '#252831'; radius: 10; border.color: '#373c47'
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 16; spacing: 12
                    RowLayout { Text { text: '原文'; color: '#e6e8ed'; font.pixelSize: 15; font.weight: Font.DemiBold } Item { Layout.fillWidth: true } Text { text: studio.characters + ' 字符  /  ' + studio.lines + ' 行'; color: '#949da9'; font.pixelSize: 11 } }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        TextArea { id: editor; objectName: 'studioEditor'; placeholderText: '在这里输入你的文字…'; color: '#e4e7ed'; placeholderTextColor: '#77818e'; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; selectByMouse: true; font.pixelSize: 15; background: null }
                    }
                    RowLayout {
                        StudioButton { text: '清空'; objectName: 'studioClear'; enabled: editor.text.length > 0; onClicked: { editor.clear(); studio.status = '原文已清空' } }
                        StudioButton { text: '使用结果'; enabled: studio.output.length > 0; onClicked: { editor.text = studio.output; studio.status = '处理结果已放入编辑区' } }
                    }
                }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true; color: '#202932'; radius: 10; border.color: '#394652'
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 16; spacing: 12
                    RowLayout { Text { text: '处理结果'; color: '#e6edf4'; font.pixelSize: 15; font.weight: Font.DemiBold } Item { Layout.fillWidth: true } Text { text: '组件能力'; color: '#96b3cd'; font.pixelSize: 11 } }
                    ScrollView { Layout.fillWidth: true; Layout.fillHeight: true; clip: true
                        TextArea { objectName: 'studioOutput'; text: studio.output; placeholderText: '整理后的文字或关键词会出现在这里'; color: '#d6e6f3'; placeholderTextColor: '#788c9e'; readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap; textFormat: TextEdit.PlainText; font.pixelSize: 15; background: null }
                    }
                    RowLayout {
                        StudioButton { text: '整理文本'; objectName: 'studioTidy'; accent: true; enabled: editor.text.length > 0 && appCapabilities.active && !studio.pending; onClicked: studio.process('tidy') }
                        StudioButton { text: '词频统计'; objectName: 'studioKeywords'; enabled: editor.text.length > 0 && appCapabilities.active && !studio.pending; onClicked: studio.process('keywords') }
                    }
                }
            }
        }
        Text { objectName: 'studioStatus'; text: studio.status; textFormat: Text.PlainText; color: '#a7b6c5'; font.pixelSize: 12; wrapMode: Text.Wrap; Layout.fillWidth: true }
    }
    Connections {
        target: appCapabilities
        function onCompleted(requestId, resultJson) {
            if (requestId !== studio.request) return
            studio.pending = false
            var result = JSON.parse(resultJson)
            studio.output = result.text
            studio.status = '处理完成 · ' + studio.output.length + ' 字符'
        }
        function onChanged() { if (!appCapabilities.active) studio.pending = false }
        function onFailed(requestId, message) {
            if (requestId === studio.request) { studio.pending = false; studio.status = message }
        }
    }
}
