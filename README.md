# latent-looks

OTA look/LUT catalog for the **Latent** Android camera-color app.

The app fetches `manifest.json` + `.cube` files from this repo via GitHub
Pages — new or updated film-simulation LUTs ship to users without an
app-store update.

## Publish a new LUT

1. Drop the `.cube` file into `looks/`.
2. Add a sidecar `looks/<stem>.json` with metadata:
   `{"lookId": "...", "brand": "...", "label": "...", "version": N, "notes": "...", "minAppVersion": 12}`
   (bump `version` to trigger updates on devices).
3. `python3 build_manifest.py` — recomputes sha256/size, bumps
   `catalogVersion`, rewrites `manifest.json`.
4. Commit + push to `main`. GitHub Pages redeploys in ~1 min.

Manifest schema (formatVersion 1) is documented in the app's
`android/README.md` ("OTA look updates" section).

App endpoint: `https://jpark0926-ux.github.io/latent-looks/`
