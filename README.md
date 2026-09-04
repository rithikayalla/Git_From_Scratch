# Git Clone

An implementation from scratch of Git's core version control model in Python with content-addressable storage, a staging area, branches, and commit history, built without any external VCS libraries.

## Why this exists

I built this project to understand how Git works internally. Instead of just using Git through the CLI, I wanted to learn how objects, trees, commits, and refs work together to track changes.

## Features

| Command | Description |
|---|---|
| `init` | Initialize a new repository |
| `add <path>...` | Stage files or entire directories |
| `commit -m "<message>"` | Record a snapshot of staged changes |
| `log [-n N]` | View commit history |
| `branch [name] [-d]` | List, create, or delete branches |
| `checkout <branch> [-b]` | Switch branches, optionally creating one |
| `status` | Show staged, unstaged, untracked, and deleted files |

## How it works

All files, directory listings, and commits are stored as a **hashed, compressed object**, the same model Git uses:

- **Blob** — a file's raw contents
- **Tree** — a directory listing of `(mode, name, hash)` entries, pointing to blobs or nested trees
- **Commit** — a pointer to one tree plus its parent commit(s), forming the version history

Objects are content-addressed: each is identified by the SHA-1 hash of its type, size, and contents, compressed with `zlib` and stored under `.git/objects/<hash[:2]>/<hash[2:]>`. Branches are plain text files under `.git/refs/heads/` holding the hash of their latest commit, and `HEAD` tracks which branch is currently checked out.

```
main.py          CLI entry point (argument parsing, command dispatch)
objects.py       RepoObject, Blob, Tree, Commit
repository.py    staging, committing, branching, checkout, status
```

## Usage

```bash
python3 main.py init
python3 main.py add file.txt src/
python3 main.py commit -m "Initial commit"
python3 main.py branch feature
python3 main.py checkout feature
python3 main.py status
python3 main.py log -n 5
```

## Requirements

Python 3.7+ (uses `from __future__ import annotations`). No third-party dependencies are involved.

## Testing

The codebase is verified with static type checking and an automated test suite:

```bash
pip install mypy pytest
python3 -m mypy main.py objects.py repository.py
python3 -m pytest test_repository.py -v
```

`test_repository.py` covers staging, committing, branching, checkout isolation, and status reporting across 30 tests. See [TESTING.md](TESTING.md) for the full manual test plan and documented edge-case behaviors.

## Known limitations

This is a simplified educational model of Git, not a drop-in replacement:

- No merging, diffing, remotes, or a `.gitignore`-style ignore mechanism
- No way to untrack a file once committed (deleting it from disk doesn't remove it from history)
- `status` only detects a file as modified if it has been re-staged since the last commit


