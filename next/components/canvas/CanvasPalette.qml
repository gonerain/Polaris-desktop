import QtQuick
QtObject {
    property string theme: "light"
    readonly property color panel: theme === "dark" ? "#17181b" : theme === "warm" ? "#f3eee6" : "#f3f5f8"
    readonly property color border: theme === "dark" ? "#36373d" : theme === "warm" ? "#e7ded1" : "#e5eaf1"
    readonly property color card: theme === "dark" ? "#202126" : theme === "warm" ? "#fffcf7" : "#ffffff"
    readonly property color ink: theme === "dark" ? "#eae8e4" : theme === "warm" ? "#443d34" : "#1f2937"
    readonly property color muted: theme === "dark" ? "#a7a6a4" : theme === "warm" ? "#7d7365" : "#697386"
    readonly property color hover: theme === "dark" ? "#30343b" : theme === "warm" ? "#ece3d6" : "#eaf0f9"
    readonly property color pressed: theme === "dark" ? "#3a4048" : theme === "warm" ? "#e3d7c5" : "#dde6f6"
    readonly property color accent: theme === "dark" ? "#b4cde0" : theme === "warm" ? "#8b6840" : "#4263c7"
    readonly property color accentInk: theme === "dark" ? "#17181b" : "#ffffff"
    readonly property color accentHover: theme === "dark" ? "#c8ddea" : theme === "warm" ? "#765735" : "#3453b3"
    readonly property color softAccent: theme === "dark" ? "#303943" : theme === "warm" ? "#f1e6d6" : "#eaf0ff"
    readonly property color focus: accent
    readonly property color scrollThumb: theme === "dark" ? "#747a80" : theme === "warm" ? "#baac98" : "#b7c2d3"
    readonly property color error: theme === "dark" ? "#f2a3a3" : "#ad4545"
}
