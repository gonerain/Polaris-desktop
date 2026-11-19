"""Offline incremental reminder lifecycle and real service queue integration."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import tempfile
import unittest
from unittest.mock import patch

from test_backend import backend, Context, Rejection, message

r = backend.reminders
NOW = datetime(2030, 1, 2, 10).astimezone()


def task(identity='t', **changes):
    result = dict(id=identity, title='准备评审', date=NOW.date().isoformat(), time='15:00',
                  notes='', important=True, done=False, subtasks=[])
    result.update(changes)
    return result


def event(identity='e', **changes):
    result = dict(id=identity, calendarId='c', title='项目评审', location='会议室', description='',
                  start={'dateTime': (NOW + timedelta(hours=5)).isoformat()},
                  end={'dateTime': (NOW + timedelta(hours=6)).isoformat()}, color='blue')
    result.update(changes)
    return result


def snapshot(tasks=None, events=None):
    return dict(tasks=[task()] if tasks is None else tasks,
                google=dict(events=events or [], lastSync=NOW.isoformat(), error=''))


def decision(request, empty=False, **changes):
    return json.dumps(dict(decisions=[dict(sourceId=row['id'], version=row['version'],
        reminders=[] if empty else [dict(sendAt=(NOW + timedelta(minutes=20)).isoformat(),
            expiresAt=(NOW + timedelta(minutes=40)).isoformat(), text='准备评审', **changes)])
        for row in request['items']]))


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.state = r.initial_state()
        r.configure(self.state, True, r.DEFAULT_PREFERENCES)
        self.data = snapshot()
        r.reconcile(self.state, self.data, NOW)

    def plan(self, empty=False):
        request = r.batch(self.state)
        r.accept(self.state, request, decision(request, empty), NOW)
        return request

    def test_empty_decision_is_remembered_and_unchanged_snapshot_has_no_delta(self):
        self.plan(empty=True)
        r.reconcile(self.state, self.data, NOW + timedelta(hours=1))
        self.assertEqual(self.state['pending'], {})
        self.assertEqual(self.state['plans'], [])

    def test_cancel_delete_and_complete_invalidate_without_model(self):
        for changed in (snapshot(tasks=[]), snapshot(tasks=[task(done=True)])):
            with self.subTest(changed=changed):
                self.setUp()
                self.plan()
                r.reconcile(self.state, changed, NOW)
                self.assertEqual(self.state['plans'][0]['state'], 'cancelled')
                self.assertEqual(self.state['pending'], {})

    def test_changes_coalesce_and_old_plan_is_invalidated(self):
        self.plan()
        r.reconcile(self.state, snapshot(tasks=[task(time='16:00')]), NOW)
        r.reconcile(self.state, snapshot(tasks=[task(time='17:00')]), NOW)
        self.assertEqual(self.state['plans'][0]['state'], 'cancelled')
        self.assertEqual(len(self.state['pending']), 1)
        self.assertEqual(r.batch(self.state)['items'][0]['content']['time'], '17:00')

    def test_model_result_cannot_overwrite_source_changed_during_planning(self):
        request = r.batch(self.state)
        r.reconcile(self.state, snapshot(tasks=[task(time='17:00')]), NOW)
        r.accept(self.state, request, decision(request), NOW)
        self.assertEqual(self.state['plans'], [])
        self.assertEqual(len(self.state['pending']), 1)

    def test_preferences_change_and_disable_reject_inflight_results(self):
        request = r.batch(self.state)
        r.configure(self.state, True, '提前一小时提醒')
        r.accept(self.state, request, decision(request), NOW)
        self.assertEqual(self.state['plans'], [])
        request = r.batch(self.state)
        r.configure(self.state, False, '提前一小时提醒')
        r.accept(self.state, request, decision(request), NOW)
        self.assertEqual(self.state['plans'], [])

    def test_rolling_window_adds_only_newly_relevant_items(self):
        self.plan(empty=True)
        future = task('future', date=(NOW.date() + timedelta(days=8)).isoformat())
        data = snapshot(tasks=[task(), future])
        r.reconcile(self.state, data, NOW)
        self.assertEqual(self.state['pending'], {})
        r.reconcile(self.state, data, NOW + timedelta(days=1))
        self.assertEqual(list(self.state['pending']), ['task:future'])

    def test_google_occurrences_have_stable_calendar_scoped_ids_and_ignore_color(self):
        data = snapshot(tasks=[], events=[event(), event(calendarId='other')])
        r.reconcile(self.state, data, NOW)
        self.assertEqual(len(self.state['sources']), 2)
        self.plan(empty=True)
        data['google']['events'][0]['color'] = 'red'
        data['google']['lastSync'] = (NOW + timedelta(minutes=5)).isoformat()
        r.reconcile(self.state, data, NOW)
        self.assertEqual(self.state['pending'], {})
        data['google']['events'].pop()
        r.reconcile(self.state, data, NOW)
        self.assertEqual(len(self.state['sources']), 1)

    def test_all_day_event_uses_exclusive_end_date_and_started_timed_events_drop(self):
        data = snapshot(tasks=[], events=[event(start={'date': NOW.date().isoformat()},
            end={'date': (NOW.date() + timedelta(days=1)).isoformat()})])
        r.reconcile(self.state, data, NOW)
        self.assertEqual(len(self.state['sources']), 1)
        r.reconcile(self.state, data, NOW + timedelta(days=1))
        self.assertEqual(self.state['sources'], {})
        data = snapshot(tasks=[], events=[event(start={'dateTime': NOW.isoformat()})])
        r.reconcile(self.state, data, NOW)
        self.assertEqual(self.state['sources'], {})

    def test_expired_task_is_replanned_not_replayed_and_event_is_dropped(self):
        self.plan()
        r.reconcile(self.state, self.data, NOW + timedelta(hours=2))
        self.assertEqual(self.state['plans'][0]['state'], 'expired')
        self.assertEqual(len(self.state['pending']), 1)
        self.assertEqual(r.batch(self.state)['history'][0]['state'], 'expired')

    def test_result_validation_is_atomic_and_rejects_missing_or_foreign_decisions(self):
        request = r.batch(self.state)
        for reply in ('not json', '{"decisions":[]}', '{"decisions":[{"sourceId":"foreign","version":"x","reminders":[]}]}'):
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                r.accept(self.state, request, reply, NOW)
        result = json.loads(decision(request))
        result['decisions'][0]['reminders'].append(dict(sendAt='2030-01-02T11:00:00', expiresAt='2030-01-02T12:00:00', text='bad timezone'))
        with self.assertRaises(ValueError):
            r.accept(self.state, request, json.dumps(result), NOW)
        self.assertEqual(self.state['plans'], [])
        self.assertEqual(len(self.state['pending']), 1)


class ReminderContext(Context):
    def __init__(self, directory):
        super().__init__(directory)
        self.schedule = snapshot()

    def call(self, alias, params):
        if alias == 'scheduleGet':
            self.calls.append((alias, deepcopy(params)))
            if alias in self.fail:
                raise self.fail[alias]
            return deepcopy(self.schedule)
        return super().call(alias, params)


class ServiceReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.context = ReminderContext(self.temp.name)
        self.service = backend.create(self.context)
        self.service.running = True
        self.now = NOW
        self.clock = patch.object(backend.Service, '_now', lambda service: self.now)
        self.clock.start()
        self.service._poll_codex()
        self.service.data['channel'] = self.service._channel(message(1, thread='topic'))
        self.service.handle('configure_reminders', dict(enabled=True, preferences=r.DEFAULT_PREFERENCES))

    def tearDown(self):
        self.service.stop()
        self.clock.stop()
        self.temp.cleanup()

    def start_plan(self):
        self.service._remind()
        self.service._submit()
        self.service._poll_codex()
        return next(row for row in self.service.data['inputs'] if row.get('source') == 'reminder-plan')

    def finish_plan(self, empty=False):
        item = self.start_plan()
        self.context.finish(decision(item['planningBatch'], empty))
        self.service._poll_codex()
        self.service._remind()
        return self.service.data['reminders']['plans']

    def test_empty_hourly_delta_does_not_call_model(self):
        self.finish_plan(empty=True)
        count = sum(alias == 'codexSend' for alias, _ in self.context.calls)
        self.now += timedelta(hours=1)
        self.service._remind()
        self.service._submit()
        self.assertEqual(sum(alias == 'codexSend' for alias, _ in self.context.calls), count)
        self.assertFalse(self.service.data['outputs'])

    def test_due_message_sends_directly_once_to_bound_topic(self):
        plans = self.finish_plan()
        self.assertFalse(self.service.data['outputs'])  # Planning JSON is never a chat reply.
        self.now += timedelta(minutes=21)
        self.service._remind()
        self.service._flush()
        self.service._remind()
        self.service._flush()
        replies = [params for alias, params in self.context.calls if alias == 'feishuReply']
        self.assertEqual(replies, [dict(message_id='m1', reply_in_thread=True, text='准备评审')])
        self.assertEqual(plans[0]['state'], 'sent')
        self.assertEqual(sum(alias == 'codexSend' for alias, _ in self.context.calls), 1)

    def test_final_read_cancels_queued_reminder_before_send(self):
        plans = self.finish_plan()
        self.now += timedelta(minutes=21)
        self.service._remind()
        self.context.schedule['tasks'] = []
        self.service._flush()
        self.assertEqual(plans[0]['state'], 'cancelled')
        self.assertEqual(self.service.data['outputs'][0]['state'], 'skipped')
        self.assertFalse(any(alias == 'feishuReply' for alias, _ in self.context.calls))

    def test_modification_invalidates_immediately_but_ai_waits_for_hour(self):
        plans = self.finish_plan()
        self.context.schedule = snapshot(tasks=[task(time='17:00')])
        self.now += timedelta(minutes=5)
        self.service._remind()
        self.assertEqual(plans[0]['state'], 'cancelled')
        self.assertEqual(len(self.service.data['inputs']), 1)
        self.now += timedelta(hours=1)
        self.service._remind()
        self.assertEqual(len(self.service.data['inputs']), 2)

    def test_new_chat_waits_for_internal_turn_then_uses_normal_start(self):
        item = self.start_plan()
        self.context.messages.append(message(2, '新的聊天', thread='topic'))
        self.service.data['cursor'] = 0
        self.service._receive()
        self.service._submit()
        self.assertEqual(sum(alias == 'codexSend' for alias, _ in self.context.calls), 1)
        self.context.finish(decision(item['planningBatch'], empty=True))
        self.service._poll_codex()
        self.service._remind()
        self.service._submit()
        self.assertEqual([params for alias, params in self.context.calls if alias == 'codexSend'][-1],
                         dict(text='新的聊天', mode='start'))

    def test_existing_chat_is_not_steered_by_planner(self):
        self.context.call('codexSend', dict(text='用户任务', mode='start'))
        self.service._poll_codex()
        self.service._remind()
        self.assertEqual(self.service.data['inputs'], [])
        self.assertEqual(len(self.service.data['reminders']['pending']), 1)

    def test_disable_during_planning_does_not_block_subsequent_chat(self):
        item = self.start_plan()
        self.service.handle('configure_reminders', dict(enabled=False, preferences=r.DEFAULT_PREFERENCES))
        self.context.finish(decision(item['planningBatch']))
        self.service._poll_codex()
        self.service._remind()
        self.assertIsNone(self.service.data['reminders']['activeInput'])
        self.assertEqual(self.service.data['reminders']['plans'], [])

    def test_recovery_does_not_replan_processed_items_or_replay_expired_messages(self):
        self.finish_plan()
        self.now += timedelta(hours=2)
        self.service = backend.create(self.context)
        self.service.running = True
        self.service._poll_codex()
        self.service._remind()
        self.service._flush()
        self.assertEqual(self.service.data['reminders']['plans'][0]['state'], 'expired')
        self.assertFalse(any(alias == 'feishuReply' for alias, _ in self.context.calls))
        self.assertEqual(self.service.data['inputs'][-1]['planningBatch']['history'][0]['state'], 'expired')

    def test_inflight_result_survives_restart_without_leaking_json(self):
        item = self.start_plan()
        self.context.finish(decision(item['planningBatch']))
        self.service = backend.create(self.context)
        self.service.running = True
        self.service._poll_codex()
        self.service._remind()
        self.assertEqual(len(self.service.data['reminders']['plans']), 1)
        self.assertEqual(self.service.data['outputs'], [])

    def test_invalid_result_is_visible_and_continue_replans_latest_delta(self):
        self.start_plan()
        self.context.finish('not json')
        self.service._poll_codex()
        self.service._step('reminders', self.service._remind)
        self.assertIn('reminders', self.service.paused)
        self.assertEqual(self.service.data['outputs'], [])
        self.service.handle('continue', {})
        self.service._remind()
        self.assertEqual(len(self.service.data['inputs']), 2)

    def test_unknown_delivery_is_not_repeated_after_restart(self):
        self.finish_plan()
        self.now += timedelta(minutes=21)
        self.service._remind()
        self.context.fail['feishuReply'] = TimeoutError('unknown delivery')
        self.service._flush()
        self.service = backend.create(self.context)
        self.service.running = True
        self.service._poll_codex()
        self.service._remind()
        self.service._flush()
        self.assertEqual(self.service.data['outputs'][0]['state'], 'unknown')
        self.assertEqual(sum(alias == 'feishuReply' for alias, _ in self.context.calls), 1)

    def test_unknown_planner_send_never_leaks_result_or_replays_request(self):
        self.service._remind()
        item = self.service.data['inputs'][0]
        self.context.fail['codexSend'] = TimeoutError('acceptance unknown')
        self.service._submit()
        self.context.fail.clear()
        self.context.codex['turns'].append(dict(turnId='accepted', threadId='existing-session',
            message=item['text'], status='completed', reply=decision(item['planningBatch']), error=None))
        self.service._poll_codex()
        self.service._remind()
        self.service._submit()
        self.assertEqual(item['state'], 'unknown')
        self.assertEqual(self.service.data['outputs'], [])
        self.assertEqual(sum(alias == 'codexSend' for alias, _ in self.context.calls), 1)
        self.service.handle('confirm', dict(kind='inputs', id=item['id']))
        self.service._remind()
        self.assertEqual(len(self.service.data['reminders']['plans']), 1)

    def test_no_delta_survives_restart_without_model_call(self):
        self.finish_plan(empty=True)
        self.now += timedelta(hours=2)
        self.service = backend.create(self.context)
        self.service.running = True
        self.service._poll_codex()
        self.service._remind()
        self.service._submit()
        self.assertEqual(sum(alias == 'codexSend' for alias, _ in self.context.calls), 1)

    def test_schedule_read_error_prevents_send_and_manual_retry_rechecks_cancel(self):
        self.finish_plan()
        self.now += timedelta(minutes=21)
        self.service._remind()
        self.context.fail['scheduleGet'] = Rejection('日程读取被拒绝')
        self.service._flush()
        output = self.service.data['outputs'][0]
        self.assertEqual(output['state'], 'failed')
        self.context.fail.clear()
        self.context.schedule = snapshot(tasks=[])
        self.service.handle('retry', dict(kind='outputs', id=output['id']))
        self.service._flush()
        self.assertEqual(output['state'], 'skipped')
        self.assertFalse(any(alias == 'feishuReply' for alias, _ in self.context.calls))


if __name__ == '__main__':
    unittest.main()
