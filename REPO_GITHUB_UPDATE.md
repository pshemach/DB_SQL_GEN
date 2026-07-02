# Update Current Codebase from GitHub Branch

Use these commands from your cloned repository folder.

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
```

## 1. Check current branch and local changes

```bash
git branch
git status
```

## 2. Fetch latest changes from GitHub

```bash
git fetch origin
```

## 3. Update the current branch

Pull the latest changes from the matching GitHub branch:

```bash
git pull origin $(git branch --show-current)
```

Example, if your current branch is `dev`:

```bash
git pull origin dev
```

---

## If you have local changes and want to keep them

Save your local changes temporarily:

```bash
git stash
```

Pull latest changes:

```bash
git pull origin $(git branch --show-current)
```

Apply your saved changes back:

```bash
git stash pop
```

If conflicts appear, fix the files manually, then run:

```bash
git add .
git commit -m "Resolve merge conflicts"
```

---

## If you want to discard all local changes

Use this only if you want the server code to become exactly the same as the GitHub branch.

```bash
git fetch origin
git reset --hard origin/$(git branch --show-current)
git clean -fd
```

For the `dev` branch specifically:

```bash
git fetch origin
git reset --hard origin/dev
git clean -fd
```

---

## Notes

- `git pull` keeps your local changes if there are no conflicts.
- `git stash` is safer when you have local uncommitted changes.
- `git reset --hard` removes local modifications.
- `git clean -fd` removes untracked files and folders.
