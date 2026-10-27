pragma ComponentBehavior: Bound

import QtQuick

// Only handles collapsing editor panels. Text focus is handled once, at the window.
Item {
    id: area

    function controlAt(item, point) {
        if (!item.visible || !item.enabled || item.opacity === 0) return false
        const local = item.mapFromItem(area, point.x, point.y)
        if (item.clip && !item.contains(local)) return false
        if (item.editBoundary === true && item.contains(local)) return true
        for (let i = 0; i < item.children.length; ++i)
            if (controlAt(item.children[i], point)) return true
        return false
    }
    function dismiss(item) {
        if (!item.visible || !item.enabled) return
        if (typeof item.dismissEditors === "function") item.dismissEditors()
        for (let i = 0; i < item.children.length; ++i) dismiss(item.children[i])
    }
    TapHandler {
        parent: area.parent
        acceptedButtons: Qt.LeftButton
        onTapped: function(eventPoint) {
            if (!area.controlAt(area.parent, eventPoint.position)) area.dismiss(area.parent)
        }
    }
}
