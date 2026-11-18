"""Repeated rendered navigation through the bundled SDK's real dedup pipeline."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from test_panels import panels, session, task, walk


SDK_CHECK = r'''
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
from lark_channel.channel.channel import _card_action_identity
from lark_channel.channel.types import CardActionPayload
from lark_channel.channel.safety.pipeline import SafetyPipeline

async def run(values):
    async def no_message(message):
        raise AssertionError('No model or chat input should run')
    pipeline = SafetyPipeline(loop=asyncio.get_running_loop(), on_message=no_message)
    received = []
    try:
        for value in values:
            action = CardActionPayload(tag='button', value=value)
            identity = 'card:message:operator:' + _card_action_identity(action)
            delivered = asyncio.Event()
            async def handler():
                received.append(value)
                delivered.set()
            previously_seen = await pipeline.seen.has(identity)
            await pipeline.push_action(identity, 'chat', handler)
            if not previously_seen:
                await asyncio.wait_for(delivered.wait(), 1)
            count = len(received)
            # Real redelivery of the same click still must be deduplicated.
            await pipeline.push_action(identity, 'chat', handler)
            await asyncio.sleep(0)
            assert len(received) == count
        return len(received)
    finally:
        await pipeline.dispose()

async def main():
    values = json.load(sys.stdin)
    fixed = await run(values)
    legacy = [{k:v for k,v in value.items() if k != 'renderId'} for value in values]
    old = await run(legacy)
    print(json.dumps(dict(delivered=fixed, legacyDelivered=old, total=len(values))))
asyncio.run(main())
'''


class SDKNavigationTests(unittest.TestCase):
    def test_repeated_paging_back_refresh_and_filters_all_survive_sdk_dedup(self):
        data = dict(sessions=[session(i) for i in range(6)],
                    schedule=dict(tasks=[task(i) for i in range(9)] + [task(10, None)],
                                  timeContext=dict(date='2026-11-18')))
        state = panels.panel_state('sessions')
        values = []
        steps = ['下一页', '上一页', '详情', '← 返回列表', '刷新',
                 '📅 日程任务', '收集箱', '全部未完成', '下一页', '上一页',
                 '详情', '← 返回列表', '📌 标记会话']
        for _ in range(4):
            for label in steps:
                card, state = panels.render_panel('app', state, data[state['view']], dict(reply='回答'))
                button = next(item for item in walk(card) if item.get('tag') == 'button'
                              and item['text']['content'] == label)
                self.assertFalse(button['disabled'], label)
                value = deepcopy(button['behaviors'][0]['value'])
                values.append(value)
                state = panels.panel_state(value['view'], filter=value['filter'], page=value['page'], detailId=value['detailId'])
        vendor = Path(__file__).resolve().parents[4] / 'marketplace/packages/feishu-bot/vendor'
        process = subprocess.run([sys.executable, '-c', SDK_CHECK, str(vendor)],
                                 input=json.dumps(values), text=True, capture_output=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        result = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertEqual(result['delivered'], 52)
        self.assertLess(result['legacyDelivered'], result['delivered'])


if __name__ == '__main__':
    unittest.main()
