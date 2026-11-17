"""Render the bundled marketplace's original, geometric 256 px icons."""
from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPolygonF

COLORS = {'schedule':'#506fbd', 'weixin':'#40946c', 'agent-bridge':'#7961aa', 'assistant':'#b27542',
          'feishu-bot':'#397eb5', 'text-tools':'#a06486', 'feishu-agent':'#438d9d', 'text-studio':'#9b7848'}


def line(p, *points):
    p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))


def sparkle(p, x, y, radius):
    line(p, (x, y-radius), (x+radius*.23, y-radius*.23), (x+radius, y),
         (x+radius*.23, y+radius*.23), (x, y+radius), (x-radius*.23, y+radius*.23),
         (x-radius, y), (x-radius*.23, y-radius*.23), (x, y-radius))


def plane(p, scale=1, dx=0, dy=0):
    p.save(); p.translate(dx, dy); p.scale(scale, scale)
    line(p, (43,108), (206,56), (164,203), (122,150), (43,108))
    line(p, (122,150), (206,56)); line(p, (122,150), (121,185), (145,170))
    p.restore()


def render(slug, color, destination):
    image=QImage(256,256,QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(color)); p.drawRoundedRect(QRectF(12,12,232,232),48,48)
    p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor('white'), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if slug=='schedule':
        p.drawRoundedRect(QRectF(51,65,154,133),14,14); line(p,(51,101),(205,101)); line(p,(89,51),(89,79)); line(p,(167,51),(167,79))
        for x,y in ((91,130),(128,130),(165,130),(91,164),(128,164),(165,164)): p.drawPoint(QPointF(x,y))
    elif slug=='weixin':
        p.drawRoundedRect(QRectF(47,62,124,83),34,34); line(p,(76,140),(68,160),(104,145))
        p.drawRoundedRect(QRectF(113,119,97,70),28,28); line(p,(181,184),(193,201),(165,190))
    elif slug=='agent-bridge':
        line(p,(76,126),(110,94),(148,94),(181,126),(148,158),(110,158),(76,126));
        for x,y in ((65,126),(115,85),(143,85),(192,126),(143,167),(115,167)): p.drawEllipse(QPointF(x,y),10,10)
    elif slug=='assistant':
        sparkle(p,123,124,61); sparkle(p,190,62,17); sparkle(p,61,192,13)
    elif slug=='feishu-bot': plane(p)
    elif slug=='feishu-agent': plane(p,.78,18,39); sparkle(p,194,65,24)
    elif slug=='text-tools':
        line(p,(55,66),(155,66)); line(p,(105,66),(105,190)); line(p,(72,190),(138,190));
        line(p,(163,111),(205,111)); line(p,(163,145),(205,145)); line(p,(163,179),(195,179))
    elif slug=='text-studio':
        p.drawRoundedRect(QRectF(44,58,168,140),13,13); line(p,(128,58),(128,198));
        for y in (91,120,149): line(p,(63,y),(108,y)); line(p,(148,y),(193,y))
    p.end(); image.save(str(destination / (slug+'.png')))


if __name__ == '__main__':
    app=QGuiApplication.instance() or QGuiApplication([])
    destination=Path(__file__).resolve().parents[1]/'marketplace'/'assets'
    destination.mkdir(parents=True,exist_ok=True)
    for slug,color in COLORS.items(): render(slug,color,destination)
