# bitwarden-vaultwarden-sync
## Design Specification v1.0 — As-Built

**Author:** T. Philip — <https://github.com/t-philip>
**Date:** 5 August 2026
**Status:** Written from the shipped code. This document describes what the tool
actually does, including where it falls short.
**Licence:** GPL-3.0, same as the code.

---

## 0. How to read this document

This is a design document, not a tutorial. [README.md](../README.md) tells you how to
*run* the tool; this explains how it is *built* and why each decision was made the way
it was. If you are evaluating whether to trust a program that holds both your
Bitwarden.com master password and your Vaultwarden one, §2 (threat model) and §8
(failure modes) are the sections that matter.

**Provenance.** No formal specification existed before implementation — this document
was written by reading the shipped source, so there is no "planned vs built" deviation
table to publish. What replaces it is §9, which states plainly which behaviour is
covered by an automated test and which is not, and §10, which lists the gaps found
while writing this up and **not** fixed.

Where this document says **MUST**, the requirement is load-bearing: violating it risks
vault data loss or credential exposure.

---

## 1. Purpose and scope

### 1.1 The problem

Bitwarden.com is the system of record. A self-hosted Vaultwarden instance is wanted as
an independent, locally-controlled replica — so that a Bitwarden.com outage, account
lockout, or subscription lapse does not put the vault out of reach. Bitwarden offers no
first-party server-to-server replication, so the copy has to be driven from outside by
something that can talk to both.

### 1.2 In scope

- One-way replication: Bitwarden.com (source) → Vaultwarden (destination).
- Personal-vault items, folders, and **attachments**.
- A GPG-encrypted snapshot of every export, with time-based retention.
- A safety audit that refuses to run when the destination has content the source
  cannot account for.
- Unattended scheduled operation, with a failure alert.

### 1.3 Out of scope

- **Bidirectional sync.** The direction is fixed and the destination is treated as
  disposable. See §3.1 for why this is the whole basis of the design.
- **Organisation / collection items.** `export.py` skips any item with an
  `organizationId`. Personal vaults only.
- **Conflict resolution.** There are no conflicts to resolve, by construction — the
  destination is replaced, not merged.
- **Sends, emergency access, password history.** Whatever `bw export --format json`
  omits, this tool omits.

### 1.4 Non-goal: being a backup tool

The GPG archives (§6) exist so that a failed run is recoverable, not as a backup
product. They are snapshots of the **source export** — see §6.2 for the consequence,
which is easy to get wrong.

---

## 2. Threat model

The tool holds, simultaneously: two master passwords, two API key pairs, a decrypted
copy of the entire source vault, and a backup passphrase. That concentration is the
central design problem, and most decisions below exist to bound it.

### 2.1 Assumed trusted

- **The host it runs on.** A compromise of the host is a total compromise. Nothing here
  defends against an attacker who is already root, or who is the same user the sync runs
  as.
- **The `bw` CLI**, Bitwarden.com, and the Vaultwarden instance. Vulnerabilities in
  those belong to their own projects (this is also [SECURITY.md](../SECURITY.md)'s
  stated scope).
- **The private network** the Vaultwarden instance sits on.

### 2.2 Defended against

| Threat | Mitigation | Where |
|---|---|---|
| Plaintext vault written to persistent storage | `TEMP_DIR` defaults to `/dev/shm` (tmpfs); the whole tree is removed in a `finally` block | §5.1, `sync.py` |
| Secrets visible in the process table | Every credential is passed to `bw` through the environment, never as an argv element | §4.4 |
| Secrets in log output | Log lines carry no credential; `_run()` additionally filters argv tokens containing `password` | §4.4 |
| Backups readable if the backup directory leaks | GPG symmetric AES-256, passphrase never on disk | §6.1 |
| Silent destruction of un-replicated destination data | Destination-only audit aborts the run before the wipe | §7 |
| A scheduled sync failing unnoticed | Telegram alert on failure and on abort; non-zero exit for the scheduler | §8.3 |

