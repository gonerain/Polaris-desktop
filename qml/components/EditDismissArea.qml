pragma ComponentBehavior: Bound

import QtQuick

// A passive tap observer: it never steals clicks or drags from controls.
Item {
    id: area
    z: 1000

    // Containment for keeping an editor panel open is intentionally broader
    // than containment for retaining text-input focus.
    function boundaryAt(item, point, propertyName) {
        if (!item.visible || !item.enabled || item.opacity === 0)
            return false
        const local = item.mapFromItem(area, point.x, point.y)
        if (item.clip && !item.contains(local)) return false
        if (item[propertyName] === true && item.contains(local))
            return true
        const children = item.children
        for (let i = 0; i < children.length; ++i) {
            if (boundaryAt(children[i], point, propertyName)) return true
        }
        return false
    }
    function blurOutsideInput(point) {
        if (!boundaryAt(area.parent, point, "editFocusBoundary"))
            area.parent.forceActiveFocus()
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
        onPressedChanged: {
            // Commit/blur before a button's action, not after its model may
            // have removed or rebuilt the active delegate.
            if (pressed) area.blurOutsideInput(point.position)
        }
        onTapped: function(eventPoint) {
            area.blurOutsideInput(eventPoint.position)
            if (!area.boundaryAt(area.parent, eventPoint.position, "editBoundary"))
                area.dismiss(area.parent)
        }
    }
}
