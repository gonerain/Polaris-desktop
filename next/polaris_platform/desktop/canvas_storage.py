"""Canvas-owned durable geometry, containing no provider or session state."""
import json
import math
from pathlib import Path

from ..persistence import write_json


def layout(value):
    if not isinstance(value, dict):
        raise ValueError('Invalid canvas layout')
    result = {}
    for key in ('x', 'y', 'width', 'height'):
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise ValueError('Invalid canvas geometry')
        if key in ('width', 'height') and number <= 0:
            raise ValueError('Invalid canvas size')
        result[key] = number
    if not isinstance(value.get('collapsed'), bool):
        raise ValueError('Invalid canvas collapse state')
    result['collapsed'] = value['collapsed']
    return result


class CanvasStorage:
    def __init__(self, data_dir=None):
        self.path = Path(data_dir) / 'layout.json' if data_dir is not None else None
        self.entries = {}
        self.size = (880, 620)
        self.theme = 'light'
        self.error = None
        try:
            if self.path is not None and self.path.exists():
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if data['version'] != 1 or not isinstance(data['views'], list):
                    raise ValueError('Unsupported canvas layout')
                width, height = data['size']
                if any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in (width, height)):
                    raise ValueError('Invalid canvas window size')
                entries = {}
                for entry in data['views']:
                    if any(not isinstance(entry[k], str) or not entry[k] for k in ('id', 'target', 'view')) or entry['id'] in entries:
                        raise ValueError('Invalid canvas view identity')
                    entries[entry['id']] = {k: entry[k] for k in ('id', 'target', 'view')}
                    entries[entry['id']]['layout'] = layout(entry['layout'])
                theme = data.get('theme', 'light')
                if theme not in ('light', 'dark', 'warm'):
                    raise ValueError('Invalid canvas theme')
                self.theme = theme
                self.entries, self.size = entries, (width, height)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.error = str(error)

    def save(self):
        if self.error is not None:
            raise ValueError('画布布局文件无法读取，已保留原文件：' + self.error)
        if self.path is None:
            return
        write_json(self.path, dict(version=1, size=list(self.size), theme=self.theme, views=list(self.entries.values())))
