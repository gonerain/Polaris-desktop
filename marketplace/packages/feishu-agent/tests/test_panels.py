"""Structured card rendering and real service routing; all transports are offline."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_backend import Context, Rejection, backend, message

panels = __import__('feishu_agent_backend.panels', fromlist=['render_panel'])


def session(index, online=True, status='completed'):
    return dict(id='session-' + str(index), title='会话 ' + str(index), adapter='pi', marked=True,
                online=online, canSend=online, cwd='/work/project', runCount=index,
                lastRun=dict(id='run-' + str(index), status=status))


def task(index, day='2026-11-18', done=False):
    return dict(id='task-' + str(index), title='任务 ' + str(index), date=day, time='09:00',
                done=done, important=False, notes='原始笔记', subtasks=[])


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def texts(card):
    return '\n'.join(item['content'] for item in walk(card) if 'content' in item)


class PanelContext(Context):
    def __init__(self, directory):
        super().__init__(directory)
        self.sessions = [session(i) for i in range(6)]
        self.schedule = dict(tasks=[task(1), task(2, '2026-11-19'), task(3, None), task(4, done=True)],
                             timeContext=dict(date='2026-11-18'))
        self.actions = []
        self.result = dict(id='completed-run', status='completed', reply='最近完整回复', replyTruncated=False)

    def call(self, alias, params):
        if alias not in ('bridgeSessions', 'bridgeResult', 'scheduleGet', 'feishuActions', 'feishuUpdateCard'):
            return super().call(alias, params)
        self.calls.append((alias, deepcopy(params)))
        if alias in self.fail:
            raise self.fail[alias]
        if alias == 'bridgeSessions':
            assert params == dict(marked=True)
            return deepcopy(self.sessions)
        if alias == 'bridgeResult':
            assert params['completed_only'] is True
            return deepcopy(self.result)
        if alias == 'scheduleGet':
            return deepcopy(self.schedule)
        if alias == 'feishuActions':
            items = [row for row in self.actions if row['cursor'] > params['after']][:params['limit']]
            return dict(items=deepcopy(items), nextCursor=items[-1]['cursor'] if items else params['after'])
        return dict(success=True, messageId=params['message_id'])


class CardTests(unittest.TestCase):
    def render(self, state=None, rows=None):
        return panels.render_panel('app', state or panels.panel_state('sessions'),
                                   rows if rows is not None else [session(i) for i in range(6)])

    def test_native_schema_and_pagination(self):
        card, state = self.render()
        self.assertEqual(card['schema'], '2.0')
        self.assertTrue(card['config']['update_multi'])
        self.assertIn('第 1 / 2 页', texts(card))
        self.assertNotIn('会话 4', texts(card))
        self.assertNotIn('session-0', texts(card))
        buttons = [row for row in walk(card) if row.get('tag') == 'button']
        self.assertTrue(next(row for row in buttons if row['text']['content'] == '上一页')['disabled'])
        self.assertFalse(next(row for row in buttons if row['text']['content'] == '下一页')['disabled'])

    def test_filters_and_shrinking_list_clamp_page(self):
        rows = [session(1, False), session(2, status='running'), session(3)]
        card, state = self.render(panels.panel_state('sessions', filter='running', page=2), rows)
        self.assertEqual(state['page'], 0)
        self.assertIn('会话 2', texts(card))
        self.assertNotIn('会话 1', texts(card))
        self.assertNotIn('会话 3', texts(card))
        card, _ = self.render(panels.panel_state('sessions', filter='offline'), rows)
        self.assertIn('⚪ 离线', texts(card))

    def test_empty_and_removed_details_are_explicit(self):
        card, _ = self.render(rows=[])
        self.assertIn('暂无符合条件的会话', texts(card))
        card, _ = self.render(panels.panel_state('sessions', detailId='removed'), [])
        self.assertIn('已不在当前列表中', texts(card))

    def test_titles_are_not_interpreted_as_mentions_or_markdown(self):
        row = session(0)
        row['title'] = '<at id=all>所有人</at> **title** [link](url)'
        card, _ = self.render(rows=[row])
        content = texts(card)
        self.assertNotIn('**<at', content)
        self.assertNotIn('**title**', content)
        self.assertIn('\\<at', content)

    def test_schedule_filters_use_provider_date_and_preserve_today_clock(self):
        data = dict(tasks=[task(1), task(2, '2026-11-24'), task(3, '2026-11-25'), task(4, None), task(5, done=True)],
                    timeContext=dict(date='2026-11-18'))
        for filter, expected in [('today', [1]), ('upcoming', [1, 2]), ('inbox', [4]), ('all', [1, 2, 3, 4]), ('done', [5])]:
            card, _ = panels.render_panel('app', panels.panel_state('schedule', filter=filter), data)
            content = texts(card)
            for index in range(1, 6):
                self.assertEqual('任务 ' + str(index) in content, index in expected, (filter, index))
        self.assertEqual(data['timeContext']['date'], '2026-11-18')

    def test_long_details_stay_within_existing_feishu_card_size_limit(self):
        row = task(1)
        row['notes'] = '汉' * 10000
        row['subtasks'] = [dict(title='汉' * 1000, done=False) for _ in range(25)]
        card, _ = panels.render_panel('app', panels.panel_state('schedule', detailId=row['id']),
                                      dict(tasks=[row], timeContext=dict(date='2026-11-18')))
        self.assertLessEqual(len(json.dumps(card)), 50000)
        self.assertIn('展示已截短', texts(card))
        self.assertIn('共 25 项子任务', texts(card))
        card, _ = panels.render_panel('app', panels.panel_state('sessions', detailId='session-1'), [session(1)],
                                      dict(reply='汉' * 10000, replyTruncated=True))
        self.assertLessEqual(len(json.dumps(card)), 50000)
        self.assertIn('来源记录标记此回复已截短', texts(card))

    def test_each_render_gives_buttons_a_new_action_identity(self):
        first, _ = self.render()
        second, _ = self.render()
        def callbacks(card):
            return [item['value'] for item in walk(card) if item.get('type') == 'callback']
        a, b = callbacks(first), callbacks(second)
        self.assertEqual(len({item['renderId'] for item in a}), 1)
        self.assertNotEqual(a[0]['renderId'], b[0]['renderId'])
        self.assertEqual([{k: v for k, v in item.items() if k != 'renderId'} for item in a],
                         [{k: v for k, v in item.items() if k != 'renderId'} for item in b])

    def test_filters_are_buttons_with_explicit_target_not_dropped_dropdown_options(self):
        for view in ('sessions', 'schedule'):
            data = [session(1)] if view == 'sessions' else dict(tasks=[], timeContext=dict(date='2026-11-18'))
            card, _ = self.render(panels.panel_state(view), data)
            self.assertFalse(any(item.get('tag') == 'select_static' for item in walk(card)))
            buttons = [item for item in walk(card) if item.get('tag') == 'button']
            for value, label in panels.FILTERS[view]:
                button = next(item for item in buttons if item['text']['content'] == label)
                self.assertEqual(button['behaviors'][0]['value']['filter'], value)
                self.assertEqual(button['behaviors'][0]['value']['page'], 0)

    def test_invalid_external_state_is_rejected(self):
        for kwargs in (dict(view='other'), dict(view='sessions', filter='today'),
                       dict(view='schedule', page=-1), dict(view='sessions', page=True),
                       dict(view='sessions', detailId=3)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                panels.panel_state(**kwargs)


class PanelServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = PanelContext(Path(self.temp.name))
        self.service = backend.create(self.context)
        self.service.running = True
        self.service._poll_codex()
        self.service._receive()

    def tearDown(self):
        self.context.stopped.set()
        self.service.stop()
        self.temp.cleanup()

    def open(self, command='面板', thread=''):
        self.context.messages.append(message(len(self.context.messages) + 1, command, thread=thread))
        self.service._receive()
        self.service._submit()
        self.service._flush()
        return self.service.data['outputs'][-1]

    def click(self, row, state, *, chat='chat', app='app_fixture', message_id=None, option=None):
        # SDK CardActionPayload includes option=null on buttons, not an absent key.
        action = dict(value=dict(app=app, **state), option=option)
        self.context.actions.append(dict(cursor=len(self.context.actions) + 1,
            messageId=message_id or row['messageId'], chatId=chat, action=action))
        self.service._receive_actions()

    def updates(self):
        return [params for alias, params in self.context.calls if alias == 'feishuUpdateCard']

    def test_panel_command_sends_card_once_in_same_topic_without_model_input(self):
        row = self.open(thread='topic')
        self.assertEqual(row['state'], 'sent')
        reply = [params for alias, params in self.context.calls if alias == 'feishuReply'][0]
        self.assertEqual(reply['message_id'], 'm1')
        self.assertTrue(reply['reply_in_thread'])
        self.assertEqual(reply['message']['card']['schema'], '2.0')
        self.service._receive()
        self.service._submit()
        self.service._flush()
        self.assertEqual(len(self.service.data['outputs']), 1)
        self.assertFalse(any(alias == 'codexSend' for alias, _ in self.context.calls))
        self.assertFalse(any(alias == 'bridgeResult' for alias, _ in self.context.calls))

    def test_normal_chat_after_panel_still_reaches_existing_codex(self):
        self.open()
        self.context.messages.append(message(2, '请介绍一下这些会话'))
        self.service._receive()
        self.service._submit()
        self.assertEqual([params for alias, params in self.context.calls if alias == 'codexSend'],
                         [dict(text='请介绍一下这些会话', mode='start')])

    def test_click_switch_filter_page_detail_and_back_updates_same_card(self):
        row = self.open()
        self.click(row, panels.panel_state('sessions', page=1))
        self.assertIn('会话 4', texts(self.updates()[-1]['card']))
        self.click(row, panels.panel_state('sessions', detailId='session-4', page=1))
        self.assertIn('最近完整回复', texts(self.updates()[-1]['card']))
        self.click(row, panels.panel_state('sessions', page=1))
        self.assertIn('第 2 / 2 页', texts(self.updates()[-1]['card']))
        self.click(row, panels.panel_state('schedule'))
        self.assertIn('任务 1', texts(self.updates()[-1]['card']))
        self.click(row, panels.panel_state('schedule', filter='inbox'))
        self.assertIn('任务 3', texts(self.updates()[-1]['card']))
        self.assertNotIn('任务 1', texts(self.updates()[-1]['card']))
        self.assertTrue(all(update['message_id'] == row['messageId'] for update in self.updates()))
        self.assertEqual(len([1 for alias, _ in self.context.calls if alias == 'feishuReply']), 1)
        self.assertFalse(any(alias == 'codexSend' for alias, _ in self.context.calls))

    def test_refresh_rereads_actual_provider_data_and_action_is_not_replayed(self):
        row = self.open()
        self.context.sessions[0]['title'] = '更新后的名称'
        self.click(row, panels.panel_state('sessions'))
        self.assertIn('更新后的名称', texts(self.updates()[-1]['card']))
        self.service._receive_actions()
        self.assertEqual(len(self.updates()), 1)
        self.assertEqual(self.service.data['actionCursor'], 1)

    def test_sdk_null_option_on_button_preserves_selected_filter(self):
        row = self.open()
        self.click(row, panels.panel_state('sessions', filter='offline'))
        self.assertIn('暂无符合条件', texts(self.updates()[-1]['card']))
        self.click(row, panels.panel_state('sessions', filter='offline'))
        self.assertEqual(self.service.data['panels'][row['messageId']]['filter'], 'offline')
        self.assertIn('暂无符合条件', texts(self.updates()[-1]['card']))

    def test_foreign_chat_application_or_unknown_message_cannot_open_data(self):
        row = self.open()
        before = len([1 for alias, _ in self.context.calls if alias == 'bridgeSessions'])
        self.click(row, panels.panel_state('sessions'), chat='other')
        self.click(row, panels.panel_state('sessions'), app='another-app')
        self.click(row, panels.panel_state('sessions'), message_id='unknown')
        self.assertEqual(self.updates(), [])
        self.assertEqual(before, len([1 for alias, _ in self.context.calls if alias == 'bridgeSessions']))

    def test_other_chat_panel_command_is_not_sent_or_passed_to_model(self):
        self.open()
        self.context.messages.append(message(2, '日程', chat='other'))
        self.service._receive()
        self.service._submit()
        self.service._flush()
        self.assertEqual(len(self.service.data['outputs']), 1)
        self.assertEqual(self.service.data['inputs'][-1]['state'], 'failed')
        self.assertFalse(any(alias == 'codexSend' for alias, _ in self.context.calls))

    def test_panel_state_survives_restart_without_resending(self):
        row = self.open()
        self.click(row, panels.panel_state('sessions', page=1))
        self.service.stop()
        self.service = backend.create(self.context)
        self.service.running = True
        self.service._receive_actions()
        self.service._flush()
        self.assertEqual(self.service.data['panels'][row['messageId']]['page'], 1)
        self.assertEqual(len(self.updates()), 1)
        self.click(row, panels.panel_state('schedule'))
        self.assertEqual(len(self.updates()), 2)
        self.assertEqual(len([1 for alias, _ in self.context.calls if alias == 'feishuReply']), 1)

    def test_permission_failure_is_visible_and_not_silently_converted_to_text(self):
        self.context.fail['bridgeSessions'] = Rejection('未授权读取会话')
        row = self.open()
        self.assertEqual(row['state'], 'failed')
        self.assertIn('未授权', row['error'])
        self.assertFalse(any(alias == 'feishuReply' for alias, _ in self.context.calls))
        self.assertFalse(any(alias == 'codexSend' for alias, _ in self.context.calls))

    def test_failed_card_update_is_paused_and_retains_cursor_for_manual_continue(self):
        row = self.open()
        self.context.fail['feishuUpdateCard'] = Rejection('更新未授权')
        self.context.actions.append(dict(cursor=1, messageId=row['messageId'], chatId='chat',
            action=dict(value=dict(app='app_fixture', **panels.panel_state('sessions')))))
        self.service._step('cards', self.service._receive_actions)
        self.assertIn('cards', self.service.paused)
        self.assertEqual(self.service.data['actionCursor'], 0)
        self.service._step('cards', self.service._receive_actions)
        self.assertEqual(len(self.updates()), 1)
        self.context.fail.clear()
        self.service.handle('continue', {})
        self.service._step('cards', self.service._receive_actions)
        self.assertEqual(self.service.data['actionCursor'], 1)

    def test_failed_expired_card_action_can_be_explicitly_skipped(self):
        row = self.open()
        self.context.fail['feishuUpdateCard'] = Rejection('卡片已失效')
        self.context.actions.append(dict(cursor=1, messageId=row['messageId'], chatId='chat',
            action=dict(value=dict(app='app_fixture', **panels.panel_state('sessions')))))
        self.service._step('cards', self.service._receive_actions)
        attention = next(row for row in self.service._attention() if row['kind'] == 'cards')
        self.assertIn('已失效', attention['error'])
        self.service.handle('skip', dict(kind='cards', id=attention['id']))
        self.assertEqual(self.service.data['actionCursor'], 1)
        self.context.fail.clear()
        self.click(row, panels.panel_state('schedule'))
        self.assertEqual(len(self.updates()), 2)
        self.assertFalse(any(row['kind'] == 'cards' for row in self.service._attention()))

    def test_provider_read_failure_before_dispatch_is_known_failed_not_unknown(self):
        self.context.fail['bridgeSessions'] = RuntimeError('数据读取失败，尚未发送')
        row = self.open()
        self.assertEqual(row['state'], 'failed')
        self.assertFalse(any(alias == 'feishuReply' for alias, _ in self.context.calls))

    def test_empty_card_polls_never_rewrite_state_file(self):
        self.open()
        with patch.object(self.service, '_save', wraps=self.service._save) as save:
            for _ in range(10):
                self.assertFalse(self.service._receive_actions())
            save.assert_not_called()

    def test_card_worker_remains_responsive_while_codex_input_is_blocked(self):
        row = self.open()
        entered, release, updated = threading.Event(), threading.Event(), threading.Event()
        original = self.context.call
        def call(alias, params):
            if alias == 'codexSend':
                entered.set()
                release.wait()
            result = original(alias, params)
            if alias == 'feishuUpdateCard':
                updated.set()
            return result
        self.context.call = call
        self.context.messages.append(message(2, '普通聊天'))
        self.service.interval = 10  # The card worker must not inherit the chat poll interval.
        self.service.start()
        try:
            self.assertTrue(entered.wait(1), 'Codex send never started')
            self.context.actions.append(dict(cursor=1, messageId=row['messageId'], chatId='chat',
                action=dict(value=dict(app='app_fixture', **panels.panel_state('sessions', page=1)), option=None)))
            started = time.monotonic()
            self.assertTrue(updated.wait(.8), 'Card navigation waited behind blocked Codex send')
            self.assertLess(time.monotonic() - started, .8)
            self.assertFalse(release.is_set())
        finally:
            release.set()
            self.service.stop()
        self.assertFalse(self.service.card_thread.is_alive())
        self.assertFalse(self.service.thread.is_alive())

    def test_desktop_panel_button_requires_connected_chat(self):
        with self.assertRaises(ValueError):
            self.service.handle('show_sessions', {})
        self.open()
        self.service.handle('show_schedule', {})
        self.service._flush()
        self.assertEqual(self.service.data['outputs'][-1]['panel']['view'], 'schedule')


if __name__ == '__main__':
    unittest.main()
