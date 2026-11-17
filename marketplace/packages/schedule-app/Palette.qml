import QtQuick
QtObject {
    property bool dark: true
    function wash(value, alpha) { var c=Qt.lighter(value,1.0); return Qt.rgba(c.r,c.g,c.b,alpha) }
    readonly property color background: dark ? '#191b20' : '#f5f7fb'
    readonly property color surface: dark ? '#202329' : '#ffffff'
    readonly property color sidebar: dark ? '#1d2026' : '#f0f3f9'
    readonly property color raised: dark ? '#292d35' : '#eaf0f8'
    readonly property color hover: dark ? '#303743' : '#e0e9f8'
    readonly property color line: dark ? '#343943' : '#e0e5ef'
    readonly property color grid: dark ? '#2c3038' : '#e9edf4'
    readonly property color text: dark ? '#eff1f6' : '#202c43'
    readonly property color muted: dark ? '#99a3b3' : '#728098'
    readonly property color accent: dark ? '#a4c3ff' : '#345fc3'
    readonly property color selected: dark ? '#303e59' : '#e4edff'
    readonly property color onAccent: dark ? '#142544' : '#ffffff'
    readonly property color error: dark ? '#f1aaaa' : '#b93749'
    readonly property color success: dark ? '#a0d7bb' : '#25825c'
}
