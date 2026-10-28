"""Bounded, user-local chat settings and history; never stores an API key."""
import json
import os
from pathlib import Path
import tempfile


def valid_text(value, limit, *, empty=True):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError("聊天配置文本无效")
    value.encode("utf8")
    return value


def validate_state(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("不支持的聊天配置版本")
    valid_text(value.get("persona"), 6000, empty=False)
    if type(value.get("autoReply")) is not bool:
        raise ValueError("自动回复配置无效")
    scope = value.get("scope")
    if not isinstance(scope, list) or len(scope) != 2:
        raise ValueError("会话归属无效")
    for part in scope:
        valid_text(part, 256)
    history = value.get("history")
    if not isinstance(history, list) or len(history) > 12 or len(history) % 2:
        raise ValueError("会话上下文无效")
    total = 0
    for index, row in enumerate(history):
        if not isinstance(row, dict) or row.get("role") != ("user" if index % 2 == 0 else "assistant"):
            raise ValueError("会话角色无效")
        total += len(valid_text(row.get("content"), 4000 if index % 2 == 0 else 1800, empty=False))
    if total > 16000:
        raise ValueError("会话上下文过大")
    messages = value.get("messages")
    if not isinstance(messages, list) or len(messages) > 100:
        raise ValueError("聊天记录无效")
    for row in messages:
        if not isinstance(row, dict) or row.get("direction") not in ("in", "out"):
            raise ValueError("聊天方向无效")
        for key, limit in (("id", 256), ("text", 8000), ("status", 100), ("time", 32)):
            valid_text(row.get(key), limit)
    if (history or messages) and not all(scope):
        raise ValueError("聊天记录缺少归属")
    return value


class ChatStateStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None

    def load(self):
        if self.path is None or not self.path.exists():
            return None
        if self.path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("聊天配置文件过大")
        return validate_state(json.loads(self.path.read_text(encoding="utf8")))

    def save(self, state):
        validate_state(state)
        if self.path is None:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf8")
        if len(data) > 4 * 1024 * 1024:
            raise ValueError("聊天配置文件过大")
        temporary = None
        try:
            # mkstemp creates a 0600 file on Unix. Replace in the same directory.
            with tempfile.NamedTemporaryFile(prefix=".chat-", suffix=".tmp", dir=self.path.parent,
                                             delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True
