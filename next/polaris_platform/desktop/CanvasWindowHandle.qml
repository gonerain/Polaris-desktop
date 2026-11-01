import QtQuick

MouseArea {
    // Zero moves the canvas; Qt.Edge combinations resize its own window.
    property int edges: 0
    acceptedButtons: Qt.LeftButton
    preventStealing: true
    cursorShape: edges === 0 ? (pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor)
        : (edges === Qt.LeftEdge || edges === Qt.RightEdge) ? Qt.SizeHorCursor
        : (edges === Qt.TopEdge || edges === Qt.BottomEdge) ? Qt.SizeVerCursor
        : (edges === (Qt.LeftEdge | Qt.TopEdge) || edges === (Qt.RightEdge | Qt.BottomEdge)) ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
    onPressed: function(mouse) {
        var point = mapToGlobal(mouse.x, mouse.y)
        canvasActions.beginWindowGesture(edges, point.x, point.y)
    }
    onPositionChanged: function(mouse) {
        if (pressed) {
            var point = mapToGlobal(mouse.x, mouse.y)
            canvasActions.updateWindowGesture(point.x, point.y)
        }
    }
    onReleased: canvasActions.endWindowGesture()
    onCanceled: canvasActions.cancelWindowGesture()
}
