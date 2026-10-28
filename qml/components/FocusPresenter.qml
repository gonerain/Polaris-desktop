pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic

// A window-level presentation layer, deliberately independent of panel allocation.
Item {
    id: presenter
    required property var targetWindow
    required property rect availableGeometry
    property bool active: false
    property bool preparing: false
    property bool returning: false
    property real progress: 0
    property var savedGeometry: null
    property var targetGeometry: null
    property rect sourceRect
    property var sourceHandle: null
    property Item view: null
    property url snapshotUrl: ""
    readonly property bool busy: preparing || active
    readonly property bool transitioning: preparing || motion.running
    signal opened()
    signal closed()
    signal failed(string reason)
    visible: active
    z: 100

    function open(handle, factory, options, properties) {
        if (busy || !handle || !handle.host || !factory || factory.status !== Component.Ready)
            return false
        const size = options && options.size ? options.size : Qt.size(0, 0)
        if (!isFinite(size.width) || !isFinite(size.height) || size.width < 0 || size.height < 0)
            return false
        const available = availableGeometry
        const maxWidth = available.width
        const maxHeight = available.height
        if (maxWidth <= 0 || maxHeight <= 0)
            return false
        savedGeometry = Qt.rect(targetWindow.x, targetWindow.y, targetWindow.width, targetWindow.height)
        const width = Math.min(maxWidth, Math.max(targetWindow.minimumWidth, size.width || savedGeometry.width))
        const height = Math.min(maxHeight, Math.max(targetWindow.minimumHeight, size.height || savedGeometry.height))
        // The usable origin can differ from the monitor origin (top/left taskbars).
        const left = available.x
        const top = available.y
        targetGeometry = Qt.rect(Math.max(left, Math.min(savedGeometry.x, left + maxWidth - width)),
                                 Math.max(top, Math.min(savedGeometry.y, top + maxHeight - height)), width, height)
        const origin = handle.host.mapToItem(presenter, 0, 0)
        sourceRect = Qt.rect(origin.x, origin.y, handle.host.width, handle.host.height)
        sourceHandle = handle
        preparing = true
        const accepted = handle.host.grabToImage(function(result) {
            if (!presenter.preparing)
                return
            presenter.snapshotUrl = result.url
            try {
                const object = factory.createObject(content, properties || {})
                const item = object as Item
                if (!item) {
                    if (object) object.destroy()
                    throw new Error("完整视图根对象必须是 Item")
                }
                presenter.view = item
                item.width = Qt.binding(function() { return content.width })
                item.height = Qt.binding(function() { return content.height })
                presenter.progress = 0
                presenter.returning = false
                presenter.active = true
                presenter.preparing = false
                item.forceActiveFocus()
                presenter.opened()
                motion.to = 1
                motion.start()
            } catch (error) {
                presenter.preparing = false
                presenter.sourceHandle = null
                presenter.snapshotUrl = ""
                presenter.failed(String(error))
            }
        })
        if (!accepted) {
            preparing = false
            sourceHandle = null
            failed("无法捕获组件过渡图像")
        }
        return accepted
    }

    function close() {
        if (!active || motion.running)
            return false
        // Move focus out of inline editors so their existing commit handlers run.
        forceActiveFocus()
        returning = true
        motion.to = 0
        motion.start()
        return true
    }

    function applyGeometry() {
        if (!active || !savedGeometry || !targetGeometry) return
        if (targetWindow.windowPositioningSupported) {
            targetWindow.x = Math.round(savedGeometry.x + (targetGeometry.x - savedGeometry.x) * progress)
            targetWindow.y = Math.round(savedGeometry.y + (targetGeometry.y - savedGeometry.y) * progress)
        }
        targetWindow.width = Math.round(savedGeometry.width + (targetGeometry.width - savedGeometry.width) * progress)
        targetWindow.height = Math.round(savedGeometry.height + (targetGeometry.height - savedGeometry.height) * progress)
    }
    onProgressChanged: applyGeometry()

    NumberAnimation {
        id: motion
        target: presenter
        property: "progress"
        duration: 320
        easing.type: Easing.InOutCubic
        onFinished: {
            if (presenter.returning) {
                if (presenter.view) presenter.view.destroy()
                presenter.view = null
                presenter.active = false
                presenter.returning = false
                presenter.snapshotUrl = ""
                presenter.sourceHandle = null
                presenter.closed()
            }
        }
    }

    // Interpolated shell: controls are cross-faded, never stretched as live UI.
    Item {
        id: shell
        x: presenter.sourceRect.x * (1 - presenter.progress)
        y: presenter.sourceRect.y * (1 - presenter.progress)
        width: presenter.sourceRect.width + (presenter.width - presenter.sourceRect.width) * presenter.progress
        height: presenter.sourceRect.height + (presenter.height - presenter.sourceRect.height) * presenter.progress
        clip: true
        Image {
            anchors.fill: parent
            source: presenter.snapshotUrl
            opacity: 1 - Math.max(0, (presenter.progress - 0.25) / 0.75)
        }
        Rectangle {
            anchors.fill: parent
            color: "#FFFFFF"
            radius: 12
            opacity: presenter.progress
        }
        Item {
            id: content
            anchors.fill: parent
            opacity: Math.max(0, (presenter.progress - 0.35) / 0.65)
            enabled: !presenter.transitioning
            readonly property var presentationContext: ({ close: function() { return presenter.close() } })
        }
    }
    // Block input to the underlying board throughout transitions.
    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.AllButtons
        onWheel: function(wheel) { wheel.accepted = true }
    }
    Shortcut {
        sequence: "Escape"
        enabled: presenter.active && !presenter.transitioning
                 && !(presenter.targetWindow.editorPopupCount > 0)
                 && !(presenter.view && presenter.view.escapeBlocked === true)
        onActivated: presenter.close()
    }
}
