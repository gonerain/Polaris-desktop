"""WeChat approval boundaries, using only in-memory tasks and fake network."""
import json
import re
import time
import unittest
from datetime import date
from unittest.mock import patch

from test_regressions import (APP, FakeNetwork, CalendarTaskStore, CalendarAPI,
                              ComponentRegistry, DeepSeekChat, DeepSeekModel, WeixinClient, pump)


class WeixinApprovalTests(unittest.TestCase):
    def setUp(self):
        self.client = WeixinClient()
        self.store = CalendarTaskStore(today=date(2026, 10, 29))
        self.registry = ComponentRegistry()
        self.registry.register("calendar", CalendarAPI(self.store))
        self.network = FakeNetwork()
        self.chat = DeepSeekChat(self.client, model=DeepSeekModel(manager=self.network), registry=self.registry)
        self.client._account = {"botId": "bot", "userId": "owner"}
        self.client._context = "fake-context"
        self.client._status("connected", "test")
        self.sent = []
        self.delivered = True

        def send(body, callback=None):
            self.sent.append(body)
            if callback:
                callback(self.delivered)
            return True

        self.sender = patch.object(self.client, "send_text", side_effect=send)
        self.sender.start()
        self.chat.tools.call("polaris_help", {"component": "calendar"}, lambda _: None)
        self.chat.tools.setReadAllowed("calendar", True)

    def tearDown(self):
        self.client.disconnectAccount()
        self.sender.stop()

    def call(self, operation, args):
        output = []
        self.chat.tools.call("polaris_call", {"component": "calendar", "operation": operation, "args": args}, output.append)
        return output

    def pending(self):
        output = self.call("task.create", {"title": "only after approval"})
        code = re.search(r"批准 ([0-9]{6})", self.sent[-1])[1]
        return output, code

    def incoming(self, text, *, sender="owner", group=None, timestamp=None):
        self.client._receive({"message_type": 1, "message_state": 2, "from_user_id": sender,
                              "message_id": str(time.time_ns()), "group_id": group,
                              "create_time_ms": timestamp or time.time() * 1000,
                              "item_list": [{"type": 1, "text_item": {"text": text}}]})

    def command(self, text, timestamp=None):
        self.chat._incoming(str(time.time_ns()), text, timestamp or time.time() * 1000 + 1)

    def test_remote_approval_executes_once_and_never_calls_model(self):
        output, code = self.pending()
        self.assertEqual(len(self.store.allEntries), 0)
        self.incoming("批准 " + code)
        self.assertTrue(output[0]["ok"])
        self.command("批准 " + code)
        self.assertEqual(len(self.store.allEntries), 1)
        self.assertEqual(self.chat.queuedCount, 0)
        self.assertFalse(self.network.posts)
        self.assertFalse(self.chat._history)

    def test_remote_reply_resumes_model_and_sends_final_without_another_user_turn(self):
        self.chat._incoming("request", "新增一个测试任务", time.time() * 1000 + 1)
        self.chat._drain()

        def tool(identity, name, args):
            return {"id": identity, "type": "function", "function": {
                "name": name, "arguments": json.dumps(args)}}

        self.network.posts[-1][2].complete({"tool_calls": [
            tool("help", "polaris_help", {"component": "calendar"}),
            tool("create", "polaris_call", {"component": "calendar", "operation": "task.create",
                                             "args": {"title": "approved via WeChat"}})]})
        pump()
        code = re.search(r"批准 ([0-9]{6})", self.sent[-1])[1]
        self.incoming("批准 " + code)
        pump()
        self.assertEqual(len(self.network.posts), 2)
        self.network.posts[-1][2].complete({"content": "已创建"})
        self.assertEqual(self.sent[-1], "已创建")
        self.assertFalse(self.chat.busy)
        self.assertEqual(self.chat.queuedCount, 0)
        self.assertEqual(len(self.chat._history), 2)
        self.assertNotIn(code, str(self.network.posts[-1][1]))

    def test_busy_sender_defers_receipt_and_scope_change_revokes_approval(self):
        self.client._sending = True
        output = self.call("task.create", {"title": "deferred"})
        self.assertFalse(self.sent)
        self.assertIsNone(self.chat._remote_approval)
        self.client._sending = False
        self.client.changed.emit()
        code = re.search(r"批准 ([0-9]{6})", self.sent[-1])[1]
        self.client._account = {"botId": "bot", "userId": "other-owner"}
        self.client.changed.emit()
        self.command("批准 " + code)
        self.assertEqual(output, [])
        self.assertFalse(self.store.allEntries)

    def test_wrong_owner_group_old_message_and_unconfirmed_receipt_cannot_approve(self):
        output, code = self.pending()
        self.incoming("批准 " + code, sender="stranger")
        self.incoming("批准 " + code, group="group")
        self.command("批准 " + code, self.chat._remote_approval["issued"] - 1000)
        self.assertEqual(output, [])
        self.assertFalse(self.store.allEntries)
        self.chat.tools.cancel()
        self.delivered = False
        output, code = self.pending()
        self.command("批准 " + code)
        self.assertEqual(output, [])

    def test_reject_expiry_disconnect_and_local_consumption_invalidate_codes(self):
        output, code = self.pending()
        self.command("拒绝 " + code)
        self.assertEqual(output[0]["error"]["code"], "approval_denied")
        self.chat.tools.cancel()
        output, code = self.pending()
        self.chat.tools._expires_at = time.monotonic() - 1
        self.command("批准 " + code)
        self.assertEqual(output[0]["error"]["code"], "approval_denied")
        self.chat.tools.cancel()
        output, code = self.pending()
        self.chat.tools.approve(self.chat.tools.pending["id"])
        self.command("批准 " + code)
        self.assertEqual(len(self.store.allEntries), 1)
        self.chat.tools.cancel()
        output, code = self.pending()
        self.client.disconnectAccount()
        self.command("批准 " + code)
        self.assertEqual(output, [])
        self.assertEqual(len(self.store.allEntries), 1)

    def test_five_bad_codes_disable_remote_and_new_request_gets_new_code(self):
        output, code = self.pending()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.command("批准 " + wrong)
        self.command("批准 " + code)
        self.assertEqual(output, [])
        self.chat.tools.cancel()
        _, next_code = self.pending()
        self.assertNotEqual(next_code, code)

    def test_numeric_title_requires_lookup_and_preview_uses_real_id(self):
        entry = self.store.addTask("22")
        self.assertNotEqual(entry.entryId, 22)
        blocked = self.call("task.delete", {"id": 22})
        self.assertEqual(blocked[0]["error"]["code"], "target_lookup_required")
        self.assertFalse(self.chat.tools.pending)
        found = self.call("task.list", {"query": "22"})[0]["result"]["tasks"][0]
        output = self.call("task.delete", {"id": found["id"]})
        self.assertIn("目标标题：22", self.sent[-1])
        self.assertIn(json.dumps({"id": entry.entryId}), self.sent[-1])
        code = re.search(r"批准 ([0-9]{6})", self.sent[-1])[1]
        self.command("批准 " + code)
        self.assertTrue(output[0]["ok"])
        self.assertFalse(self.store.allEntries)

    def test_oversized_preview_and_plain_agreement_cannot_approve(self):
        self.call("task.create", {"title": "长" * 1900})
        self.assertIsNone(self.chat._remote_approval)
        self.assertIn("完整参数", self.sent[-1])
        self.command("同意")
        self.assertFalse(self.store.allEntries)


if __name__ == "__main__":
    unittest.main()
