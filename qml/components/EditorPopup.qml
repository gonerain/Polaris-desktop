pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

Popup {
    id: popup
    required property Item anchorItem
    parent: anchorItem
    y: anchorItem.height + 6
    popupType: Popup.Window
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    property var _owner: null
    property bool _registered: false

    function release() {
        if (_registered && _owner) {
            _registered = false
            _owner.editorPopupCount = Math.max(0, _owner.editorPopupCount - 1)
        }
        _owner = null
    }
    onOpened: {
        _owner = anchorItem.Window.window
        if (_owner && typeof _owner.editorPopupCount === "number") {
            _registered = true
            _owner.editorPopupCount += 1
        }
    }
    onClosed: release()
    Component.onDestruction: release()
}
