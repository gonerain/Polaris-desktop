import QtQuick
import QtQuick.Controls.Basic

ScrollView {
    id: viewport
    objectName: "editorViewport"
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

    TextArea {
        objectName: "editor"
        textFormat: TextEdit.PlainText
        wrapMode: TextEdit.Wrap
        selectByMouse: true
        focus: true
        padding: 10
        color: "black"
        background: null
    }
}
