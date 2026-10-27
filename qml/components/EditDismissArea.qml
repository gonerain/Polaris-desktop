pragma ComponentBehavior: Bound

import QtQuick

// A passive tap observer: it never steals clicks or drags from controls.
Item {
    id: area
    z: 1000

    function controlAt(item, point) {
        if (!item.visible || !item.enabled || item.opacity === 0)
            return false
        const local = item.mapFromItem(area, point.x, point.y)
        if (item.clip && !item.contains(local)) return false
        if (item.editBoundary === true && item.contains(local))
            return true
        const children = item.children
        for (let i = 0; i < children.length; ++i) {
            if (controlAt(children[i], point)) return true
        }
        return false
    }
    function dismiss(item) {
        if (!item.visible || !item.enabled) return
        if (typeof item.dismissEditors === "function") item.dismissEditors()
        const children = item.children
        for (let i = 0; i < children.length; ++i) dismiss(children[i])
    }
    TapHandler {
        parent: area.parent
        acceptedButtons: Qt.LeftButton
        gesturePolicy: TapHandler.DragThreshold
        onTapped: function(eventPoint) {
            if (area.controlAt(area.parent, eventPoint.position)) return
            area.parent.forceActiveFocus()
            area.dismiss(area.parent)
        }
    }
}
