import QtQuick
Item {
    id: skin
    objectName: "petSkinOne"
    property string action: "restOne"
    property int requestId: 0
    signal finished(int requestId)
    property var actions: ({idle:"restOne",hoverEnter:"greetOne",hoverLeave:"leaveOne",press:"pressOne",release:"releaseOne",dragLift:"liftOne",drag:"dragOne",drop:"dropOne"})
    property var idleAnimations: { var values = []; for (var i=0;i<40;i++) values.push("idleOne_"+i); return values }
    property int idleInterval: 60000
    property var inputRegions: [{x:90,y:150,width:100,height:120,radius:30}]
    property string observedAction: ""
    property int starts: 0
    property int animationRequestId: 0
    onRequestIdChanged: {
        observedAction = action
        starts++
        movement.stop()
        if (action === "pressOne") { animationRequestId = requestId; movement.restart() }
    }
    Rectangle { id: visual; objectName:"skinVisualOne"; x:90; y:150; width:100; height:120; radius:30; color:"#5964b8" }
    NumberAnimation { id: movement; target:visual; property:"opacity"; from:1; to:0.6; duration:40; onFinished: skin.finished(skin.animationRequestId) }
}
