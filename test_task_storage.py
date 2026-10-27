"""Real filesystem snapshots; tests never read or write the user's data directory."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from headless_test_support import HeadlessQtTestCase
from polaris.storage import SnapshotRepository, StorageError, validate_snapshot
from polaris.tasks import CalendarTaskStore


class TaskStorageTests(HeadlessQtTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "tasks.json"

    def store(self):
        store = CalendarTaskStore(today=date(2024, 1, 31))
        store.initialize_storage(self.path)
        self.addCleanup(store.deleteLater)
        return store

    def test_roundtrip_all_mutations_and_stable_ids(self):
        store = self.store()
        task = store.addTask("晨会", "09:30")
        child = task.addSubtask("准备资料")
        task.rename("项目晨会")
        task.setTime("10:00")
        child.rename("准备会议材料")
        child.setDone(True)
        task.setDone(True)
        store.selectDate("2024-02-01")
        second = store.addTask("新月份")
        restored = self.store()
        self.assertEqual(restored.taskCount, 1)
        entry = restored.tasks[0]
        self.assertEqual((entry.entryId, entry.title, entry.time, entry.done),
                         (task.entryId, "项目晨会", "10:00", True))
        self.assertEqual((entry.subtasks[0].entryId, entry.subtasks[0].title, entry.subtasks[0].done),
                         (child.entryId, "准备会议材料", True))
        restored.selectDate("2024-02-01")
        self.assertEqual(restored.tasks[0].entryId, second.entryId)
        self.assertGreater(restored.addTask("编号不冲突").entryId, second.entryId)
        self.assertFalse(restored.storageError)

    def test_subtask_removal_is_saved(self):
        store = self.store()
        task = store.addTask("父任务")
        child = task.addSubtask("子任务")
        task.removeSubtask(child.entryId)
        self.assertEqual(self.store().tasks[0].subtaskCount, 0)

    def test_delete_undo_restores_original_day_id_and_children(self):
        store = self.store()
        task = store.addTask("可恢复")
        task.addSubtask("子任务").setDone(True)
        self.assertTrue(store.removeTask(task.entryId))
        self.assertEqual(self.store().taskCount, 0)
        store.selectDate("2024-02-01")
        self.assertTrue(store.undoDelete())
        self.assertFalse(store.canUndoDelete)
        restored = self.store().tasks[0]
        self.assertEqual(restored.entryId, task.entryId)
        self.assertTrue(restored.subtasks[0].done)
        self.assertFalse(store.undoDelete())

    def test_move_task_across_dates_and_delete_from_overview(self):
        store = self.store()
        task = store.addTask("改期", "12:00")
        self.assertFalse(store.moveTask(task.entryId, "20240202"))
        self.assertFalse(store.moveTask(task.entryId, "2024-02-30"))
        self.assertTrue(store.moveTask(task.entryId, "2024-02-02"))
        self.assertEqual(store.taskCount, 0)
        restored = self.store()
        restored.selectDate("2024-02-02")
        self.assertEqual(restored.tasks[0].entryId, task.entryId)
        self.assertTrue(store.removeTask(task.entryId))  # not the selected date
        self.assertEqual(store.allEntries, [])

    def test_corrupt_main_recovers_backup_and_preserves_input(self):
        store = self.store()
        task = store.addTask("上个版本")
        task.rename("最新版本")
        self.path.write_text("broken", encoding="utf-8")
        recovered = self.store()
        self.assertEqual(recovered.tasks[0].title, "上个版本")
        self.assertTrue(recovered.storageNotice)
        self.assertTrue(list(self.path.parent.glob("tasks.corrupt-*.json")))
        recovered.addTask("恢复后")
        self.assertFalse(recovered.storageError)
        self.assertEqual(self.store().taskCount, 2)

    def test_corrupt_main_and_backup_never_overwrite_originals(self):
        self.path.write_text("bad main", encoding="utf-8")
        backup = self.path.with_suffix(".json.bak")
        backup.write_text("bad backup", encoding="utf-8")
        store = self.store()
        self.assertTrue(store.storageError)
        store.addTask("临时内存任务")
        self.assertFalse(store.retrySave())
        self.assertEqual(self.path.read_text(), "bad main")
        self.assertEqual(backup.read_text(), "bad backup")

    def test_failed_atomic_commit_retains_previous_snapshot_and_retries(self):
        store = self.store()
        task = store.addTask("已保存")
        original_write = SnapshotRepository.atomic_write

        def fail_primary(path, data):
            if path == self.path:
                raise StorageError("模拟磁盘写入失败")
            return original_write(path, data)

        with patch.object(SnapshotRepository, "atomic_write", side_effect=fail_primary):
            task.rename("内存新版本")
            self.assertIn("保存失败", store.storageError)
            self.assertEqual(SnapshotRepository.read(self.path)["days"]["2024-01-31"][0]["title"], "已保存")
        self.assertTrue(store.retrySave())
        self.assertFalse(store.storageError)
        self.assertEqual(self.store().tasks[0].title, "内存新版本")

    def test_runtime_corruption_blocks_overwrite(self):
        store = self.store()
        store.addTask("正常数据")
        self.path.write_text("external corruption", encoding="utf-8")
        store.addTask("新任务")
        self.assertTrue(store.storageError)
        self.assertEqual(self.path.read_text(), "external corruption")

    def test_missing_primary_can_recover_backup(self):
        store = self.store()
        task = store.addTask("备份版本")
        task.rename("新版本")
        self.path.unlink()
        self.assertEqual(self.store().tasks[0].title, "备份版本")

    def test_reject_bad_version_duplicate_ids_and_invalid_time(self):
        entry = {"id": 1, "title": "任务", "done": False, "time": "25:00", "subtasks": []}
        document = {"version": 1, "days": {"2024-01-31": [entry]}}
        with self.assertRaises(StorageError):
            validate_snapshot(document)
        entry["time"] = ""
        document["days"]["2024-02-01"] = [dict(entry)]
        with self.assertRaises(StorageError):
            validate_snapshot(document)
        with self.assertRaises(StorageError):
            validate_snapshot({"version": 99, "days": {}})

    def test_navigation_does_not_write_task_file(self):
        store = self.store()
        store.addTask("不变")
        before = self.path.read_bytes()
        stamp = self.path.stat().st_mtime_ns
        store.selectDate("2024-02-02")
        store.changeDay(1)
        store.goToday()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_midnight_follows_today_but_not_browsed_date(self):
        store = CalendarTaskStore()
        self.addCleanup(store.deleteLater)
        store._today = date(2024, 1, 31)
        store._selected = store._today
        with patch("polaris.tasks.date", wraps=date) as clock:
            clock.today.return_value = date(2024, 2, 1)
            store.refreshToday()
        self.assertEqual(store.selectedDate, "2024-02-01")
        store.selectDate("2024-01-20")
        with patch("polaris.tasks.date", wraps=date) as clock:
            clock.today.return_value = date(2024, 2, 2)
            store.refreshToday()
        self.assertEqual(store.todayDate, "2024-02-02")
        self.assertEqual(store.selectedDate, "2024-01-20")
