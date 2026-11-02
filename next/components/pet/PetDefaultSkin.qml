import QtQuick

Item {
    property string action: "idle"
    property int requestId: 0
    signal finished(int requestId)
    property var actions: ({idle: "idle"})
    property var idleAnimations: []
    // A static envelope covers the existing floating animation without alpha readback.
    property var inputRegions: [
        {x: 64, y: 148, width: 152, height: 123, radius: 56},
        {x: 40, y: 204, width: 55, height: 51, radius: 12},
        {x: 185, y: 204, width: 55, height: 51, radius: 12}
    ]
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
}
