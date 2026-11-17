import QtQuick
QtObject {
    property var source: null
    readonly property color background: source && source.background ? source.background : "#17181c"
    readonly property color surface: source && source.surface ? source.surface : "#202126"
    readonly property color raised: source && source.surfaceRaised ? source.surfaceRaised : "#292a30"
    readonly property color border: source && source.border ? source.border : "#3b3c43"
    readonly property color text: source && source.text ? source.text : "#e9e9e5"
    readonly property color muted: source && source.muted ? source.muted : "#a1a29d"
    readonly property color accent: source && source.accent ? source.accent : "#afc7db"
    readonly property bool dark: surface.hslLightness < 0.5
    readonly property color selected: dark ? "#343d47" : "#e5edf5"
    readonly property color hover: dark ? "#303137" : "#edf0f4"
    readonly property color warning: dark ? "#d7b28a" : "#8b6040"
    readonly property color error: dark ? "#e7aaa5" : "#a33e38"
    readonly property color onAccent: dark ? "#1c252e" : "#ffffff"
}
