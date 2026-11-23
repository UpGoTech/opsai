# OpsAi

Frappe / ERPNext app that stores per-user AI gateway settings for [OpsAi](https://github.com/UpGoTech/opsai).

## Install

Use the **lowercase** GitHub URL. On Linux, `bench get-app` / `git clone` name the folder from the URL path, and Frappe requires that folder (and `sites/apps.txt`) to match the Python package name `opsai`.

```bash
cd ~/frappe-bench
bench get-app https://github.com/UpGoTech/opsai
bench --site <site> install-app opsai
bench --site <site> migrate
```

### Fix: `App opsai not in apps.txt` / `No module named 'OpsAi'`

That means the app was cloned as `apps/OpsAi` (mixed case). Rename with a two-step move (needed on case-insensitive mounts too), refresh the editable install, then install:

```bash
cd ~/frappe-bench/apps
# only if the folder is still OpsAi:
mv OpsAi opsai-tmp && mv opsai-tmp opsai

cd ~/frappe-bench
# ensure sites/apps.txt lists `opsai` (not OpsAi)
sed -i 's/^OpsAi$/opsai/' sites/apps.txt
grep -qx 'opsai' sites/apps.txt || echo opsai >> sites/apps.txt

bench setup requirements
bench --site <site> install-app opsai
bench --site <site> migrate
```

After install, assign the **OpsAi User** role to users who should see OpsAi on Desk (apps screen + dock utility below Search / Notifications). System Managers always have access.

## Usage

### OpsAi Users (Hermes assignment)

1. Open **OpsAi Users** in Desk.
2. **New** — choose **User** and a unique **Gateway URL** (host + port; one Hermes agent port per user). No defaults are filled in. Use **Test**, then **Save**.
3. On the saved record, open **Sign in**, enter Hermes username/password (or API key), and click **Connect**. Credentials are stored in Frappe Password fields; Connect reuses them and does not re-prompt unless Hermes rejects the saved password.
4. **Disconnect** clears the Hermes session and marks the assignment offline. Chat stays offline until Connect runs again (no silent auto-login).
5. **User** cannot be changed after create — delete the record and create settings for another user if needed.

### Chat when Hermes is offline

- Full `/opsai` and the Desk chat panel show a **Brain not connected** empty state (quote + ask an administrator for access).
- The composer is hidden and the **Chats** sidebar list is cleared until Connect succeeds.
- History returns after a successful Connect.

### Hermes workspace (Desk)

When Connected, OpsAi Users proxies live Hermes tools (model, identity/memory, config, skills, cron, sessions, logs, gateway restart) — OpsAi does not store those files locally.

## API

- `GET /api/method/opsai.api.ping` — confirms the site supports OpsAi
- `GET /api/method/opsai.api.get_my_opsai_users` — caller’s AI settings (Password fields decrypted)
- `POST /api/method/opsai.api.connect_hermes` — Connect (uses saved credentials; prefers a live session when cookies still work)
- `POST /api/method/opsai.api.disconnect_hermes` — sticky Disconnect (keeps username/password; clears session cookies)
- `GET /api/method/opsai.api.test_connection` — Hermes reachability (does not auto-login after Disconnect)
- `GET /api/method/opsai.api.boot` — chat island boot (`hermes_configured`, `hermes_connected`)

Requires a logged-in session (`sid`). Guest and cross-user access are rejected.
No settings row → OpsAi shows “This user is not permitted to use AI.”

## Bench notes (Frappe 16.60+)

OpsAi does **not** depend on Frappe Flow or Studio. Both ship inside `frappe` from 16.60 and cannot be uninstalled like a normal app. Use the steps below so upgrades and builds stay quiet on small machines.

### After upgrading Frappe / ERPNext

Re-link frontend packages that 16.60 introduced (needed once per checkout / after `bench update`):

```bash
cd ~/frappe-bench/apps/frappe/ui && yarn install
cd ~/frappe-bench/apps/erpnext/islands && yarn install
```

Without this, `bench build` fails with `Cannot find package '@framework/ui'`.

### Build without Flow / Studio Vite (recommended on low RAM)

Studio + Flow Vite builds often OOM (`exit 137`) on ~8GB boxes. Skip them:

```bash
SKIP_FRAPPE_VITE=1 bench build
```

If you later need those UIs:

```bash
cd ~/frappe-bench/apps/frappe/studio/frontend && NODE_OPTIONS='--max-old-space-size=4096' yarn build
cd ~/frappe-bench/apps/frappe/flow && yarn build
```

Stop heavy Node watchers (island `--watch`, etc.) before building Studio if memory is tight.

### Migrate without starting flow-server

Flow’s `after_migrate` may try to start a local daemon and print a yellow warning. To skip the local start:

```bash
bench set-config -g flow_server_manager supervisor
```

OpsAi does not need `flow-server`. The warning is non-fatal either way; migrate still completes.

### Soft-disable Flow for users

- Do not assign **Flow User**.
- Users without read on `Flow Session` do not get the Flow dock icon.

Do **not** delete `frappe/flow` or `frappe/studio` — that breaks core hooks and comes back on the next update.
