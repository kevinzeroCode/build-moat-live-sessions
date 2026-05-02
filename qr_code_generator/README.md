# qr-code-generator — dynamic link manager

A dynamic QR Code generator with a terminal-style web UI.
Generate short links, scan analytics, soft-delete, and expiration — all through the browser.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/kevinzeroCode/build-moat-live-sessions)

---

## Features

| | |
|---|---|
| QR Code image | Generated from the short redirect URL |
| Dynamic redirect | Change the target URL without regenerating the QR |
| Soft delete | `/r/{token}` returns 410 Gone; history is preserved |
| Expiration | Token expires at a set time → 410 |
| Analytics | Total scans + daily breakdown |
| Web UI | Terminal-style frontend, no extra tools needed |

---

## Quick Start (local)

**Prerequisite:** Python 3.10+

```bash
cd qr_code_generator/scaffold

python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

Start the server:

```bash
# default port 8000
uvicorn app.main:app --reload

# if port 8000 is blocked, pick another
uvicorn app.main:app --reload --port 8001
```

Open your browser at `http://localhost:8000` (or whichever port you chose).

---

## Using the Web UI

1. Paste any URL into the input field and press **↵ generate** (or hit Enter).
2. The panel shows the generated **TOKEN**, **SHORT** link, **TARGET**, timestamps, and the QR code image.
3. Click the **SHORT** link or scan the QR code to test the redirect.
4. **analytics** — toggle scan count and daily breakdown.
5. **test redirect** — opens `/r/{token}` in a new tab so you can confirm the live redirect.
6. **delete** — soft-deletes the token. The card updates to show `DELETED yes` and the status line changes to `✗ deleted — /r/{token} returns 410`. The QR image and history are still readable.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/qr/create` | Create a new QR mapping |
| `GET` | `/r/{token}` | Redirect (302) or 410 if deleted/expired |
| `GET` | `/api/qr/{token}` | Get metadata (works even after soft-delete) |
| `PATCH` | `/api/qr/{token}` | Update target URL or expiration |
| `DELETE` | `/api/qr/{token}` | Soft-delete (sets `is_deleted = true`) |
| `GET` | `/api/qr/{token}/image` | QR code PNG |
| `GET` | `/api/qr/{token}/analytics` | Scan counts |

### Create

```bash
curl -X POST http://localhost:8000/api/qr/create \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

Response:

```json
{
  "token": "aB3xZ9k",
  "short_url": "http://localhost:8000/r/aB3xZ9k",
  "qr_code_url": "http://localhost:8000/api/qr/aB3xZ9k/image",
  "original_url": "https://example.com"
}
```

### Create with expiration

```bash
curl -X POST http://localhost:8000/api/qr/create \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "expires_at": "2026-12-31T23:59:59"}'
```

### Soft delete

```bash
curl -X DELETE http://localhost:8000/api/qr/aB3xZ9k
```

After deletion, `GET /r/aB3xZ9k` returns **410 Gone**.
`GET /api/qr/aB3xZ9k` still returns the full record with `"is_deleted": true`.

---

## Deploy to Render (free)

1. Fork or push this repo to your own GitHub account.
2. Click the **Deploy to Render** button at the top of this file.
3. Render will detect `render.yaml` and configure the service automatically.
4. After the first deploy, copy your service URL (e.g. `https://qr-code-generator.onrender.com`).
5. In Render → your service → **Environment**, add:

   ```
   BASE_URL = https://qr-code-generator.onrender.com
   ```

6. Trigger a redeploy. Short links will now use your live domain.

> **Note:** Render's free tier uses an ephemeral disk — the SQLite database resets on each redeploy.
> For persistent storage, swap SQLite for a Render PostgreSQL database (free tier available).

---

## Exercise Track (for Build Moat live sessions)

| Track | How to start |
|-------|-------------|
| **Challenge** | Read `PROMPT.md`, build from scratch (any language/framework) |
| **Guided** | Go to `scaffold/`, fill in the `TODO` blocks |

Files with TODOs:

| File | Function | Concept |
|------|----------|---------|
| `app/token_gen.py` | `generate_token()` | SHA-256 + Base62, collision handling |
| `app/url_validator.py` | `validate_url()` | URL normalization, blocklist |
| `app/routes.py` | `redirect()` | Cache → DB → 404/410 fallback |

Verify your implementation with the curl tests at the bottom of `PROMPT.md`.
