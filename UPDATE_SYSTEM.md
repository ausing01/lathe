# Update system - the standing procedure

Follow this every time, so updates are boring and mistakes don't creep in.

## The one rule
**Never push red.** `verify.py` is the gate. If it fails, the machine repo stays
at the last green state until the failure is fixed. A failing verify means the
update is not ready, full stop.

## Getting an update onto the machine
Every update ships as a FULL archive (`lathe-project.tar.gz`), never loose files.

1. Move the archive to the machine home dir, then unpack over the repo:
   ```
   cd ~
   tar -xzf lathe-project.tar.gz
   ```
   This replaces code files inside ~/lathe. It does not touch .git or history.

2. Run the health check FIRST, before committing:
   ```
   cd ~/lathe
   python3 verify.py
   ```

3. Branch on the result:
   - **ALL OK** -> commit and push:
     ```
     git add .
     git commit -m "<message from the update notes>"
     git push
     ```
   - **FAILURES** -> do NOT commit. The archive's accompanying notes will say
     whether the failure is KNOWN/expected (work in progress) or unexpected.
     If unexpected, stop and report it.

## Why full archives, not loose files
Placing individual files by hand is where errors enter (wrong folder, missed
file, stale copy). One archive + one unpack = the whole repo is exactly the
intended state. `verify.py` then proves the transfer worked.

## What verify.py checks
- all modules import
- geom2d self-test (13 primitives)
- all four parts chain cleanly (correct element counts, no problems)
- comp reproduces known reference numbers (arc radii, scope cutoff)

If you add parts or features, we add guards to verify.py so the smoke test grows
with the project.

## File placement reference (if ever placing by hand)
- code modules   -> ~/lathe/contour/*.py
- verify.py      -> ~/lathe/verify.py         (project root)
- status/docs    -> ~/lathe/*.md              (project root)
- test data      -> ~/lathe/tests/
