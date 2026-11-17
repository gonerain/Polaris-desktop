"""Select only the environment proxy relevant to a Feishu HTTP endpoint."""
from urllib.request import getproxies, proxy_bypass_environment
from urllib.parse import urlsplit


def http_proxy_kwargs(url):
    proxies = getproxies()
    target = urlsplit(url)
    proxy = None
    if not proxy_bypass_environment(target.netloc, proxies):
        proxy = proxies.get(target.scheme) or proxies.get('all')
    # Do not let httpx eagerly parse unrelated environment proxy entries.
    return dict(proxy=proxy, trust_env=False)


def configure_sdk_proxy():
    """Adapt the locked SDK's HTTP client options, leaving WS setup unchanged."""
    from lark_channel.core.http import transport

    def client_kwargs(conf):
        if conf.proxy_url or conf.trust_env_proxy is False:
            return dict(proxy=conf.proxy_url, trust_env=False)
        return http_proxy_kwargs(conf.domain)

    transport._httpx_client_kwargs = client_kwargs
