"""Run with PYTHONPATH=next:marketplace/packages/schedule python -m unittest discover -s marketplace/packages/schedule/tests -v."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from polaris_schedule import Schedule
from polaris_schedule.google_calendar import GoogleCalendar, GoogleError, SCOPES


class Vault:
    def __init__(self):
        self.value = json.dumps({'client_id': 'test.apps.googleusercontent.com', 'refresh_token': 'saved-refresh'})

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self):
        self.value = None


def event(identity='one', **fields):
    return {'id': identity, 'summary': 'Meeting', 'start': {'dateTime': '2026-11-04T09:00:00+08:00'},
            'end': {'dateTime': '2026-11-04T10:00:00+08:00'}, **fields}


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Vault()
        self.calls = []
        self.pages = []
        self.calendars = [{'id': 'primary@example.com', 'summary': 'Work', 'primary': True},
                          {'id': 'other', 'summary': 'Other'}]
        def transport(url, **kwargs):
            self.calls.append((url, kwargs))
            if '/token' in url:
                return {'access_token': 'access'}
            if '/calendarList?' in url:
                return {'items': self.calendars}
            page = self.pages.pop(0)
            if isinstance(page, Exception):
                raise page
            return page
        self.service = GoogleCalendar(self.tmp.name, transport=transport, vault=self.vault)
        self.service.data['connected'] = True

    def test_full_paginated_and_incremental_delete_and_change(self):
        self.pages = [{'items': [event()], 'nextPageToken': 'page2'},
                      {'items': [event('two', summary='All-day', start={'date': '2026-11-04'}, end={'date': '2026-11-06'})], 'nextSyncToken': 'sync1'}]
        self.service._sync(initial=True)
        self.assertEqual(len(self.service.snapshot()['events']), 2)
        self.assertEqual(self.service.data['selected'], ['primary@example.com'])
        self.pages = [{'items': [{'id': 'one', 'status': 'cancelled'}, event('two', summary='Changed')], 'nextSyncToken': 'sync2'}]
        self.service._sync()
        view = self.service.snapshot()
        self.assertEqual([e['title'] for e in view['events']], ['Changed'])
        self.assertEqual(self.service.data['cache']['primary@example.com']['syncToken'], 'sync2')
        query = parse_qs(urlparse(self.calls[-1][0]).query)
        self.assertEqual(query['syncToken'], ['sync1'])
        self.assertNotIn('timeMin', query)
        self.assertNotIn('timeMax', query)
        self.assertEqual(self.calls[2][1]['token'], 'access')
        self.assertNotIn('access', self.service.path.read_text())
        self.assertNotIn('saved-refresh', self.service.path.read_text())
        reloaded = GoogleCalendar(self.tmp.name, vault=self.vault)
        self.assertEqual(reloaded.snapshot()['events'], view['events'])

    def test_410_rebuilds_only_google_cache(self):
        self.pages = [{'items': [event()], 'nextSyncToken': 'old'}]
        self.service._sync(initial=True)
        self.pages = [GoogleError(410, 'Expired'), {'items': [event('replacement')], 'nextSyncToken': 'new'}]
        self.service._sync()
        self.assertEqual([e['id'] for e in self.service.snapshot()['events']], ['replacement'])
        query = parse_qs(urlparse(self.calls[-1][0]).query)
        self.assertIn('timeMin', query)
        self.assertNotIn('syncToken', query)

    def test_failed_page_keeps_cache_and_token(self):
        self.pages = [{'items': [event()], 'nextSyncToken': 'old'}]
        self.service._sync(initial=True)
        before = deepcopy(self.service.data)
        disk = self.service.path.read_bytes()
        self.pages = [{'items': [event('new')], 'nextPageToken': 'next'}, GoogleError(503, 'Offline')]
        with self.assertRaises(GoogleError):
            self.service._sync()
        self.assertEqual(self.service.data, before)
        self.assertEqual(self.service.path.read_bytes(), disk)

    def test_new_day_renews_window(self):
        self.pages = [{'items': [event()], 'nextSyncToken': 'old'}]
        self.service._sync(initial=True)
        self.service.data['cache']['primary@example.com']['windowDay'] = '2000-01-01'
        self.pages = [{'items': [], 'nextSyncToken': 'new'}]
        self.service._sync()
        self.assertIn('timeMax=', self.calls[-1][0])
        self.assertEqual(self.service.snapshot()['events'], [])

    def test_selection_empty_persists_and_disconnect_clears(self):
        self.service.data['connected'] = False
        self.service.start()
        self.service.data['connected'] = True
        self.addCleanup(self.service.stop)
        self.service.select([])
        self.wait_idle()
        self.assertEqual(self.service.snapshot()['selected'], [])
        self.assertEqual(self.service.snapshot()['events'], [])
        self.service.disconnect()
        self.wait_idle()
        self.assertFalse(self.service.snapshot()['connected'])
        self.assertIsNone(self.vault.value)

    def wait_idle(self):
        for _ in range(300):
            if not self.service.snapshot()['busy']:
                return
            time.sleep(.01)
        self.fail('worker did not finish')

    def test_worker_exposes_error_and_releases_busy(self):
        self.vault.value = None
        self.service.data['connected'] = False
        self.service.start()
        self.service.data['connected'] = True
        self.addCleanup(self.service.stop)
        self.service.sync()
        self.wait_idle()
        self.assertIn('重新连接', self.service.snapshot()['error'])

    def test_invalid_client_and_selection(self):
        p = Path(self.tmp.name) / 'client.json'
        p.write_text(json.dumps({'web': {'client_id': 'wrong'}}))
        with self.assertRaisesRegex(ValueError, '桌面应用'):
            self.service.connect(str(p))
        with self.assertRaises(ValueError):
            self.service.select(['unknown'])

    def test_oauth_pkce_state_and_cancel_without_deadline(self):
        self.service.data['connected'] = False
        captured = []
        ready = threading.Event()
        def browser(url):
            captured.append(url)
            ready.set()
        with patch('polaris_schedule.google_calendar.webbrowser.open', browser):
            worker = threading.Thread(target=lambda: self.service._authorize({'client_id': 'test.apps.googleusercontent.com'}))
            worker.start()
            self.assertTrue(ready.wait(3))
            query = parse_qs(urlparse(captured[0]).query)
            self.assertEqual(query['code_challenge_method'], ['S256'])
            self.assertEqual(set(query['scope'][0].split()), set(SCOPES))
            self.assertEqual(query['access_type'], ['offline'])
            self.assertNotIn('calendar.events', query['scope'][0].split())
            redirect = query['redirect_uri'][0]
            from urllib.error import HTTPError
            with self.assertRaises(HTTPError) as error:
                urlopen(redirect + '?state=wrong&code=stolen')
            self.assertEqual(error.exception.code, 400)
            self.assertTrue(worker.is_alive())
            self.assertTrue(self.service.snapshot()['authorizing'])
            self.service.cancel_authorization()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(self.service.snapshot()['authorizing'])
            self.assertEqual(self.service.snapshot()['authUrl'], '')
            self.assertFalse(self.service.data['connected'])

    def test_oauth_success_exchanges_code_and_preserves_client(self):
        original = self.service.transport
        def transport(url, **kwargs):
            if kwargs.get('form', {}).get('grant_type') == 'authorization_code':
                self.assertEqual(kwargs['form']['code'], 'test-code')
                verifier = kwargs['form']['code_verifier']
                import base64, hashlib
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                self.assertEqual(challenge, authorization['code_challenge'][0])
                return {'refresh_token': 'new-refresh', 'access_token': 'new-access'}
            return original(url, **kwargs)
        self.service.transport = transport
        authorization = {}
        def browser(url):
            authorization.update(parse_qs(urlparse(url).query))
            def callback():
                with urlopen(authorization['redirect_uri'][0] + '?state=' + authorization['state'][0] + '&code=test-code') as response:
                    response.read()
            threading.Thread(target=callback).start()
        self.pages = [{'items': [event()], 'nextSyncToken': 'sync'}]
        with patch('polaris_schedule.google_calendar.webbrowser.open', browser):
            self.service._authorize({'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'client-secret'})
        saved = json.loads(self.vault.value)
        self.assertEqual(saved['refresh_token'], 'new-refresh')
        self.assertEqual(saved['client_secret'], 'client-secret')
        self.assertTrue(self.service.snapshot()['connected'])
        self.assertEqual(len(self.service.snapshot()['events']), 1)

    def test_local_tasks_unchanged_and_operations_discoverable(self):
        schedule = Schedule(self.tmp.name)
        task = schedule.store.add('Local only')
        path = Path(self.tmp.name) / 'schedule.json'
        original = path.read_bytes()
        self.pages = [{'items': [event()], 'nextSyncToken': 'sync'}]
        self.service._sync(initial=True)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(schedule.get()['tasks'], [task])
        self.assertIn('google', schedule.get())
        operations = schedule.describe()['operations']
        for name in ('google_connect', 'google_sync', 'google_cancel', 'google_select', 'google_disconnect'):
            self.assertEqual(operations[name]['access'], 'write')
            self.assertIn('parameters', operations[name])


if __name__ == '__main__':
    unittest.main()
