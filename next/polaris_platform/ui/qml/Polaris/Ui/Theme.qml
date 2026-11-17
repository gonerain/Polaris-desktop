import QtQuick
QtObject {
    property string mode: "dark"
    readonly property int fontSizeSmall: 12
    readonly property int fontSizeBody: 13
    readonly property int fontSizeTitle: 17
    readonly property int spaceSmall: 6
    readonly property int spaceMedium: 12
    readonly property int spaceLarge: 20
    readonly property int radiusSmall: 6
    readonly property int radiusMedium: 8
    readonly property int radiusLarge: 12
    readonly property int controlHeight: 34
    readonly property int navigationHeight: 38
    readonly property int iconSize: 18
    readonly property color panel: mode === "dark" ? "#1b1c20" : mode === "warm" ? "#f3eee6" : "#f3f5f8"
    readonly property color sidebar: mode === "dark" ? "#18191d" : mode === "warm" ? "#ebe5db" : "#ebedf1"
    readonly property color selected: mode === "dark" ? "#2b3038" : mode === "warm" ? "#e4d9ca" : "#dde4ed"
    readonly property color selectedInk: mode === "dark" ? "#dde4ee" : ink
    readonly property color quiet: mode === "dark" ? "#70737d" : muted
    readonly property color border: mode === "dark" ? "#2c2d33" : mode === "warm" ? "#e7ded1" : "#e5eaf1"
    readonly property color card: mode === "dark" ? "#202126" : mode === "warm" ? "#fffcf7" : "#ffffff"
    readonly property color ink: mode === "dark" ? "#eae8e4" : mode === "warm" ? "#443d34" : "#1f2937"
    readonly property color muted: mode === "dark" ? "#a7a6a4" : mode === "warm" ? "#7d7365" : "#697386"
    readonly property color hover: mode === "dark" ? "#27292f" : mode === "warm" ? "#ece3d6" : "#eaf0f9"
    readonly property color pressed: mode === "dark" ? "#3a4048" : mode === "warm" ? "#e3d7c5" : "#dde6f6"
    readonly property color accent: mode === "dark" ? "#b4cde0" : mode === "warm" ? "#8b6840" : "#4263c7"
    readonly property color accentInk: mode === "dark" ? "#17181b" : "#ffffff"
    readonly property color accentHover: mode === "dark" ? "#c8ddea" : mode === "warm" ? "#765735" : "#3453b3"
    readonly property color softAccent: mode === "dark" ? "#2c333c" : mode === "warm" ? "#f1e6d6" : "#eaf0ff"
    readonly property color focus: accent
    readonly property color scrollThumb: mode === "dark" ? "#747a80" : mode === "warm" ? "#baac98" : "#b7c2d3"
    readonly property color error: mode === "dark" ? "#f2a3a3" : "#ad4545"
}
