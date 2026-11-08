"""System local time, sampled afresh for each request."""
from datetime import datetime


class LocalClock:
    def now(self):
        return datetime.now().astimezone()

    def context(self):
        now = self.now()
        offset = now.utcoffset()
        if offset is None:
            raise ValueError('日程时钟必须返回带时区的时间')
        return {'now': now.isoformat(timespec='seconds'), 'date': now.date().isoformat(),
                'timezone': {'name': now.tzname() or '',
                             'utcOffsetMinutes': int(offset.total_seconds() / 60)}}
