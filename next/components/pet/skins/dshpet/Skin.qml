import QtQuick
import QtQuick.Window
import "Clips.js" as PetClips

// PC2005-cloud/dsh-pet artwork, CC BY-NC-SA 4.0; see ATTRIBUTION.md.
// Only the skin lives here: no old business, menu or sleep state machine.
Item {
    id: skin
    property string action: "idle"
    property int requestId: 0
    signal finished(int requestId)
    property var actions: ({idle:"idle",hoverEnter:"wave",press:"press",dragLift:"lift",drag:"drag",drop:"drop"})
    property var idleAnimations: ["stretch", "puzzle", "glance", "drowsy"]
    property int idleInterval: 32000
    property bool active: visible && !!Window.window && Window.window.visible
    property real squash: 1
    property real lift: 0
    property int playbackRequest: -1
    property int animationRequest: -1
    property int previousFrame: -1
    property bool cycleArmed: false
    property bool starting: false
    property string clipName: "idle"
    property bool staticPose: false
    // Alpha >16 envelope of all selected frames, rendered at 200x200, with
    // drag lift/squash and press/settle endpoints; 16px bands plus 2px padding.
    // Static geometry, so animation does not read pixels or update the mask.
    property var envelope: [
        {x:62,y:-1,width:47,height:20}, {x:58,y:15,width:76,height:20},
        {x:51,y:31,width:92,height:20}, {x:46,y:47,width:102,height:20},
        {x:39,y:63,width:122,height:20}, {x:35,y:79,width:128,height:20},
        {x:32,y:95,width:137,height:20}, {x:32,y:111,width:141,height:20},
        {x:28,y:127,width:141,height:20}, {x:27,y:143,width:144,height:20},
        {x:27,y:159,width:143,height:20}, {x:63,y:175,width:99,height:20}
    ]
    property var inputRegions: envelope.map(function(r) {
        return {x: (skin.width-200)/2+r.x, y:skin.height-208+r.y, width:r.width, height:r.height}
    })
    function armCycle() {
        if (!starting && active && !staticPose && playbackRequest === requestId && frames.status === Image.Ready && !cycleArmed) {
            previousFrame = frames.currentFrame
            cycleArmed = true
            frames.playing = true
        }
    }
    function playRequest() {
        cycleArmed = false; starting = true
        frames.playing = false
        pressMotion.stop(); liftMotion.stop(); settle.stop()
        playbackRequest = requestId; animationRequest = requestId
        squash = 1; lift = 0
        staticPose = action === "press" || action === "drop" || action === "lift"
        if (!active) { starting = false; return }
        if (action === "press") { starting = false; pressMotion.restart(); return }
        if (action === "lift") { squash = 0.96; starting = false; liftMotion.restart(); return }
        if (action === "drop") { starting = false; settle.restart(); return }
        if (action === "drag") { squash = 0.96; lift = -4 }
        clipName = PetClips.clips[action] && action !== "drop" ? action : "idle"
        frames.source = Qt.resolvedUrl(PetClips.clips[clipName].file)
        frames.currentFrame = 0
        starting = false
        armCycle()
    }
    onRequestIdChanged: playRequest()
    onActiveChanged: {
        if (active) playRequest()
        else {
            cycleArmed = false; frames.playing = false
            pressMotion.stop(); liftMotion.stop(); settle.stop()
        }
    }
    Item {
        x: (parent.width-width)/2; y: parent.height-208+skin.lift
        width: 200; height: 200
        transform: Scale { origin.x:100; origin.y:184; xScale:skin.squash; yScale:1/skin.squash }
        Image { anchors.fill:parent; visible:skin.staticPose; source:Qt.resolvedUrl("poster.webp"); fillMode:Image.PreserveAspectFit; smooth:true }
        AnimatedImage {
            id: frames; objectName:"dshSkinFrames"
            anchors.fill:parent; visible:!skin.staticPose
            source:Qt.resolvedUrl("idle.webp")
            playing:false; cache:false; fillMode:Image.PreserveAspectFit; smooth:true
            onStatusChanged: if (status === Image.Ready) skin.armCycle()
            onCurrentFrameChanged: {
                var wrapped = skin.previousFrame >= 0 && currentFrame < skin.previousFrame
                skin.previousFrame = currentFrame
                if (!skin.cycleArmed || skin.playbackRequest !== skin.requestId || !skin.active) return
                if (wrapped && skin.clipName !== "idle" && skin.clipName !== "drag") {
                    var completed = skin.playbackRequest
                    skin.cycleArmed = false; playing = false
                    skin.finished(completed)
                }
            }
        }
    }
    NumberAnimation {
        id: pressMotion; target:skin; property:"squash"; from:1; to:0.96; duration:100
        onFinished: if (skin.active && skin.animationRequest === skin.requestId) skin.finished(skin.animationRequest)
    }
    NumberAnimation {
        id: liftMotion; target:skin; property:"lift"; from:0; to:-4; duration:140
        onFinished: if (skin.active && skin.animationRequest === skin.requestId) skin.finished(skin.animationRequest)
    }
    SequentialAnimation {
        id: settle
        NumberAnimation { target:skin; property:"squash"; from:1.06; to:0.98; duration:120 }
        NumberAnimation { target:skin; property:"squash"; to:1; duration:200; easing.type:Easing.OutCubic }
        onFinished: if (skin.active && skin.animationRequest === skin.requestId) skin.finished(skin.animationRequest)
    }
}
