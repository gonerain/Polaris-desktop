"""Offline, deterministic tests: never contact Microsoft or use real credentials."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from uuid import uuid4

from support import initialize_qt_tests, pump
from polaris.sync_merge import capture, merge, materialize, SyncError
from polaris.storage import SnapshotRepository, StorageError, empty_snapshot
from polaris.tasks import CalendarTaskStore
from polaris.calendar_sync import CalendarSync
from polaris import onedrive_api as api

EMPTY = {"version": 1, "records": {}}


def snapshot(title="task", uid=None, identity=1):
    return {"version": 3, "nextId": identity + 1, "syncState": deepcopy(EMPTY),
            "days": {}, "inbox": [{"id": identity, "syncId": uid or str(uuid4()),
             "title": title, "done": False, "time": "", "notes": "", "important": False, "subtasks": []}]}


class MergeTests(unittest.TestCase):
    def test_independent_integer_ids_do_not_collide(self):
        a, b = snapshot("a"), snapshot("b")
        state, conflicts = merge([capture(a, EMPTY, "A"), capture(b, EMPTY, "B")])
        doc = materialize(state, a)
        self.assertEqual(conflicts, 0)
        self.assertEqual({t["title"] for t in doc["inbox"]}, {"a", "b"})
        self.assertEqual(len({t["id"] for t in doc["inbox"]}), 2)
        self.assertEqual(next(t["id"] for t in doc["inbox"] if t["title"] == "a"), 1)

    def test_concurrent_edits_keep_both_and_converge(self):
        doc = snapshot()
        initial = capture(doc, EMPTY, "A")
        a, b = deepcopy(doc), deepcopy(doc)
        a["inbox"][0]["notes"] = "a-notes"
        b["inbox"][0]["notes"] = "b-notes"
        sa, sb = capture(a, initial, "A"), capture(b, initial, "B")
        merged, conflicts = merge([initial, sa, sb])
        self.assertEqual(conflicts, 1)
        self.assertEqual(merged, merge([sb, initial, sa])[0])
        output = materialize(merged, a)
        self.assertEqual({t["notes"] for t in output["inbox"]}, {"a-notes", "b-notes"})
        self.assertEqual(merge([merged, sa, sb, initial])[0], merged)
        self.assertEqual(merge([merged, merged])[0], merged)

    def test_sequential_edit_and_delete_do_not_resurrect(self):
        doc = snapshot()
        initial = capture(doc, EMPTY, "A")
        changed = deepcopy(doc)
        changed["inbox"][0]["done"] = True
        edited = capture(changed, initial, "B")
        deleted = capture(empty_snapshot(), edited, "A")
        state, conflicts = merge([initial, deleted, edited])
        self.assertEqual(conflicts, 0)
        self.assertEqual(materialize(state, doc)["inbox"], [])

    def test_delete_edit_conflict_preserves_edit(self):
        doc = snapshot()
        initial = capture(doc, EMPTY, "A")
        deleted = capture(empty_snapshot(), initial, "A")
        doc["inbox"][0]["notes"] = "do not lose"
        edited = capture(doc, initial, "B")
        state, conflicts = merge([deleted, edited])
        self.assertEqual(conflicts, 1)
        self.assertEqual(materialize(state, doc)["inbox"][0]["notes"], "do not lose")

    def test_subtasks_conflict_copies_have_unique_ids(self):
        doc = snapshot()
        doc["inbox"][0]["subtasks"] = [snapshot("child", identity=2)["inbox"][0]]
        initial = capture(doc, EMPTY, "A")
        a, b = deepcopy(doc), deepcopy(doc)
        a["inbox"][0]["subtasks"][0]["title"] = "child A"
        b["inbox"][0]["subtasks"][0]["title"] = "child B"
        state, _ = merge([capture(a, initial, "A"), capture(b, initial, "B")])
        output = materialize(state, doc)
        entries = [e for task in output["inbox"] for e in [task, *task["subtasks"]]]
        self.assertEqual(len({e["id"] for e in entries}), 4)
        self.assertEqual(len({e["syncId"] for e in entries}), 4)

    def test_deleted_conflict_copy_stays_deleted(self):
        doc = snapshot()
        initial = capture(doc, EMPTY, "A")
        a, b = deepcopy(doc), deepcopy(doc)
        a["inbox"][0]["title"], b["inbox"][0]["title"] = "A", "B"
        sa, sb = capture(a, initial, "A"), capture(b, initial, "B")
        merged, _ = merge([sa, sb])
        output = materialize(merged, a)
        output["inbox"] = [t for t in output["inbox"] if "冲突副本" not in t["title"]]
        deleted = capture(output, merged, "A")
        final, _ = merge([deleted, initial, sa, sb])
        self.assertEqual(len(materialize(final, output)["inbox"]), 1)

    def test_invalid_remote_state_refused(self):
        with self.assertRaises(StorageError):
            merge([{"version": 99, "records": {}}])
        state = capture(snapshot(), EMPTY, "A")
        next(iter(state["records"].values()))["clock"] = {"A": -1}
        with self.assertRaises(StorageError):
            merge([state])


class TransportTests(unittest.TestCase):
    def test_graph_pagination_never_leaks_token_to_other_host(self):
        for url in ["https://evil.example/v1.0/me", "https://graph.microsoft.com@evil.example/v1.0/me",
                    "https://graph.microsoft.com:443/v1.0/me"]:
            with patch.object(api, "request_json") as request:
                with self.assertRaises(SyncError):
                    api.graph(url, {"access_token": "secret"})
                request.assert_not_called()

    def test_unique_checkpoint_no_change_and_pagination(self):
        state = capture(snapshot(), EMPTY, "A")
        owner = str(uuid4())
        packets, uploads = {}, []

        def graph(path, token, **kw):
            if kw.get("method") == "PUT":
                uploads.append(path)
                self.assertIn("conflictBehavior=fail", path)
                packets["latest"] = json.loads(kw["data"])
                return {"id": "latest"}
            if path == "/me/drive/special/approot":
                return {}
            if path.startswith("/me/drive/special/approot/children"):
                if not packets:
                    return {"value": []}
                name = api.PREFIX + owner + "-00000000000000000001-" + str(uuid4()) + ".json"
                return {"value": [{"id": "latest", "name": name, "file": {}}],
                        "@odata.nextLink": api.GRAPH + "/next"}
            if path == api.GRAPH + "/next":
                return {"value": []}
            return {"@microsoft.graph.downloadUrl": "https://download.example/signed"}

        with patch.object(api, "graph", side_effect=graph), patch.object(api, "request_json", side_effect=lambda url: packets["latest"]):
            self.assertEqual(api.synchronize(state, {}, Event(), owner, 1)[0], state)
            self.assertEqual(api.synchronize(state, {}, Event(), owner, 2)[0], state)
        self.assertEqual(len(uploads), 1)

    def test_device_login_pending_then_success(self):
        class NoWait:
            def wait(self, _):
                return False
        notifications = []
        responses = [{"verification_uri": "https://microsoft.com/devicelogin", "user_code": "ABCD",
                      "device_code": "private", "expires_in": 900, "interval": 5},
                     api.ApiFailure(400, "authorization_pending"),
                     {"access_token": "fake-access", "refresh_token": "fake-refresh", "expires_in": 3600}]
        with patch.object(api, "oauth", side_effect=responses) as oauth:
            token = api.login(str(uuid4()), NoWait(), notifications.append)
        self.assertEqual(token["access_token"], "fake-access")
        self.assertEqual(notifications, [{"url": "https://microsoft.com/devicelogin", "code": "ABCD"}])
        self.assertEqual(oauth.call_args_list[0].args[1]["scope"], "offline_access Files.ReadWrite.AppFolder")

    def test_device_login_rejects_unknown_verification_host(self):
        with patch.object(api, "oauth", return_value={"verification_uri": "https://evil.example"}):
            with self.assertRaises(SyncError):
                api.login(str(uuid4()), Event(), lambda value: self.fail("Unexpected login prompt"))

    def test_expired_token_refresh_uses_public_client(self):
        token = {"access_token": "old", "refresh_token": "refresh", "expires_at": 0}
        with patch.object(api, "oauth", return_value={"access_token": "new", "expires_in": 3600}) as oauth:
            fresh = api.refresh("client", token)
        self.assertEqual(fresh["refresh_token"], "refresh")
        self.assertNotIn("client_secret", oauth.call_args.args[1])

    def test_cancel_does_not_upload(self):
        cancel = Event()
        cancel.set()
        with patch.object(api, "graph", return_value={}) as graph:
            with self.assertRaises(SyncError):
                api.synchronize(EMPTY, {}, cancel, str(uuid4()), 1)
            self.assertFalse(any(call.kwargs.get("method") == "PUT" for call in graph.call_args_list))

    def test_newest_checkpoint_only_downloaded(self):
        owner = str(uuid4())
        names = [api.PREFIX + owner + f"-{n:020d}-" + str(uuid4()) + ".json" for n in [1, 2]]
        visited = []

        def graph(path, token, **kw):
            visited.append(path)
            if path == "/me/drive/special/approot":
                return {}
            if "children" in path:
                return {"value": [{"name": name, "id": str(i), "file": {}} for i, name in enumerate(names)]}
            return {"@microsoft.graph.downloadUrl": "https://download.example/signed"}

        with patch.object(api, "graph", side_effect=graph), patch.object(api, "request_json", return_value={
            "format": "polaris-calendar", "version": 1, "state": EMPTY}):
            api.synchronize(EMPTY, {}, Event(), owner, 3)
        self.assertIn("/me/drive/items/1", visited)
        self.assertNotIn("/me/drive/items/0", visited)


class StoreControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = initialize_qt_tests()

    def test_uuid_roundtrip_and_atomic_causal_checkpoint(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tasks.json"
            SnapshotRepository(path).save(snapshot())
            store = CalendarTaskStore()
            store.initialize_storage(path)
            doc = store.export_sync_snapshot()
            state = capture(doc, EMPTY, "A")
            store.checkpoint_sync(state)
            other = CalendarTaskStore()
            other.initialize_storage(path)
            self.assertEqual(other.export_sync_snapshot(), store.export_sync_snapshot())
            with patch.object(store._repository, "save", side_effect=StorageError("disk full")):
                with self.assertRaises(StorageError):
                    store.checkpoint_sync(EMPTY)
            self.assertEqual(store._sync_state, state)

    def test_deleted_integer_ids_are_not_reused_on_import(self):
        with TemporaryDirectory() as directory:
            store = CalendarTaskStore()
            store.initialize_storage(Path(directory) / "tasks.json")
            entry = store.addInboxTask("deleted")
            deleted_id = entry.entryId
            store.removeTask(deleted_id)
            local = store.export_sync_snapshot()
            state = capture(snapshot("remote"), EMPTY, "B")
            output = materialize(state, local)
            self.assertGreater(output["inbox"][0]["id"], deleted_id)
            store.apply_sync_snapshot(output)
            self.assertGreater(store.addInboxTask("next").entryId, output["inbox"][0]["id"])

    def test_import_commits_before_changing_live_models(self):
        with TemporaryDirectory() as directory:
            store = CalendarTaskStore()
            store.initialize_storage(Path(directory) / "tasks.json")
            before = store.export_sync_snapshot()
            state = capture(snapshot("remote"), EMPTY, "B")
            output = materialize(state, before)
            with patch.object(store._repository, "save", side_effect=StorageError("disk full")):
                with self.assertRaises(StorageError):
                    store.apply_sync_snapshot(output)
            self.assertEqual(store.export_sync_snapshot(), before)
            store.apply_sync_snapshot(output)
            self.assertEqual(store.export_sync_snapshot()["inbox"][0]["title"], "remote")

    def test_edit_during_network_sync_is_not_replaced(self):
        with TemporaryDirectory() as directory:
            store = CalendarTaskStore()
            store.initialize_storage(Path(directory) / "tasks.json")
            sync = CalendarSync(store, Path(directory) / "config.json")
            sync._token = {"access_token": "not-a-real-token", "expires_at": 10**12}
            remote = capture(snapshot("remote"), EMPTY, "B")
            ready, release = Event(), Event()

            def transport(*args):
                ready.set()
                release.wait(2)
                return remote, 0

            with patch.object(api, "synchronize", side_effect=transport):
                sync.syncNow()
                for _ in range(100):
                    pump(5)
                    if ready.is_set():
                        break
                self.assertTrue(ready.is_set())
                store.addTask("local edit")
                release.set()
                for _ in range(100):
                    pump(5)
                    if not sync.busy:
                        break
            self.assertFalse(sync.busy)
            self.assertIn("本地编辑", sync.status)
            self.assertNotIn("remote", str(store.export_sync_snapshot()["inbox"]))
            self.assertNotIn("not-a-real-token", (Path(directory) / "config.json").read_text())
            sync.shutdown()


if __name__ == "__main__":
    unittest.main()
