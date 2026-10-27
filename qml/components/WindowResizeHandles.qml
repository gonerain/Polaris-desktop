pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: handles

    required property Window targetWindow
    readonly property int edgeSize: 5
    readonly property int cornerSize: 10

    Repeater {
        model: [
            Qt.TopEdge | Qt.LeftEdge, Qt.TopEdge, Qt.TopEdge | Qt.RightEdge,
            Qt.LeftEdge, Qt.RightEdge,
            Qt.BottomEdge | Qt.LeftEdge, Qt.BottomEdge, Qt.BottomEdge | Qt.RightEdge
        ]

        delegate: MouseArea {
            required property int modelData
            objectName: "resizeHandle" + modelData

            readonly property bool leftEdge: (modelData & Qt.LeftEdge) !== 0
            readonly property bool rightEdge: (modelData & Qt.RightEdge) !== 0
            readonly property bool topEdge: (modelData & Qt.TopEdge) !== 0
            readonly property bool bottomEdge: (modelData & Qt.BottomEdge) !== 0
            readonly property bool corner: (leftEdge || rightEdge) && (topEdge || bottomEdge)

            width: corner ? handles.cornerSize
                : (leftEdge || rightEdge ? handles.edgeSize : handles.width - 2 * handles.cornerSize)
            height: corner ? handles.cornerSize
                : (topEdge || bottomEdge ? handles.edgeSize : handles.height - 2 * handles.cornerSize)
            x: leftEdge ? 0 : (rightEdge ? handles.width - width : handles.cornerSize)
            y: topEdge ? 0 : (bottomEdge ? handles.height - height : handles.cornerSize)
            cursorShape: corner
                ? (leftEdge === topEdge ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor)
                : (leftEdge || rightEdge ? Qt.SizeHorCursor : Qt.SizeVerCursor)
            acceptedButtons: Qt.LeftButton
            onPressed: handles.targetWindow.startSystemResize(modelData)
        }
    }
}
