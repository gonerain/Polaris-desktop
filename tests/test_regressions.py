"""Boundary regressions; no real credentials, network or user data."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import unittest
from datetime import date
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QUICK_BACKEND"] = "software"
os.environ["DEEPSEEK_API_KEY"] = "test-only-fake-key"

from PySide6.QtCore import QObject, QEventLoop, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtQml import QQmlComponent, QQmlEngine

from main import create_engine
from polaris.agent_tools import AgentTools, TOOLS
from polaris.agents import AgentHub
from polaris.calendar_api import CalendarAPI
from polaris.chat_state import ChatStateStore
from polaris.component_api import ComponentRegistry
from polaris.deepseek_api import DeepSeekModel
from polaris.deepseek_chat import DeepSeekChat, DEFAULT_PERSONA
from polaris.tasks import CalendarTaskStore
from polaris.weixin import WeixinClient

APP = QGuiApplication.instance() or QGuiApplication([])


def pump(milliseconds=20):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.store = CalendarTaskStore(today=date(2026, 10, 29))
        self.api = CalendarAPI(self.store)

    def test_inbox_rule_shared_by_ui_and_api_and_saved_once(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            self.store.initialize_storage(Path(directory) / "tasks.json")
            for route in ("ui", "api", "review", "api_review"):
                entry = self.store.addTask(route, "09:30")
                with patch.object(self.store._repository, "save", wraps=self.store._repository.save) as save:
                    if route == "ui":
                        self.assertTrue(self.store.moveTask(entry.entryId, ""))
                    elif route == "api":
                        self.api.call("task.reschedule", {"id": entry.entryId, "date": None})
                    elif route == "review":
                        self.assertTrue(self.store.finishDay(self.store.todayDate, [
                            {"id": entry.entryId, "action": "inbox"}]))
                    else:
                        self.api.call("day.review", {"date": self.store.todayDate, "decisions": [
                            {"id": entry.entryId, "action": "inbox"}]})
                    self.assertEqual(save.call_count, 1)
                self.assertEqual(entry.time, "")
                self.assertFalse(entry.setTime("12:00"))
                self.assertTrue(self.store.moveTask(entry.entryId, self.store.todayDate))
                self.assertEqual(entry.time, "")
                self.assertTrue(entry.setTime("12:00"))

    def test_review_rejects_stale_decisions_before_any_edits(self):
        entry = self.store.addTask("keep me", "09:30")
        self.assertFalse(self.store.finishDay(self.store.todayDate, [
            {"id": entry.entryId, "action": "inbox"}, {"id": 999, "action": "tomorrow"}]))
        self.assertEqual(entry.time, "09:30")
        self.assertEqual(self.store.tasks, [entry])

    def test_reorder_is_before_target_in_both_routes(self):
        entries = [self.store.addTask(title) for title in ("A", "B", "C")]
        self.store.reorderToday(entries[0].entryId, entries[2].entryId)
        self.assertEqual([entry.title for entry in self.store.tasks], ["B", "A", "C"])
        self.api.call("task.reorder", {"id": entries[2].entryId, "beforeId": entries[1].entryId})
        self.assertEqual([entry.title for entry in self.store.tasks], ["C", "B", "A"])
        entries[1].setDone(True)
        self.assertFalse(self.store.reorderToday(entries[0].entryId, entries[1].entryId))

    def test_legacy_inbox_time_is_normalized_on_load(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "tasks.json"
            path.write_text(json.dumps({"version": 2, "days": {}, "inbox": [
                {"id": 1, "title": "old inbox", "done": False, "time": "09:30"}]}), encoding="utf8")
            self.store.initialize_storage(path)
            self.assertEqual(self.store.allEntries[0]["task"].time, "")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.store = CalendarTaskStore(today=date(2026, 10, 29))
        self.registry = ComponentRegistry()
        self.registry.register("calendar", CalendarAPI(self.store))
        self.tools = AgentTools(self.registry)
        self.tools.call("polaris_help", {"component": "calendar"}, lambda _: None)

    def request(self, operation, args=None):
        output = []
        params = {"component": "calendar", "operation": operation}
        if args is not None:
            params["args"] = args
        self.tools.call("polaris_call", params, output.append)
        return output

    def test_independent_identical_writes_require_fresh_approval(self):
        entry = self.store.addTask("toggle")
        self.tools.setReadAllowed("calendar", True)
        self.request("task.list", {"query": "toggle"})
        for done in (True, False, True):
            output = self.request("task.complete", {"id": entry.entryId, "done": done})
            self.assertEqual(output, [])
            self.tools.approve(self.tools.pending["id"])
            self.assertEqual(entry.done, done)
            self.assertEqual(output[0]["result"]["task"]["done"], done)

    def test_approval_is_consumed_and_cancelled_approval_cannot_write(self):
        output = self.request("task.create", {"title": "once"})
        identity = self.tools.pending["id"]
        self.tools.approve(identity)
        self.tools.approve(identity)
        self.assertEqual(len(self.store.allEntries), 1)
        self.assertEqual(len(output), 1)
        self.request("task.create", {"title": "cancelled"})
        identity = self.tools.pending["id"]
        self.tools.cancel()
        self.tools.approve(identity)
        self.assertEqual(len(self.store.allEntries), 1)

    def test_denied_write_does_not_prompt_again_in_same_turn(self):
        output = self.request("task.create", {"title": "denied"})
        self.tools.reject(self.tools.pending["id"])
        self.assertEqual(output[0]["error"]["code"], "approval_denied")
        self.assertEqual(self.request("task.create", {"title": "denied"})[0]["error"]["code"], "approval_denied")
        self.assertFalse(self.tools.pending)
        self.tools.cancel()
        self.assertEqual(self.request("task.create", {"title": "denied"}), [])
        self.assertTrue(self.tools.pending)

    def test_optional_args_and_read_grants(self):
        self.assertEqual(self.request("calendar.status")[0]["error"]["code"], "permission_denied")
        self.tools.setReadAllowed("calendar", True)
        self.assertTrue(self.request("calendar.status")[0]["ok"])
        self.tools.cancel(revoke=True)
        self.assertFalse(self.tools.components[0]["readAllowed"])


class FakeReply(QObject):
    readyRead = Signal()
    finished = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.buffer = b""
        self.status = 200
        self.failure = QNetworkReply.NoError

    def readAll(self):
        value, self.buffer = self.buffer, b""
        return value

    def error(self):
        return self.failure

    def attribute(self, _):
        return self.status

    def abort(self):
        self.failure = QNetworkReply.OperationCanceledError
        self.finished.emit()

    def complete(self, message):
        self.buffer = json.dumps({"choices": [{"message": message}]}).encode()
        self.readyRead.emit()
        self.finished.emit()


class FakeNetwork(QObject):
    def __init__(self):
        super().__init__()
        self.posts = []

    def post(self, request, data):
        reply = FakeReply(self)
        self.posts.append((request, json.loads(bytes(data)), reply))
        return reply


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.network = FakeNetwork()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-fake-key"}):
            self.model = DeepSeekModel(manager=self.network)

    def tearDown(self):
        self.model.cancel()
        self.model.deleteLater()
        self.network.deleteLater()
        pump()

    def test_redaction_and_request_policy(self):
        output = []
        self.model.generate([{"role": "user", "content": "hello"}], lambda *result: output.append(result))
        request, body, reply = self.network.posts[-1]
        self.assertEqual(request.attribute(QNetworkRequest.RedirectPolicyAttribute), QNetworkRequest.ManualRedirectPolicy)
        self.assertNotIn("tools", body)
        reply.complete({"content": "test-only-fake-key"})
        self.assertEqual(output, [("[密钥已隐藏]", "")])

    def test_malformed_message_returns_error_instead_of_stalling(self):
        for message in ([], "wrong", None, {"content": ""}):
            output = []
            self.model.generate([], lambda *result: output.append(result))
            self.network.posts[-1][2].complete(message)
            self.assertTrue(output[0][1])

    def test_cancel_discards_old_reply_and_rate_limit_does_not_retry(self):
        output = []
        self.model.generate([], lambda *result: output.append(result))
        self.model.cancel()
        self.assertEqual(output, [])
        for _ in range(9):
            self.model.generate([], lambda *_: None)
            self.network.posts[-1][2].complete({"content": "ok"})
        self.model.generate([], lambda *result: output.append(result))
        self.assertEqual(len(self.network.posts), 10)
        self.assertIn("10", output[0][1])


class ChatTests(unittest.TestCase):
    def test_agent_tool_round_executes_each_approved_call_then_sends_final_reply(self):
        client = WeixinClient()
        store = CalendarTaskStore(today=date(2026, 10, 29))
        entry = store.addTask("toggle")
        registry = ComponentRegistry()
        registry.register("calendar", CalendarAPI(store))
        network = FakeNetwork()
        model = DeepSeekModel(manager=network)
        chat = DeepSeekChat(client, model=model, registry=registry)
        client._account = {"botId": "bot", "userId": "user"}
        client._context = "test-context"
        client._status("connected", "test")
        sent = []

        def send(body, callback=None):
            sent.append(body)
            if callback:
                callback(True)
            return True

        def call(identity, name, args):
            return {"id": identity, "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}}

        with patch.object(client, "send_text", side_effect=send):
            chat.tools.setReadAllowed("calendar", True)
            chat._incoming("new", "完成、取消完成，再次完成这件事", time.time() * 1000 + 1)
            chat._drain()
            calls = [call("help", "polaris_help", {"component": "calendar"}),
                     call("list", "polaris_call", {"component": "calendar", "operation": "task.list", "args": {"query": "toggle"}})]
            network.posts[-1][2].complete({"tool_calls": calls})
            pump()
            calls = []
            calls += [call(str(i), "polaris_call", {"component": "calendar", "operation": "task.complete",
                       "args": {"id": entry.entryId, "done": done}}) for i, done in enumerate((True, False, True))]
            network.posts[-1][2].complete({"tool_calls": calls})
            pump()
            for done in (True, False, True):
                self.assertTrue(chat.tools.pending)
                chat.tools.approve(chat.tools.pending["id"])
                self.assertEqual(entry.done, done)
                pump()
            self.assertEqual(len(network.posts), 3)
            network.posts[-1][2].complete({"content": "已完成"})
            self.assertEqual(sent[-1], "已完成")
            self.assertFalse(chat.busy)
        client.disconnectAccount()

    def test_transport_stands_alone_and_restore_uses_public_interface(self):
        client = WeixinClient()
        client.restoreMessages([{"id": "incoming", "direction": "in", "text": "hello", "time": "10:00", "status": "已接收"},
                                {"id": "outgoing", "direction": "out", "text": "reply", "time": "10:01", "status": "发送中"}])
        self.assertIn("结果未知", client.messages[1]["status"])
        client.clearMessages()
        self.assertEqual(client.messages, [])
        client.disconnectAccount()

    def test_saved_history_restored_only_for_matching_account(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "chat.json"
            ChatStateStore(path).save({"version": 1, "persona": DEFAULT_PERSONA, "autoReply": False,
                "scope": ["bot", "user"], "history": [], "messages": [
                    {"id": "1", "text": "old", "direction": "in", "time": "10:00", "status": "已接收"}]})
            client = WeixinClient()
            chat = DeepSeekChat(client, state_path=path)
            self.assertEqual(client.messages, [])
            client._account = {"botId": "bot", "userId": "user"}
            client.changed.emit()
            self.assertEqual(client.messages[0]["text"], "old")
            client._account = {"botId": "other", "userId": "other"}
            client.changed.emit()
            self.assertEqual(client.messages, [])
            chat.suspend()

    def test_live_status_path_still_uses_read_permission_and_no_model(self):
        client = WeixinClient()
        registry = ComponentRegistry()
        registry.register("agents", AgentHub())
        network = FakeNetwork()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-fake-key"}):
            model = DeepSeekModel(manager=network)
        chat = DeepSeekChat(client, model=model, registry=registry)
        client._account = {"botId": "bot", "userId": "user"}
        client._context = "test-context"
        client._status("connected", "test")
        sent = []

        def send(body, callback):
            sent.append(body)
            callback(True)
            return True

        with patch.object(client, "send_text", side_effect=send):
            for allowed in (False, True):
                chat.tools.setReadAllowed("agents", allowed)
                chat._incoming("new", "有没有执行中的会话？", time.time() * 1000 + 1)
                chat._drain()
        self.assertIn("读取权限", sent[0])
        self.assertIn("0 个执行中", sent[1])
        self.assertEqual(network.posts, [])
        client.disconnectAccount()
        self.assertFalse(chat.enabled)
        self.assertFalse(chat.tools.components[0]["readAllowed"])


class QmlTests(unittest.TestCase):
    def test_all_components_compile_and_full_views_keep_drafts(self):
        # Isolate the QML render loop from the fake QNetworkReply lifetimes.
        if os.environ.get("POLARIS_QML_TEST") != "1":
            result = subprocess.run([
                sys.executable, "-X", "utf8", "-B", "-m", "unittest", "discover", "-s", "tests", "-k", "QmlTests"],
                env={**os.environ, "POLARIS_QML_TEST": "1"}, capture_output=True, text=True, encoding="utf8", timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        engine = create_engine()
        compiler = QQmlEngine()
        compiler.addImportPath(str(Path("qml").resolve()))
        for path in Path("qml").rglob("*.qml"):
            component = QQmlComponent(compiler, QUrl.fromLocalFile(str(path.resolve())))
            self.assertFalse(component.isError(), [error.toString() for error in component.errors()])
        window = engine.rootObjects()[0]
        window.expand()
        pump(200)
        for name in ("calendarTasks", "agentPanel", "weixinPanel"):
            self.assertIsNotNone(window.findChild(QObject, name))
        window.showComponent("weixin")
        pump(500)
        presenter = window.findChild(QObject, "focusPresenter")
        view = presenter.property("view")
        draft = view.findChild(QObject, "weixinReplyField")
        persona = view.findChild(QObject, "weixinPersonaEditor")
        draft.setProperty("text", "unsent reply")
        persona.setProperty("text", "unsaved persona")
        self.assertTrue(presenter.close())
        pump(400)
        window.showComponent("agents")
        pump(500)
        self.assertIsNotNone(presenter.property("view"))
        presenter.close()
        pump(400)
        window.showComponent("weixin")
        pump(500)
        self.assertIs(presenter.property("view"), view)
        self.assertEqual(draft.property("text"), "unsent reply")
        self.assertEqual(persona.property("text"), "unsaved persona")
        presenter.close()
        pump(400)
        window.findChild(QObject, "agendaPanel").focusRequested.emit()
        pump(500)
        self.assertIsNotNone(presenter.property("view").findChild(QObject, "focusComposer"))
        window.setVisible(False)
        engine.deleteLater()
        compiler.deleteLater()
        pump()


if __name__ == "__main__":
    unittest.main()
