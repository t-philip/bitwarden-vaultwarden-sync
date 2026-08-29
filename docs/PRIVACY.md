# Publishing rule — what may and may not appear in this repo

This is a public repository belonging to a personal project. The code and its
comments are written from a working installation, which is what makes them
worth reading — and is also how a specific home's network, devices, dates or
occupants can end up published. That has happened before in a sibling repo,
twice, in comments nobody thought were sensitive while writing them.

## The rule

> **A comment may describe behaviour and reasoning. It may not describe a
> specific installation.**

Evidence is cited **generalised**, never **particular**: no real dates, no
event labels, no host names, no SSIDs, no internal domains, no date paired
with a reading.

The test to apply to any line you are about to write:

> *Could this have been written by someone who has never seen the author's
> home or network?*

Generalising costs nothing. "A multi-week absence can run at 0.03–0.08 m³/day"
says everything a reader needs; naming when it happened only tells them about
one house. In practice the general form reads better, because it states the
behaviour rather than an anecdote nobody else can verify.

## Where the specific detail goes instead

Into a private note, not here. Real hostnames, dates, readings and network
details belong in whatever private record you keep; they are useful there and
a disclosure here.

## Checking

Two halves, and **both** are required.

**Structural** — `scripts/check_privacy.sh`, run automatically by the
`pre-push` hook. It checks the *diff*, not the whole tree, so it stays quiet
enough to survive: bare dates in prose, durations attached to household
events, internal host names, real IPs, emails, quoted log notes.

The hook lives in the tracked `.githooks/` directory rather than `.git/hooks`,
because `.git/` is never cloned — a hook kept there exists only on the machine
that wrote it. Activate it once per clone:

```sh
git config core.hooksPath .githooks
```

`.github/workflows/check-privacy.yml` runs the same script server-side, since
a hook can be skipped with `--no-verify`. It cannot un-publish anything; it
buys finding out in minutes rather than never.

Repo-specific terms go in `.privacy-denylist` — one extended-regex per line,
`#` for comments — so this script stays byte-identical across every public
repo and a fix can be copied once instead of diverging.

**Semantic** — a read of the diff by someone, or something, with no memory of
writing it, answering the one question above.

The second is not optional. Both real leaks were phrases no denylist would
have held in advance. A single quoted proper noun in particular cannot be
distinguished mechanically from a column label without flagging every
capitalised string in the codebase.

**A pass from the script does not mean the diff is safe to publish.** It means
the cheap half found nothing.
