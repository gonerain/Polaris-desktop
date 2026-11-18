"""Read-only Feishu JSON 2.0 panels, rendered from structured capability data."""
from copy import deepcopy
from datetime import date, timedelta
import re
from uuid import uuid4


PAGE_SIZE = 4
FILTERS = {
    'sessions': [('all', '全部标记'), ('running', '运行中'), ('online', '在线'), ('offline', '离线')],
    'schedule': [('today', '今天'), ('upcoming', '未来七天'), ('inbox', '收集箱'), ('all', '全部未完成'), ('done', '已完成')],
}
COMMANDS = {
    '面板': 'sessions', '/面板': 'sessions', '会话': 'sessions', '/会话': 'sessions',
    '标记会话': 'sessions', '查看标记会话': 'sessions',
    '日程': 'schedule', '/日程': 'schedule', '查看日程': 'schedule',
}
RUN_LABELS = {'running': '🟢 运行中', 'completed': '✅ 已完成', 'failed': '🔴 失败',
              'stopped': '⏹ 已停止', 'unknown': '⚪ 结果未知'}


def panel_state(view, *, filter=None, page=0, detailId=None):
    if view not in FILTERS or filter is not None and filter not in dict(FILTERS[view]):
        raise ValueError('无效的卡片页面或筛选条件')
    if type(page) is not int or page < 0 or detailId is not None and not isinstance(detailId, str):
        raise ValueError('无效的卡片页码或详情标识')
    return dict(view=view, filter=filter or FILTERS[view][0][0], page=page, detailId=detailId)


def plain(text):
    return dict(tag='plain_text', content=text)


def escaped(text):
    # Data is display text, not executable Feishu Markdown (mentions, links, etc.).
    return re.sub(r'([\\`*_\[\]<>~!])', r'\\\1', str(text))


def excerpt(text, size):
    return text if len(text) <= size else text[:size] + '…（展示已截短）'


def markdown(text):
    return dict(tag='markdown', content=text)


def columns(*elements):
    return dict(tag='column_set', flex_mode='none', columns=[
        dict(tag='column', width='weighted', weight=1, elements=[element]) for element in elements])


def session_status(row):
    if not row['online']:
        return '⚪ 离线'
    run = row['lastRun']
    return RUN_LABELS[run['status']] if run else '🔵 空闲'


def task_time(row):
    return (row['date'] or '收集箱') + (' · ' + row['time'] if row['time'] else '')


