"""Offscreen integration tests for independent full views and reversible presentation."""
import unittest

from test_floating_box import FloatingBoxTests as _FloatingBoxTests
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest


class FocusPresentationTests(unittest.TestCase):
    setUpClass = classmethod(_FloatingBoxTests.setUpClass.__func__)
    setUp = _FloatingBoxTests.setUp
    close_window = _FloatingBoxTests.close_window
    find = _FloatingBoxTests.find
    click = _FloatingBoxTests.click
    expand = _FloatingBoxTests.expand

    def test_full_view_shares_data_and_restores_board(self):
        self.expand()
        original = self.window.geometry()
        board = self.find("componentBoard")
        store = self.window.findChild(QObject, "calendarTaskStore")
        store.addTask("Shared task", "09:30")
        self.click("openFocusButton")
        QTest.qWait(600)
        presenter = self.find("focusPresenter")
        self.assertTrue(presenter.property("active"))
        self.assertFalse(presenter.property("transitioning"))
        self.assertGreater(self.window.width(), original.width())
        self.assertEqual((board.width(), board.height()), (original.width(), original.height()))
        self.assertEqual(board.property("freePanelCount"), 0)
        agenda = self.find("focusAgenda")
        self.assertEqual(agenda.property("taskStore"), store)
        store.addTask("Added while focused", "")
        self.assertEqual(store.property("taskCount"), 2)
        self.window.collapse()
        self.assertFalse(self.window.property("collapsing"))
        # A second open cannot replace the active view.
        self.click("focusBackButton")
        QTest.qWait(380)
        self.assertFalse(presenter.property("active"))
        self.assertEqual(self.window.geometry(), original)
        self.assertEqual(store.property("taskCount"), 2)
        self.assertEqual(self.window.property("expandedWidth"), original.width())

    def evaluate(self, expression):
        from PySide6.QtQml import QQmlExpression
        from pathlib import Path
        import json
        expression = expression.replace('"Notepad.qml"', json.dumps(
            (Path(__file__).parent / "qml/components/Notepad.qml").resolve().as_uri()))
        script = QQmlExpression(self.engine.rootContext(), self.find("componentBoard"), expression)
        result = script.evaluate()
        self.assertFalse(script.hasError(), script.error().toString())
        return result[0] if isinstance(result, tuple) else result

    def test_generic_cover_and_source_release_guard(self):
        self.expand()
        original = self.window.geometry()
        self.assertTrue(self.evaluate('present(_handles[Object.keys(_handles)[0]], '
                                      'Qt.createComponent("Notepad.qml"), {}, {})'))
        QTest.qWait(500)
        self.assertTrue(self.find("focusPresenter").property("active"))
        self.assertEqual(self.window.geometry(), original)
        self.assertFalse(self.evaluate('release(_handles[Object.keys(_handles)[0]])'))
        self.assertFalse(self.evaluate('present(_handles[Object.keys(_handles)[0]], '
                                       'Qt.createComponent("Notepad.qml"), {}, {})'))
        self.find("focusPresenter").close()
        QTest.qWait(380)
        self.assertEqual(self.window.geometry(), original)

    def test_invalid_span_and_failed_view_leave_board_intact(self):
        self.expand()
        original = self.window.geometry()
        self.assertFalse(self.evaluate('present(_handles[Object.keys(_handles)[0]], '
                                       'Qt.createComponent("Notepad.qml"), {span: Qt.size(0, 4)}, {})'))
        self.evaluate('present(_handles[Object.keys(_handles)[0]], '
                      'Qt.createQmlObject(\'import QtQml; Component { QtObject {} }\', presenter), {}, {})')
        QTest.qWait(300)
        self.assertFalse(self.find("focusPresenter").property("busy"))
        self.assertEqual(self.window.geometry(), original)
        self.assertEqual(self.find("componentBoard").property("freePanelCount"), 0)

    def test_overview_search_completion_and_reschedule(self):
        from PySide6.QtCore import Qt
        self.expand()
        store = self.window.findChild(QObject, "calendarTaskStore")
        store.selectDate("2024-01-01")
        task = store.addTask("Alpha")
        child = task.addSubtask("needle")
        other = store.addTask("Beta")
        other.setDone(True)
        self.click("openFocusButton")
        QTest.qWait(450)
        self.click("overviewModeButton")
        listing = self.find("overviewList")
        self.assertEqual(listing.property("count"), 1)
        search = self.find("overviewSearch")
        search.setProperty("text", "needle")
        self.app.processEvents()
        self.assertEqual(listing.property("count"), 1)
        child.rename("renamed")
        self.app.processEvents()
        self.assertEqual(listing.property("count"), 0)
        search.setProperty("text", "")
        self.click("overviewShowCompleted")
        self.assertEqual(listing.property("count"), 2)
        self.click("taskDate" + str(task.entryId))
        QTest.keyClick(self.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.find("taskDate" + str(task.entryId)).setProperty("text", "2024-02-03")
        QTest.keyClick(self.window, Qt.Key.Key_Return)
        QTest.qWait(80)
        self.assertEqual(next(row["date"] for row in store.allEntries if row["task"] == task), "2024-02-03")
        self.find("focusPresenter").close()
        QTest.qWait(380)

    def test_escape_closes_composer_before_full_view(self):
        from PySide6.QtCore import Qt
        self.expand()
        self.click("openFocusButton")
        QTest.qWait(450)
        agenda = self.find("focusAgenda")
        agenda.toggleComposer()
        QTest.qWait(100)
        self.assertTrue(agenda.property("composerOpen"))
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        QTest.qWait(100)
        self.assertFalse(agenda.property("composerOpen"))
        self.assertTrue(self.find("focusPresenter").property("active"))
        QTest.keyClick(self.window, Qt.Key.Key_Escape)
        QTest.qWait(380)
        self.assertFalse(self.find("focusPresenter").property("active"))

    def test_unsaved_failure_requires_explicit_discard_before_quit(self):
        store = self.window.findChild(QObject, "calendarTaskStore")
        store._storage_error = "simulated write failure"
        store._save = lambda: False
        self.window.requestQuit()
        QTest.qWait(100)
        dialog = self.window.findChild(QObject, "unsavedQuitDialog")
        self.assertTrue(dialog.property("visible"))
        self.assertFalse(self.window.property("allowQuit"))
        self.assertTrue(self.window.isVisible())
        dialog.discarded.emit()
        QTest.qWait(50)
        self.assertTrue(self.window.property("allowQuit"))
        self.assertFalse(self.window.isVisible())

    def test_normal_calendar_has_no_persistent_save_status(self):
        self.expand()
        self.click("openFocusButton")
        QTest.qWait(450)
        statuses = self.window.findChildren(QObject, "storeStatus")
        self.assertGreaterEqual(len(statuses), 2)
        self.assertFalse(any(status.isVisible() for status in statuses))
        self.find("focusPresenter").close()
        QTest.qWait(380)

    def test_time_picker_holds_window_open_until_dismissed(self):
        self.expand()
        self.click("openComposerButton")
        self.click("newTaskTimeInput")
        field = self.find("newTaskTimeInput")
        picker = field.findChild(QObject, "timePicker")
        self.assertTrue(picker.property("visible"))
        self.assertEqual(self.window.property("editorPopupCount"), 1)
        self.window.collapse()
        self.assertFalse(self.window.property("collapsing"))
        picker.close()
        QTest.qWait(60)
        self.assertEqual(self.window.property("editorPopupCount"), 0)

    def test_full_view_background_dismisses_composer(self):
        from PySide6.QtCore import QPoint, Qt
        self.expand()
        self.click("openFocusButton")
        QTest.qWait(450)
        agenda = self.find("focusAgenda")
        agenda.toggleComposer()
        QTest.qWait(100)
        self.assertTrue(agenda.property("composerOpen"))
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton,
                         pos=QPoint(self.window.width() - 8, self.window.height() - 8))
        QTest.qWait(250)
        self.assertFalse(agenda.property("composerOpen"))
        self.find("focusPresenter").close()
        QTest.qWait(380)

    def test_repeated_open_and_escape(self):
        from PySide6.QtCore import Qt
        self.expand()
        for _ in range(2):
            self.click("openFocusButton")
            QTest.qWait(500)
            self.assertTrue(self.find("focusPresenter").property("active"))
            QTest.keyClick(self.window, Qt.Key.Key_Escape)
            QTest.qWait(380)
            self.assertFalse(self.find("focusPresenter").property("active"))


# Do not discover the imported fixture's original tests a second time.
del _FloatingBoxTests

if __name__ == "__main__":
    unittest.main()
