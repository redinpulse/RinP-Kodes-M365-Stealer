# Development

## Layout

```
kodes/
├── src/
│   ├── main.py                  entry: `python -m src.main server|client`
│   ├── client/                  implant: api, auth (+headless), tunnel, proxy, ui
│   ├── utils/config.py          shared config loader (client)
│   └── server/
│       ├── app.py               app factory, SQLite column migrations, headers
│       ├── models.py            DeviceInfo, Campaign, Target, TeamsMessages, Log
│       ├── routes/              api (device endpoint), auth, web (panel API),
│       │                        campaign (panel pages)
│       ├── services/            powershell (token minting), data (REST viewer),
│       │                        campaign, device
│       └── utils/               powershell (sessions, TokenLog parsing),
│                                security (Fernet, JWT), config, validators
├── templates/                   Jinja2 + Alpine.js panel (English)
├── build/client_build.spec      PyInstaller spec (all platforms)
├── config/                      secret.key, crypto.key (gitignored), server.json
└── database/                    kodes.db, TokenLog.log (persistent volume)
../tokentactics, ../aadinternals  vendored PS modules (read-only mounts)
```

## Key flows

- **Token acquisition**: `POST /?h=<host>&c=<token>` →
  `PowerShellService.start_token_acquisition` → pwsh `Get-AzureToken`
  session; the device code is parsed from ANSI-stripped output and returned
  to the client. On login, tokens land in `TokenLog.log`;
  `process_tokens_for_device` attributes sections, encrypts and persists
  identity + permission fields.
- **Service tokens**: `services/powershell.py::TOKEN_SERVICES` registry →
  `generate_service_token(hostname, key)`; refresh token travels base64 into
  pwsh (never interpolated raw); minted tokens land in the
  `service_tokens` JSON column, teams also mirrors to `DeviceInfo.teams_token`.
- **Data Viewer**: `services/data.py::DATA_RESOURCES` + direct REST via
  `requests`; `Fetch First N` = single page, `Fetch All` = nextLink paging
  (MAX_FULL_ITEMS 5000 / MAX_FULL_PAGES 40). 401 triggers one silent re-mint.
- **Tunnel**: client `TunnelManager` (pyngrok TCP) → SOCKS5
  (`socketserver` threads, RFC 1929 auth) → URL registered via `?url=`.

## Extending

**Add a TokenTactics service**

1. `services/powershell.py` → `TOKEN_SERVICES[key] = {'func': 'Invoke-RefreshTo…', 'label': '…'}`
   (add `'needs_spo': True` if the function requires `-spoDomain`).
2. Optional REST resources: `services/data.py` → `DATA_RESOURCES[key]`; the
   service chip appears in the Data Viewer automatically once a token exists.
3. Nothing else: the panel grid, JWT inspection and recommendations are
   registry-driven.

**Recommendations**: `recommendations_for_device()` maps scopes/roles to
service keys; extend the keyword checks there.

**DB migrations**: additive columns go into `_migrate_sqlite_columns`
(`create_all()` never alters existing tables; idempotent `ALTER TABLE`).

## Deploying to a server

```bash
rsync -az --delete \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'database/' --exclude '/config/' \
  --exclude 'aadinternals/' --exclude 'tokentactics/' \
  --exclude '.git/' --exclude '*.log' --exclude 'build/' --exclude 'dist/' \
  kodes/ user@server:/path/kodes/
docker compose up -d --build
```

> **Exclude patterns are anchored**: `/config/` protects `crypto.key` on the
> remote. A pattern like `kodes/config/` does NOT match the top-level
> `config/` and `--delete` will destroy the remote key; every stored token
> becomes undecryptable (recovery: TokenLog re-import). Keep
> `docker-compose.yaml` in sync on both sides or a full-tree rsync will
> revert `TOKEN_LOG_PATH`.

## Conventions

- Panel and all user-facing strings: **English**; no comments in source
  (docstrings only).
- All external input passes through `utils/validators.py`.
- Sensitive values Fernet-encrypted at rest; raw tokens never logged.

## References

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)
