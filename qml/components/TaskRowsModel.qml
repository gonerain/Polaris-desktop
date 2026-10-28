pragma ComponentBehavior: Bound

import QtQuick

// A task changing content must not destroy its editor or another task's draft.
ListModel {
    id: model
    property var rows: []
    dynamicRoles: true
    onRowsChanged: Qt.callLater(model.sync)
    Component.onCompleted: sync()

    function sync() {
        for (let i = 0; i < rows.length; ++i) {
            const row = rows[i]
            const identity = row.task.entryId
            let found = i
            while (found < count && get(found).identity !== identity) ++found
            if (found === count)
                insert(i, {identity: identity, task: row.task, date: row.date,
                    overdue: row.overdue, group: row.overdue ? "overdue" : row.date})
            else {
                if (found !== i) move(found, i, 1)
                setProperty(i, "date", row.date)
                setProperty(i, "overdue", row.overdue)
                setProperty(i, "group", row.overdue ? "overdue" : row.date)
            }
        }
        if (count > rows.length) remove(rows.length, count - rows.length)
    }
}
