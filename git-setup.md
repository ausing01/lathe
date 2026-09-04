# Git Setup — from nothing to a working repo on the LinuxCNC machine

Goal: put the lathe project on GitHub once, then get every future change onto
the LinuxCNC machine with a single `git pull` — whether you're at home or SSH'd
in from your phone.

Assumes no git or GitHub experience. Type commands exactly as shown.

There are three stages:
1. Make a GitHub account and an empty repo (in a web browser)
2. Put the project files into that repo (from wherever you downloaded them)
3. Clone the repo onto the LinuxCNC machine, and learn the daily pull/commit loop

---

## A word on what git actually is

Git tracks versions of a folder of files. "The repo" is that tracked folder.
GitHub is a website that hosts a copy of the repo online, so multiple machines
(your PC, your phone session, the LinuxCNC box) can share the same files and
stay in sync.

The pattern you'll use forever after setup:
- I give you changed files → you `commit` and `push` them to GitHub
- On the LinuxCNC machine → you `pull` to receive them

That's it. Everything below is getting to that loop.

---

## Stage 1 — GitHub account and empty repo (web browser)

### 1a. Make an account
Go to `github.com` and sign up. Free tier is all you need. Pick a username you
don't mind being public — it becomes part of your repo's web address.

### 1b. Create the repository
1. Once logged in, click the **+** in the top-right → **New repository**
2. **Repository name:** `lathe` (or whatever you like)
3. Leave it **Public** if you're happy for the community to see it (the eventual
   goal), or **Private** for now — you can flip it later
4. **Do NOT** check "Add a README" / "Add .gitignore" / "Add a license" — the
   project already has those, and checking them here causes a conflict on the
   first push
5. Click **Create repository**

You'll land on a page showing setup instructions. Note the web address at the
top — it looks like `https://github.com/YOURNAME/lathe`. You'll need it.

### 1c. Make a Personal Access Token (the step that trips everyone up)
GitHub no longer accepts your account password on the command line. Instead you
use a **token** — a long generated string that acts as a password for git.

1. Go to `github.com/settings/tokens` (or: your avatar top-right → Settings →
   Developer settings → Personal access tokens → **Tokens (classic)**)
2. Click **Generate new token** → **Generate new token (classic)**
3. **Note:** type something like `linuxcnc machine`
4. **Expiration:** 90 days is fine, or "No expiration" if you don't want to
   redo this (less secure, but practical for a personal machine)
5. **Scopes:** check the box next to **`repo`** (this covers everything you need)
6. Scroll down, click **Generate token**
7. **COPY THE TOKEN NOW and paste it somewhere safe temporarily** (a note on
   your phone). GitHub shows it exactly once. If you lose it, you just make a
   new one — no disaster, but you can't view the old one again.

The token looks like `ghp_` followed by a long string. Treat it like a password.

---

## Stage 2 — Get the project files into the repo

You have the project files (downloaded from the chat). The cleanest way to get
them onto GitHub is to do it **from the LinuxCNC machine itself**, since that's
where they need to end up anyway. So Stage 2 and Stage 3 happen on the machine.

If the files are currently on a different device (laptop/phone), get them onto
the LinuxCNC machine first — a USB stick, or if they're on your phone, you can
transfer them into the SSH session. Simplest for now: put them in a folder in
your home directory on the LinuxCNC machine, arranged like this:

```
lathe/
├── README.md
├── LICENSE
├── .gitignore
├── contour/
│   ├── __init__.py
│   ├── model.py
│   ├── dxf_import.py
│   └── post_linuxcnc.py
└── tests/
    ├── test_part_1.dxf
    └── Finish_Turn_reference.NC
```

The folder structure matters — the four `.py` files must be inside `contour/`
or the code won't run.

---

## Stage 3 — On the LinuxCNC machine

Open a terminal (or connect from your phone via the Termux/mosh setup).

### 3a. Install git (skip if you already did this in the Termux setup)
```
sudo apt update
```
```
sudo apt install git
```

### 3b. Tell git who you are (once, ever)
Replace with your name and the email you used for GitHub.
```
git config --global user.name "Austin"
```
```
git config --global user.email "you@example.com"
```

### 3c. Make git remember your token (so you don't paste it every time)
```
git config --global credential.helper store
```
This saves the token to a file in your home directory after the first use.
Fine for a personal machine. (On a shared machine you'd skip this.)

### 3d. Turn your project folder into a repo and push it

Go into the folder where you put the files:
```
cd ~/lathe
```

Start tracking it:
```
git init
```
```
git add .
```
```
git commit -m "Initial commit: contour model, DXF import, LinuxCNC post"
```

`git add .` stages every file (the `.` means "everything here"). `git commit`
saves a snapshot with a message describing it.

Now connect it to your GitHub repo. Replace YOURNAME:
```
git remote add origin https://github.com/YOURNAME/lathe.git
```
```
git branch -M main
```
```
git push -u origin main
```

On that last command it will ask for:
- **Username:** your GitHub username
- **Password:** paste your **token** (not your GitHub password!)

Nothing appears as you paste the token — that's normal. Press Enter.

If it succeeds, refresh your repo's web page — your files are now on GitHub.
Because of `credential.helper store`, you won't be asked for the token again.

---

## The daily loop (this is what you'll actually use)

From here on, the workflow is short.

### When I give you changed or new files
Put them in the right place in `~/lathe`, then:
```
cd ~/lathe
```
```
git add .
```
```
git commit -m "short description of what changed"
```
```
git push
```
That sends your changes up to GitHub.

### To receive changes on another machine (or after editing elsewhere)
```
cd ~/lathe
```
```
git pull
```
That pulls the latest down.

### To see what you've changed but not yet committed
```
git status
```

### To clone the repo fresh onto a NEW machine
```
git clone https://github.com/YOURNAME/lathe.git
```
This creates the `lathe` folder with everything in it, correctly structured.
(Asks for username + token the first time.)

---

## How this fits your workflow

Once this is set up, our iteration loop becomes painless:
- I hand you updated code
- You drop it in `~/lathe`, then `git add . && git commit -m "..." && git push`
- Anywhere else — the shop machine, a laptop — `git pull` and you're current

And when you're ready to share with the LinuxCNC community, the repo is already
public-ready: it has the code, a README, a license, and version history. The
distribution step becomes "post the GitHub link on the forum," not a scramble
to package things.

---

## Things that will probably go wrong

| Symptom | Cause / fix |
|---|---|
| `Authentication failed` on push | You typed your GitHub *password* instead of the *token*. Use the token. |
| `remote origin already exists` | You ran `git remote add origin` twice. Skip it — it's already set. |
| `failed to push some refs` / rejected | GitHub has commits your machine doesn't (usually from checking "Add README" in step 1b). Run `git pull --rebase origin main` then push again. |
| `Permission denied` | Wrong username, or the token lacks `repo` scope. Make a new token with `repo` checked. |
| git asks for the token every single time | You skipped step 3c (`credential.helper store`), or the first push failed before it could save. |
| `nothing to commit` | No files changed since last commit — you're already up to date. Not an error. |

---

## Two cautions

1. Your token is a password. `credential.helper store` writes it to
   `~/.git-credentials` in plain text — fine on your own machine, but don't do
   this on a shared or public computer.
2. If you ever accidentally commit the token (or anything secret) into the repo
   itself, treat it as compromised: delete it on GitHub's token page and make a
   new one. The `.gitignore` in the project already excludes the usual junk.
