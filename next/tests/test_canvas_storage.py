import json
from pathlib import Path
import tempfile
import unittest

import importlib.util

HAS_QT = importlib.util.find_spec('PySide6') is not None
if HAS_QT:
    from polaris_platform.desktop.canvas_storage import CanvasStorage


@unittest.skipUnless(HAS_QT, 'Optional PySide6 is not installed')
class CanvasStorageTests(unittest.TestCase):
    def test_round_trip_multiple_instances_and_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CanvasStorage(directory)
            store.size = (1000, 730)
            geometry = dict(x=11, y=22, width=340, height=240, collapsed=True)
            store.entries = {key: dict(id=key, target='provider', view='main', layout=geometry) for key in ('one', 'two')}
            store.save()
            restored = CanvasStorage(directory)
            self.assertEqual(restored.entries, store.entries)
            self.assertEqual(restored.size, (1000, 730))
            self.assertEqual(set(json.loads(store.path.read_text())), {'version', 'size', 'views', 'theme'})

    def test_old_layout_defaults_to_light_and_presets_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            path.write_text(json.dumps(dict(version=1, size=[880, 620], views=[])))
            store = CanvasStorage(directory)
            self.assertEqual(store.theme, 'light')
            for theme in ('dark', 'warm', 'light'):
                store.theme = theme
                store.save()
                self.assertEqual(CanvasStorage(directory).theme, theme)

    def test_invalid_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'layout.json'
            for content in ('{', '{"version": 2}', '{"version": 1, "views": [], "size": [0, 2]}'):
                path.write_text(content)
                store = CanvasStorage(directory)
                with self.assertRaises(ValueError):
                    store.save()
                self.assertEqual(path.read_text(), content)
