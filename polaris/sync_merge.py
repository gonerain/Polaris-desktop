"""Provider-neutral, task-level causal merge. No timestamps or silent overwrites.

Concurrent task edits keep both versions; delete/edit keeps the edited task.
Cloud packets are immutable checkpoints, so no storage-provider CAS is assumed.
"""
from copy import deepcopy
import hashlib
import json
from uuid import UUID, uuid5

from .storage import StorageError, validate_snapshot, empty_snapshot


class SyncError(StorageError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf8")


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def dominates(a, b):
    return all(a.get(k, 0) >= v for k, v in b.items()) and a != b


def validate_state(state):
    if (not isinstance(state, dict) or type(state.get("version")) is not int
            or state["version"] != 1 or not isinstance(state.get("records"), dict)):
        raise SyncError("不支持的同步数据格式，请升级 Polaris")
    if len(state["records"]) > 100000:
        raise SyncError("同步记录过多")
    child_ids = set()
    for uid, row in state["records"].items():
        try:
            if str(UUID(uid)) != uid:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise SyncError("同步任务 UUID 无效") from None
        if (not isinstance(row, dict) or set(row) != {"clock", "value"}
                or not isinstance(row.get("clock"), dict) or not row["clock"]):
            raise SyncError("同步因果版本无效")
        if len(row["clock"]) > 1000 or any(not isinstance(k, str) or type(v) is not int or v < 1
                                          for k, v in row["clock"].items()):
            raise SyncError("同步因果版本无效")
        value = row.get("value")
        if value is not None:
            if not isinstance(value, dict) or set(value) != {"task", "date", "position"}:
                raise SyncError("同步任务结构无效")
            if type(value["position"]) is not int or value["position"] < 0:
                raise SyncError("同步排序无效")
            task = deepcopy(value["task"])
            if not isinstance(task, dict) or not isinstance(task.get("subtasks", []), list):
                raise SyncError("同步子任务结构无效")
            seen = {uid}
            task.update(id=1, syncId=uid)
            for index, child in enumerate(task.get("subtasks", []), 2):
                if not isinstance(child, dict):
                    raise SyncError("同步子任务结构无效")
                try:
                    child_uid = str(UUID(child["syncId"]))
                    if child_uid != child["syncId"]:
                        raise ValueError()
                except (KeyError, ValueError, TypeError, AttributeError):
                    raise SyncError("同步子任务 UUID 无效") from None
                if child_uid in seen or child_uid in child_ids or child_uid in state["records"]:
                    raise SyncError("同步子任务 UUID 重复")
                seen.add(child_uid)
                child_ids.add(child_uid)
                child["id"] = index
            day = value["date"]
            if day is not None and not isinstance(day, str):
                raise SyncError("同步日期无效")
            document = empty_snapshot()
            document.update(days={day: [task]} if day is not None else {},
                            inbox=[task] if day is None else [], nextId=len(task.get("subtasks", [])) + 2)
            validate_snapshot(document)
    return state


def capture(snapshot, previous, device):
    """Record local changes relative to the last durable causal checkpoint."""
    state = deepcopy(validate_state(previous))
    present = {}
    groups = [(None, snapshot.get("inbox", [])), *snapshot["days"].items()]
    for day, tasks in groups:
        for position, original in enumerate(tasks):
            task = deepcopy(original)
            uid = task.pop("syncId")
            task.pop("id", None)
            for child in task.get("subtasks", []):
                child.pop("id", None)
            present[uid] = {"date": day, "position": position, "task": task}
    for uid in present.keys() | state["records"].keys():
        value = present.get(uid)
        old = state["records"].get(uid)
        if old is None or old["value"] != value:
            clock = dict(old["clock"]) if old else {}
            clock[device] = clock.get(device, 0) + 1
            state["records"][uid] = {"clock": clock, "value": value}
    return validate_state(state)


def merge(states):
    """Join all checkpoints first, then resolve only causally maximal conflicts.

    Resolution is deterministic. Distinct live versions become separate tasks,
    and each resolution clock dominates its inputs, preventing resurrection.
    """
    candidates = {}
    for state in states:
        for uid, row in validate_state(state)["records"].items():
            rows = candidates.setdefault(uid, [])
            if row not in rows:
                rows.append(deepcopy(row))
    result, copies, conflicts = {}, {}, 0
    for uid, rows in candidates.items():
        maximal = [r for r in rows if not any(dominates(other["clock"], r["clock"]) for other in rows)]
        by_value = {}
        joined = {}
        for row in maximal:
            for device, counter in row["clock"].items():
                joined[device] = max(joined.get(device, 0), counter)
            by_value[digest(row["value"])] = row["value"]
        live = sorted((key, val) for key, val in by_value.items() if val is not None)
        if len(by_value) > 1:
            conflicts += 1
        result[uid] = {"clock": joined, "value": deepcopy(live[0][1]) if live else None}
        for key, value in live[1:]:
            copy_uid = str(uuid5(UUID(uid), key))
            value = deepcopy(value)
            value["task"]["title"] += "（同步冲突副本）"
            # A conflict copy must not share child identities with the original.
            for child in value["task"].get("subtasks", []):
                child["syncId"] = str(uuid5(UUID(copy_uid), child["syncId"]))
            copies[copy_uid] = {"clock": joined, "value": value}
    # Already recorded copies/tombstones win over regenerated historical copies.
    for uid, row in copies.items():
        result.setdefault(uid, row)
    return validate_state({"version": 1, "records": result}), conflicts


def materialize(state, local):
    """Keep existing device-local integer IDs; remap imported ones safely."""
    ids = {}
    for group in [local.get("inbox", []), *local["days"].values()]:
        for task in group:
            for entry in [task, *task.get("subtasks", [])]:
                ids[entry["syncId"]] = entry["id"]
    next_id = max(max(ids.values(), default=0) + 1, local["nextId"])
    used = set()

    def identity(uid):
        nonlocal next_id
        value = ids.get(uid)
        if value is None or value in used:
            value, next_id = next_id, next_id + 1
        used.add(value)
        return value

    output = {"version": 3, "days": {}, "inbox": [], "syncState": deepcopy(state)}
    ordered = sorted(((uid, row["value"]) for uid, row in state["records"].items() if row["value"] is not None),
                     key=lambda item: (item[1]["date"] or "", item[1]["position"], item[0]))
    for uid, value in ordered:
        task = deepcopy(value["task"])
        task.update(syncId=uid, id=identity(uid))
        for child in task.get("subtasks", []):
            child["id"] = identity(child["syncId"])
        if value["date"] is None:
            task["time"] = ""
            output["inbox"].append(task)
        else:
            output["days"].setdefault(value["date"], []).append(task)
    output["nextId"] = next_id
    return validate_snapshot(output)
