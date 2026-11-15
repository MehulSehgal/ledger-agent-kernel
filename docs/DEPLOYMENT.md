# Deployment

Ledger is deployed as two independent services:

```text
ledger-agent-kernel/
├── static/             # frontend: static/index.html, app.js, styles.css
├── server.py           # backend FastAPI application
├── Dockerfile          # Fly.io backend image
├── fly.toml.example    # Fly.io app configuration template
├── requirements.txt    # backend dependencies
└── vercel.json         # optional root/serverless preview only
```

## Backend: Fly.io

1. Install `flyctl` and authenticate:

   ```bash
   curl -L https://fly.io/install.sh | sh
   fly auth login
   ```

2. From the repository root, copy [`fly.toml.example`](../fly.toml.example)
   and replace `replace-with-your-fly-app-name` with a globally unique app
   name:

   ```bash
   cp fly.toml.example fly.toml
   sed -i '' 's/replace-with-your-fly-app-name/your-unique-fly-app-name/' fly.toml
   ```

   On Linux, omit the empty string after `-i`:

   ```bash
   sed -i 's/replace-with-your-fly-app-name/your-unique-fly-app-name/' fly.toml
   ```

3. Create and deploy the app:

   ```bash
   fly apps create your-unique-fly-app-name
   fly secrets set LEDGER_OFFLINE_STUB=1
   fly deploy
   ```

   The checked-in [`Dockerfile`](../Dockerfile) starts FastAPI on port `8080`
   and the Fly health check calls `/api/status`.

4. For live providers, replace the offline setting with:

   ```bash
   fly secrets set \
     BIFROST_URL="https://your-bifrost-host" \
     BIFROST_VK="your-bifrost-key" \
     TAVILY_API_KEY="your-tavily-key" \
     LEDGER_CHEAP="provider/cheap-model" \
     LEDGER_STRONG="provider/strong-model"
   ```

   Add `LEDGER_CORS_ORIGINS` after the frontend is deployed.

5. Verify the backend:

   ```bash
   fly status
   fly logs
   curl https://your-unique-fly-app-name.fly.dev/api/status
   ```

## Backend: Render (alternative)

1. Create a new **Blueprint** from this repository.
2. Keep the repository root (`.`) as the service root.
3. Render will use [`render.yaml`](../render.yaml), which installs
   `requirements.txt` and starts:

   ```text
   uvicorn server:app --host 0.0.0.0 --port $PORT
   ```

4. After the first deploy, copy the service URL, for example:
   `https://your-unique-fly-app-name.fly.dev`.
5. Set these Render environment variables:

   | Variable | Value |
   |---|---|
   | `LEDGER_CORS_ORIGINS` | Your frontend origin, such as `https://ledger.vercel.app` |
   | `LEDGER_OFFLINE_STUB` | `1` for an offline demo; remove for live providers |
   | `BIFROST_URL` | Your Bifrost base URL |
   | `BIFROST_VK` | Your Bifrost key |
   | `TAVILY_API_KEY` | Your Tavily key |

   Do not commit these values. The health check is
   `https://ledger-agent-kernel.onrender.com/api/status`.

## Frontend: Vercel

1. Create a Vercel project from the same repository.
2. Set **Root Directory** to `static`.
3. Leave the framework preset as **Other** and do not configure a build
   command.
4. Before deploying, edit [`static/runtime-config.js`](../static/runtime-config.js)
   and set:

   ```js
   window.LEDGER_API_URL = "https://ledger-agent-kernel.onrender.com";
   ```

5. Deploy and copy the resulting frontend origin into Fly's
   `LEDGER_CORS_ORIGINS`.
6. Set the origin and restart the backend:

   ```bash
   fly secrets set LEDGER_CORS_ORIGINS="https://your-app.vercel.app"
   ```

The frontend uses `LEDGER_API_URL` for status, Brief, Fix, run events,
approvals, red-team checks, and benchmark loading. It contains no provider
credentials.

## Other static hosts

The same `static/` directory can be uploaded to Netlify, Cloudflare Pages, or
any static web host. Configure the host's publish directory as `static/`, set
the backend URL in `runtime-config.js`, and add the resulting origin to
`LEDGER_CORS_ORIGINS`.

## Local split check

Run the backend from the repository root:

```bash
uvicorn server:app --reload
```

Serve the frontend separately:

```bash
python -m http.server 4173 --directory static
```

Set `window.LEDGER_API_URL = "http://127.0.0.1:8000"` in
`static/runtime-config.js`, then open `http://127.0.0.1:4173`.
