# Running the B3 editor against hatd

1. Build the editor (Node 24 via nvm): `cd editor/packages/scratch-gui && npm run build:dev`
2. Config `.superpowers/dev/config.toml`: pin, `data_dir`, `static_dir = <repo>/editor/packages/scratch-gui/build`
3. `cd hatd && .venv/bin/python -m b3hatd --config ../.superpowers/dev/config.toml --sim`
   Other simulated devices: `--sim-devices "A=8,B=64,C=34,D=35"` (Light, 3×3 matrix, WeDo tilt,
   WeDo motion; type ids in `b3hatd/devices.py`). With `--sim` sounds are accepted and cached but
   not played (no `aplay` needed).
4. Open http://localhost:8080, enter the PIN, Take control, Run.
5. End-to-end test: `B3_URL=http://localhost:8080 npx playwright test -c test/b3-e2e/playwright.config.mjs` (in scratch-gui)
6. Production build (what a release ships): `cd editor/packages/scratch-gui && npm run build:b3` →
   `build-b3/` (99 MB; rebuild scratch-vm first with `NODE_ENV=production npm run build --workspace=packages/scratch-vm`
   from `editor/`, because scratch-gui uses its `dist/`). End-to-end test against it:
   `PYTHON=hatd/.venv/bin/python ci/e2e.sh` from the repository root (hatd --sim on port 8090).
