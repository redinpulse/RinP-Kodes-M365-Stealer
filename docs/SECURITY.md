# Security Model

Kodes is an offensive platform; this document covers both its own attack
surface and the operational hygiene expected from operators.

## Authorization

- Panel access: single admin access key (`config/secret.key`), Flask session
  cookie (`HttpOnly`, `SameSite=Strict`). All panel routes are behind
  `login_required`; failed logins are rate-limited.
- Client→server endpoint has no auth by design (implant traffic); it only
  accepts strictly validated parameters (below).

## Input validation (`utils/validators.py`)

Every externally controlled value is validated at the boundary, and again
at the sink where it reaches a dangerous context:

| Input | Rule | Blocks |
|---|---|---|
| `?h=` hostname | `^[A-Za-z0-9]([A-Za-z0-9._-]{0,48})[A-Za-z0-9]$` | PowerShell injection, stored XSS via panel JS contexts |
| `?url=` tunnel | `tcp://host:port` / `tls://host:port` only | stored XSS via `writeText('…')` |
| `?base=` override | strict `http(s)://host[:port]` | reflected XSS |
| campaign / global domain | DNS regex at save **and** before every PS call (sink) | RCE via `Invoke-RefreshTo*Token -domain` |
| Data Viewer `top` | clamped 1–999 | crash + abuse |
| SharePoint host | derived + `*.sharepoint.com` regex | SSRF-ish host confusion |
| campaign name/desc | length caps | noise / storage abuse |

Tokens and hostnames that must cross into PowerShell travel **base64-encoded
and decoded inside the script**; raw values are never string-interpolated
into command lines.

## XSS posture

- Jinja autoescaping everywhere; no `|safe` on dynamic data.
- Client-side HTML builders (`displayTokenInfo`, viewer tables) escape via a
  shared `esc()` helper.
- Inline JS never interpolates stored values; copy buttons read from DOM
  element values instead.
- Security headers on every response: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.

## Crypto at rest

- All tokens (access, refresh, teams, every service token) Fernet-encrypted
  with `config/crypto.key` before storage.
- Keys have `0600` permissions and live on the persistent volume.
- Raw tokens are shown only in the operator-facing inspection modal; they are
  never written to logs.

## Known residual risks (accepted)

- Panel is single-factor (access key); restrict it to a trusted network or
  front it with a VPN/mTLS; no IP allowlist built in yet.
- Campaign token appears in client URLs (`?c=`); same trust level as the
  existing `?h=` spoofing surface; logs store only short prefixes.
- `login_required` XHR calls return the login page HTML rather than 401;
  cosmetic, no security impact.
- SQLite without FK enforcement (SQLite default); `campaign_id` is
  declarative only.

## Operational rules

- Run only against tenants with written authorization.
- Keep `crypto.key` and DB backups encrypted and access-controlled.
- Tear down after an engagement: `docker compose down --rmi all --volumes`,
  remove the deployment tree, DB, TokenLog and any key backups.
- ngrok TCP requires account verification; tunnels are visible in the ngrok
  dashboard; consider self-hosted alternatives for long engagements.

## References

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)
