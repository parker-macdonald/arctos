# Arctos Dioxus Frontend

SPA for Arctos. Backend is Flask; this app talks to `/_api/*` (same origin). SPA is served at `/app/`.

## Build (production)

```bash
cargo install dioxus-cli
cd frontend
dx build
```

Output goes to `frontend/dist/`. Flask serves that at `/app/`.

## Dev (with hot reload)

With Flask on port 5006 and dx serve on 8080:

1. Start Flask: `python run_app.py` (or `flask run --port 5006`).
2. Build the frontend with the API base baked in, then serve:
   ```bash
   ARCTOS_API_BASE=http://127.0.0.1:5006 dx serve
   ```
   Or build once and run: `ARCTOS_API_BASE=http://127.0.0.1:5006 cargo build --target wasm32-unknown-unknown` then `dx serve`.

3. Open the URL dx prints (e.g. http://localhost:8080). The app will call `http://127.0.0.1:5006/_api/*`.

If you don't set `ARCTOS_API_BASE`, the app infers the API from the page origin: when the page is on `localhost` or `127.0.0.1` (e.g. http://localhost:8080), it uses the same host with port 5006 (http://localhost:5006). If that still doesn't work (e.g. requests stay on 8080), use the env var when building.

### "CORS request did not succeed" / Status code (null)

That means the browser **never got an HTTP response**—the request failed before CORS headers were sent. Common causes:

- **Protocol mismatch**  
  The app is calling **http**://127.0.0.1:5006 but Flask is serving **https**. Nothing listens on http:5006, so the connection fails and you see status (null).
  - **Fix (recommended for dev):** Run Flask over **http** on 5006 so the URL matches:
    ```bash
    ARCTOS_PORT=5006 python run_app.py
    ```
    Then build/serve the frontend with `ARCTOS_API_BASE=http://127.0.0.1:5006`.
  - **If you must use https for Flask:** Build with `ARCTOS_API_BASE=https://127.0.0.1:5006`. Open https://127.0.0.1:5006 in a tab and accept the self-signed certificate so the browser allows the API requests.

- **Flask not reachable**  
  Confirm the API responds: `curl -i http://127.0.0.1:5006/_api/tournaments` (or https if you use it). If that fails, start Flask and fix port/host.

## Build WASM only (no dx)

```bash
cargo build --target wasm32-unknown-unknown
```

Then use wasm-bindgen or dx to generate `dist/`. For full `dist/` use `dx build`.
