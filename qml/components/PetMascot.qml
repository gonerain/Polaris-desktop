import QtQuick
import "../../assets/dsh-pet/Clips.js" as PetClips

// PC2005-cloud/dsh-pet artwork: non-commercial, CC BY-NC-SA character.
// Source, authors and conversion details: assets/dsh-pet/ATTRIBUTION.md.
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
    property real squash: 1
    property real dragLean: 0
    property double lastGreeting: 0
    property double lastInteraction: Date.now()
    property int activityIndex: 0
    property real lift: dragging && !reducedMotion ? -4 : 0
    readonly property var clips: PetClips.clips
    readonly property var clip: clips[action]
    readonly property string frameName: active && !reducedMotion ? clip.file : "poster.webp"
    readonly property bool waving: action === "wave"

    implicitWidth: 180
    implicitHeight: 180
    onActiveChanged: if (ready)
        reset()
    onReducedMotionChanged: if (ready)
        reset()
    onDraggingChanged: {
        if (!ready || !active || reducedMotion)
            return;
        lastInteraction = Date.now();
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
    AnimatedImage {
        id: mascot
        objectName: "petFrameImage"
        anchors.fill: parent
        source: Qt.resolvedUrl("../../assets/dsh-pet/" + root.frameName)
        playing: root.active && !root.reducedMotion && root.action !== "drop"
        // Decode current frames rather than retaining whole decoded clips in RAM.
        cache: false
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        transform: [
            Translate {
                y: root.lift
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
            root.lastInteraction = Date.now();
            if (hovered) {
                sleepTimer.stop();
                activityTimer.stop();
                if (root.action === "sleep" || root.action === "drowsy")
                    root.play("wake");
                else if (root.action === "idle")
                    root.playWave();
            } else if (root.action === "idle")
                root.scheduleIdleTimers();
        }
    }
    Timer {
        id: actionTimer
        objectName: "petActionTimer"
        onTriggered: root.advanceFrame()
    }
    Timer {
        id: sleepTimer
        objectName: "petSleepTimer"
        onTriggered: if (!petHover.hovered)
            root.rest(false)
    }
    Timer {
        id: activityTimer
        objectName: "petActivityTimer"
        onTriggered: root.playActivity(false)
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
        lastInteraction = Date.now();
        actionTimer.stop();
        sleepTimer.stop();
        activityTimer.stop();
        settle.stop();
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
        actionTimer.stop();
        sleepTimer.stop();
        activityTimer.stop();
        action = name;
        mascot.currentFrame = 0;
        if (active && !reducedMotion && name !== "idle" && name !== "sleep" && name !== "drag") {
            actionTimer.interval = clip.duration;
            actionTimer.restart();
        }
    }
    function scheduleIdleTimers() {
        if (!active || reducedMotion || petHover.hovered || action !== "idle")
            return;
        const remaining = Math.max(1, 60000 - (Date.now() - lastInteraction));
        sleepTimer.interval = remaining;
        sleepTimer.restart();
        activityTimer.interval = 32000 + Math.round(Math.random() * 12000);
        if (remaining > activityTimer.interval + 8000)
            activityTimer.restart();
    }
    function startIdle() {
        if (celebrationPending && Date.now() > pendingUntil)
            celebrationPending = false;
        if (active && celebrationPending && !reducedMotion && !dragging) {
            celebrate();
            return;
        }
        play("idle");
        scheduleIdleTimers();
    }
    function playWave(force) {
        if (!active || reducedMotion || dragging || action === "complete" || waving)
            return;
        if (force) {
            restingByRequest = false;
            lastGreeting = 0;
            lastInteraction = Date.now();
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
    function playActivity(manual) {
        if (!active || reducedMotion || dragging || action === "complete")
            return;
        if (!manual && (petHover.hovered || action !== "idle"))
            return;
        if (manual)
            lastInteraction = Date.now();
        restingByRequest = false;
        const actions = ["stretch", "puzzle", "glance"];
        play(actions[activityIndex % actions.length]);
        activityIndex += 1;
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
        if (action === "drowsy")
            play("sleep");
        else if (action === "wake") {
            lastGreeting = 0;
            playWave();
        } else
            startIdle();
    }
}
