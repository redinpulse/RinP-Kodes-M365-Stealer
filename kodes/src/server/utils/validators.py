import re

HOSTNAME_RE = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9._-]{0,48})[A-Za-z0-9]$')
DOMAIN_RE = re.compile(
    r'^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
    r'(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$')
NGROK_URL_RE = re.compile(r'^(tcp|tls)://[A-Za-z0-9.-]+:\d{1,5}$')
NGROK_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{1,128}$')
SP_HOST_RE = re.compile(r'^[A-Za-z0-9-]{1,63}\.sharepoint\.com$')


def valid_hostname(hostname):
    return bool(hostname and HOSTNAME_RE.match(hostname))


def valid_domain(domain):
    return bool(domain and DOMAIN_RE.match(domain))


def valid_ngrok_url(url):
    return bool(url and len(url) <= 200 and NGROK_URL_RE.match(url))


def valid_ngrok_token(token):
    return not token or bool(NGROK_TOKEN_RE.match(token))


def valid_sp_host(host):
    return bool(host and SP_HOST_RE.match(host))


def clamp_int(value, default, lo, hi):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))
