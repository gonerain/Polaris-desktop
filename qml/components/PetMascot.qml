import QtQuick

Item {
    id: root

    readonly property var idleFrames: [
        { name: "idle_pillow_awake", duration: 3400 },
        { name: "idle_pillow_blink", duration: 130 },
        { name: "idle_pillow_awake", duration: 2400 },
        { name: "idle_pillow_blink", duration: 110 }
    ]

    readonly property var waveFrames: [
        { name: "idle_pillow_awake", duration: 80 },
        { name: "idle_pillow_wave_1", duration: 140 },
        { name: "idle_pillow_wave_2", duration: 220 },
        { name: "idle_pillow_wave_1", duration: 140 },
        { name: "idle_pillow_awake", duration: 120 }
    ]

    property int idleIndex: 0
    property int waveIndex: 0
    property bool waving: false
    property string frameName: "idle_pillow_awake"
    property real bobOffset: 0

    implicitWidth: 180
    implicitHeight: 180
    transformOrigin: Item.Bottom
    scale: petHover.hovered ? 1.02 : 1

    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        id: shadow
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        width: 76
        height: 9
        radius: 4.5
        color: "#26000000"
        opacity: petHover.hovered ? 0.75 : 0.55
        scale: petHover.hovered ? 1.04 : 1

        Behavior on opacity {
            NumberAnimation { duration: 150 }
        }

        Behavior on scale {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }
    }

    Image {
        id: mascot
        objectName: "petFrameImage"
        anchors.fill: parent
        source: Qt.resolvedUrl("../../assets/whale/" + root.frameName + ".webp")
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        cache: true
        asynchronous: false
        transform: Translate { y: root.bobOffset }
    }

    HoverHandler {
        id: petHover

        cursorShape: Qt.PointingHandCursor

        onHoveredChanged: {
            if (hovered)
                root.playWave()
        }
    }

    Timer {
        id: frameTimer
        repeat: false
        interval: 3400
        onTriggered: root.advanceFrame()
    }

    SequentialAnimation {
        loops: Animation.Infinite
        running: true

        NumberAnimation {
            target: root
            property: "bobOffset"
            from: 0
            to: -3
            duration: 2200
            easing.type: Easing.InOutSine
        }

        NumberAnimation {
            target: root
            property: "bobOffset"
            from: -3
            to: 0
            duration: 2200
            easing.type: Easing.InOutSine
        }
    }

    Component.onCompleted: root.startIdle()

    function showFrame(frame) {
        root.frameName = frame.name
        frameTimer.interval = frame.duration
        frameTimer.restart()
    }

    function startIdle() {
        root.waving = false
        root.idleIndex = 0
        root.showFrame(root.idleFrames[0])
    }

    function playWave() {
        if (root.waving)
            return
        root.waving = true
        root.waveIndex = 0
        root.showFrame(root.waveFrames[0])
    }

    function advanceFrame() {
        if (root.waving) {
            root.waveIndex += 1
            if (root.waveIndex >= root.waveFrames.length) {
                root.startIdle()
                return
            }
            root.showFrame(root.waveFrames[root.waveIndex])
            return
        }

        root.idleIndex = (root.idleIndex + 1) % root.idleFrames.length
        root.showFrame(root.idleFrames[root.idleIndex])
    }
}
