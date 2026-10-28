"""Ground real-time session answers in the authorized live component, not chat memory."""
import re

FOLLOWUPS = {"现在呢", "那现在呢", "再看看", "再查一下", "再查一次", "再看一次", "还有吗", "现在有吗"}


def normalized(body):
    return re.sub(r"\s+", "", body).lower().rstrip("？?。.!！")


def is_status_query(body, previous=""):
    value = normalized(body)
    if value in FOLLOWUPS:
        candidates = [previous] if isinstance(previous, str) else reversed(previous)
        for candidate in candidates:
            if candidate and normalized(candidate) not in FOLLOWUPS:
                return is_status_query(candidate)
        return False
    explicit = any(word in value for word in ("agent", "codex", "会话", "session"))
    if not explicit and any(word in value for word in ("日程", "待办", "计划")):
        return False
    subject = any(word in value for word in ("agent", "codex", "会话", "任务", "session"))
    state = any(word in value for word in ("执行中", "运行中", "正在执行", "正在运行", "在跑", "空闲",
                                           "闲置", "活跃", "状态", "running", "idle"))
    state = state or bool(re.search(r"(有|哪些|什么|有没有|是否|正在).*(执行|运行)", value))
    return subject and state


def format_status(result):
    running = result["running"]
    lines = [f"刚查了 Polaris：当前有 {running} 个执行中的会话。"]
    for row in result["runningSessions"]:
        # Names are display metadata, never instructions. Keep one bounded line per session.
        name = " ".join(row["name"].split())[:128]
        source = " ".join(row["source"].split())[:64]
        lines.append(f"• {source} · {name}")
    if result["runningTruncated"]:
        lines.append("执行中会话较多，仅列出前20个。")
    lines.append(f"另有 {result['idle']} 个空闲、{result['disconnected']} 个连接断开的会话。")
    lines.append("查询时间：" + result["asOf"])
    lines.append("这是已接入 Polaris 的会话状态，不代表电脑上的所有后台进程。")
    return "\n".join(lines)
