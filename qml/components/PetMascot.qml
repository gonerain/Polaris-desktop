import QtQuick

// Artwork and idle/wave sequence adapted from Er1c0v0/dsh-whale-pet.
// See assets/whale/ATTRIBUTION.md (CC BY 4.0 artwork, MIT reference code).
Item {
    id: root

    property bool active: true
    property bool reducedMotion: false
    property bool dragging: false
    property bool celebrationPending: false
    property double pendingUntil: 0
    property bool ready: false
    property bool restingByRequest: false
    property string action: "idle"
    property int frameIndex: 0
    property real bobOffset: 0
    property real squash: 1
    property real dragLean: 0
    property double lastGreeting: 0
    readonly property var clips: ({
            idle: [
                {
                    name: "idle_pillow_awake",
                    duration: 3400
                },
                {
                    name: "idle_pillow_blink",
                    duration: 130
                },
                {
                    name: "idle_pillow_awake",
                    duration: 2400
                },
                {
                    name: "idle_pillow_blink",
                    duration: 110
                }
            ],
            wave: [
                {
                    name: "idle_pillow_awake",
                    duration: 80
                },
                {
                    name: "idle_pillow_wave_1",
                    duration: 140
                },
                {
                    name: "idle_pillow_wave_2",
                    duration: 220
                },
                {
                    name: "idle_pillow_wave_1",
                    duration: 140
                },
                {
                    name: "idle_pillow_awake",
                    duration: 120
                }
            ],
            drowsy: [
                {
                    name: "idle_pillow_drowsy",
                    duration: 800
                }
            ],
            sleep: [
                {
                    name: "idle_pillow_sleep",
                    duration: 0
                }
            ],
            wake: [
                {
                    name: "idle_pillow_startle",
                    duration: 420
                }
            ],
            drag: [
                {
                    name: "idle_pillow_startle",
                    duration: 0
                }
            ],
            drop: [
                {
                    name: "idle_pillow_blink",
                    duration: 180
                },
                {
                    name: "idle_pillow_awake",
                    duration: 220
                }
            ],
            complete: [
                {
                    name: "ready_0",
                    duration: 130
                },
                {
                    name: "ready_1",
                    duration: 130
                },
                {
                    name: "ready",
                    duration: 280
                },
                {
                    name: "ready_3",
                    duration: 140
                },
                {
                    name: "ready_4",
                    duration: 280
                }
            ]
        })
    readonly property var clip: clips[action]
    readonly property string frameName: clip[Math.min(frameIndex, clip.length - 1)].name
    readonly property bool waving: action === "wave"
    property real lift: dragging && !reducedMotion ? -4 : 0

    implicitWidth: 180
    implicitHeight: 180
    onActiveChanged: if (ready)
        reset()
    onReducedMotionChanged: if (ready)
        reset()
    onDraggingChanged: {
        if (!ready || !active || reducedMotion)
            return;
        if (dragging) {
            restingByRequest = false;
            settle.stop();
            squash = 0.96;
            play("drag");
        } else {
            dragLean = 0;
            play("drop");
            settle.restart();
        }
    }
    Behavior on dragLean {
        enabled: root.active && !root.reducedMotion
        NumberAnimation {
            duration: 100
            easing.type: Easing.OutCubic
        }
    }
    Behavior on lift {
        enabled: root.active && !root.reducedMotion
        NumberAnimation {
            duration: 140
            easing.type: Easing.OutCubic
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        width: 76
        height: 9
        radius: 4.5
        color: "#26000000"
        opacity: root.dragging && !root.reducedMotion ? 0.25 : 0.55
        Behavior on opacity {
            enabled: root.active && !root.reducedMotion
            NumberAnimation {
                duration: 150
            }
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
        transform: [
            Translate {
                y: root.bobOffset + root.lift
            },
            Rotation {
                origin.x: root.width / 2
                origin.y: root.height - 16
                angle: root.dragLean
            },
            Scale {
                origin.x: root.width / 2
                origin.y: root.height - 16
                xScale: root.squash
                yScale: 1 / root.squash
            }
        ]
    }
    HoverHandler {
        id: petHover
        objectName: "petHoverHandler"
        enabled: root.active
        cursorShape: root.dragging ? Qt.ClosedHandCursor : Qt.PointingHandCursor
        onHoveredChanged: {
            if (!root.ready || !root.active || root.reducedMotion || root.dragging || root.restingByRequest)
                return;
            if (hovered) {
                if (root.action === "sleep" || root.action === "drowsy")
                    root.play("wake");
                else
                    root.playWave();
            } else if (root.action === "idle")
                sleepTimer.restart();
        }
    }
    Timer {
        id: frameTimer
        objectName: "petFrameTimer"
        onTriggered: root.advanceFrame()
    }
    Timer {
        id: sleepTimer
        objectName: "petSleepTimer"
        interval: 60000
        onTriggered: root.rest()
    }
    SequentialAnimation {
        id: breathe
        objectName: "petBreathingAnimation"
        loops: Animation.Infinite
        running: root.active && !root.reducedMotion && root.action !== "drag" && root.action !== "complete"
        NumberAnimation {
            target: root
            property: "bobOffset"
            from: 0
            to: root.action === "sleep" ? -1 : -2
            duration: 2400
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: root
            property: "bobOffset"
            to: 0
            duration: 2400
            easing.type: Easing.InOutSine
        }
    }
    SequentialAnimation {
        id: settle
        NumberAnimation {
            target: root
            property: "squash"
            from: 1.06
            to: 0.98
            duration: 120
        }
        NumberAnimation {
            target: root
            property: "squash"
            to: 1
            duration: 200
            easing.type: Easing.OutCubic
        }
    }

    Component.onCompleted: {
        ready = true;
        reset();
    }

    function reset() {
        restingByRequest = false;
        frameTimer.stop();
        sleepTimer.stop();
        settle.stop();
        bobOffset = 0;
        squash = 1;
        dragLean = 0;
        if (reducedMotion)
            celebrationPending = false;
        if (active && dragging && !reducedMotion)
            play("drag");
        else
            startIdle();
    }
    function play(name) {
        frameTimer.stop();
        sleepTimer.stop();
        action = name;
        frameIndex = 0;
        scheduleFrame();
    }
    function scheduleFrame() {
        if (!active || reducedMotion || clip[frameIndex].duration === 0)
            return;
        frameTimer.interval = clip[frameIndex].duration;
        frameTimer.restart();
    }
    function startIdle() {
        if (celebrationPending && Date.now() > pendingUntil)
            celebrationPending = false;
        if (active && celebrationPending && !reducedMotion && !dragging) {
            celebrate();
            return;
        }
        play("idle");
        if (active && !reducedMotion && !petHover.hovered)
            sleepTimer.restart();
    }
    function playWave(force) {
        if (!active || reducedMotion || dragging || action === "complete" || waving)
            return;
        if (force) {
            restingByRequest = false;
            lastGreeting = 0;
        }
        if (action === "sleep" || action === "drowsy") {
            play("wake");
            return;
        }
        if (Date.now() - lastGreeting < 12000)
            return;
        lastGreeting = Date.now();
        play("wave");
    }
    function rest(manual) {
        if (!active || reducedMotion || dragging || action === "complete")
            return;
        restingByRequest = !!manual;
        if (action !== "sleep")
            play("drowsy");
    }
    function celebrate() {
        if (reducedMotion)
            return;
        if (!active || dragging) {
            celebrationPending = true;
            pendingUntil = Date.now() + 120000;
            return;
        }
        if (action === "complete")
            return;
        celebrationPending = false;
        restingByRequest = false;
        play("complete");
    }
    function lean(delta) {
        if (dragging && !reducedMotion)
            dragLean = Math.max(-6, Math.min(6, delta / 3));
    }
    function advanceFrame() {
        if (frameIndex + 1 < clip.length) {
            frameIndex += 1;
            scheduleFrame();
        } else if (action === "idle") {
            frameIndex = 0;
            scheduleFrame();
        } else if (action === "drowsy")
            play("sleep");
        else if (action === "wake") {
            lastGreeting = 0;
            playWave();
        } else
            startIdle();
    }
}
