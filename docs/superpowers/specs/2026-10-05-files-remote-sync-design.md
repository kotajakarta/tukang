# Files: Remote folder mapping (upload / download between servers)

**Date:** 2026-10-05
**Status:** Approved (concept + ignore rules agreed in chat; engine decisions below made during implementation)

## Goal

Work on a project on server A, deploy it to server B from the Files menu, the way the VS Code
SFTP extension (Natizyskunk) works: a folder on A is paired once with a folder on B, then any file or
folder inside it can be uploaded to B or downloaded from B with one click.

## Concept

- **Remote mapping** (stored in the controller DB, shared by all admins): name, local server + folder (A),
  remote server + folder (B), ignore patterns. One local folder may have several mappings (staging, prod).
- Files menu, when the current folder is inside a mapping's local folder:
  - toolbar badge `↔ <name>` with Upload / Download current folder / Edit remote;
  - item context menu: **Upload to <name>**, **Download from <name>**;
  - folder menu: **Set up remote for this folder…** (or edit the existing one).
- Transfer rules (same as Natizyskunk):
  - always **overwrite**; new files are added;
  - files that exist only on the destination are **never deleted** (`.env`, `uploads/`, logs stay safe);
  - file mode and mtime follow the source; **ownership follows the destination** (existing files keep
    their owner, new files/dirs take their parent directory's owner); setuid/setgid/sticky bits are dropped.
- Confirmation before each transfer shows file count, size and ignored count (a preview scan).

## Ignore rules

`.gitignore` syntax, one pattern per line, applied relative to the mapping root, in **both** directions:

- no `/` in the pattern → matches the name at any depth (`node_modules`, `*.log`, `.env.*.local`);
- a `/` inside the pattern (or a leading `/`) → anchored to the mapping root (`docs/*.*`);
- trailing `/` → directories only; `!` re-includes; `#` comments; `*`, `?`, `[...]`, `**` wildcards;
- an ignored directory is pruned (nothing below it is sent);
- an explicitly selected path that is ignored is skipped and reported, never sent.

Defaults: `.git`, `.vscode`, `.idea`. The mapping dialog offers to import `ignore` (and `remotePath`,
`host` to preselect the server) from `<local folder>/.vscode/sftp.json`.

## Engine

- The controller relays a tar stream: `files_agent` op `pack` on the source node writes a tar of the
  selected paths (ignore rules applied by our own matcher, not `tar --exclude`) to stdout; op `unpack`
  on the destination node reads a JSON header line then the tar stream from stdin. Nothing is buffered
  to disk on the controller; A and B never need to reach each other or hold each other's credentials.
- `unpack` treats the archive as untrusted (a compromised A must not escalate to B): member names must
  be relative without `..`; every parent directory is resolved and must stay inside the destination root
  (in-root symlinks are fine, escaping ones are refused); files are written to a temp name and renamed
  into place, so an interrupted transfer never leaves a half-written file.
- Transfers run as in-memory background jobs on the controller (single process) with polling for
  progress (`bytes relayed / estimated tar size`) and cancel. One running job per mapping.
- Every transfer is audited (`files.sync.upload` / `files.sync.download`).

## API (admin only, under `/api/v1/files`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/files/remotes` | list mappings |
| POST | `/files/remotes` | create |
| PUT / DELETE | `/files/remotes/{id}` | update / delete |
| POST | `/files/remotes/{id}/scan` | preview `{direction, paths}` → counts |
| POST | `/files/remotes/{id}/transfer` | start job → job state |
| GET | `/files/transfers/{job_id}` | job state |
| POST | `/files/transfers/{job_id}/cancel` | cancel |

`paths` are always absolute paths on the **local (A) side** inside the mapping's local folder; the
backend maps them to the remote folder.

Validation: both servers exist; folders absolute and not a protected system path (`/`, `/etc`, …);
the same server may be used only with non-overlapping folders; ≤ 500 ignore patterns.
Deleting a server deletes its mappings.

## Testing

- Ignore matcher unit tests (incl. the user's real `sftp.json` list).
- `unpack` safety: `..`, absolute names, escaping symlinks, setuid bits.
- End-to-end upload/download between two folders on the direct local node: overwrite, keep extra
  destination files, ignore pruning, explicit ignored selection, symlinks, modes.
- CRUD validation and admin-only policy.
