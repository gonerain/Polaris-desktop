pragma ComponentBehavior: Bound

import QtQuick

IconButton {
    id: root
    objectName: "calendarSyncButton"
    required property var taskStore
    text: "☁"
    buttonSize: 28
    accessibleName: qsTr("OneDrive 日程同步")
    tooltip: taskStore && taskStore.cloudSync ? taskStore.cloudSync.status : accessibleName
    onClicked: {
        if (!popupLoader.item)
            popupLoader.setSource("CalendarSyncPopup.qml", {anchorItem: root, sync: root.taskStore ? root.taskStore.cloudSync : null})
        popupLoader.item.open()
    }
    Loader { id: popupLoader }
}