def render_panel(application_id, state, data, result=None):
    """Return the card and its actual (possibly shortened by a shrinking list) page."""
    state = deepcopy(state)
    view = state['view']
    render_id = uuid4().hex

    def button(label, target=None, *, primary=False, disabled=False):
        return dict(tag='button', text=plain(label), type='primary' if primary else 'default',
                    width='fill', size='small', disabled=disabled,
                    behaviors=[dict(type='callback', value=dict(app=application_id, renderId=render_id, **(target or state)))])

    elements = [columns(
        button('📌 标记会话', panel_state('sessions'), primary=view == 'sessions'),
        button('📅 日程任务', panel_state('schedule'), primary=view == 'schedule'))]
    if view == 'sessions':
        all_rows = data
        rows = [row for row in all_rows if state['filter'] == 'all'
                or state['filter'] == 'online' and row['online']
                or state['filter'] == 'offline' and not row['online']
                or state['filter'] == 'running' and row['online'] and row['lastRun'] and row['lastRun']['status'] == 'running']
        online = sum(bool(row['online']) for row in all_rows)
        summary = f"**{len(all_rows)}** 个标记会话　·　**{online}** 个在线"
        title, color = '📌 标记会话', 'blue'
    else:
        all_rows = data['tasks']
        today = date.fromisoformat(data['timeContext']['date'])
        end = (today + timedelta(days=6)).isoformat()
        today = today.isoformat()
        rows = [row for row in all_rows if
                (state['filter'] == 'done' and row['done']) or (not row['done'] and (
                    state['filter'] == 'all'
                    or state['filter'] == 'inbox' and row['date'] is None
                    or state['filter'] == 'today' and row['date'] == today
                    or state['filter'] == 'upcoming' and row['date'] is not None and today <= row['date'] <= end))]
        rows.sort(key=lambda row: (row['date'] or '9999', row['time'] or '99:99'))
        pending_today = sum(not row['done'] and row['date'] == today for row in all_rows)
        summary = f"**{today}**　·　今天 **{pending_today}** 项待办　·　共 **{len(all_rows)}** 项任务"
        title, color = '📅 日程任务', 'green'

    elements.append(markdown(summary))
    if state['detailId'] is not None:
        row = next((row for row in all_rows if row['id'] == state['detailId']), None)
        elements.append(dict(tag='hr'))
        if row is None:
            elements.append(markdown('此条目已不在当前列表中，请返回列表刷新。'))
        elif view == 'sessions':
            elements.extend([
                markdown('**' + escaped(excerpt(row['title'], 160)) + '**'),
                markdown(session_status(row) + '　·　' + escaped(row['adapter']) + f"　·　{row['runCount']} 轮记录"),
                markdown('**工作目录**\n' + escaped(row['cwd'] or '未提供')),
                markdown('**最近已完成的回复**\n' + (escaped(excerpt(result['reply'], 6000))
                         if result and result.get('reply') else '暂无文字回复。')),
            ])
            if result and result.get('replyTruncated'):
                elements.append(markdown('来源记录标记此回复已截短。'))
        else:
            elements.extend([
                markdown(('⭐ ' if row['important'] else '') + '**' + escaped(excerpt(row['title'], 160)) + '**'),
                markdown(('✅ 已完成' if row['done'] else '🔵 待办') + '　·　' + task_time(row)),
                markdown('**笔记**\n' + (escaped(excerpt(row['notes'], 3000)) if row['notes'] else '暂无笔记。')),
            ])
            if row['subtasks']:
                elements.append(markdown('**子任务**\n' + '\n'.join(
                    ('✅ ' if item['done'] else '○ ') + escaped(excerpt(item['title'], 120)) for item in row['subtasks'][:20])))
                if len(row['subtasks']) > 20:
                    elements.append(markdown(f"展示前 20 项，共 {len(row['subtasks'])} 项子任务。"))
        elements.append(columns(button('← 返回列表', dict(state, detailId=None)), button('刷新详情')))
    else:
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        state['page'] = min(state['page'], pages - 1)
        choices = [button(label, dict(state, filter=value, page=0), primary=state['filter'] == value)
                   for value, label in FILTERS[view]]
        per_row = (len(choices) + 1) // 2
        for offset in range(0, len(choices), per_row):
            elements.append(columns(*choices[offset:offset + per_row]))
        elements.append(dict(tag='hr'))
        if not rows:
            elements.append(markdown('暂无符合条件的会话。' if view == 'sessions' else '暂无符合条件的任务。'))
        for row in rows[state['page'] * PAGE_SIZE:(state['page'] + 1) * PAGE_SIZE]:
            if view == 'sessions':
                content = [markdown('**' + escaped(excerpt(row['title'], 100)) + '**'),
                           markdown(session_status(row) + '　·　' + escaped(row['adapter']) + f"　·　{row['runCount']} 轮记录")]
                if row['cwd']:
                    content.append(markdown(escaped(excerpt(row['cwd'], 160))))
            else:
                content = [markdown(('✅ ' if row['done'] else '⭐ ' if row['important'] else '○ ') + '**' + escaped(excerpt(row['title'], 100)) + '**'),
                           markdown(task_time(row))]
                if row['subtasks']:
                    content.append(markdown(f"子任务 {sum(bool(item['done']) for item in row['subtasks'])}/{len(row['subtasks'])}"))
            elements.append(dict(tag='column_set', flex_mode='none', columns=[
                dict(tag='column', width='weighted', weight=4, elements=content),
                dict(tag='column', width='weighted', weight=1,
                     elements=[button('详情', dict(state, detailId=row['id']))])]))
            elements.append(dict(tag='hr'))
        elements.extend([
            markdown(f"共 {len(rows)} 项　·　第 {state['page'] + 1} / {pages} 页"),
            columns(button('上一页', dict(state, page=max(0, state['page'] - 1)), disabled=state['page'] == 0),
                    button('刷新'),
                    button('下一页', dict(state, page=state['page'] + 1), disabled=state['page'] + 1 == pages)),
        ])
    elements.append(markdown('点击刷新获取最新数据 · 发送「面板」可打开新卡片'))
    return dict(schema='2.0', config=dict(update_multi=True),
                header=dict(title=plain(title), template=color),
                body=dict(elements=elements, padding='12px', vertical_spacing='8px')), state
