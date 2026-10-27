"""Sample hover animation frames, not just end states, to catch dark flashes."""
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtTest import QTest
from headless_test_support import HeadlessQtTestCase


class HoverFeedbackTests(HeadlessQtTestCase):
    def setUp(self):
        self.window = self.load_window('''
import QtQuick
import "components"
Window {
    width: 620; height: 200; visible: true; color: "white"
    IconButton { objectName: "hoverButton"; x: 20; y: 30; text: "+"; buttonSize: 40 }
    InlineField { objectName: "hoverField"; x: 100; y: 30; width: 120; bare: true; text: "Title" }
    CalendarDayCell {
        objectName: "hoverDay"; x: 260; y: 30; width: 60; height: 40; cellHeight: 40
        modelData: ({date: "2024-01-10", day: 10, inMonth: true,
                     today: false, selected: false, taskCount: 0, openCount: 0})
    }
    TaskCard { objectName: "hoverCard"; x: 340; y: 20; width: 240 }
}
''')
        QTest.mouseMove(self.window, QPoint(600, 180))
        QTest.qWait(160)

    def assert_no_dark_frames(self, control, fill):
        inside = control.mapToScene(QPointF(control.width() / 2, control.height() / 2)).toPoint()
        # Include rapid reversals: endpoints alone cannot reveal this regression.
        for position, frames in [(inside, 12), (QPoint(600, 180), 12),
                                 (inside, 4), (QPoint(600, 180), 4), (inside, 12)]:
            QTest.mouseMove(self.window, position)
            for _ in range(frames):
                QTest.qWait(12)
                color = fill.property("color")
                alpha = color.alphaF()
                composite = [round(channel * alpha + 255 * (1 - alpha))
                             for channel in (color.red(), color.green(), color.blue())]
                self.assertGreaterEqual(min(composite), 235,
                    f"dark intermediate hover frame: {color.name(color.NameFormat.HexArgb)} -> {composite}")

    def test_icon_button_hover_never_flashes_dark(self):
        button = self.item(self.window, "hoverButton")
        self.assert_no_dark_frames(button, button.property("background"))

    def test_inline_field_hover_never_flashes_dark(self):
        field = self.item(self.window, "hoverField")
        self.assert_no_dark_frames(field, field.property("background"))

    def test_calendar_day_hover_never_flashes_dark(self):
        day = self.item(self.window, "hoverDay")
        circle = day.property("contentItem").childItems()[0]
        self.assert_no_dark_frames(day, circle)

    def test_task_card_hover_never_flashes_dark(self):
        card = self.item(self.window, "hoverCard")
        self.assert_no_dark_frames(card, card)
