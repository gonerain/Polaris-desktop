"""Codex app-server JSON-RPC transport."""
import json
import subprocess
import threading


class Transport:
    def __init__(self, on_message, on_exit):
        self.on_message, self.on_exit = on_message, on_exit
        self.process = subprocess.Popen(['codex', 'app-server', '--listen', 'stdio://'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lock = threading.Lock()
        self.pending = {}
        self.counter = 0
        threading.Thread(target=self._read, daemon=True, name='codex-app-server').start()
        self.call('initialize', {'clientInfo': {'name': 'polaris_codex_cli', 'title': 'Polaris Codex CLI', 'version': '0.1.0'}})
        self.write({'method': 'initialized'})

    def write(self, value):
        with self.lock:
            self.process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n')
            self.process.stdin.flush()

    def call(self, method, params):
        with self.lock:
            self.counter += 1
            ident = self.counter
            ready = threading.Event()
            slot = [ready, None]
            self.pending[ident] = slot
            self.process.stdin.write(json.dumps({'id': ident, 'method': method, 'params': params}, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
        ready.wait()
        result = slot[1]
        if 'error' in result:
            raise RuntimeError(result['error'].get('message', str(result['error'])))
        return result['result']

    def reply(self, ident, result):
        self.write({'id': ident, 'result': result})

    def _read(self):
        try:
            for line in self.process.stdout:
                message = json.loads(line)
                if 'method' not in message and 'id' in message:
                    with self.lock:
                        slot = self.pending.pop(message['id'], None)
                    if slot:
                        slot[1] = message
                        slot[0].set()
                else:
                    self.on_message(message)
        finally:
            with self.lock:
                pending, self.pending = self.pending, {}
            for slot in pending.values():
                slot[1] = {'error': {'message': 'Codex 进程已退出，操作结果未知'}}
                slot[0].set()
            self.on_exit()

    def close(self):
        self.process.stdin.close()
        self.process.wait()
