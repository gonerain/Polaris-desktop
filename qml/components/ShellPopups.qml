pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

// Keep Qt Quick Controls and popup objects out of the initial pet-only scene.
Item {
    id: popups
    required property var shell
    required property var pet
    required property var presenter
    readonly property bool menuVisible: contextMenu.visible
    readonly property bool quitVisible: unsavedQuitDialog.visible

    function popup(point) { contextMenu.popup(point) }
    function confirmQuit() { unsavedQuitDialog.open() }

    Dialog {
        id: unsavedQuitDialog
        objectName: "unsavedQuitDialog"
        anchors.centerIn: parent
        popupType: Popup.Window
        modal: true
        width: 360
        title: qsTr("日程尚未保存")
        standardButtons: Dialog.Discard | Dialog.Cancel
        onOpened: {
            standardButton(Dialog.Discard).text = qsTr("仍然退出")
            standardButton(Dialog.Cancel).text = qsTr("返回")
        }
        Label {
            width: parent.width
            text: qsTr("保存失败，退出会丢失尚未写入的修改。建议返回后重试保存或备份数据。")
            wrapMode: Text.Wrap
        }
        onDiscarded: popups.shell.finishQuit()
    }

    Menu {
        id: contextMenu
        objectName: "quitMenu"
        parent: popups
        popupType: Popup.Window
        implicitWidth: 152
        padding: 4
        onOpened: popups.shell.pauseAutoCollapse()
        onClosed: popups.shell.resumeAutoCollapse()
        background: Rectangle {
            color: Theme.surface
            radius: 8
            border.width: 1
            border.color: Theme.border
        }
        MenuItem {
            objectName: "agentPageMenuItem"
            text: qsTr("Agent 会话") + (popups.shell.agentHub && popups.shell.agentHub.unreadCount ? " · " + popups.shell.agentHub.unreadCount : "")
            font.pixelSize: 12
            enabled: !popups.presenter.transitioning
            onTriggered: popups.shell.showComponent("agents")
        }
        MenuItem {
            text: qsTr("打开日程")
            font.pixelSize: 12
            enabled: !popups.presenter.transitioning
            onTriggered: popups.shell.showComponent("calendar")
        }
        MenuSeparator {}
        MenuItem {
            objectName: "petGreetMenuItem"
            text: qsTr("打个招呼")
            font.pixelSize: 12
            enabled: popups.shell.compact
            onTriggered: {
                popups.shell.showSpeech(qsTr("Hi！👋"), 6500)
                if (!popups.shell.reducedPetMotion) popups.pet.playWave(true)
            }
        }
        MenuItem {
            objectName: "petActivityMenuItem"
            text: qsTr("换个小动作")
            font.pixelSize: 12
            enabled: popups.shell.compact && !popups.shell.reducedPetMotion
            onTriggered: popups.pet.playActivity(true)
        }
        MenuItem {
            objectName: "petRestMenuItem"
            text: qsTr("休息一下")
            font.pixelSize: 12
            enabled: popups.shell.compact && !popups.shell.reducedPetMotion
            onTriggered: popups.pet.rest(true)
        }
        MenuItem {
            objectName: "petMotionMenuItem"
            text: qsTr("减少动态")
            font.pixelSize: 12
            checkable: true
            checked: popups.shell.reducedPetMotion
            onTriggered: popups.shell.reducedPetMotion = checked
        }
        MenuItem {
            text: qsTr("素材协议 · 非商用")
            font.pixelSize: 12
            onTriggered: Qt.openUrlExternally("https://github.com/PC2005-cloud/dsh-pet/blob/86181ce1660a57ab27336630bab5b344de71b28c/README.md#%E8%AE%B8%E5%8F%AF")
        }
        MenuSeparator {}
        MenuItem {
            id: quitItem
            objectName: "quitMenuItem"
            text: qsTr("退出")
            implicitWidth: 144
            implicitHeight: 30
            contentItem: Text {
                text: quitItem.text
                color: Theme.danger
                font.pixelSize: 12
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: 6
                color: quitItem.hovered ? "#FEF2F2" : "transparent"
            }
            onTriggered: popups.shell.requestQuit()
        }
    }
}
