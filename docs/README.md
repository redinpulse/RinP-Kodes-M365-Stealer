# Kodes M365 Red Team Documentation

All documentation for the Kodes platform: Microsoft device-code phishing,
token harvesting, TokenTactics service-token minting, in-panel data
collection and SOCKS5 reverse tunneling.

## Documents

### Operator

- [Installation](INSTALLATION.md): server (local + Docker), client, Windows build
- [User Guide](USER_GUIDE.md): panel walkthrough: campaigns, devices, tokens, data viewer
- [FAQ](FAQ.md): common failures and their fixes (ngrok, AADSTS, Windows)

### Technical

- [Development](DEVELOPMENT.md): architecture, module map, how to extend
- [Security](SECURITY.md): threat model, input validation, crypto at rest
- [Flow diagram](flow-diagram.md): end-to-end sequence

## External references

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing post: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)

## Quick start

```bash
cd kodes
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.main server        # panel at http://localhost:9000
python -m src.main client -c client.json
```

See the main [README](../README.md) for the platform overview.
