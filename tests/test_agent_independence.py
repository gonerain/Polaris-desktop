"""Verify agent behavior when calendar implementation cannot even be imported."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class AgentIndependenceTests(unittest.TestCase):
    def test_agent_runs_without_calendar_modules_or_registration(self):
        script = r'''
import importlib.abc
import json
import sys
import time
from unittest.mock import patch

class NoCalendar(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"polaris.calendar_api", "polaris.tasks", "polaris.storage"}:
            raise ImportError("Calendar deliberately unavailable: " + fullname)

sys.meta_path.insert(0, NoCalendar())
sys.path.insert(0, "tests")
from support import FakeNetwork, initialize_qt_tests, pump
app = initialize_qt_tests()
from polaris.component_api import ComponentRegistry
from polaris.deepseek_api import DeepSeekModel
from polaris.deepseek_chat import DeepSeekChat
from polaris.weixin import WeixinClient
from polaris.agents import AgentHub

registry = ComponentRegistry()
network = FakeNetwork()
client = WeixinClient()
chat = DeepSeekChat(client, model=DeepSeekModel(manager=network), registry=registry)
client._account = {"botId": "test-bot", "userId": "test-owner"}
client._context = "fake-context"
client._status("connected", "test")
sent = []

def send(body, callback=None):
    sent.append(body)
    if callback:
        callback(True)
    return True

def incoming(body):
    chat._incoming(str(time.time_ns()), body, time.time() * 1000 + 1)
    chat._drain()

def tools(*calls):
    network.posts[-1][2].complete({"tool_calls": [
        {"id": "call" + str(i), "type": "function", "function": {
            "name": name, "arguments": json.dumps(args)}}
        for i, (name, args) in enumerate(calls)]})
    pump()

checks = []
with patch.object(client, "send_text", side_effect=send):
    incoming("你好")
    network.posts[-1][2].complete({"content": "你好，我在。"})
    assert sent[-1] == "你好，我在。" and chat.enabled and not chat.busy
    checks.append("ordinary conversation")

    incoming("查看我的日程")
    tools(("polaris_components", {}), ("polaris_help", {"component": "calendar"}))
    outputs = [json.loads(row["content"]) for row in network.posts[-1][1]["messages"] if row["role"] == "tool"]
    assert outputs[0] == {"ok": True, "components": []}
    assert outputs[1]["error"]["code"] == "unknown_component"
    network.posts[-1][2].complete({"content": "当前没有日程组件，无法读取日程。"})
    assert sent[-1] == "当前没有日程组件，无法读取日程。" and chat.enabled and not chat.busy
    incoming("继续聊聊")
    network.posts[-1][2].complete({"content": "可以，继续。"})
    assert sent[-1] == "可以，继续。" and chat.enabled and not chat.busy
    checks.append("missing calendar returns error; subsequent conversation still works")

    hub = AgentHub()
    registry.register("agents", hub)
    chat.tools.setReadAllowed("agents", True)
    count = len(network.posts)
    incoming("有没有执行中的会话？")
    assert len(network.posts) == count and "0 个执行中" in sent[-1]
    assert chat.enabled and not chat.busy
    checks.append("live agent session query")

    class Counter:
        name = "Test counter"
        operations = [{"name": "get", "description": "Read", "access": "read"},
                      {"name": "set", "description": "Set", "access": "write"}]
        value = 0
        def call(self, operation, args):
            if operation == "set":
                self.value = args["value"]
            return {"value": self.value}

    counter = Counter()
    registry.register("counter", counter)
    chat.tools.setReadAllowed("counter", True)
    incoming("把测试计数设为7")
    tools(("polaris_help", {"component": "counter"}),
          ("polaris_call", {"component": "counter", "operation": "get", "args": {}}),
          ("polaris_plan", {"steps": [{"id": "set", "component": "counter", "operation": "set", "args": {"value": 7}}]}))
    assert counter.value == 0 and chat.tools.pending
    chat.tools.approve(chat.tools.pending["id"])
    pump()
    assert counter.value == 7 and not chat.tools.pending
    network.posts[-1][2].complete({"content": "计数已设为7。"})
    assert sent[-1] == "计数已设为7。" and chat.enabled and not chat.busy
    checks.append("other component read, approved write plan, and final reply")

client.disconnectAccount()
assert not {"polaris.calendar_api", "polaris.tasks", "polaris.storage"} & sys.modules.keys()
checks.append("no calendar implementation imported")
print(json.dumps(checks))
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", script],
                                cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True, text=True, encoding="utf8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(json.loads(result.stdout.strip().splitlines()[-1])), 5)


if __name__ == "__main__":
    unittest.main()
