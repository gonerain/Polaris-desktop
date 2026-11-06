"""Per-instance worker transport; credentials travel only through private stdin."""
from concurrent.futures import Future, TimeoutError
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4
from polaris_platform.protocol import PlatformError


class WorkerTransport:
    def __init__(self, on_event, command=None):
        self.on_event = on_event
        self.command = command
        self.process = None
        self._pending = {}
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()

    @staticmethod
    def default_command():
        if getattr(sys, 'frozen', False):
            return [sys.executable, '--component-python', '-m', 'polaris_feishu_bot.worker']
        return [sys.executable, '-m', 'polaris_feishu_bot.worker']

    def start(self):
        with self._lock:
            if self.process is not None and self.process.poll() is None:
                return self.process
            root = str(Path(__file__).resolve().parents[1])
            env = dict(os.environ)
            env['PYTHONPATH'] = root + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
            process = subprocess.Popen(self.command or self.default_command(), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', env=env,
                bufsize=1, start_new_session=True, cwd=root)
            self.process = process
            threading.Thread(target=self._read, args=(process,), daemon=True).start()
            return process

    def _read(self, process):
        failed = False
        try:
            for line in process.stdout:
                value = json.loads(line)
                if 'event' in value:
                    with self._lock:
                        if self.process is process:
                            self.on_event(value['event'], value['payload'])
                else:
                    with self._lock:
                        entry = self._pending.get(value['id'])
                        pending = self._pending.pop(value['id'])[1] if entry and entry[0] is process else None
                    if pending is not None and not pending.done():
                        if 'error' in value:
                            pending.set_exception(PlatformError(value.get('code', 'feishu_operation_failed'), value['error']))
                        else:
                            pending.set_result(value.get('result', {}))
        except Exception:
            failed = True
        finally:
            with self._lock:
                pending = [entry[1] for entry in self._pending.values() if entry[0] is process]
                self._pending = {key: entry for key, entry in self._pending.items() if entry[0] is not process}
                if self.process is process:
                    self.process = None
                    try:
                        self.on_event('connection', {'connectionState': 'disconnected'})
                    except Exception:
                        failed = True
            if failed and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            try:
                process.stdin.close()
                process.stdout.close()
            except (OSError, ValueError):
                pass
            for future in pending:
                if not future.done():
                    future.set_exception(PlatformError('feishu_disconnected', '连接中断；在途写操作结果不确定，请先检查飞书会话后再操作'))

    def request(self, operation, params=None, timeout=35):
        request_id, pending = uuid4().hex, Future()
        process = None
        try:
            with self._write_lock:
                process = self.start()
                with self._lock:
                    self._pending[request_id] = (process, pending)
                process.stdin.write(json.dumps(dict(id=request_id, operation=operation, params=params or {})) + '\n')
                process.stdin.flush()
            return pending.result(timeout=timeout)
        except TimeoutError:
            self.close(process)
            message = ('发送超时，结果不确定；请先检查飞书会话，勿直接重复发送' if operation in ('send', 'send_card', 'update_card')
                       else '飞书操作超时，连接已关闭，请重新连接')
            raise PlatformError('feishu_timeout', message) from None
        except (OSError, ValueError):
            self.close(process)
            raise PlatformError('feishu_disconnected', '连接中断；在途写操作结果不确定，请先检查飞书会话后再操作') from None
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def close(self, expected=None):
        with self._write_lock:
            with self._lock:
                if expected is not None and self.process is not expected:
                    return
                process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
