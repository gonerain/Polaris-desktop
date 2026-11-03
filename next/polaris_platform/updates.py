"""GitHub Release discovery and verified Debian package downloads."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .metadata import VERSION

REPOSITORY = 'gonerain/Polaris-desktop'
API_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
MAX_PACKAGE_SIZE = 1024 * 1024 * 1024


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+(?:\.\d+){2,3}', value):
        raise ValueError('发布版本必须采用 v1.2.3 或 v1.2.3.4 格式')
    parts = tuple(int(part) for part in value.removeprefix('v').split('.'))
    return parts + (0,) * (4 - len(parts))


def architecture():
    machine = platform.machine().lower()
    try:
        return {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64'}[machine]
    except KeyError:
        raise ValueError(f'暂不支持此架构的 deb 更新：{machine}') from None


@dataclass(frozen=True)
class Release:
    version: str
    name: str
    url: str
    size: int
    sha256: str


def _open(url, *, api=False):
    headers = {'User-Agent': f'Polaris/{VERSION}', 'Accept': 'application/vnd.github+json' if api else 'application/octet-stream'}
    return urlopen(Request(url, headers=headers), timeout=30)


def parse_release(data, current=VERSION, arch=None):
    if data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name', '')
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix('v')
    expected = f'polaris_{version}_{arch or architecture()}.deb'
    for asset in data.get('assets', []):
        if asset.get('name') != expected:
            continue
        url = asset.get('browser_download_url', '')
        parsed = urlparse(url)
        prefix = f'/{REPOSITORY}/releases/download/{tag}/'
        if parsed.scheme != 'https' or parsed.netloc != 'github.com' or parsed.path != prefix + expected or parsed.query or parsed.fragment:
            raise ValueError('更新包地址不属于官方 GitHub Release')
        digest = asset.get('digest', '') or ''
        if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}', digest):
            raise ValueError('发布包缺少 GitHub SHA-256 校验值，请通过项目发布页下载')
        size = asset.get('size')
        if type(size) is not int or not 0 < size <= MAX_PACKAGE_SIZE:
            raise ValueError('发布包大小无效')
        return Release(version, expected, url, size, digest[7:].lower())
    raise ValueError(f'发现新版本 {tag}，但发布中没有 {expected}')


def check_release(current=VERSION, arch=None):
    try:
        with _open(API_URL, api=True) as response:
            payload = response.read(2 * 1024 * 1024 + 1)
    except HTTPError as error:
        if error.code == 404:
            raise ValueError('项目尚无可用的正式 GitHub Release') from error
        raise
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('发布信息超过大小限制')
    return parse_release(json.loads(payload), current, arch)


def download_release(release, directory, progress=lambda value: None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # The name is always derived from validated release metadata, never a URL path.
    if Path(release.name).name != release.name:
        raise ValueError('无效的更新文件名')
    destination = directory / release.name
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix='.polaris-', suffix='.part', dir=directory)
    temporary = Path(temporary)
    digest, received = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, 'wb') as output, _open(release.url) as response:
            while chunk := response.read(256 * 1024):
                received += len(chunk)
                if received > release.size:
                    raise ValueError('更新包大小与发布信息不符')
                digest.update(chunk)
                output.write(chunk)
                progress(int(received * 100 / release.size))
        if received != release.size or digest.hexdigest() != release.sha256:
            raise ValueError('更新包校验失败，请重新下载')
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)
