pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

Tumbler {
    id: wheel
    visibleItemCount: 5
    wheelEnabled: true
    clip: true
    background: Rectangle { color: Theme.background; radius: 8 }
    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
        height: parent.height / 5
        color: Theme.primarySoft
        radius: 6
        z: -1
    }
    delegate: Text {
        id: number
        required property int index
        text: String(index).padStart(2, "0")
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: index === wheel.currentIndex ? Theme.primary : Theme.muted
        font.pixelSize: index === wheel.currentIndex ? 22 : 15
        opacity: Math.max(0.25, 1 - Math.abs(Tumbler.displacement) * 0.25)
        TapHandler { onTapped: wheel.currentIndex = number.index }
    }
}
