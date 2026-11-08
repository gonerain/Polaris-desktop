"""Explicit local Codex plugin installation, owned by the Agent component."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading


PLUGIN = 'polaris-agent@polaris-agent-local'
MARKETPLACE = 'polaris-agent-local'


class CodexPlugin:
    def __init__(self, data_dir, source_dir=None):
        self.directory = Path(data_dir) / 'codex-plugin'
        self.source = Path(source_dir) if source_dir else Path(__file__).resolve().parents[1] / 'integrations'
        self.marketplace = self.directory / 'marketplace'
        self.receipt = self.directory / 'installed.json'
        self._lock = threading.Lock()

    def _run(self, args):
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            raise RuntimeError(detail or 'Codex 命令执行失败')
        return result.stdout

    @staticmethod
    def _metadata(directory):
        manifest = json.loads((directory / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        if manifest.get('name') != 'polaris-agent' or not manifest.get('version'):
            raise ValueError('插件清单无效')
        files = sorted(p for p in directory.rglob('*') if p.is_file() and p.suffix != '.pyc' and
                       not any(part in ('__pycache__', 'node_modules', '.git', 'tests') for part in p.relative_to(directory).parts))
        digest = hashlib.sha256()
        for path in files:
            if path.is_symlink():
                raise ValueError('插件资源不能包含符号链接')
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(b'\0')
            digest.update(path.read_bytes())
        return manifest['version'], digest.hexdigest()

    def _helpers(self, command, sessions):
        directory = self.marketplace if command == '--upgrade-helpers' else self.source
        result = subprocess.run([shutil.which('node'), str(directory / 'codex/hook.mjs'), command],
                                input=json.dumps({'sessions': sessions}), capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()[-1200:])
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise ValueError('会话连接状态格式不受支持')
        return payload

    @staticmethod
    def _helper_state(state, helpers):
        state['helpers'] = helpers
        state['reload'] = any(row.get('status') not in ('current', 'not_running')
                              for row in helpers['results'])
        if state['reload']:
            state['message'] += '；部分会话连接待更新或无法确认，旧版连接需重启对应会话'

    def _repairable(self):
        try:
            receipt = json.loads(self.receipt.read_text(encoding='utf-8'))
            return (receipt.get('sourcePath') == str(self.marketplace.resolve()) and
                    self._metadata(Path(receipt['cachePath'])) == (receipt['version'], receipt['digest']))
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def status(self, sessions=None):
        state = {'installed': False, 'enabled': False, 'managed': False,
                 'installedVersion': '', 'bundledVersion': '', 'updateAvailable': False,
                 'codexAvailable': False, 'nodeAvailable': False, 'message': '', 'sourcePath': ''}
        try:
            version, digest = self._metadata(self.source)
            state['bundledVersion'] = version
            codex, node = shutil.which('codex'), shutil.which('node')
            state['codexAvailable'] = bool(codex)
            if node:
                match = re.match(r'v?(\d+)\.', self._run([node, '--version']).strip())
                state['nodeAvailable'] = bool(match and int(match.group(1)) >= 20)
            if not codex:
                state['message'] = '未找到 Codex CLI'
                return state
            payload = json.loads(self._run([codex, 'plugin', 'list', '--marketplace', MARKETPLACE, '--json']))
            if not isinstance(payload.get('installed'), list):
                raise ValueError('Codex 插件状态格式不受支持')
            entry = next((row for row in payload['installed'] if row.get('pluginId') == PLUGIN), None)
            if entry and entry.get('installed') is True:
                state['installed'] = True
                state['enabled'] = entry.get('enabled') is True
                state['installedVersion'] = str(entry.get('version', ''))
                source = entry.get('marketplaceSource', {}).get('source', '')
                state['sourcePath'] = source
                state['managed'] = bool(source and Path(source).resolve() == self.marketplace.resolve())
                try:
                    receipt = json.loads(self.receipt.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    receipt = {}
                try:
                    cache_matches = self._metadata(Path(receipt['cachePath'])) == (version, digest)
                except (OSError, ValueError, KeyError, TypeError):
                    cache_matches = False
                state['updateAvailable'] = (not state['managed'] or state['installedVersion'] != version or
                                            receipt.get('digest') != digest or not cache_matches)
                state['message'] = '已启用' if state['enabled'] else '已安装，未启用'
            else:
                state['message'] = '尚未安装'
            if not state['nodeAvailable']:
                state['message'] += '；需要 Node.js 20 或更新版本'
            elif sessions:
                try:
                    self._helper_state(state, self._helpers('--helper-status', sessions))
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    state['helperError'] = str(error)
                    state['reload'] = True
                    state['message'] += '；无法确认会话连接状态'
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            state['message'] = f'无法确认插件状态：{error}'
            state['error'] = True
            state['repairable'] = self._repairable()
            if state['repairable']:
                state['message'] += '；可从随包资源修复插件目录'
        return state

    def install(self, sessions=None):
        if not self._lock.acquire(blocking=False):
            return {'ok': False, 'message': '插件安装正在进行'}
        backup = None
        changed = False
        registered = False
        removed_source = None
        install_attempted = False
        before = {}
        try:
            before = self.status()
            if (before.get('error') and not before.get('repairable')) or not before['codexAvailable'] or not before['nodeAvailable']:
                return dict(before, ok=False)
            version, digest = self._metadata(self.source)
            codex = shutil.which('codex')
            old_source = str(self.marketplace.resolve()) if before.get('repairable') else None
            if not before.get('repairable'):
                markets = json.loads(self._run([codex, 'plugin', 'marketplace', 'list', '--json']))
                if not isinstance(markets.get('marketplaces'), list):
                    raise ValueError('Codex marketplace 状态格式不受支持')
                market = next((row for row in markets['marketplaces'] if row.get('name') == MARKETPLACE), None)
                old_source = market.get('marketplaceSource', {}).get('source') if market else None
                if market and not old_source:
                    raise RuntimeError('无法核实已有插件市场来源')
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='stage-', dir=self.directory) as temporary:
                staging = Path(temporary) / 'marketplace'
                shutil.copytree(self.source, staging, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'node_modules', '.git', 'tests'))
                if self._metadata(staging) != (version, digest):
                    raise RuntimeError('插件资源复制校验失败')
                backup = self.directory / 'previous'
                if backup.exists():
                    raise RuntimeError('上次安装备份仍存在，请先恢复或移走 codex-plugin/previous')
                if self.marketplace.exists():
                    self.marketplace.rename(backup)
                changed = True
                staging.rename(self.marketplace)
            if before.get('repairable'):
                repaired = self.status()
                if repaired.get('error') or not repaired.get('managed'):
                    raise RuntimeError('修复目录后仍无法核实 Codex 插件来源')
            if old_source and Path(old_source).resolve() != self.marketplace.resolve():
                self._run([codex, 'plugin', 'marketplace', 'remove', MARKETPLACE, '--json'])
                removed_source = old_source
            json.loads(self._run([codex, 'plugin', 'marketplace', 'add', str(self.marketplace), '--json']))
            registered = True
            install_attempted = True
            installed = json.loads(self._run([codex, 'plugin', 'add', PLUGIN, '--json']))
            cache = installed.get('installedPath')
            if not cache or self._metadata(Path(cache)) != (version, digest):
                raise RuntimeError('Codex 安装缓存与随包插件不一致')
            after = self.status()
            if not after['installed'] or not after['managed'] or after['installedVersion'] != version or after.get('error'):
                raise RuntimeError('Codex 未确认已安装随包插件')
            receipt_tmp = self.receipt.with_suffix('.tmp')
            receipt_tmp.write_text(json.dumps({'version': version, 'digest': digest, 'cachePath': cache, 'sourcePath': str(self.marketplace.resolve())}), encoding='utf-8')
            os.replace(receipt_tmp, self.receipt)
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
            result = dict(self.status(), ok=True, message='插件已安装；请在 Codex 确认启用并按提示信任 hooks')
            if sessions:
                try:
                    self._helper_state(result, self._helpers('--upgrade-helpers', sessions))
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    result['helperError'] = str(error)
                    result['reload'] = True
                    result['message'] = '插件已安装，会话连接更新未完成；请重启对应会话'
            return result
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            rollback_error = ''
            if changed:
                try:
                    if self.marketplace.exists():
                        shutil.rmtree(self.marketplace)
                    if backup and backup.exists():
                        backup.rename(self.marketplace)
                except OSError as rollback:
                    rollback_error = f'；旧插件资源恢复失败，备份保留在 {backup}：{rollback}'
            if removed_source:
                try:
                    if registered:
                        self._run([shutil.which('codex'), 'plugin', 'marketplace', 'remove', MARKETPLACE, '--json'])
                    self._run([shutil.which('codex'), 'plugin', 'marketplace', 'add', removed_source, '--json'])
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as rollback:
                    rollback_error = f'；原插件来源恢复失败：{rollback}'
            if install_attempted and before.get('installed') and not rollback_error:
                try:
                    self._run([shutil.which('codex'), 'plugin', 'add', PLUGIN, '--json'])
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as rollback:
                    rollback_error += f'；旧插件安装缓存恢复失败：{rollback}'
            return dict(self.status(), ok=False, message=f'安装失败：{error}{rollback_error}')
        finally:
            self._lock.release()
