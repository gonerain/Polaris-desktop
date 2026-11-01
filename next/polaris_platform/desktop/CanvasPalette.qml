import QtQuick
QtObject {
    property string theme: "light"
    readonly property color panel: theme === "dark" ? "#25272c" : theme === "warm" ? "#f1e9dc" : "#f5f6f7"
    readonly property color border: theme === "dark" ? "#494d56" : theme === "warm" ? "#d8cbbb" : "#d8dce1"
    readonly property color card: theme === "dark" ? "#30333a" : theme === "warm" ? "#fffbf4" : "#ffffff"
    readonly property color ink: theme === "dark" ? "#e8eaf0" : theme === "warm" ? "#51483c" : "#30343b"
    readonly property color muted: theme === "dark" ? "#aeb4bf" : theme === "warm" ? "#847968" : "#68707b"
    readonly property color hover: theme === "dark" ? "#414650" : theme === "warm" ? "#e6d9c5" : "#e9ecf0"
    readonly property color pressed: theme === "dark" ? "#4e5561" : theme === "warm" ? "#dbccb6" : "#dfe4ea"
    readonly property color focus: theme === "dark" ? "#b4becf" : theme === "warm" ? "#a88e69" : "#8a96a6"
    readonly property color error: theme === "dark" ? "#f2a3a3" : "#ad4545"
}
