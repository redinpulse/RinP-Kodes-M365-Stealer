# FAQ

## The client hangs / server returns nothing for ~3 minutes

`start_token_acquisition` runs synchronously in the request handler and waits
up to ~180 s for a device code. This is expected on first registration; the
health-check calls afterwards are fast.

## No device code is ever captured

pwsh 7 prints object tables with ANSI color codes and line wrapping. The
parser strips ANSI first and matches several `user_code` formats. If it still
fails, check `docker logs` for the raw output and extend the patterns in
`utils/powershell.py::read_output`.

## "Error decrypting refresh token"

`config/crypto.key` changed after the tokens were stored (common cause: an
rsync with a wrong `--exclude` deleted the remote key and the container
generated a new one). Recovery: tokens still exist in plaintext inside
`database/TokenLog.log`; re-run `process_tokens_for_device(hostname,
db.session)` in an app context and they are re-encrypted with the current
key. See Development → Deploying.

## Teams messages stuck at "processing" forever

A background thread died (e.g. container restart) and left a stale
`processing/pending` record. Records older than 5 minutes are detected and
the fetch is restarted automatically; click **Fetch First N** again.

## `AADSTS50020 … does not exist in tenant`

The campaign's target domain is not the victim's tenant. Set the campaign
domain (or the global domain in Settings) to the victim organization's real
domain, e.g. `corp.com`, not a third party's.

## ngrok fails with ERR_NGROK_8013

Free ngrok accounts need card verification before TCP endpoints are allowed
(not charged): <https://dashboard.ngrok.com/settings#id-verification>.
`ERR_NGROK_107` instead means the token itself is invalid; update it in
Settings.

## Windows: auto code entry never works

1. `opencv-python-headless` must be installed (it is in `requirements.txt`);
   `locateOnScreen(confidence=…)` needs OpenCV.
2. Display scaling 125 %/150 %: the client marks itself DPI-aware at startup;
   if a custom launcher drops that, screenshots won't match the template.
3. Build with `pyinstaller build/client_build.spec` from the `kodes/`
   directory so `static/img/microsoft.png` is found (source tree, bundle
   root and exe directory are all checked).

## Where do I see the raw tokens?

Device detail → Token status card (**Present — Raw**) or any service card →
**JWT** button: claims table plus the raw token with copy support.

## Data Viewer says "resource unavailable" for SharePoint

The tenant SharePoint host is derived from the campaign domain
(`corp.com → corp.sharepoint.com`). If the tenant's SP prefix differs, the
host won't resolve; use the MS Graph *SharePoint Sites* resource instead.

## Fetch All pulled fewer items than expected

Fetch All is bounded (5000 records / 40 pages) as a memory guard; the
summary bar shows a *more available* flag when it hits the cap.

## References

- AADInternals: <https://github.com/Gerenios/AADInternals>
- AADInternals phishing: <https://aadinternals.com/post/phishing/>
- TokenTactics: <https://github.com/rvrsh3ll/TokenTactics> (vendored, v0.0.2)
