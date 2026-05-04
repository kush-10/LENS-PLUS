# Phone Testing

Use this workflow to test the phone camera against the local development server.

## LAN Testing

Connect the phone and dev machine to the same Wi-Fi.

Camera access on mobile browsers generally requires HTTPS or localhost.

If you open `http://<your-dev-machine-ip>:5173`, some browsers may block `getUserMedia` and show `navigator.mediaDevices` as undefined.

Allow camera access when prompted.

In the UI, select `Phone Camera`, click `Start Source`, then `Connect`.

If camera is blocked, use `Video File (dev)` mode or enable HTTPS with mkcert.

## Local HTTPS With mkcert

Fast path for local no-Docker development:

```bash
scripts/setup-dev-https.sh
```

If IP auto-detect fails, or if you are opening the app through a Tailscale/LAN IP, pass that IP explicitly:

```bash
scripts/setup-dev-https.sh 100.119.33.58
```

For Docker Compose HTTPS paths and container cert locations, pass `docker` as the second argument:

```bash
scripts/setup-dev-https.sh 100.119.33.58 docker
```

The script installs and trusts the mkcert local CA, creates `web/certs/dev-cert.pem` and `web/certs/dev-key.pem`, updates `.env`, and sets signaling to `/api` to avoid HTTPS mixed-content errors.

For local mode, it sets `VITE_API_PROXY_TARGET=http://localhost:8000`.

For Docker mode, it sets `VITE_API_PROXY_TARGET=http://api:8000` and cert paths under `/app/certs/`.

Restart the local frontend after generating certs:

```bash
cd web
npm run dev -- --host 0.0.0.0 --port 5173
```

Keep the local API running on `http://localhost:8000`; Vite proxies `/api` to it.

Open from phone:

```text
https://<your-dev-machine-ip>:5173
```

If your phone still shows trust warnings, install and trust the mkcert local CA on the phone.

## Windows mkcert Notes

Install mkcert on Windows with Winget:

```powershell
winget install FiloSottile.mkcert
```

Or install with Chocolatey:

```powershell
choco install mkcert
```

When running the helper from Git Bash, Cygwin, or WSL, pass your LAN IP explicitly if auto-detection does not work:

```bash
scripts/setup-dev-https.sh 192.168.1.42
```

## Confirm HTTPS Is Enabled

Vite startup output should show `https://` URLs.

If it still shows `http://`, `DEV_HTTPS` vars were not loaded.

With HTTPS enabled, signaling should go to `/api/...` through the Vite proxy, not `http://localhost:8000/...`.

If Safari cannot establish a secure connection, stop and restart `npm run dev` after generating certs.

## Visual Stream Proof

Start a stream and connect from the web UI.

Copy the session id from the UI log line:

```text
Connected signaling session <session_id>
```

Or use the built-in `Debug mode` toggle in the web UI and select a session.

Verify backend frame intake through the Vite proxy:

```text
https://<your-dev-machine-ip>:5173/api/debug/sessions
```

You should see `total_frames` increasing and `has_snapshot: true`.

Open the live snapshot:

```text
https://<your-dev-machine-ip>:5173/api/debug/sessions/<session_id>/latest.jpg
```

Refresh to view updated snapshots from the incoming stream.

View persisted session dump history:

```text
https://<your-dev-machine-ip>:5173/api/debug/sessions/history
```

Each session artifact stores grouped processed frames, frame metadata JSON, optional model sidecars, and `session.json` metadata.

The artifact path is ignored by git and excluded from API Docker build context.
