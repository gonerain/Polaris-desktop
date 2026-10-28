"""Request-sized authorization and partial execution; no network or user storage."""
import json
from pathlib import Path
import tempfile
import unittest

from support import FakeNetwork, initialize_qt_tests
from polaris.agent_tools import AgentTools, TOOLS
from polaris.tasks import CalendarTaskStore
from polaris.calendar_api import CalendarAPI
from polaris.component_api import ComponentRegistry
from polaris.deepseek_chat import DeepSeekChat
from polaris.deepseek_api import DeepSeekModel
from polaris.weixin import WeixinClient

APP = initialize_qt_tests()


def step(identity, operation, **args):
    return {"id": identity, "component": "calendar", "operation": operation, "args": args}


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.store = CalendarTaskStore()
        self.registry = ComponentRegistry()
        self.registry.register("calendar", CalendarAPI(self.store))
        self.tools = AgentTools(self.registry)
        self.tools.begin_request("处理当前请求里的任务")
        self.tools.call("polaris_help", {"component": "calendar"}, lambda _: None)
        self.tools.setReadAllowed("calendar", True)

    def tearDown(self):
        self.tools.cancel()

    def call(self, operation, args):
        output = []
        self.tools.call("polaris_call", {"component": "calendar", "operation": operation, "args": args}, output.append)
        return output

    def plan(self, steps):
        output = []
        self.tools.call("polaris_plan", {"steps": steps}, output.append)
        return output

    def lookup(self):
        return self.call("task.list", {})

    def family(self):
        return [step("parent", "task.create", title="主任务"),
                step("child1", "subtask.create", taskId={"$ref": "parent.task.id"}, title="子任务一"),
                step("child2", "subtask.create", taskId={"$ref": "parent.task.id"}, title="子任务二")]

    def test_family_is_one_low_risk_plan_with_zero_approvals(self):
        output = self.plan(self.family())
        self.assertTrue(output[0]["ok"], output)
        self.assertEqual(len(output[0]["result"]["steps"]), 3)
        self.assertEqual(output[0]["result"]["risk"], "low")
        self.assertFalse(self.tools.pending)
        self.assertEqual(len(self.store.allEntries), 1)
        self.assertEqual([child.title for child in self.store.allEntries[0]["task"].subtasks], ["子任务一", "子任务二"])

    def test_plan_and_direct_api_share_creation_normalization(self):
        direct = CalendarAPI(self.store)
        args = {"title": "  同样的任务  ", "date": "2026-10-29", "time": "9:00"}
        expected = direct.call("task.create", args)["task"]
        output = self.plan([step("create", "task.create", **args)])
        self.assertTrue(output[0]["ok"], output)
        actual = output[0]["result"]["steps"][0]["result"]["task"]
        for field in ("title", "date", "time", "done", "important"):
            self.assertEqual(actual[field], expected[field])
        self.assertEqual(actual["time"], "09:00")
        self.assertEqual(actual["title"], "同样的任务")

    def test_component_preflight_is_side_effect_free_and_preview_is_normalized(self):
        args = {"title": "  稍后创建  ", "date": "2026-10-29", "time": "9:00"}
        prepared = self.registry.prepare_write("calendar", "task.create", args)
        self.assertFalse(self.store.allEntries)
        self.assertEqual(args["time"], "9:00")
        self.assertEqual(prepared["time"], "09:00")
        self.tools.setAutoLowRisk(False)
        self.assertEqual(self.plan([step("create", "task.create", **args)]), [])
        shown = json.loads(self.tools.pending["arguments"])["steps"][0]["args"]
        self.assertEqual(shown, prepared)
        self.assertFalse(self.store.allEntries)

    def test_shared_tool_contract_has_no_weixin_policy(self):
        definitions = json.loads((Path(__file__).resolve().parent.parent / "integrations" / "tools.json").read_text(encoding="utf8"))
        self.assertNotIn("微信", str(definitions))
        self.assertNotIn("polaris_plan", str(definitions))
        local = next(row["function"] for row in TOOLS if row["function"]["name"] == "polaris_call")
        self.assertIn("polaris_plan", local["description"])

    def test_two_deletes_need_one_approval_and_do_not_execute_before_it(self):
        one, two = self.store.addTask("11"), self.store.addTask("22")
        self.lookup()
        output = self.plan([step("one", "task.delete", id=one.entryId), step("two", "task.delete", id=two.entryId)])
        self.assertEqual(output, [])
        self.assertEqual(len(self.store.allEntries), 2)
        self.assertIn("目标标题：22", self.tools.pending["description"])
        identity = self.tools.pending["id"]
        self.tools.approve(identity)
        self.tools.approve(identity)
        self.assertTrue(output[0]["ok"])
        self.assertEqual(len(output), 1)
        self.assertFalse(self.store.allEntries)

    def test_mixed_plan_waits_as_whole_and_rejection_does_not_add_anything(self):
        entry = self.store.addTask("keep")
        self.lookup()
        steps = [step("create", "task.create", title="new"), step("delete", "task.delete", id=entry.entryId)]
        output = self.plan(steps)
        self.assertEqual(len(self.store.allEntries), 1)
        self.tools.reject(self.tools.pending["id"])
        self.assertEqual(output[0]["error"]["code"], "approval_denied")
        self.assertEqual(self.plan(steps)[0]["error"]["code"], "approval_denied")
        self.assertEqual([entry["task"].title for entry in self.store.allEntries], ["keep"])

    def test_approved_snapshot_cannot_be_mutated_or_expanded(self):
        entry = self.store.addTask("old")
        self.lookup()
        steps = [step("rename", "task.update", id=entry.entryId, title="approved")]
        output = self.plan(steps)
        identity = self.tools.pending["id"]
        steps[0]["args"]["title"] = "injected"
        self.assertEqual(self.plan([step("extra", "task.create", title="extra")])[0]["error"]["code"], "approval_pending")
        self.tools.approve(identity)
        self.assertTrue(output[0]["ok"])
        self.assertEqual(entry.title, "approved")
        self.assertEqual(len(self.store.allEntries), 1)
        extra = self.plan([step("newDelete", "task.delete", id=entry.entryId)])
        self.assertEqual(extra, [])
        self.assertTrue(self.tools.pending)

    def test_invalid_child_or_forward_reference_fails_before_parent_creation(self):
        family = self.family()
        family[-1]["args"]["title"] = " "
        self.assertFalse(self.plan(family)[0]["ok"])
        family = self.family()
        family[1]["args"]["taskId"] = {"$ref": "child2.task.id"}
        self.assertEqual(self.plan(family)[0]["error"]["code"], "invalid_reference")
        self.assertFalse(self.store.allEntries)

    def test_partial_failure_stops_remaining_steps_and_prevents_plan_replay(self):
        entry = self.store.addTask("delete once")
        self.lookup()
        steps = [step("delete1", "task.delete", id=entry.entryId),
                 step("delete2", "task.delete", id=entry.entryId),
                 step("never", "task.create", title="must not be created")]
        output = self.plan(steps)
        self.tools.approve(self.tools.pending["id"])
        self.assertFalse(output[0]["ok"])
        self.assertTrue(output[0]["applied"])
        self.assertEqual(output[0]["unexecuted"], ["never"])
        self.assertEqual(len(output[0]["steps"]), 2)
        self.assertFalse(self.store.allEntries)
        self.assertEqual(self.plan(steps)[0]["error"]["code"], "plan_already_submitted")

    def test_budget_counts_steps_and_direct_write_cannot_bypass_plan(self):
        self.assertEqual(self.call("task.create", {"title": "bypass"})[0]["error"]["code"], "plan_required")
        steps = [step("s" + str(i), "task.create", title=str(i)) for i in range(8)]
        self.assertTrue(self.plan(steps)[0]["ok"])
        self.assertEqual(self.plan([step("extra", "task.create", title="extra")])[0]["error"]["code"], "plan_limit")
        self.assertEqual(len(self.store.allEntries), 8)

    def test_cancel_and_unknown_operation_do_not_inherit_low_risk_permission(self):
        entry = self.store.addTask("preserve")
        self.lookup()
        output = self.plan([step("complete", "task.complete", id=entry.entryId)])
        identity = self.tools.pending["id"]
        self.tools.cancel()
        self.tools.approve(identity)
        self.assertEqual(output, [])
        self.assertFalse(entry.done)
        self.assertEqual(self.plan(self.family())[0]["error"]["code"], "request_required")

    def test_expanded_low_risk_scope_requires_new_approval(self):
        self.assertTrue(self.plan([step("first", "task.create", title="first")])[0]["ok"])
        output = self.plan([step("extra", "task.create", title="extra")])
        self.assertEqual(output, [])
        self.assertEqual(len(self.store.allEntries), 1)
        self.assertIn("追加计划", self.tools.pending["description"])
        self.tools.approve(self.tools.pending["id"])
        self.assertTrue(output[0]["ok"])

    def test_renaming_step_ids_cannot_replay_a_completed_or_rejected_plan(self):
        self.assertTrue(self.plan([step("first", "task.create", title="first")])[0]["ok"])
        self.assertEqual(self.plan([step("renamed", "task.create", title="first")])[0]["error"]["code"], "plan_already_submitted")
        output = self.plan([step("extra", "task.create", title="extra")])
        self.tools.reject(self.tools.pending["id"])
        self.assertEqual(output[0]["error"]["code"], "approval_denied")
        self.assertEqual(self.plan([step("renamedExtra", "task.create", title="extra")])[0]["error"]["code"], "approval_denied")

    def test_strict_policy_persists_and_old_configs_default_to_automatic_low_risk(self):
        client = WeixinClient()
        model = DeepSeekModel(manager=FakeNetwork())
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "chat.json"
            chat = DeepSeekChat(client, model=model, registry=self.registry, state_path=path)
            self.assertTrue(chat.autoLowRisk)
            chat.setAutoLowRisk(False)
            self.assertFalse(json.loads(path.read_text(encoding="utf8"))["autoLowRisk"])
            restored = DeepSeekChat(WeixinClient(), model=model, registry=self.registry, state_path=path)
            self.assertFalse(restored.autoLowRisk)
            old = json.loads(path.read_text(encoding="utf8"))
            old.pop("autoLowRisk")
            path.write_text(json.dumps(old), encoding="utf8")
            legacy = DeepSeekChat(WeixinClient(), model=model, registry=self.registry, state_path=path)
            self.assertTrue(legacy.autoLowRisk)
            self.tools.setAutoLowRisk(False)
            output = self.plan(self.family())
            self.assertEqual(output, [])
            self.assertFalse(self.store.allEntries)
            self.tools.approve(self.tools.pending["id"])
            self.assertTrue(output[0]["ok"])
            restored.suspend()
            legacy.suspend()
            chat.suspend()


if __name__ == "__main__":
    unittest.main()
