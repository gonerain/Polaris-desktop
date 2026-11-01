"""Schedule business and persistence contract tests (without Qt)."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / 'components' / 'schedule'
sys.path.insert(0, str(PACKAGE.parents[1]))
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
from polaris_schedule.model import ScheduleStore
from polaris_schedule.storage import StorageError, SnapshotRepository


class ScheduleTests(unittest.TestCase):
    def test_round_trip_and_backup_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            store = ScheduleStore(path)
            first = store.add('任务', date='2026-10-30', time='09:00')
            child = store.add_subtask(first['id'], '步骤')
            store.update_subtask(first['id'], child['id'], done=True, notes='细节')
            store.update(first['id'], important=True, notes='笔记')
            loaded = ScheduleStore(path)
            self.assertEqual(loaded.get(first['id']), store.get(first['id']))
            path.write_text('{broken', encoding='utf-8')
            recovered = ScheduleStore(path)
            self.assertTrue(recovered.storage_notice)
            self.assertTrue(list(path.parent.glob('tasks.json.corrupt-*')))
            recovered.add('恢复后')
            self.assertEqual(len(ScheduleStore(path).tasks()), 2)

    def test_atomic_failure_rolls_back_memory_and_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            store = ScheduleStore(path)
            task = store.add('原文')
            original = path.read_bytes()
            with patch('polaris_schedule.storage.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(StorageError):
                    store.update(task['id'], title='新文')
            self.assertEqual(store.get(task['id'])['title'], '原文')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(ScheduleStore(path).get(task['id'])['title'], '原文')

    def test_unreadable_data_never_becomes_empty_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            for content in ('broken', '{"version":99,"tasks":[]}'):
                path.write_text(content)
                with self.assertRaises(StorageError):
                    ScheduleStore(path)
                self.assertEqual(path.read_text(), content)

    def test_strict_rules_inbox_and_defensive_copies(self):
        store = ScheduleStore()
        for day in ('2026-02-29', '20261030', '2026-1-01', False):
            with self.assertRaises(ValueError):
                store.add('bad', date=day)
        for time in ('9:00', '24:00', '12:60', None):
            with self.assertRaises(ValueError):
                store.add('bad', date='2026-10-30', time=time)
        task = store.add('  valid  ', date='2026-10-30', time='09:00')
        moved = store.update(task['id'], date=None)
        self.assertEqual(moved['time'], '')
        moved['title'] = 'external'
        self.assertEqual(store.get(task['id'])['title'], 'valid')
        with self.assertRaises(ValueError):
            store.update(task['id'], done=1)
        self.assertEqual(len(store.tasks()), 1)

    def test_subtasks_search_delete_undo(self):
        store = ScheduleStore()
        parent = store.add('Parent')
        sub = store.add_subtask(parent['id'], 'Hidden needle')
        store.update_subtask(parent['id'], sub['id'], done=True, notes='memo')
        self.assertEqual(len(store.tasks(query='NEEDLE')), 1)
        with self.assertRaises(ValueError):
            store.update_subtask(parent['id'], sub['id'], subtasks=[])
        store.delete_subtask(parent['id'], sub['id'])
        self.assertTrue(store.can_undo)
        store.undo_delete()
        self.assertTrue(store.get(parent['id'])['subtasks'][0]['done'])
        store.delete(parent['id'])
        store.add('Another')
        store.undo_delete()
        self.assertEqual(len(store.tasks()), 2)
        self.assertIsNone(store.undo_delete())

    def test_day_batch_validates_all_and_overdue_excludes_completed(self):
        store = ScheduleStore()
        first = store.add('First', date='2026-10-28', time='08:00')
        second = store.add('Second', date='2026-10-28')
        store.update(second['id'], done=True)
        with self.assertRaises(ValueError):
            store.organize_day('2026-10-28', [{'id': first['id'], 'date': '2026-10-30'}, {'id': second['id'], 'time': '25:00'}])
        self.assertEqual(store.get(first['id'])['date'], '2026-10-28')
        moved = store.move_overdue('2026-10-30', today='2026-10-30')
        self.assertEqual([task['id'] for task in moved], [first['id']])
        self.assertEqual(store.get(second['id'])['date'], '2026-10-28')

    def test_stable_sort_and_reorder(self):
        store = ScheduleStore()
        first = store.add('First', date='2026-10-30', time='09:00')
        second = store.add('Second', date='2026-10-30', time='09:00')
        earlier = store.add('Earlier', date='2026-10-30', time='08:00')
        store.reorder([second['id'], first['id'], earlier['id']], date='2026-10-30')
        self.assertEqual([task['title'] for task in store.tasks()], ['Second', 'First', 'Earlier'])
        with self.assertRaises(ValueError):
            store.reorder([first['id'], first['id'], earlier['id']])


class ScheduleRegressionTests(unittest.TestCase):
    def test_explicit_inbox_time_is_rejected_but_reschedule_clears_old_time(self):
        store = ScheduleStore()
        for invalid in ('10:00', 'bad', None, 1):
            with self.assertRaises(ValueError):
                store.add('inbox', time=invalid)
        task = store.add('dated', date='2026-10-30', time='10:00')
        with self.assertRaises(ValueError):
            store.update(task['id'], date=None, time='10:00')
        self.assertEqual(store.get(task['id'])['date'], '2026-10-30')
        self.assertEqual(store.update(task['id'], date=None)['time'], '')
        with self.assertRaises(ValueError):
            store.update(task['id'], time='12:00')

    def test_day_organize_rejects_completed_inbox_foreign_and_invalid_ids(self):
        store = ScheduleStore()
        first = store.add('first', date='2026-10-30')
        done = store.add('done', date='2026-10-30')
        store.update(done['id'], done=True)
        foreign = store.add('foreign', date='2026-10-31')
        for invalid in ({'id': done['id']}, {'id': foreign['id']}, {'id': []}, {'id': {}}, {'id': None}, {'id': ''}, {'id': first['id']}):
            with self.assertRaises(ValueError):
                store.organize_day('2026-10-30', [{'id': first['id'], 'title': 'changed'}, invalid])
            self.assertEqual(store.get(first['id'])['title'], 'first')
        with self.assertRaises(ValueError):
            store.organize_day(None, [])
        for invalid in ([], {}, None, ''):
            with self.assertRaises(ValueError):
                store.reorder([first['id'], done['id'], invalid])

    def test_two_store_stale_writes_and_external_repair_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            first, second = ScheduleStore(path), ScheduleStore(path)
            winner = first.add('winner')
            with self.assertRaises(StorageError):
                second.add('stale')
            self.assertEqual(second.tasks(), [])
            self.assertEqual(ScheduleStore(path).tasks(), [winner])
            first.add('backup trigger')
            path.write_text('broken')
            recovered = ScheduleStore(path)
            # An external repair after recovery must not be overwritten by stale backup data.
            repaired = {'version': 1, 'tasks': [winner]}
            path.write_bytes(SnapshotRepository.encode(repaired))
            original = path.read_bytes()
            with self.assertRaises(StorageError):
                recovered.add('would overwrite repair')
            self.assertEqual(path.read_bytes(), original)

    def test_simultaneous_process_writers_have_one_winner(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'tasks.json'
            source = """
import sys, time
from pathlib import Path
from polaris_schedule.model import ScheduleStore, StorageError
path, ready, gate = map(Path, sys.argv[1:])
store = ScheduleStore(path)
ready.touch()
while not gate.exists():
    time.sleep(0.01)
try:
    store.add(ready.name)
except StorageError:
    sys.exit(3)
"""
            gate = Path(directory) / 'go'
            import os
            import time
            env = dict(os.environ, PYTHONPATH=str(PACKAGE) + os.pathsep + str(PACKAGE.parents[1]), PYTHONDONTWRITEBYTECODE='1')
            processes = [subprocess.Popen([sys.executable, '-c', source, str(path), str(Path(directory) / f'ready{i}'), str(gate)], env=env) for i in range(2)]
            try:
                deadline = time.monotonic() + 10
                while len(list(Path(directory).glob('ready*'))) != 2:
                    if time.monotonic() > deadline:
                        self.fail('writer startup timeout')
                    time.sleep(0.01)
                gate.touch()
                self.assertEqual(sorted(process.wait(timeout=10) for process in processes), [0, 3])
                self.assertEqual(len(ScheduleStore(path).tasks()), 1)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait()
