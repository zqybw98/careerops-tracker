# Local Browser Capture Bridge

CareerOps includes an opt-in localhost Bridge for a separately installed
companion browser extension. The Bridge lets the extension preview reviewed
job-page fields and save a confirmed application into the same local SQLite
database used by Streamlit.

The Bridge does not scrape in the background, submit job applications, or send
CareerOps data to a cloud service.

## Start Modes

| Start method | Streamlit UI | Capture Bridge |
| --- | --- | --- |
| Double-click `start.bat` | `http://127.0.0.1:8501` | Enabled on `http://127.0.0.1:8765` |
| Manual `streamlit run app.py` | Streamlit default | Disabled |
| Hosted Streamlit demo | Hosted URL | Disabled |

`start.bat` explicitly binds Streamlit to `127.0.0.1:8501`. It also sets
`CAREEROPS_CAPTURE_ENABLED=1`, which allows the process-level Bridge singleton
to start on `127.0.0.1:8765`.

## Pair the Companion Extension

1. Start CareerOps with `start.bat`.
2. Open `More > Data & Settings > Browser Capture pairing`.
3. Open the companion extension options.
4. Grant its optional loopback permission.
5. In CareerOps, enable `Reveal pairing token`.
6. Paste the token into the extension options and confirm pairing.

The token is local authentication material. Do not paste it into chat, commit
it to Git, include it in screenshots, or reuse it for another service.

To disconnect the current extension:

1. Open `Browser Capture pairing`.
2. Confirm that you understand the current extension will be disconnected.
3. Click `Rotate pairing token`.
4. Replace the stored token in the extension before pairing again.

## API Contract

The Bridge supports API version `1` only.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Public local service identity and version check |
| `POST` | `/api/v1/pair/confirm` | Bind the first authenticated extension origin |
| `POST` | `/api/v1/applications/preview` | Validate fields and return duplicate candidates |
| `POST` | `/api/v1/applications` | Create or update a reviewed application |

Authenticated requests use:

```text
Authorization: Bearer <local pairing token>
Origin: chrome-extension://<extension id>
X-CareerOps-API-Version: 1
Content-Type: application/json
```

Application saves require a UUID v4 `client_request_id`. Retrying the same
canonical payload with the same ID returns the original result instead of
creating another application or activity event.

The server accepts only the fixed routes and reviewed application fields. It
rejects unsupported origins, unknown fields, oversized bodies, malformed URLs,
and unsafe duplicate updates.

## Privacy and Data Boundaries

- Both the Streamlit UI and Bridge bind to loopback addresses only.
- The hosted demo never starts the Bridge.
- The pairing token is stored locally and is excluded from Git and exports.
- Browser Capture writes only after the user reviews and confirms fields.
- Application, activity-event, and idempotency writes commit atomically.
- `capture_requests` is internal bookkeeping and is excluded from private CSV
  and SQL exports.
- The Bridge never uploads a CV, attaches a file, or submits an application.

The local security model protects against ordinary web pages, unpaired
extensions, LAN access, and accidental hosted deployment. It does not claim to
protect the pairing token from a malicious process running as the same Windows
user.

## Troubleshooting

### Browser Capture is disabled

Start with `start.bat`. The normal manual Streamlit command intentionally leaves
the Bridge disabled.

### Hosted demo reports Browser Capture unavailable

This is expected. Capture is local-only and has no cloud fallback.

### Another CareerOps process owns the Bridge

Close the other local CareerOps process or use that process and its pairing UI.
The new process detects the existing Bridge but does not adopt it or reveal its
token.

### Port 8765 is already in use

Close the unrelated application using that port, then restart CareerOps.
CareerOps does not fall back to a broad bind address or another port.

### Pairing-state warning on Windows

CareerOps may be unable to confirm the file's Windows DACL. The warning is
shown in the pairing UI without exposing the token or local path. Keep the
pairing file inside your Windows user profile and do not share it.

### Database is busy

The Bridge waits up to five seconds, then returns retryable HTTP `503` without
leaving a partial application, event, or idempotency row. Retry with the same
`client_request_id` after the other database operation finishes.

### Open in CareerOps does not load

CareerOps must still be running on port `8501`. If `localhost` does not resolve
to IPv4 on the machine, open `http://127.0.0.1:8501` and preserve the
`workspace=Applications&application_id=...` query parameters.

## Synthetic Local Smoke Test

Use temporary paths so a manual test cannot touch real application data:

```powershell
$smokeRoot = Join-Path $env:TEMP ("careerops-capture-smoke-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $smokeRoot | Out-Null

$env:CAREEROPS_DB_PATH = Join-Path $smokeRoot "applications.db"
$env:CAREEROPS_CAPTURE_PAIRING_PATH = Join-Path $smokeRoot "capture_pairing.json"
$env:CAREEROPS_CAPTURE_ENABLED = "1"
.\.venv\Scripts\python.exe -m streamlit run app.py `
  --server.address=127.0.0.1 `
  --server.port=8501
```

Verify health, pair with a synthetic extension context, preview one synthetic
job, save it, and retry with the same request ID. The database should contain
one application, one activity event, and one idempotency row. The returned
`open_url` should open the synthetic application once.

Stop Streamlit before deleting the unique temporary directory:

```powershell
Remove-Item -LiteralPath $smokeRoot -Recurse -Force
```
