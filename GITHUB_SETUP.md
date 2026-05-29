# Push "Minerva Indian Stock Screener" to GitHub — one-time setup

Run these from your **Mac**, in the project folder. GitHub repo names can't contain
spaces, so we'll name the repo **`minerva-indian-stock-screener`** (you can set the
pretty display name later in repo Settings).

```bash
cd ~/Claude/minervini-stock-screener-india
```

---

## Step 0 — Start with a clean git repo

A partial git repo was created on the sandbox side and its index is stuck. Remove it
and start fresh natively on your Mac (this is safe — it only resets version history,
not your files):

```bash
rm -rf .git
git init
```

---

## Step 1 — Confirm what will be committed

```bash
git add -A
git status
```

**Should be tracked (✓):**
`sepa_screener_india.py`, `build_universe_india.py`, `build_dashboard_india.py`,
`test_data_india.py`, `run_screener_india.sh`, `run_screener_india.bat`,
`com.eswar.sepa-screener-india.plist`, `config.example.india.json`, `tickers_india.txt`,
`sepa_audit_history.json`, `sepa_screen_volume_history.json`, `README.md`,
`GITHUB_SETUP.md`, `.gitignore`

**Should be ignored (✗ — not listed):**
`config.json` (your local settings), `sepa_data_india_latest.json`,
`sepa_vcp_india_watchlist.html`, `fundamentals_cache.json`, `prices_cache/`,
`venv/`, `__pycache__/`, `*.log`

If anything looks wrong, edit `.gitignore` and re-run `git add -A`.

---

## Step 2 — First commit

```bash
git config user.email "eswar.perla@wheelseye.com"
git config user.name "Eswar Perla"
git commit -m "Initial commit: Minerva India SEPA-VCP screener (NSE), config-driven, with dashboard + scheduler"
```

---

## Step 3 — Create the GitHub repo and push

### Option A — GitHub CLI (easiest: creates the repo and pushes in one command)

If you have the `gh` CLI (`brew install gh` if not):

```bash
gh auth login          # once, follow the browser prompt
gh repo create minerva-indian-stock-screener --public --source=. --remote=origin --push
```

That's it — a public repo is created under your account and the code is pushed.
(Swap `--public` for `--private` if you ever change your mind.)

### Option B — Web UI + git

1. Go to https://github.com/new
2. **Repository name:** `minerva-indian-stock-screener`
3. **Visibility:** **Public**
4. **Do NOT** add a README, .gitignore, or license (we already have them)
5. Click **Create repository**, then run (replace `YOUR_USERNAME`):

```bash
git remote add origin https://github.com/YOUR_USERNAME/minerva-indian-stock-screener.git
git branch -M main
git push -u origin main
```

If prompted for a password, use a **Personal Access Token** (GitHub → Settings →
Developer settings → Personal access tokens), not your account password.

---

## Step 4 — Day-to-day updates

After tweaking config or code:

```bash
git add -A
git commit -m "describe what changed"
git push
```

---

## Cloning to another machine later

```bash
git clone https://github.com/YOUR_USERNAME/minerva-indian-stock-screener.git
cd minerva-indian-stock-screener
cp config.example.india.json config.json     # recreate your local config
python3 build_universe_india.py               # refresh the Nifty 500 list
./run_screener_india.sh                        # first run builds the venv
```

> Your personal `config.json` is intentionally **not** in the repo. The committed
> `config.example.india.json` is the template — copy it to `config.json` on each machine.
