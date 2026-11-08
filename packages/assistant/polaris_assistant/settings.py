"""Local model settings. Status never contains credentials or performs a request."""
import json
import os
from pathlib import Path
import tempfile

from .model import ChatModel, ModelError, PROFILES, _settings, configured_model, selected_provider


def snapshot(directory):
    directory = Path(directory)
    try:
        saved = _settings(directory).get('provider', 'deepseek')
    except ModelError:
        saved = 'deepseek'
    if not isinstance(saved, str) or saved not in PROFILES:
        saved = 'deepseek'
    providers = []
    for name, (label, model, variable, _) in PROFILES.items():
        providers.append(dict(id=name, label=label + (' · 国际站' if name == 'zai' else ''),
                              model=model, keyEnv=variable, keyOverride=bool(os.environ.get(variable, '').strip()),
                              keyStored=(directory / (name + '-api-key')).is_file()))
    result = dict(providers=providers, savedProvider=saved, provider='', model='', ready=False,
                  providerOverride=bool(os.environ.get('POLARIS_AGENT_MODEL_PROVIDER', '').strip()), detail='')
    try:
        result['provider'] = selected_provider(directory)
        model = configured_model(directory)
        result.update(ready=True, model=model.model_id)
    except ModelError as error:
        result['detail'] = str(error)
    return result


def _stage(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(name)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def save(directory, provider, api_key):
    if not isinstance(provider, str) or provider not in PROFILES:
        raise ModelError('请选择已有的模型服务')
    if not isinstance(api_key, str):
        raise ModelError('密钥格式无效')
    api_key = api_key.strip()
    if api_key:
        # Construction validates the local format only; it never opens a connection.
        ChatModel(api_key, provider=provider)
    directory = Path(directory)
    key_path = directory / (provider + '-api-key')
    if not api_key and not key_path.is_file() and not os.environ.get(PROFILES[provider][2], '').strip():
        raise ModelError('请输入所选服务的 API 密钥')
    try:
        previous = _settings(directory)
    except ModelError:
        # An explicit local save can repair an unreadable model.json.
        previous = {}
    settings = dict(previous, version=1, provider=provider)
    # Keep reasoning_effort and other existing settings when changing service/key.
    staged_key = staged_settings = backup_key = None
    replaced_key = False
    preserve_backup = False
    try:
        staged_settings = _stage(directory / 'model.json', (json.dumps(settings, ensure_ascii=False, indent=2) + '\n').encode())
        if api_key:
            if key_path.exists():
                backup_key = _stage(key_path, key_path.read_bytes())
            staged_key = _stage(key_path, (api_key + '\n').encode())
            os.replace(staged_key, key_path)
            replaced_key = True
        try:
            os.replace(staged_settings, directory / 'model.json')
        except OSError:
            if replaced_key:
                try:
                    if backup_key is not None:
                        os.replace(backup_key, key_path)
                    else:
                        key_path.unlink()
                except OSError:
                    preserve_backup = backup_key is not None
                    detail = ('已在配置目录保留旧密钥备份（' + backup_key.name + '）' if preserve_backup
                              else '新密钥文件可能已写入')
                    raise ModelError('模型设置未保存，旧密钥恢复未完成；' + detail + '。请检查写入权限后重试') from None
            raise
    except OSError:
        raise ModelError('模型设置保存失败，请检查配置目录的空间和写入权限后重试') from None
    finally:
        for path in (staged_key, staged_settings, backup_key):
            if path is not None and not (preserve_backup and path == backup_key):
                path.unlink(missing_ok=True)
