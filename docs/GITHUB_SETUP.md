# GitHub Setup and CI

This project uses GitHub Actions (`.github/workflows/ci.yml`) to run tests on every push and pull request to `main`.

## Push blocked: `workflow` scope required

If `git push` fails with:

```text
refusing to allow a Personal Access Token to create or update workflow
`.github/workflows/ci.yml` without `workflow` scope
```

your Personal Access Token (PAT) cannot modify workflow files. Fix it using one of the options below.

### Option A — Update the PAT (recommended)

1. Open GitHub → **Settings** → **Developer settings** → **Personal access tokens**.
2. Edit or create a token with:
   - `repo` (full control of private repositories)
   - `workflow` (update GitHub Action workflows)
3. Update the credential in your git client:
   - **macOS Keychain / Git Credential Manager**: replace the stored token for `github.com`.
   - **CLI**: `gh auth login` and choose HTTPS with the new token.
4. Push again:

```bash
git push origin main
```

### Option B — GitHub Desktop

1. Sign out and sign back in to GitHub Desktop.
2. Push from the app — Desktop uses OAuth and includes workflow permissions.

### Option C — SSH remote

If you use SSH keys instead of HTTPS:

```bash
git remote set-url origin git@github.com:PedroCarneiroMarques/the-sql-alchemist.git
git push origin main
```

## Verify CI after push

```bash
gh run list --limit 5
gh run watch
```

Or open the **Actions** tab on GitHub and confirm the **CI** workflow is green.

## What CI runs

1. `pip install -e ".[dev]"`
2. `python -m src.health --startup` — config and dataset validation
3. `pytest tests/ -v`
4. Dataset schema check (`validate_dataset`)

## Local pre-push checklist

```bash
python -m pip install -e ".[dev]"
python -m src.health --startup
python -m pytest tests/ -q
```
