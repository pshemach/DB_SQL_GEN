# Merge using Git commands

```bash
# Fetch latest branches
git fetch origin

# Switch to master
git checkout main

# Get latest master changes
git pull origin main

# Merge dev branch into master
git merge origin/dev

# Push updated master to GitHub
git push origin main
```

## After fixing the conflicts

```bash
git add .
git commit
git push origin master
```
