# Push the latest to git

Updates this round: connectivity-based chain builder (fixes the backface),
entity-identity hook (`source_id` on every element), refreshed README, and a
new CHAINBUILDER_STATUS.md. The archive is the full project, so unpacking it
brings everything current at once.

---

## 1. Get the archive onto the machine

Move `lathe-project.tar.gz` to your home directory on the LinuxCNC machine
(same way you've moved files before). Then unpack it over your existing folder:

```
cd ~
```
```
tar -xzf lathe-project.tar.gz
```

This overwrites the code files in `~/lathe` with the latest. It does NOT touch
your `.git` folder or history - it only replaces the files inside the repo.

---

## 2. See what changed (optional, good habit)

```
cd ~/lathe
```
```
git status
```

You should see modified files (`contour/dxf_import.py`, `contour/model.py`,
`README.md`) and new untracked files (`CHAINBUILDER_STATUS.md`, and any test
files not previously committed). Nothing stray.

---

## 3. Commit and push

```
git add .
```
```
git commit -m "connectivity-based chain builder + entity-identity hook; closes end-to-end validation on all 4 parts"
```
```
git push
```

If it asks for credentials: username + your token (not your GitHub password).
It should remember from setup.

---

## 4. Confirm it worked

Refresh your repo page on GitHub - the new commit should show with the changed
files.

On the machine, confirm nothing broke in the transfer:

```
python3 contour/geom2d.py
```
Expect: `geom2d self-test: 13 passed, 0 failed`

And that all four parts still import cleanly:
```
python3 -c "from contour.dxf_import import import_dxf; from contour.model import Side; c,p=import_dxf('tests/backface.dxf',side=Side.OD); print(len(c.elements),'elems',p or 'clean')"
```
Expect: `3 elems clean`

---

## If git push is rejected

If it says the remote has commits you don't have (rare, only if you committed
from elsewhere):
```
git pull --rebase origin main
```
```
git push
```

---

## Summary

1. `cd ~ && tar -xzf lathe-project.tar.gz`
2. `cd ~/lathe && git add . && git commit -m "..." && git push`
3. `python3 contour/geom2d.py` -> 13 passed
