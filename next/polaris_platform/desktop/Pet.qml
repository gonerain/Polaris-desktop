import QtQuick
import QtQuick.Controls
Rectangle {
    id: root
    color: 'transparent'
    property string message: ''
    property string displayMessage: (typeof petActions !== 'undefined' && petActions && petActions.notice) ? petActions.notice : message
    Rectangle {
        visible: root.displayMessage.length > 0
        x: 20; y: 20; width: parent.width - 40; height: 90; radius: 18
        color: 'white'; border.color: '#dce3ef'
        ScrollView {
            id: bubbleScroll; objectName: 'bubbleScroll'
            anchors.fill: parent; anchors.margins: 12; clip: true
            Text { objectName: 'petMessage'; width: bubbleScroll.availableWidth; text: root.displayMessage; textFormat: Text.PlainText
                wrapMode: Text.Wrap; color: '#344762'; font.pixelSize: 15 }
        }
    }
    Rectangle {
        id: body; x: 65; y: 155; width: 150; height: 115; radius: 55; color: '#728be8'
        SequentialAnimation on y {
            loops: Animation.Infinite
            NumberAnimation { to: 149; duration: 1500 }
            NumberAnimation { to: 155; duration: 1500 }
        }
        Rectangle { x: 35; y: 36; width: 12; height: 16; radius: 6; color: '#182848' }
        Rectangle { x: 102; y: 36; width: 12; height: 16; radius: 6; color: '#182848' }
        Text { x: 66; y: 55; text: '⌣'; font.pixelSize: 30; color: '#182848' }
        Rectangle { x: -20; y: 65; width: 45; height: 25; radius: 12; rotation: -25; color: '#728be8' }
        Rectangle { x: 125; y: 65; width: 45; height: 25; radius: 12; rotation: 25; color: '#728be8' }
    }
        MouseArea {
            id: petHitArea; objectName: 'petHitArea'; x: 45; y: 145; width: 190; height: 135
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            preventStealing: true
            property point pressGlobal
            property bool moved: false
            onPressed: function(mouse) {
                pressGlobal = petActions.pointerPosition()
                moved = false
                if (mouse.button === Qt.LeftButton) petActions.beginDrag(pressGlobal.x, pressGlobal.y)
            }
            onPositionChanged: function(mouse) {
                if (!pressed || !(pressedButtons & Qt.LeftButton)) return
                let point = petActions.pointerPosition()
                if (Math.abs(point.x - pressGlobal.x) + Math.abs(point.y - pressGlobal.y) > 7) moved = true
                if (moved) petActions.dragTo(point.x, point.y)
            }
            onReleased: function(mouse) {
                if (mouse.button === Qt.RightButton) {
                    let point = mapToItem(root, mouse.x, mouse.y)
                    petMenu.popup(point.x, point.y)
                } else {
                    if (moved) {
                        let point = petActions.pointerPosition()
                        petActions.dragTo(point.x, point.y)
                    }
                    petActions.endDrag()
                    if (!moved) petActions.activate()
                }
            }
            onCanceled: petActions.endDrag()
        }
    Menu {
        id: petMenu; objectName: 'petMenu'
        MenuItem { objectName: 'managePetMenuItem'; text: '组件管理'; onTriggered: petActions.management() }
        MenuItem { objectName: 'quitPetMenuItem'; text: '退出'; onTriggered: petActions.quit() }
    }
}