### 2.3 Explicitly **not** defended against

Stated plainly because a credential tool that overstates its protections is worse than
one that does not claim them:

- **A same-user process reading `/proc/<pid>/environ`.** Environment variables keep
  secrets out of `ps` output, which is world-readable; they do not hide them from a
  process running as the same user. This is a real limit of the approach in §4.4, not a
  gap that env vars close.
- **Memory disclosure.** Master passwords and the decrypted vault are ordinary Python
  strings and `bw` process memory. Nothing is locked, zeroed, or protected from a core
  dump or swap.
- **A hostile Vaultwarden server.** The destination master password hash is computed and
  sent to whatever `BW_DEST_URL` points at (§5.4). Point it somewhere you control.
- **Retention of the passphrase.** `BACKUP_GPG_PASSPHRASE` sits in `.env` in plaintext
  alongside both master passwords. The file's permissions are the only thing protecting
  any of it; the tool does not manage them.

---

## 3. Core design decisions

### 3.1 Wipe-and-restore, not differential merge

**Decision.** Every run deletes the entire destination vault and re-imports the source
export in full.

**Why.** A differential sync needs stable identity across the two servers, and there is
none: Bitwarden.com and Vaultwarden assign their own item IDs, so the *same* item has
different IDs on each side even immediately after a successful copy. Any diffing logic
would therefore have to match on mutable content — name, folder, username — and then
decide what an edit on both sides means. That is a conflict-resolution problem, and
getting it wrong in a password vault means either a silently lost credential or a
silently resurrected one.

Full replacement removes the question. The destination is defined as *"whatever the
source contained at the last successful run"* — a definition that is always true after
a run and never requires a merge rule.

**What it costs.** Three things, all accepted deliberately:

1. A window where the destination is empty (§8.1).
2. Item IDs on the destination change on every run, so anything referencing a
   Vaultwarden item ID externally will break. Nothing here does.
3. Genuine destination-only edits are destroyed. §7 exists specifically to detect that
   case and refuse rather than proceed.

### 3.2 Matching on `(item_name, folder_name)`

**Decision.** Wherever the two vaults must be compared or joined — the audit (§7) and
attachment re-upload (§5.5) — the key is the tuple `(item name, folder name)`.

