pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import "Theme.js" as Theme

Tumbler {
    id: wheel
    visibleItemCount: 5
    // Control.wheelEnabled only consumes the event; Tumbler does not step it.
    // Handle actual mouse wheels and high-resolution touchpad deltas explicitly.
    wheelEnabled: false
    property real wheelRemainder: 0
    WheelHandler {
        target: null
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(event) {
            const delta = event.angleDelta.y !== 0
                ? event.angleDelta.y / 120 : event.pixelDelta.y / 30
            if (delta === 0) return
            wheel.wheelRemainder += delta
            const steps = wheel.wheelRemainder > 0
                ? Math.floor(wheel.wheelRemainder) : Math.ceil(wheel.wheelRemainder)
            if (steps !== 0 && wheel.count > 0) {
                wheel.currentIndex = ((wheel.currentIndex - steps) % wheel.count + wheel.count) % wheel.count
                wheel.wheelRemainder -= steps
                wheel.positionViewAtIndex(wheel.currentIndex, Tumbler.Center)
            }
            event.accepted = true
        }
    }
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
