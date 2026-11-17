import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import httpx
from polaris_feishu_bot.proxy import http_proxy_kwargs, configure_sdk_proxy


class ProxyTests(TestCase):
    def test_https_ignores_unrelated_all_proxy(self):
        env = dict(https_proxy='http://127.0.0.1:7897', all_proxy='socks://127.0.0.1:7897')
        with patch.dict(os.environ, env, clear=True):
            kwargs = http_proxy_kwargs('https://open.feishu.cn/open-apis/im/v1/messages')
            self.assertEqual(kwargs, dict(proxy=env['https_proxy'], trust_env=False))
            # Construction previously failed before a request could be sent.
            httpx.AsyncClient(**kwargs)
            self.assertEqual(dict(os.environ), env)

    def test_http_and_https_choose_their_own_proxy(self):
        with patch.dict(os.environ, dict(http_proxy='http://http-proxy:80', https_proxy='http://https-proxy:81'), clear=True):
            self.assertEqual(http_proxy_kwargs('http://example.com')['proxy'], 'http://http-proxy:80')
            self.assertEqual(http_proxy_kwargs('https://example.com')['proxy'], 'http://https-proxy:81')

    def test_no_proxy_bypasses_even_invalid_all_proxy(self):
        for no_proxy in ('open.feishu.cn', '.feishu.cn', '*'):
            with self.subTest(no_proxy=no_proxy), patch.dict(os.environ, dict(
                    https_proxy='http://proxy:80', all_proxy='socks://proxy:80', no_proxy=no_proxy), clear=True):
                self.assertEqual(http_proxy_kwargs('https://open.feishu.cn/path'), dict(proxy=None, trust_env=False))

    def test_all_proxy_is_used_only_without_scheme_proxy(self):
        with patch.dict(os.environ, dict(ALL_PROXY='http://proxy:80'), clear=True):
            self.assertEqual(http_proxy_kwargs('https://open.feishu.cn')['proxy'], 'http://proxy:80')
        with patch.dict(os.environ, dict(all_proxy='socks://proxy:80'), clear=True):
            with self.assertRaises(ValueError):
                httpx.AsyncClient(**http_proxy_kwargs('https://open.feishu.cn'))

    def test_no_proxy_configured(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(http_proxy_kwargs('https://open.feishu.cn'), dict(proxy=None, trust_env=False))

    def test_sdk_options_preserve_explicit_configuration(self):
        from lark_channel.core.http import transport
        with patch.object(transport, '_httpx_client_kwargs'), patch.dict(os.environ, dict(
                https_proxy='http://proxy:80', all_proxy='socks://proxy:80'), clear=True):
            configure_sdk_proxy()
            conf = SimpleNamespace(domain='https://open.feishu.cn', proxy_url=None, trust_env_proxy=None)
            self.assertEqual(transport._httpx_client_kwargs(conf)['proxy'], 'http://proxy:80')
            conf.trust_env_proxy = False
            self.assertEqual(transport._httpx_client_kwargs(conf), dict(proxy=None, trust_env=False))
            conf.proxy_url = 'http://explicit:81'
            self.assertEqual(transport._httpx_client_kwargs(conf)['proxy'], conf.proxy_url)