**Why.** It is the only key that survives the ID rewrite described above. Folder is part
of the key rather than name alone, because the same name in two folders is a normal,
deliberate arrangement ("Router" under *Home* and under *Office"*), and collapsing them
would make the audit blind to a real orphan. `test_folder_disambiguates_same_name_different_folder`
pins this.

**What it costs.** Two items with the *same* name in the *same* folder are
indistinguishable. The audit tolerates this (it compares sets, so a duplicate is simply
present or absent), but attachment restore cannot: `restore.py` keeps the first ID seen
for a given key, so both items' attachments land on one of them. This is documented in
the README's limitations and is unfixable without a stable ID.

### 3.3 Two wipe methods rather than one

`VW_WIPE_METHOD=cli` deletes items one at a time through the `bw` CLI. It works
everywhere and is the default. Its cost is linear: a vault of several hundred items is
several hundred round trips.

`VW_WIPE_METHOD=api` issues a single `POST /api/ciphers/purge` and finishes instantly
regardless of vault size — but the endpoint requires a master password hash, which means
the tool must reproduce Bitwarden's client-side KDF (§5.4). That is only implemented for
PBKDF2; an Argon2 destination raises `NotImplementedError` with an explicit instruction
to switch to `cli`, rather than failing obscurely.

**Why both exist.** The fast path needs a credential the slow path does not (the
destination *email*, to salt the KDF) and makes an assumption the slow path does not
(the KDF type). Making the safe, universal method the default and the fast one opt-in
puts the burden of the extra assumption on the person who chose to take it on.

### 3.4 Persistent CLI application-data directory

**Decision.** `APPDATA_DIR` is a persistent on-disk path, deliberately *outside*
`TEMP_DIR`, and is not wiped between runs.

**Why.** This was a bug fix, and the reasoning is preserved in a comment in `sync.py`.
The `bw` CLI stores its device identifier in its application-data directory. When that
directory lived under the temp tree, it was destroyed with everything else at the end of
every run — so each nightly sync logged in as a brand-new device, and Bitwarden.com
correctly sent a "new device logged in" security email every single day. The fix is to
persist exactly the CLI's own identity and nothing else.

**Why that is not a security regression.** `logout()` runs in the `finally` block of
every run, success or failure, and clears account and session state from the directory.
What survives between runs is the device ID and the last-configured server URL — no
vault data, no session key. The directory is created `0o700` and `chmod`ed again on
every login, because `mkdir(mode=...)` is subject to the process umask and cannot be
relied on alone.

**A second-order consequence, handled.** Because the directory persists, a run that
crashed after `login()` but before `logout()` leaves it in a logged-in state — and
`bw login` refuses to log in twice. `BwSession.login()` therefore issues a
best-effort `logout` *before* every login, swallowing the error that occurs when there
was nothing to log out of.

### 3.5 Isolated session per vault

Source and destination each get their own `BwSession` with its own
`BITWARDENCLI_APPDATA_DIR` (`src-appdata`, `dst-appdata`). The `bw` CLI is a
single-account tool with global state; without isolation, configuring the server URL for
one vault would reconfigure it for the other. Two directories make two concurrent
logins possible in one process.

---

## 4. Component architecture

### 4.1 Module map

| Module | Lines | Responsibility |
|---|---|---|
| `sync.py` | 211 | Entry point, argument parsing, and the entire run sequence |
| `bwsync/config.py` | 96 | Environment → `Config` dataclass, with validation |
| `bwsync/session.py` | 128 | `bw` CLI wrapper: login, unlock, logout, JSON commands |
| `bwsync/export.py` | 98 | Source vault export + attachment download |
| `bwsync/audit.py` | 114 | Destination-only comparison and rename-tolerance state |
| `bwsync/backup.py` | 53 | GPG encryption and retention pruning |
| `bwsync/wipe.py` | 119 | Both destination wipe methods |
| `bwsync/restore.py` | 91 | Vault import + attachment re-upload |
| `bwsync/notify.py` | 50 | Telegram alerts |
| `bwsync/log.py` | 12 | Logging setup |

The orchestration is deliberately all in `sync.py` and linear top to bottom. Each module
is a step that takes explicit inputs and returns a result dataclass; none of them call
each other. A reader auditing "what does this program do to my vault, in what order"
reads one file.

### 4.2 Run sequence

```
parse args → load .env → Config.from_env() → validate()
    ↓
create TEMP_DIR (tmpfs) and APPDATA_DIR (persistent, 0700)
    ↓
source: login → unlock          destination: login → unlock
    ↓
export source vault  ──────────────→  vault.json + attachments/   [tmpfs]
    ↓
if BACKUP_ENABLED:  GPG-encrypt vault.json → BACKUP_DIR, prune old
    ↓
audit: compare export against live destination
    ├── destination-only items, not explained  →  ALERT + exit 1   [no changes made]
    └── explained by last sync's key set       →  log, continue
    ↓
if --dry-run:  report and return               [nothing below this line runs]
    ↓
wipe destination  (cli or api)
    ↓
restore: bw import  →  bw sync  →  re-upload each attachment
    ↓
persist this run's source keys → last_synced_keys.json
    ↓
finally:  logout both sessions, rmtree(TEMP_DIR)
```

The ordering is a safety property, not a convenience. Export precedes backup precedes
audit precedes wipe: at the moment the destination is first modified, a verified export
and an encrypted copy of it already exist, and the audit has already had its chance to
abort.

### 4.3 Result dataclasses

`ExportResult`, `AuditResult`, `RestoreResult` carry step outcomes rather than having
steps mutate shared state or log-and-forget. This is what allows the audit to be a pure
comparison over an already-materialised export — which in turn is what makes it unit
testable without a live vault (§9).

### 4.4 Secret handling in subprocess calls

Every `bw` invocation goes through `BwSession._run()`, which:

- passes credentials via `extra_env`, never as argv — API key as `BW_CLIENTID` /
  `BW_CLIENTSECRET`, session key as `BW_SESSION`;
- unlocks with `bw unlock --passwordenv <VAR>`, so even the *name* of the variable is
  what appears on the command line, not the password;
- filters any argv token containing `password` out of the debug log.

The log filter is belt-and-braces: because of the two rules above, no secret is ever an
argv element in the first place, so there is nothing for it to catch. It is kept as a
guard against a future call that forgets. See §2.3 for what the environment approach
does **not** protect against.

---

## 5. Data flow detail

### 5.1 Export

`bw export --format json` produces a **fully decrypted** vault file. This is the most
sensitive artefact the tool creates, and it dictates the `TEMP_DIR` design: the default
`/dev/shm/bw-sync` is tmpfs, so the plaintext never reaches persistent storage, and the
whole tree is removed in `sync.py`'s `finally` block.

### 5.2 Attachment download

Attachments are not included in `bw export`. They must be enumerated per item and
fetched individually, so `export.py` walks every item, skips organisation-owned ones,
and downloads each attachment to `attachments/<folder>/<item>/<filename>`.

Path components pass through `_safe_name()`, which whitelists
`[A-Za-z0-9 -_.()]`, replaces everything else with `_`, truncates to 64 characters, and
falls back to `_` for an empty result. A whitelist rather than a blacklist is the right
shape here: vault item names are arbitrary user text and will contain `/`, `..`, control
characters and non-ASCII, any of which could otherwise escape the intended directory.

### 5.3 Backup

Immediately after export, `vault.json` is encrypted with
`gpg --symmetric --cipher-algo AES256` to `BACKUP_DIR/vault-YYYYMMDD-HHMMSS.json.gpg`.
`prune_backups()` then deletes archives whose filename timestamp is older than
`BACKUP_RETENTION_DAYS`, parsing the timestamp back out of the name and ignoring
anything that does not match — so an unrelated file in the backup directory is never
deleted.

### 5.4 Wipe — the `api` path in detail

The purge endpoint requires a master password hash, computed the way a Bitwarden client
computes it:

1. `POST /api/accounts/prelogin` with the destination email returns the KDF type and
   iteration count. A non-zero `kdf` (Argon2) raises `NotImplementedError` here.
2. `master_key = PBKDF2-SHA256(password, salt=email.lower(), iterations)`.
3. `master_password_hash = base64(PBKDF2-SHA256(master_key, salt=password, 1))`.
4. `POST /identity/connect/token` with the API key yields an access token.
5. `POST /api/ciphers/purge` with the hash and bearer token.

Step 3's single-iteration second pass is not an oversight — it is Bitwarden's
specification. The value sent to the server is deliberately *not* the key that decrypts
the vault; the server can verify it without ever being able to derive the vault key.

### 5.5 Restore

`bw import bitwardenjson` restores items and folders in one call. Attachments then need
a second pass, because import does not carry them:

1. `bw sync` — without this the CLI's local cache does not contain the items just
   imported, and every subsequent lookup fails.
2. Build `(item_name, new_folder_id) → item_id` from the destination's *post-import*
   state. The folder IDs are new, so the source folder ID recorded at export time is
   translated back through the folder **name**.
3. `bw create attachment` per file.

Each attachment failure is caught, recorded in `RestoreResult.attachment_failures`, and
reported at the end. One unmatched attachment does not abort a sync that has otherwise
restored the whole vault — but it is never silent.

---

## 6. Backup design

### 6.1 Symmetric GPG, not asymmetric

Symmetric AES-256 with a passphrase, rather than a public/private keypair. The
restoring party is the same person as the backing-up party, and a keypair would add key
management — generation, storage, expiry, revocation — protecting against nothing extra
in that scenario. The passphrase comes from the environment and is never written to
disk by this tool.

### 6.2 What the backup actually contains — read this before relying on it

**The archive is a snapshot of the source export, not of the destination as it stood
before the wipe.**

This is the correct choice for the failure that actually matters: if the run dies
between wipe and restore, the archive holds exactly the data the destination should have
received, and re-running restores it. The source is the system of record, so a copy of
the source is what recovery needs.

But it means there is **no snapshot of pre-wipe destination state**. If the destination
had diverged, that divergence is not recoverable from these archives. §7's audit is the
control for that risk — it stops the run before the wipe rather than backing the
divergence up.

### 6.3 `--dry-run` still writes a backup

The dry-run early-return sits *after* the backup step. This is intentional and worth
knowing: `python sync.py --dry-run` is a safe, complete way to take an encrypted vault
snapshot without touching the destination at all.

---

## 7. The destination-only audit

The single most important safety mechanism in the tool.

### 7.1 What it does

Before the wipe, every item in the live destination is checked against the source
export by `(name, folder)`. Anything present in the destination and absent from the
source is *destination-only* — data the imminent wipe would destroy and the restore
would not put back.

If any remain unexplained, the run aborts with exit 1, sends a Telegram alert listing
them, and **makes no changes**. The user resolves it by hand.

### 7.2 Why a naive version of this is unusable

An exact "any destination-only item aborts" rule breaks on ordinary use. Rename an item
at the source, and the next run sees the old name in the destination — put there by the
previous successful sync — as an orphan, and aborts. Delete an item at the source: same.
Routine edits therefore cause routine manual aborts, and a safety mechanism that fires
on routine actions is one that gets disabled.

### 7.3 The rename tolerance, and why it is still safe

`last_synced_keys.json` records the key set the **last successful sync actually
restored**. Because the destination is wiped and rebuilt from the source every run, the
only thing that should be in it immediately before this run is exactly that set.

So a destination-only item is tolerated **only** if it appears in that recorded set —
positive proof that *this tool* put that exact key there, and that the source has since
renamed or deleted it. An item that was never part of any run the tool performed was
added out of band, is a genuine anomaly, and still aborts. Tolerance requires evidence;
it is never assumed.

Two properties keep the failure direction safe:

- **The file is only written after a real wipe-and-restore succeeds.** At that instant
  the destination provably equals the source, which is the entire basis of the
  comparison next time. A dry run does not write it.
- **Missing or corrupt file → empty set → every destination-only item aborts.** The
  degraded mode is the strict original behaviour, so losing the state file costs a
  manual review, never a silent deletion. `test_load_corrupt_file_returns_empty_set`
  pins this.

---

## 8. Failure modes

### 8.1 The wipe/restore window

Between `wipe_vault()` and the end of `restore_vault()` the destination is empty or
partial. A crash, power loss, or network failure in that window leaves it that way.

**Why this is acceptable:** the destination is a replica, never the system of record.
The source is untouched, and an encrypted copy of exactly what should be there was
written minutes earlier (§6.2). Recovery is to re-run.

**Why it is not made transactional:** neither the `bw` CLI nor the Vaultwarden API
offers a transaction across a purge and an import. The alternatives — import-then-delete
with per-item reconciliation — reintroduce the identity problem §3.1 exists to avoid,
and would make the failure mode *duplicates in a password vault* rather than *an empty
replica*. An empty replica is the better failure.

### 8.2 Enumerated failures

| # | Failure | Behaviour | Consequence |
|---|---|---|---|
| F1 | Missing/invalid config | `validate()` fails before any login | Clean exit 1, nothing touched |
| F2 | Source login or unlock fails | Exception → alert → exit 1 | Destination never contacted |
| F3 | Destination login fails | Exception → alert → exit 1 | Export not yet started |
| F4 | Export fails | Exception → alert → exit 1 | No wipe; tmpfs cleaned |
| F5 | GPG missing or backup fails | `RuntimeError` → alert → exit 1 | **Wipe never reached** — backup failure is fatal by design |
| F6 | Unexplained destination-only items | Alert with item list → exit 1 | No wipe; manual resolution |
| F7 | Argon2 destination with `api` wipe | `NotImplementedError` naming the fix | No partial wipe |
| F8 | Crash between wipe and restore | Destination left empty | §8.1; re-run recovers |
| F9 | Attachment has no matching item | Logged, collected, reported | Sync completes; that attachment is missing |
| F10 | Attachment upload fails | Same as F9 | Same |
| F11 | Telegram unreachable | Warning only | Never masks or replaces the real error |
| F12 | Temp cleanup fails | Swallowed silently | **Plaintext export may survive the run** — see §10.4 |

F5 is worth calling out: a failed backup stops the run *before* anything is destroyed,
rather than proceeding unprotected. That is the intended priority.

### 8.3 Alerting

Telegram alerts fire on two events only: an unexplained-orphan abort, and an unhandled
failure. Both are conditions where a human must act. Successful runs are silent, because
a notification that arrives nightly whether or not anything is wrong stops being read.
Alerts are entirely optional — blank token or chat ID disables them — and a failure to
deliver one never changes the exit code.

---

## 9. Verification status

**Stated honestly, because "implemented" is not "verified".**

### 9.1 Covered by automated tests

21 tests, all passing (`pytest tests/ -q`, Python 3.13.13, 0.58 s). They cover the two
areas where a logic error would be silent and costly:

- **Audit and rename tolerance** (`test_audit_rename_tolerance.py`, 11 tests) — matching
  vaults, orphan detection, tolerance of a recorded rename, a genuine orphan still
  aborting *alongside* a tolerated one, folder disambiguation, and state
  load/save/corruption behaviour.
- **Matching helpers** (`test_matching.py`, 10 tests) — folder-name resolution and
  `_safe_name()` sanitisation, including path separators, angle brackets, empty input
  and truncation.

Both suites use fakes (`SimpleNamespace`) rather than a live vault, which is possible
only because `audit_vaults()` is a pure function over an already-written export file
(§4.3).

### 9.2 **Not** covered by any automated test

No test exercises: `session.py` (login/unlock/logout), `export.py`'s vault export or
attachment download, `wipe.py` (**neither** method — including the KDF computation in
§5.4), `restore.py`'s import and re-upload path, `backup.py`'s GPG invocation or
pruning, `notify.py`, or `config.py`'s validation. That is the majority of the modules
and every part that talks to a real server or destroys data.

The reason is structural, not neglect: these are thin wrappers over an external binary
and two live HTTPS servers, and a meaningful test needs a real Vaultwarden instance and
a real Bitwarden.com account. There is no integration harness in this repository.

### 9.3 Verified by hand

The tool has run against a live Bitwarden.com account and a self-hosted Vaultwarden
instance, including attachments, on a scheduled timer over an extended period. The
persistent-`APPDATA_DIR` fix (§3.4) is confirmed by absence: the daily "new device"
emails stopped.

What has **not** been deliberately exercised: the `api` wipe path against Argon2 (only
the guard is reasoned, not run), recovery from a crash inside the wipe/restore window
(§8.1), and restore behaviour with duplicate item names in one folder (§3.2).

Treat §9.2 and this paragraph as the honest state. Nothing in this repository proves
those paths work; they are reasoned, not demonstrated.

---

## 10. Known gaps — found while writing this document, not fixed

### 10.1 `BW_DEST_TLS_VERIFY` is only half-applied

`config.py` reads `BW_DEST_TLS_VERIFY`, but it is consumed only by `wipe.py`, so it
affects **only** the `api` wipe path. Every other destination operation goes through the
`bw` CLI, which does its own TLS validation and is unaffected by this setting. Setting
it to `false` therefore does **not** make the tool work against a self-signed
certificate — the CLI calls still fail, and they need `NODE_EXTRA_CA_CERTS` instead.

Until this document was written the variable was also absent from both the README
configuration table and `.env.example`, so a user with a self-signed certificate had no
way to discover it at all. The README now documents it, with the caveat above. The
underlying half-application is **not** fixed: making the setting mean what its name
implies requires plumbing a CA bundle through to every `bw` invocation in
`session.py`.

### 10.2 `items_restored` is assumed, not confirmed

`restore.py` sets `result.items_restored = export.item_count` immediately after
`bw import` returns, without querying the destination. The closing "Sync complete — N
item(s)" line therefore reports what was **sent**, not what the destination confirms it
holds. A partial import that still exits zero would be reported as a full success. A
post-restore count would be one extra `bw list items` call.

### 10.3 No post-restore verification pass

More generally, the run ends at the moment of writing. Nothing re-reads the destination
to confirm it now matches the source — even though `audit_vaults()` is exactly the
function that could do it, and running it a second time after restore would turn "we
sent the data" into "we verified the data arrived".

### 10.4 Temp cleanup failure is silent

`shutil.rmtree(tmp)` is wrapped in a bare `except Exception: pass`. If cleanup fails,
the **decrypted vault export survives** with no warning in the log. The suppression is
correct in intent — cleanup must not mask a real error — but it should log a warning at
minimum. This is the one gap here with a direct security consequence.

### 10.5 `datetime.utcnow()` is deprecated

`backup.py` uses `datetime.utcnow()`, which raises a `DeprecationWarning` on Python 3.12+
and is scheduled for removal. Confirmed on Python 3.13.13. Backup filenames and
retention still work; the fix is `datetime.now(datetime.UTC)`.

### 10.6 Documented Python floor is unverified

The README states Python 3.9+. The code's use of `str.removeprefix` / `removesuffix`
(`backup.py`) is consistent with that floor — both are 3.9 additions — but the suite has
only been run on 3.13. No CI matrix exists to substantiate the claim.

---

## 11. Configuration

The full variable reference lives in [README.md](../README.md) and `.env.example` and is
not duplicated here. Three design notes:

- **Fail fast and explicitly.** `Config.from_env()` raises on a missing required
  variable naming it; `validate()` catches cross-variable errors (backups enabled with
  no passphrase; `api` wipe with no destination email) before any network call.
- **Defaults are the safe option, not the fast one.** `VW_WIPE_METHOD=cli`,
  `BACKUP_ENABLED=true`, `TLS verify on`. Every performance choice is opt-in.
- **Refusing to run is a feature.** Backups enabled with no passphrase is a hard error
  rather than a silent downgrade to no backup, with the message stating the explicit
  `BACKUP_ENABLED=false` opt-out.

---

## 12. Possible future work

Ordered by value, given §10.

1. Post-restore verification (§10.3) — reuse `audit_vaults()` in reverse.
2. Fix §10.1, §10.2, §10.4, §10.5 — all small and all found by writing this document.
3. An integration test against a throwaway Vaultwarden container, which would close most
   of §9.2.
4. Organisation/collection support, if the `bw` CLI's export makes it tractable.
5. Age or restic as a backup backend alternative to GPG.

---

## 13. Licence and provenance

Published under **GPL-3.0** alongside the code it describes, so the reasoning is
available and not only the implementation.

Written and built by **T. Philip** — <https://github.com/t-philip>.
Repository: <https://github.com/t-philip/bitwarden-vaultwarden-sync>.
Uses the [Bitwarden CLI](https://github.com/bitwarden/clients). Not affiliated with,
endorsed by, or supported by Bitwarden, Inc. or the Vaultwarden project.
