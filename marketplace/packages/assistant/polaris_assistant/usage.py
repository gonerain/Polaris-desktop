"""Bounded local model accounting. No message bodies or credentials are stored."""
import json
import logging
import os
from pathlib import Path
import threading
import time


class UsageLog:
    def __init__(self, path):
        self.path = Path(path) if path is not None else None
        self.lock = threading.Lock()

    def append(self, record):
        if self.path is None:
            return
        try:
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size >= 1024 * 1024:
                    os.replace(self.path, self.path.with_suffix('.jsonl.1'))
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, 'w', encoding='utf8') as stream:
                    os.chmod(self.path, 0o600)
                    stream.write(json.dumps(dict(timestamp=time.time(), **record), ensure_ascii=False) + '\n')
        except OSError:
            # Accounting must not turn an accepted response into a retry.
            logging.getLogger(__name__).warning('Model usage accounting unavailable')


def token_usage(response):
    usage = response.get('usage', {})
    if not isinstance(usage, dict):
        return {}
    result = {}
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        value = usage.get(name)
        if type(value) is int and value >= 0:
            result[name] = value
    for group, name in (('prompt_tokens_details', 'cached_tokens'),
                        ('completion_tokens_details', 'reasoning_tokens')):
        detail = usage.get(group)
        value = detail.get(name) if isinstance(detail, dict) else None
        if type(value) is int and value >= 0:
            result[name] = value
    return result
