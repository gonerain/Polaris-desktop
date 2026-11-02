import QtQuick
import QtQuick as Quick

Quick.Canvas {
    property string kind: "plus"
    property color ink: "#606570"
    width: 18; height: 18
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onKindChanged: requestPaint()
    onInkChanged: requestPaint()
    onPaint: {
        var c = getContext("2d")
        c.reset(); c.scale(width / 18, height / 18); c.strokeStyle = ink; c.fillStyle = ink
        c.lineWidth = 1.5; c.lineCap = "round"; c.lineJoin = "round"
        c.beginPath()
        if (kind === "plus") { c.moveTo(9, 4); c.lineTo(9, 14); c.moveTo(4, 9); c.lineTo(14, 9) }
        else if (kind === "close") { c.moveTo(5, 5); c.lineTo(13, 13); c.moveTo(13, 5); c.lineTo(5, 13) }
        else if (kind === "up") { c.moveTo(5, 11); c.lineTo(9, 7); c.lineTo(13, 11) }
        else if (kind === "down") { c.moveTo(5, 7); c.lineTo(9, 11); c.lineTo(13, 7) }
        else if (kind === "right") { c.moveTo(7, 5); c.lineTo(11, 9); c.lineTo(7, 13) }
        else if (kind === "resize") { c.moveTo(7, 14); c.lineTo(14, 7); c.moveTo(11, 14); c.lineTo(14, 11) }
        else if (kind === "board") { c.roundedRect(3, 3, 12, 12, 2, 2); c.moveTo(7, 3); c.lineTo(7, 15) }
        else if (kind === "palette") {
            c.moveTo(15, 9); c.bezierCurveTo(15, 5.3, 12.4, 3, 9, 3)
            c.bezierCurveTo(5.5, 3, 3, 5.6, 3, 9); c.bezierCurveTo(3, 12.5, 5.5, 15, 8.5, 15)
            c.bezierCurveTo(10.5, 15, 9.4, 12, 11.5, 12); c.bezierCurveTo(13.8, 12, 15, 11, 15, 9)
            c.stroke(); c.beginPath()
            c.arc(6.5, 7, .8, 0, Math.PI * 2); c.fill(); c.beginPath()
            c.arc(10, 5.8, .8, 0, Math.PI * 2); c.fill(); c.beginPath()
            c.arc(6, 10.5, .8, 0, Math.PI * 2); c.fill(); c.beginPath()
        }
        else if (kind === "grip") {
            for (var x = 6; x <= 12; x += 6) for (var y = 5; y <= 13; y += 4) c.fillRect(x - .8, y - .8, 1.6, 1.6)
        }
        c.stroke()
    }
}
