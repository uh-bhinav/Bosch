# Mold Workstation (frontend-web)

React + TypeScript + Three.js replacement for the Streamlit UI in
`frontend/app.py`, being built incrementally per
`docs/` phase plan (F0 architecture spec → F1 shell → ...). This directory
is new and independent of `frontend/` -- the existing Streamlit app is
untouched and still runs exactly as before; nothing here replaces it yet.

**Phase F1 status**: application shell only (top bar, tool rail, persistent
viewport, contextual inspector, status strip). No real analysis calls, no
import/export, no manual override -- see `CHANGELOG.md`'s "Phase F1" entry
for the exact scope.

## Install

Requires Node.js 20+ (developed against Node 22) and npm.

```bash
cd frontend-web
npm install
```

## Run (development)

```bash
npm run dev
```

Starts the Vite dev server (default `http://localhost:5173`, or the next
free port if that one is taken). Open it in a browser.

## Connecting to the backend

The dev server proxies `/api/*` to the FastAPI backend
(`backend/api/main.py`, normally `http://localhost:8000`) so the browser
never makes a cross-origin request -- this is why `backend/api/main.py`
needed no CORS changes for F1. To point at a different backend host, set
`VITE_BACKEND_URL` before starting the dev server:

```bash
VITE_BACKEND_URL=http://localhost:9000 npm run dev
```

For a production build, set `VITE_BACKEND_URL` to the real backend origin
at build time; the app then calls it directly instead of using the dev
proxy (a production deployment will need either backend CORS headers or a
reverse proxy in front of both services -- not yet configured, out of
scope for F1).

## Build

```bash
npm run build    # type-checks (tsc -b) then produces dist/
npm run preview  # serve the production build locally
```

## Test

```bash
npm run test         # one-shot (vitest run)
npm run test:watch   # watch mode
```

## Lint

```bash
npm run lint
```

## Where things live

```
frontend-web/
  src/
    shell/            WorkstationShell -- composes the five shell regions
    components/        TopBar, ToolRail, ContextInspector, StatusStrip
    viewport/          Viewport (React) + ViewportEngine (vanilla three.js,
                        the persistence mechanism) + engineSingleton
    geometry/          meshAdapter -- the one place backend display-mesh
                        JSON becomes three.js buffers
    store/             analysisStore -- the one shared Zustand store
    api/               client (fetch boundary), endpoints, types
    domain/            shared types (ToolId, Vec3, pull-direction source, ...)
    styles/tokens.css   design tokens (CSS custom properties)
```
