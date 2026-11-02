import QtQuick
Item {
    id: skin
    objectName: "petSkinTwo"
    property string action: "restTwo"
    property int requestId: 0
    signal finished(int requestId)
    property var actions: ({idle:"restTwo",press:"pressTwo",drag:"dragTwo",drop:"dropTwo"})
    property var idleAnimations: []
    property var inputRegions: [{x:10,y:25,width:90,height:100,radius:20}]
    property string observedAction: ""
    property int starts: 0
    property int animationRequestId: 0
    onRequestIdChanged: {
        observedAction = action
        starts++
        movement.stop()
        if (action === "pressTwo") { animationRequestId = requestId; movement.restart() }
    }
    Rectangle { id: visual; objectName:"skinVisualTwo"; x:10; y:25; width:90; height:100; radius:20; color:"#bb7650" }
    NumberAnimation { id: movement; target:visual; property:"opacity"; from:1; to:0.8; duration:40; onFinished: skin.finished(skin.animationRequestId) }
}
