# Git workflow

Production commands for this repo (`pshemach/DB_SQL_GEN`). Run them from the repository root.

Remote: `origin` → `https://github.com/pshemach/DB_SQL_GEN.git`.

| Branch | Role |
| --- | --- |
| `dev` | Integration branch for current work |
| `main` | Reviewed snapshot. Updated by merging `dev` |
| `prod` | Code the Linux host runs |
| `feature/<name>` | One change, branched from `dev` |

`fetch` downloads commits and does not touch the working tree. `pull` applies them. A pull deletes a file on disk only when that file is still tracked and the incoming commit deletes it.

Ignored local state stays put: `data/`, `.env`, `cache/`, `database/`, `vector_store/`. Those hold business definitions, API keys, and vector indexes. They are not source.

## 1. Inspect before changing anything

```bash
git status -sb
git branch -vv
git stash list
git log --oneline -15
```

Confirm local-only paths are ignored and untracked:

```bash
git check-ignore -v data .env cache database vector_store
git ls-files data .env
```

`git ls-files` must print nothing for those paths. A listed path is still tracked. The next pull can delete it, and the next push can publish it.

See ignored files that exist on disk:

```bash
git status --ignored --short -- data .env cache
```

## 2. Update a branch you are on

Fast-forward only. This refuses the pull when you have local commits, so a shared branch does not grow a surprise merge.

```bash
git fetch origin
git log --oneline HEAD..origin/dev
git diff --stat HEAD...origin/dev
git diff --name-status --diff-filter=D HEAD...origin/dev
git pull --ff-only origin dev
```

Read the `D` list before the pull. Each `D` line is a tracked file this update will remove from disk.

`git pull --ff-only` fails when the local branch has its own commits. For a personal feature branch that nobody else has checked out:

```bash
git fetch origin
git rebase origin/dev
```

For `dev`, `main`, or `prod`, merge instead of rebasing:

```bash
git fetch origin
git merge origin/dev
```

Uncommitted work, kept across the update. `-u` stashes untracked files. Ignored files such as `data/` are left on disk.

```bash
git stash push -u -m "wip before sync"
git pull --ff-only origin dev
git stash pop
```

## 3. Keep machine-local files off GitHub

Run once if a path was committed and must become local-only. `--cached` removes it from the index and leaves the files in the folder.

```bash
git rm -r --cached data
```

`.gitignore` already contains:

```gitignore
data
.env
cache
database
vector_store/
```

Commit the untrack on its own:

```bash
git add .gitignore
git commit -m "Stop tracking local data and secrets"
git push origin HEAD
```

After that commit is on the branch you pull, later syncs leave the folder alone.

Copy `data/` aside when a reviewed diff still deletes files you need.

PowerShell:

```powershell
Copy-Item -Recurse -Force data ..\data-backup
```

bash:

```bash
cp -a data ../data-backup
```

## 4. Feature branch

Start from an updated `dev`.

```bash
git switch dev
git pull --ff-only origin dev
git switch -c feature/sql-row-limit
```

Stage by path. Check the staged set before the commit. `git add .` will pick up a secret if `.gitignore` does not cover it.

```bash
git diff
git add src/agents/graph/sql_pipeline_nodes.py src/core/sql_safety.py
git diff --cached --stat
git diff --cached --name-only
git commit -m "Cap generated SELECT results at the configured row limit"
git push -u origin HEAD
```

Commit `uv.lock` in the same commit as a dependency change. Leave out `.env`, `data/`, `cache/`, `database/`, `vector_store/`, and any `*.sqlite3` index.

Open the pull request into `dev`:

```bash
gh pr create --base dev --fill
```

Review the range GitHub will merge:

```bash
git fetch origin
git diff --stat origin/dev...HEAD
git diff --name-only origin/dev...HEAD
```

On an AI change, read these diffs in full before approving:

- `src/agents/prompt/` — prompt or schema change
- `src/agents/graph/` — routing change
- `src/core/sql_safety.py` — read-only policy
- `src/config/config_management.py` — new required env var
- `uv.lock` — dependency bump

```bash
git diff origin/dev...HEAD -- src/agents/prompt src/agents/graph src/core/sql_safety.py src/config/config_management.py
```

Search the staged diff for secrets before pushing:

```bash
git diff --cached -G "API_KEY|api_key|SECRET|PASSWORD|TOKEN"
```

## 5. Promote

`dev` lands on `main` through a pull request. `prod` is what the host runs. Update `prod` only from a commit already on `main`.

```bash
git fetch origin
git log --oneline origin/prod..origin/main
git diff --stat origin/prod...origin/main
git diff --name-status --diff-filter=D origin/prod...origin/main
```

Merge with `--no-ff` so the release stays one revertible commit:

```bash
git switch prod
git pull --ff-only origin prod
git merge --no-ff origin/main -m "Release main into prod"
git push origin prod
```

## 6. Update the Linux host

On the server, from the deploy checkout. Fast-forward to `prod`. Do not reset, and do not clean ignored files.

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
git status -sb
git fetch origin
git diff --name-status --diff-filter=D HEAD..origin/prod
git pull --ff-only origin prod
sudo systemctl restart textsql-streamlit textsql-api
sudo systemctl status textsql-streamlit textsql-api --no-pager
```

Streamlit listens on `8582`. The API listens on `8688`. Confirm health after restart:

```bash
curl -fsS http://127.0.0.1:8688/health
```

A dirty server tree means the host has edits that are not in Git. Stash them and look before pulling:

```bash
git stash push -u -m "server-local before release"
git pull --ff-only origin prod
```

## 7. Restore a file a pull removed

Find the last commit that still had the path:

```bash
git log --diff-filter=D --summary -- data
git log --oneline -- data/business_definitions.yaml
```

Write it back into the working tree without staging it:

```bash
git restore --source=2c15c8c --worktree -- "data/business_definitions.yaml" "data/sales_flat sql.txt"
git check-ignore -v "data/business_definitions.yaml"
```

Replace `2c15c8c` with the parent of the delete commit. `--worktree` keeps the file unstaged, so an ignored path is not added to the next commit.

Show what that commit changed:

```bash
git show --stat 2c15c8c
```

## 8. Conflicts

See the overlap, fix the files, then continue.

```bash
git status
git diff
git add src/agents/graph/production_graph.py
git commit
```

Leave a merge you do not want:

```bash
git merge --abort
```

Leave a rebase you do not want:

```bash
git rebase --abort
```

Move the last commit back to unstaged edits. Use this only when that commit is still local and `git status` does not say the branch is ahead of origin:

```bash
git reset --soft HEAD~1
```

## 9. Commands that remove work

| Command | Effect |
| --- | --- |
| `git clean -fd` | Deletes untracked files and folders. Ignored files stay. |
| `git clean -fdx` | Deletes untracked and ignored files. This removes `data/`, `.env`, and local indexes. |
| `git reset --hard` | Drops uncommitted edits to tracked files and matches the given commit, including its deletions. |
| `git push --force` | Rewrites a remote branch. Never use it on `main`, `dev`, or `prod`. |
| `git checkout .` | Drops uncommitted edits to tracked files in the current directory. |

`git clean -fd` matches `REPO_GITHUB_UPDATE.md` for a server that should drop untracked code. On a machine that keeps local definitions and keys, omit `-x`.

## 10. History lookup

```bash
git log -S "assess_sql" --oneline -- src/core/sql_safety.py
git blame -L 36,63 src/core/sql_safety.py
git show 066cbc1 --stat
```

`-S` finds the commit that introduced or removed a string. Use it when a prompt or the SELECT guard changed and the branch history is noisy.
