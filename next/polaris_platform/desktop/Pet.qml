import QtQuick
import QtQuick.Controls
import QtQuick.Window
Rectangle {
    id: root
    color: 'transparent'
    property string message: ''
    property int menuRegionEpoch: 0
    property var inputRegions: {
        var regions = skinRegions.slice()
        if (messageBubble.visible)
            regions.push({x: messageBubble.x - 1, y: messageBubble.y - 1,
                width: messageBubble.width + 2, height: messageBubble.height + 2, radius: 19})
        if (petMenu.visible && petMenu.background) {
            var background = petMenu.background
            // Read geometry dependencies before mapping the actual Item popup.
            var geometry = background.x + background.y + petMenu.x + petMenu.y + root.width + root.height + root.menuRegionEpoch
            var point = background.mapToItem(root, 0, 0)
            regions.push({x: point.x - 1, y: point.y - 1,
                width: background.width + 2, height: background.height + 2, radius: 0})
        }
        return regions
    }
    function containsRegions(regions, point) {
        return regions.some(function(r) {
            if (point.x < r.x || point.x >= r.x + r.width || point.y < r.y || point.y >= r.y + r.height) return false
            var radius = r.radius || 0
            var dx = Math.max(r.x + radius - point.x, 0, point.x - (r.x + r.width - radius))
            var dy = Math.max(r.y + radius - point.y, 0, point.y - (r.y + r.height - radius))
            return dx * dx + dy * dy <= radius * radius
        })
    }
    function containsInput(point) { return containsRegions(inputRegions, point) }
    // This non-activating Item popup cannot rely on WindowDeactivated.
    // Only while open, observe the existing cursor API; re-entry cancels dismissal.
    Timer {
        interval: 40; repeat: true; running: petMenu.visible
        onRunningChanged: if (!running) menuDismiss.stop()
        onTriggered: {
            var global = petActions.pointerPosition()
            var point = root.mapFromGlobal(global.x, global.y)
            if (root.containsInput(point)) menuDismiss.stop()
            else if (!menuDismiss.running) menuDismiss.start()
        }
    }
    Timer { id: menuDismiss; interval: 160; onTriggered: petMenu.close() }
    Connections {
        target: root.Window.window
        function onVisibleChanged(visible) { if (!visible) { petMenu.close(); root.cancelInteraction() } }
    }
    property string displayMessage: skinError || ((typeof petActions !== 'undefined' && petActions && petActions.notice) ? petActions.notice : message)
    property url skinSource: Qt.resolvedUrl("skins/dshpet/Skin.qml")
    property string skinError: ""
    property bool skinReady: false
    property string actionSlot: "idle"
    property string actionName: "idle"
    property int requestId: 0
    property int idleIndex: -1
    property bool bodyHovered: false
    property bool pressActive: false
    property bool dragging: false
    property var skinRegions: skinReady && skinLoader.item ? skinLoader.item.inputRegions || [] : []
    property var idleAnimations: skinReady && skinLoader.item ? skinLoader.item.idleAnimations || [] : []
    function requestAction(slot, animation) {
        var skin = skinLoader ? skinLoader.item : null
        var mapping = skin ? skin.actions || {} : {}
        actionSlot = typeof mapping[slot] === 'string' && mapping[slot] ? slot : "idle"
        actionName = animation || mapping[actionSlot] || "idle"
        requestId++
        if (skin && skinReady) {
            skin.action = actionName
            skin.requestId = requestId
        }
    }
    function resetActions() {
        dragging = false; pressActive = false; bodyHovered = false; idleIndex = -1
        if (petHitArea) petHitArea.moved = false
        requestAction("idle")
    }
    function cancelInteraction() {
        petActions.endDrag()
        resetActions()
    }
    function chooseIdle() {
        if (!idleAnimations.length) return
        idleIndex = Math.floor(Math.random() * idleAnimations.length)
        requestAction("idle", idleAnimations[idleIndex])
    }
    function bodyHit(point) {
        if (messageBubble.visible && point.x >= messageBubble.x && point.x < messageBubble.x + messageBubble.width
                && point.y >= messageBubble.y && point.y < messageBubble.y + messageBubble.height) return false
        return containsRegions(skinRegions, point)
    }
    function updateHover(point) {
        var inside = bodyHit(point)
        if (inside === bodyHovered) return
        bodyHovered = inside
        if (!pressActive && !dragging && !petMenu.visible) {
            idleIndex = -1
            requestAction(inside ? "hoverEnter" : "hoverLeave")
        }
    }
    function validSkin(skin) {
        return skin && typeof skin.action === 'string' && typeof skin.requestId === 'number'
            && skin.actions && typeof skin.actions.idle === 'string' && skin.actions.idle.length > 0
            && Array.isArray(skin.inputRegions) && skin.inputRegions.length > 0
            && skin.inputRegions.every(function(r) {
                return r && ['x','y','width','height'].every(function(key) { return typeof r[key] === 'number' && isFinite(r[key]) })
                    && r.width > 0 && r.height > 0
                    && (r.radius === undefined || typeof r.radius === 'number' && isFinite(r.radius) && r.radius >= 0)
            })
            && Array.isArray(skin.idleAnimations) && skin.idleAnimations.every(function(name) { return typeof name === 'string' && name.trim().length > 0 })
            && typeof skin.finished === 'function'
    }
    function fallbackSkin(reason) {
        skinReady = false
        if (String(skinSource) !== String(Qt.resolvedUrl("PetDefaultSkin.qml"))) {
            var failedSource = String(skinSource)
            Qt.callLater(function() {
                if (String(root.skinSource) !== failedSource) return
                root.skinSource = Qt.resolvedUrl("PetDefaultSkin.qml")
                root.skinError = reason + "，已使用备用外观"
            })
        } else skinError = reason
    }
    onSkinSourceChanged: {
        skinError = ""; skinReady = false
        if (petMenu) petMenu.close()
        cancelInteraction()
    }
    Loader {
        id: skinLoader; objectName: "petSkinLoader"
        anchors.fill: parent
        source: root.skinSource
        onLoaded: {
            if (!root.validSkin(item)) { root.fallbackSkin("皮肤接口无效"); return }
            root.skinReady = true
            root.resetActions()
        }
        onStatusChanged: {
            if (status !== Loader.Ready) root.skinReady = false
            if (status === Loader.Error) root.fallbackSkin("皮肤加载失败")
        }
    }
    Connections {
        target: skinLoader.item
        ignoreUnknownSignals: true
        function onFinished(id) {
            if (id !== root.requestId) return
            if (root.pressActive && !root.dragging) return
            root.idleIndex = -1
            root.requestAction(root.dragging ? "drag" : "idle")
        }
    }
    Timer {
        interval: skinLoader.item && skinLoader.item.idleInterval > 0 ? skinLoader.item.idleInterval : 8000
        repeat: true
        running: !!root.Window.window && root.Window.window.visible && root.actionSlot === "idle"
            && root.idleIndex < 0 && !root.bodyHovered && !root.pressActive && !root.dragging && !petMenu.visible && root.idleAnimations.length > 0
        onTriggered: root.chooseIdle()
    }
    MouseArea {
        id: petHitArea; objectName: 'petHitArea'; anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        preventStealing: true; hoverEnabled: true
        enabled: root.skinReady
        property point pressGlobal
        property bool moved: false
        onEntered: root.updateHover(Qt.point(mouseX, mouseY))
        onExited: root.updateHover(Qt.point(-1, -1))
        onPressed: function(mouse) {
            if (!root.bodyHit(Qt.point(mouse.x, mouse.y))) { mouse.accepted = false; return }
            pressGlobal = petActions.pointerPosition()
            moved = false; root.pressActive = true; root.idleIndex = -1
            root.requestAction("press")
            if (mouse.button === Qt.LeftButton) petActions.beginDrag(pressGlobal.x, pressGlobal.y)
        }
        onPositionChanged: function(mouse) {
            if (!pressed) { root.updateHover(Qt.point(mouse.x, mouse.y)); return }
            if (!(pressedButtons & Qt.LeftButton)) return
            let point = petActions.pointerPosition()
            if (!moved && Math.abs(point.x - pressGlobal.x) + Math.abs(point.y - pressGlobal.y) > 7) {
                moved = true; root.dragging = true
                var actions = skinLoader.item ? skinLoader.item.actions || {} : {}
                root.requestAction(actions.dragLift ? "dragLift" : "drag")
            }
            if (moved) petActions.dragTo(point.x, point.y)
        }
        onReleased: function(mouse) {
            if (!root.pressActive) return
            root.pressActive = false
            if (mouse.button === Qt.RightButton) {
                root.requestAction("release")
                let point = mapToItem(root, mouse.x, mouse.y)
                petMenu.popup(point.x, point.y)
            } else {
                if (moved) {
                    let point = petActions.pointerPosition()
                    petActions.dragTo(point.x, point.y)
                }
                root.dragging = false
                root.requestAction(moved ? "drop" : "release")
                petActions.endDrag()
                if (!moved) petActions.activate()
            }
        }
        onCanceled: root.cancelInteraction()
    }
    Rectangle {
        id: messageBubble
        objectName: 'petBubble'
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
    Menu {
        id: petMenu; objectName: 'petMenu'
        onOpened: root.menuRegionEpoch++
        // Qt 6.5 already uses Item popups; newer Qt may choose native windows.
        Component.onCompleted: if ('popupType' in petMenu) petMenu['popupType'] = 0
        MenuItem { objectName: 'managePetMenuItem'; text: '组件管理'; onTriggered: petActions.management() }
        MenuItem { objectName: 'quitPetMenuItem'; text: '退出'; onTriggered: petActions.quit() }
    }
}
