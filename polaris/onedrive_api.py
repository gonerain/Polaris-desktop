"""OneDrive app-folder transport: public-client device login, immutable packets.

Inspired by Super Productivity's provider separation; no upstream code/keys used.
Only the global Microsoft cloud is supported. Tokens stay in process memory.
"""
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

from .sync_merge import SyncError, encoded, validate_state, merge, digest

GRAPH = "https://graph.microsoft.com/v1.0"
AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0"
SCOPE = "offline_access Files.ReadWrite.AppFolder"
PREFIX = "polaris-calendar-v1-"
MAX_PACKET = 8 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ApiFailure(SyncError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f"OneDrive 请求失败（HTTP {status}，{code}）")


def request_json(url, *, method="GET", data=None, headers=None):
    # Never forward bearer credentials through redirects (Graph paging included).
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(MAX_PACKET + 1)
            if len(raw) > MAX_PACKET:
                raise SyncError("云端同步包过大，已停止，不覆盖本地数据")
            return json.loads(raw)
    except HTTPError as error:
        try:
            body = json.loads(error.read(65536))
            code = body.get("error", "http_error")
            if isinstance(code, dict):
                code = code.get("code", "http_error")
            # Only known protocol error strings; never surface response bodies.
            if code not in {"authorization_pending", "slow_down", "authorization_declined", "expired_token",
                            "invalid_grant", "invalid_client", "invalid_request", "access_denied"}:
                code = "request_rejected"
        except (ValueError, TypeError, AttributeError):
            code = "http_error"
        raise ApiFailure(error.code, code) from None
    except (URLError, TimeoutError, OSError):
        raise SyncError("网络请求失败，请检查连接后重试") from None
    except (ValueError, TypeError):
        raise SyncError("云端返回了无效 JSON") from None


def oauth(endpoint, fields):
    return request_json(AUTH + endpoint, method="POST", data=urlencode(fields).encode(),
                        headers={"Content-Type": "application/x-www-form-urlencoded"})


def login(client_id, cancel, notify):
    device = oauth("/devicecode", {"client_id": client_id, "scope": SCOPE})
    uri = device.get("verification_uri")
    if uri != "https://microsoft.com/devicelogin":
        # Microsoft may use its canonical www host as well.
        if uri != "https://www.microsoft.com/devicelogin":
            raise SyncError("微软返回了未知登录地址，已停止登录")
    notify({"url": uri, "code": device["user_code"]})
    interval = max(5, int(device.get("interval", 5)))
    deadline = time.monotonic() + min(int(device["expires_in"]), 900)
    while time.monotonic() < deadline:
        if cancel.wait(interval):
            raise SyncError("已取消登录")
        try:
            return token_result(oauth("/token", {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                                "client_id": client_id, "device_code": device["device_code"]}))
        except ApiFailure as error:
            if error.code == "slow_down":
                interval += 5
            elif error.code != "authorization_pending":
                raise
    raise SyncError("登录码已过期，请重新登录")


def token_result(result, previous=None):
    if not isinstance(result.get("access_token"), str) or not result["access_token"]:
        raise SyncError("微软未返回有效访问凭证")
    return {"access_token": result["access_token"],
            "refresh_token": result.get("refresh_token") or (previous or {}).get("refresh_token", ""),
            "expires_at": time.time() + int(result.get("expires_in", 3600))}


def refresh(client_id, token):
    if token.get("expires_at", 0) > time.time() + 120:
        return token
    if not token.get("refresh_token"):
        raise SyncError("登录已过期，请断开后重新登录")
    return token_result(oauth("/token", {"client_id": client_id, "grant_type": "refresh_token",
                                       "refresh_token": token["refresh_token"], "scope": SCOPE}), token)


def graph(path, token, **kwargs):
    url = path if path.startswith("https://") else GRAPH + path
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or not parsed.path.startswith("/v1.0/"):
        raise SyncError("拒绝未知 Graph 地址，不发送访问凭证")
    return request_json(url, headers={"Authorization": "Bearer " + token["access_token"],
                                      "Content-Type": "application/json"}, **kwargs)


def synchronize(local_state, token, cancel, device, sequence):
    """Read immutable checkpoints, join, then publish to a new unique filename.

    No in-place cloud writes; two devices cannot overwrite each other's packet.
    Historical packets are intentionally retained in this first version.
    """
    states = [validate_state(local_state)]
    remote_hashes = set()
    # GET approot provisions the application's folder on first use.
    graph("/me/drive/special/approot", token)
    path = "/me/drive/special/approot/children?$top=200"
    seen_pages, total = set(), 0
    latest = {}
    pattern = re.compile(re.escape(PREFIX) + r"([0-9a-f-]{36})-(\d{20})-([0-9a-f-]{36})\.json$")
    while path:
        if cancel.is_set():
            raise SyncError("已取消同步")
        if path in seen_pages or len(seen_pages) >= 50:
            raise SyncError("云端分页异常，已停止同步")
        seen_pages.add(path)
        page = graph(path, token)
        if not isinstance(page.get("value"), list):
            raise SyncError("OneDrive 文件列表无效")
        for item in page["value"]:
            name = item.get("name", "")
            if not name.startswith(PREFIX) or not name.endswith(".json") or "file" not in item:
                continue
            match = pattern.fullmatch(name)
            if not match:
                raise SyncError("云端检查点名称不兼容，请升级或检查应用文件夹")
            owner, serial = match[1], int(match[2])
            previous = latest.get(owner)
            if previous is None or serial > previous[0]:
                latest[owner] = (serial, [item])
            elif serial == previous[0]:
                previous[1].append(item)
        path = page.get("@odata.nextLink")
    # A newer checkpoint from one device includes its prior causal history.
    # List old packets for recovery, but download only the newest per device.
    items = [item for _, group in latest.values() for item in group]
    if len(items) > 500:
        raise SyncError("同步设备/分支过多，已停止同步")
    for item in items:
        if cancel.is_set():
            raise SyncError("已取消同步")
        metadata = graph("/me/drive/items/" + quote(item["id"], safe=""), token)
        download_url = metadata.get("@microsoft.graph.downloadUrl", "")
        parsed = urlsplit(download_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise SyncError("OneDrive 下载地址无效")
        # Signed download URLs receive NO bearer header, and no redirects.
        packet = request_json(download_url)
        total += len(encoded(packet))
        if total > 64 * 1024 * 1024:
            raise SyncError("云端数据超过首版读取上限，已停止同步")
        if not isinstance(packet, dict) or packet.get("format") != "polaris-calendar" or packet.get("version") != 1:
            raise SyncError("云端同步包格式不支持，请升级 Polaris")
        state = validate_state(packet.get("state"))
        states.append(state)
        remote_hashes.add(digest(state))
    state, conflicts = merge(states)
    if digest(state) not in remote_hashes:
        if cancel.is_set():
            raise SyncError("已取消同步")
        packet = encoded({"format": "polaris-calendar", "version": 1, "state": state})
        if len(packet) > MAX_PACKET:
            raise SyncError("同步数据超过首版8MiB上限")
        sequence = max(sequence, latest.get(device, (0, []))[0] + 1)
        name = PREFIX + device + f"-{sequence:020d}-" + str(uuid4()) + ".json"
        graph("/me/drive/special/approot:/" + name + ":/content?@microsoft.graph.conflictBehavior=fail",
              token, method="PUT", data=packet)
    return state, conflicts
