"""Read-only Google Calendar desktop OAuth and paginated incremental sync."""
import base64
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlparse, unquote
from urllib.request import Request, urlopen
import webbrowser

from .credentials import CredentialStore
from .storage import SnapshotRepository

SCOPES = ('https://www.googleapis.com/auth/calendar.calendarlist.readonly',
          'https://www.googleapis.com/auth/calendar.events.readonly')
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API_URL = 'https://www.googleapis.com/calendar/v3/'


class GoogleError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def request_json(url, *, form=None, token=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if form is not None:
        data = urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        body = json.loads(error.read())
        detail = body.get('error', {})
        message = detail.get('message', str(error)) if isinstance(detail, dict) else body.get('error_description', detail)
        raise GoogleError(error.code, 'Google Calendar：' + message) from None


def event_view(event, calendar):
    """Keep exact API time values; the view renders timed events in system local time."""
    return {'id': event['id'], 'calendarId': calendar['id'], 'calendarTitle': calendar['title'],
            'color': calendar['color'], 'title': event.get('summary', '（无标题）'),
            'start': event['start'], 'end': event['end'], 'location': event.get('location', ''),
            'description': event.get('description', ''), 'url': event.get('htmlLink', ''),
            'recurring': 'recurringEventId' in event, 'googleEvent': True}


class GoogleCalendar:
    def __init__(self, directory, changed=lambda: None, transport=request_json, vault=None):
        self.directory = Path(directory)
        self.path = self.directory / 'google-calendar.json'
        self.changed = changed
        self.transport = transport
        self.vault = vault or CredentialStore(hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest())
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.closed = threading.Event()
        self.cancelled = threading.Event()
        self.thread = None
        self.job = None
        self.busy = False
        self.error = ''
        self.auth_url = ''
        self.authorizing = False
        self.data = {'version': 1, 'connected': False, 'calendars': [], 'selected': [],
                     'cache': {}, 'lastSync': '', 'windowDay': ''}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
            if self.data['version'] != 1:
                raise ValueError('不支持的 Google 日历缓存版本')

    def snapshot(self):
        with self.lock:
            events = []
            for calendar in self.data['calendars']:
                if calendar['id'] in self.data['selected']:
                    for event in self.data['cache'].get(calendar['id'], {}).get('events', {}).values():
                        events.append(event_view(event, calendar))
            return deepcopy({'connected': self.data['connected'], 'calendars': self.data['calendars'],
                             'selected': self.data['selected'], 'events': events,
                             'lastSync': self.data['lastSync'], 'busy': self.busy, 'error': self.error,
                             'authorizing': self.authorizing, 'authUrl': self.auth_url})

    def _save(self, data):
        if self.closed.is_set():
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        SnapshotRepository.atomic_write(self.path, SnapshotRepository.encode(data))
        with self.lock:
            self.data = data

    def start(self):
        self.thread = threading.Thread(target=self._run, name='schedule-google-calendar', daemon=True)
        self.thread.start()
        if self.data['connected']:
            self.wake.set()

    def stop(self):
        self.closed.set()
        self.cancelled.set()
        self.wake.set()

    def _notify(self):
        if not self.closed.is_set():
            self.changed()

    def _submit(self, job):
        with self.lock:
            if self.busy:
                raise ValueError('Google 日历正在处理，请等待完成或取消授权')
            self.busy = True
            self.error = ''
            self.job = job
            self.wake.set()
        self._notify()
        return {'accepted': True}

    def _run(self):
        # Sync independently of view lifetime. Waiting for OAuth has no total deadline.
        while not self.closed.is_set():
            self.wake.wait(300)
            self.wake.clear()
            if self.closed.is_set():
                return
            with self.lock:
                job, self.job = self.job, None
                if job is None and self.data['connected']:
                    job = self._sync
                if job is not None:
                    self.busy = True
            self._notify()
            if job is not None:
                try:
                    job()
                except Exception as error:
                    with self.lock:
                        self.error = str(error)
                finally:
                    with self.lock:
                        self.busy = False
                        self.authorizing = False
                        self.auth_url = ''
                    self._notify()

    def connect(self, client_file):
        if not isinstance(client_file, str) or not client_file.strip():
            raise ValueError('请选择 Google 桌面 OAuth 客户端 JSON 文件')
        if client_file.startswith('file:'):
            client_file = unquote(urlparse(client_file).path)
            if __import__('os').name == 'nt':
                client_file = client_file.lstrip('/')
        config = json.loads(Path(client_file).expanduser().read_text(encoding='utf-8'))
        client = config.get('installed')
        if not isinstance(client, dict) or not isinstance(client.get('client_id'), str) or not client['client_id'].endswith('.apps.googleusercontent.com'):
            raise ValueError('需要 Google Cloud 中“桌面应用”类型的 OAuth 客户端 JSON')
        client = {k: client[k] for k in ('client_id', 'client_secret') if k in client}
        return self._submit(lambda: self._authorize(client))

    def cancel_authorization(self):
        with self.lock:
            if self.authorizing:
                self.cancelled.set()
        return {'cancelled': True}

    def sync(self):
        if not self.data['connected']:
            raise ValueError('请先连接 Google Calendar')
        return self._submit(self._sync)

    def select(self, calendar_ids):
        if not isinstance(calendar_ids, list) or any(not isinstance(x, str) for x in calendar_ids):
            raise ValueError('calendar_ids 必须为日历 ID 数组')
        if not set(calendar_ids) <= {c['id'] for c in self.data['calendars']}:
            raise ValueError('选择了未知日历')
        def select_and_sync():
            data = deepcopy(self.data)
            data['selected'] = list(dict.fromkeys(calendar_ids))
            data['cache'] = {k: v for k, v in data['cache'].items() if k in calendar_ids}
            self._save(data)
            self._notify()
            self._sync()
        return self._submit(select_and_sync)

    def disconnect(self):
        def disconnect():
            # Local disconnect removes the saved credential and cached events.
            self.vault.delete()
            self._save({'version': 1, 'connected': False, 'calendars': [], 'selected': [],
                        'cache': {}, 'lastSync': '', 'windowDay': ''})
        return self._submit(disconnect)

    def _authorize(self, client):
        # Verify that the native credential store is available before opening OAuth.
        self.vault.get()
        self.cancelled.clear()
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        state = secrets.token_urlsafe(32)
        outcome = {}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # Authorization codes must not reach request logs.

            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                valid = parsed.path == '/oauth2callback' and secrets.compare_digest(params.get('state', [''])[0], state)
                if not valid:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'Invalid OAuth callback')
                    return
                outcome.update(params)
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write('授权结果已收到，可以关闭此页面并返回北极星。'.encode())
        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            server.timeout = 0.5  # Poll cancellation, not an authorization deadline.
            redirect = 'http://127.0.0.1:' + str(server.server_port) + '/oauth2callback'
            url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
                'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
                'scope': ' '.join(SCOPES), 'access_type': 'offline', 'prompt': 'consent',
                'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
            with self.lock:
                self.authorizing = True
                self.auth_url = url
            self._notify()
            webbrowser.open(url)
            while not outcome and not self.cancelled.is_set():
                server.handle_request()
        with self.lock:
            self.authorizing = False
            self.auth_url = ''
        self._notify()
        if self.cancelled.is_set():
            return
        if 'error' in outcome:
            raise ValueError('Google 授权失败：' + outcome['error'][0])
        tokens = self.transport(TOKEN_URL, form={**client, 'grant_type': 'authorization_code',
                                'code': outcome['code'][0], 'code_verifier': verifier, 'redirect_uri': redirect})
        if 'refresh_token' not in tokens:
            raise ValueError('Google 未返回离线授权令牌，请重新连接并授予日历读取权限')
        if self.closed.is_set():
            return
        self.vault.set(json.dumps({**client, 'refresh_token': tokens['refresh_token']}))
        self._save({'version': 1, 'connected': True, 'calendars': [], 'selected': [],
                    'cache': {}, 'lastSync': '', 'windowDay': ''})
        self._sync(initial=True)

    def _pages(self, path, token, params=None):
        params = dict(params or {})
        while True:
            page = self.transport(API_URL + path + '?' + urlencode(params), token=token)
            yield page
            if 'nextPageToken' not in page:
                break
            params['pageToken'] = page['nextPageToken']

    def _events(self, calendar_id, token, previous, day):
        path = 'calendars/' + quote(calendar_id, safe='') + '/events'
        params = {'singleEvents': 'true', 'maxResults': 2500}
        incremental = previous.get('syncToken') and previous.get('windowDay') == day.isoformat()
        if incremental:
            params['syncToken'] = previous['syncToken']
        else:
            # A new window each local day also discovers newly entering recurring instances.
            params['timeMin'] = datetime.combine(day - timedelta(days=90), datetime.min.time(), timezone.utc).isoformat()
            params['timeMax'] = datetime.combine(day + timedelta(days=366), datetime.min.time(), timezone.utc).isoformat()
        events = deepcopy(previous['events']) if incremental else {}
        try:
            for page in self._pages(path, token, params):
                for event in page.get('items', []):
                    if event.get('status') == 'cancelled':
                        events.pop(event['id'], None)
                    else:
                        events[event['id']] = event
                if 'nextSyncToken' in page:
                    sync_token = page['nextSyncToken']
        except GoogleError as error:
            if error.status == 410 and incremental:
                return self._events(calendar_id, token, {}, day)
            raise
        return {'events': events, 'syncToken': sync_token, 'windowDay': day.isoformat()}

    def _sync(self, initial=False):
        saved = self.vault.get()
        if saved is None:
            raise ValueError('系统凭据库中没有 Google 授权，请重新连接')
        credential = json.loads(saved)
        result = self.transport(TOKEN_URL, form={**credential, 'grant_type': 'refresh_token'})
        token = result['access_token']
        data = deepcopy(self.data)
        calendars = []
        for page in self._pages('users/me/calendarList', token):
            for item in page.get('items', []):
                calendars.append({'id': item['id'], 'title': item.get('summaryOverride', item['summary']),
                                  'color': item.get('backgroundColor', '#4285f4'), 'primary': item.get('primary', False)})
        data['calendars'] = calendars
        ids = {c['id'] for c in calendars}
        data['selected'] = ([c['id'] for c in calendars if c['primary']] if initial else
                            [i for i in data['selected'] if i in ids])
        data['cache'] = {k: v for k, v in data['cache'].items() if k in data['selected']}
        day = date.today()
        for identity in data['selected']:
            if self.closed.is_set():
                return
            data['cache'][identity] = self._events(identity, token, data['cache'].get(identity, {}), day)
        data['lastSync'] = datetime.now().astimezone().isoformat(timespec='seconds')
        data['windowDay'] = day.isoformat()
        self._save(data)
