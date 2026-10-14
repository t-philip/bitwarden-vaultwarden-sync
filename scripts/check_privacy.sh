#!/usr/bin/env bash
# Structural half of the public-repo privacy rule (see docs/PRIVACY.md).
#
# WHAT THIS IS FOR
# This repo documents its own design in comments, and the evidence behind those
# decisions comes from measured data. That is what makes the comments worth
# reading -- and it is also how details of a particular installation can end up
# in a public repo.
#
# WHAT THIS CANNOT DO
# This is NOT a keyword scanner pretending to be complete. A denylist only ever
# encodes what someone already thought of, and the leaks that matter are
# phrases nobody would have listed in advance (a verbatim free-text note, a
# description of the people in a building).
# Do not read a pass from this script as "safe to publish". It is the cheap
# half. The other half is a semantic read of the diff by someone -- or
# something -- with no memory of writing it, answering one question: could
# this have been written by a person who has never seen the author's home?
#
# This script excludes itself from its own scan, because it necessarily
# contains the patterns it searches for. Documentation has the same hazard:
# docs/PRIVACY.md must illustrate the rule with invented examples, never by quoting
# removed text, which would republish it.
#
# WHY IT CHECKS THE DIFF, NOT THE TREE
# A large test suite carries many legitimate synthetic dates.
# Flagging those buries the signal and the check gets switched off within a
# week. Added lines are few, so even a loose rule stays quiet there.
#
#   scripts/check_privacy.sh              # added lines vs origin/main
#   scripts/check_privacy.sh --staged     # added lines, staged only
#   scripts/check_privacy.sh --all        # whole tree (audit; noisy by design)
#
# On Windows, run this under Git Bash -- the same bash git itself uses for
# hooks. PowerShell resolves `bash` to WSL (C:\WINDOWS\system32\bash.exe),
# which sees the repo through /mnt/c with different line-ending settings, so
# every file looks modified and the diff balloons to the entire tree. The
# check then reports failures on code nobody touched. The pre-push hook is
# unaffected: git runs it with its own bash.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

MODE="${1:---push}"
fail=0

# This file necessarily contains every pattern it searches for, so it would
# always flag itself. Reviewed as code, not scanned as prose.
SELF_EXCLUDE=':(exclude)scripts/check_privacy.sh'

case "$MODE" in
    --all)    ADDED=$(git ls-files -- '*.py' '*.md' '*.js' '*.html' '*.yml' '*.json' '*.sh' '*.css' \
                      | grep -v '\.min\.' | xargs -r grep -Hn '' 2>/dev/null) ;;
    --staged) ADDED=$(git diff --cached -U0 -- . "$SELF_EXCLUDE" | grep '^+' | grep -v '^+++') ;;
    *)        # PRIVACY_BASE lets CI name the range it wants checked; locally
              # we compare against the published branch plus the working tree.
              if [ -n "${PRIVACY_BASE:-}" ]; then
                  base="$PRIVACY_BASE"
              else
                  git fetch -q origin 2>/dev/null || true
                  base=$(git rev-parse --verify -q origin/main || git rev-parse HEAD)
              fi
              ADDED=$(git diff -U0 "$base"...HEAD -- . "$SELF_EXCLUDE" 2>/dev/null | grep '^+' | grep -v '^+++'
                      git diff -U0 -- . "$SELF_EXCLUDE" | grep '^+' | grep -v '^+++'
                      git diff --cached -U0 -- . "$SELF_EXCLUDE" | grep '^+' | grep -v '^+++') ;;
esac

report() {  # report <severity> <label> <pattern> [inverse-filter]
    local sev="$1" label="$2" pat="$3" drop="${4:-__nomatch__}"
    local hits
    hits=$(printf '%s\n' "$ADDED" | grep -inE -e "$pat" 2>/dev/null | grep -viE -e "$drop" || true)
    [ -z "$hits" ] && return 0
    printf '\n  [%s] %s\n' "$sev" "$label"
    printf '%s\n' "$hits" | sed 's/^/      /' | head -20
    [ "$sev" = "FAIL" ] && fail=1
    return 0
}

echo "privacy check — $MODE"

# --- Identity and infrastructure -------------------------------------------
# A denylist, and treated as one: cheap, exact, zero false positives, and
# grown by hand every time something new is found. It is a backstop, never
# the mechanism.
# Names of the author's own hosts, sites and projects are NOT listed here: a
# tracked denylist of private vocabulary would itself publish that vocabulary.
# They live in an untracked file, .privacy-denylist.private (gitignored), one
# extended regex per line. Comments ('#') must be on their own line; a '#'
# after a pattern is part of the pattern. Patterns that match the empty string
# (for example a trailing '|') or are invalid regexes are rejected with a
# warning naming the line number. If the file is absent -- a fresh clone, or
# CI -- this rule is simply skipped and only the generic rules below run.
# PRIVACY_DENYLIST_LOCAL overrides the path (useful from a git worktree, where
# the untracked file is not present in the checkout); if it is set explicitly
# and the file does not exist, that is an error.

# load_patterns <file> -> sets LOADED_PAT (alternation of valid lines) and
# LOADED_N (count). Warnings print line numbers, never pattern text.
load_patterns() {
    local file="$1" n=0 lineno=0 line rc
    LOADED_PAT=""; LOADED_N=0
    while IFS= read -r line || [ -n "$line" ]; do
        lineno=$((lineno + 1))
        [ "$lineno" -eq 1 ] && line="${line#$'\xEF\xBB\xBF'}"   # strip UTF-8 BOM
        line="${line%$'\r'}"                       # tolerate CRLF files
        line="${line#"${line%%[![:space:]]*}"}"    # trim leading whitespace
        line="${line%"${line##*[![:space:]]}"}"    # trim trailing whitespace
        case "$line" in ''|'#'*) continue ;; esac
        printf '\n' | grep -E -e "$line" >/dev/null 2>&1
        rc=$?
        if [ "$rc" -eq 0 ]; then
            echo "  WARNING: $file line $lineno matches the empty string -- ignored"
        elif [ "$rc" -eq 1 ]; then
            LOADED_PAT="${LOADED_PAT:+$LOADED_PAT|}$line"
            n=$((n + 1))
        else
            echo "  WARNING: $file line $lineno is not a valid regex -- ignored"
        fi
    done < "$file"
    LOADED_N=$n
}

LOCAL_DENYLIST="${PRIVACY_DENYLIST_LOCAL:-.privacy-denylist.private}"
if [ -f "$LOCAL_DENYLIST" ]; then
    load_patterns "$LOCAL_DENYLIST"
    if [ "$LOADED_N" -eq 0 ]; then
        echo "  NOTE: $LOCAL_DENYLIST has 0 usable patterns -- private-vocabulary rule did NOT run"
    else
        report FAIL "private vocabulary (local denylist)" "$LOADED_PAT"
    fi
elif [ -n "${PRIVACY_DENYLIST_LOCAL:-}" ]; then
    echo "  ERROR: PRIVACY_DENYLIST_LOCAL is set but $LOCAL_DENYLIST does not exist"
    fail=1
else
    echo "  NOTE: no $LOCAL_DENYLIST found -- the private-vocabulary rule did NOT run (generic rules still ran)"
fi

report FAIL "people, relationships, places" \
    "\b(mom|mum|dad|mother|father|wife|husband|son|daughter|sister|brother)\b|\b(contractor|plumber|electrician|handyman|nanny|tenant|landlord)\b"

# --- Network and contact ----------------------------------------------------
# RFC 5737 documentation ranges (192.0.2/24, 198.51.100/24, 203.0.113/24) and
# loopback are the correct things to publish, so they are excluded, as is
# 192.168.4.1, the fixed default address of common captive-portal WiFi setup
# tooling, which says nothing about anyone's network.
report FAIL "real IP addresses" \
    '\b(10|127|172|192)\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b' \
    '192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|127\.0\.0\.1|0\.0\.0\.0|192\.168\.4\.1\b'

report FAIL "email addresses" \
    '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' \
    'example\.com|noreply|@param|@return|@type|[-+ ]@pytest\.'

# --- The actual pattern that leaks -----------------------------------------
# Not a word: a real date sitting in PROSE. That is what turns a line from
# "how this behaves" into "what happened in this house on this day".
#
# Do not detect prose by a leading '#': most narrative is in docstrings,
# which carry no marker.
#
# The reliable signal is quoting. Prose writes a date bare ("gas low
# YYYY-MM-DD", "fired on YYYY-MM-DD"); a test fixture writes it quoted
# ("YYYY-MM-DD"). So: flag bare dates, leave quoted ones to the advisory
# rule below.
report FAIL "bare date in prose (a dated observation, not behaviour)" \
    '(^|[^"'"'"'0-9-])20(2[3-9]|[3-9][0-9])-[0-9]{2}-[0-9]{2}' \
    '__nomatch__'

report FAIL "month-year in prose" \
    '\b(January|February|March|April|May|June|July|August|September|October|November|December) 20[0-9]{2}\b'

# A duration in days attached to a household event. Requires a household word
# on the same line, so "30-day retention" passes untouched.
report FAIL "duration attached to a household event" \
    '\b[0-9]+-day\b.*(absence|trip|visit|stay|span|away|empty|guest|occupan)|(absence|trip|visit|stay|span|away|empty|guest|occupan).*\b[0-9]+-day\b'

# A bare year on a line about absence -- catches a month and its year split
# across two wrapped comment lines.
report FAIL "year on a line describing an absence" \
    '\b20[0-9]{2}\b.*(absence|nobody there|empty house|house was empty)|(absence|nobody there|empty house|house was empty).*\b20[0-9]{2}\b' \
    '20[0-9]{2}-[0-9]{2}-[0-9]{2}'

# A quoted phrase whose first word is a proper noun is often a verbatim
# free-text note copied out of a database.
#
# Case-SENSITIVE on purpose, and therefore not run through report(), which
# forces -i: with -i this matches ordinary phrases.
hits=$(printf '%s\n' "$ADDED" | grep -nE '"[A-Z][a-z]+ [a-z]+( [A-Z]{2})?"' 2>/dev/null \
       | grep -viE 'e\.g\.|for example|SELECT|INSERT|UPDATE|CREATE|ALTER|PRAGMA|Content-Type|User-Agent' || true)
if [ -n "$hits" ]; then
    printf '\n  [FAIL] quoted proper-noun phrase (verbatim log note?)\n'
    printf '%s\n' "$hits" | sed 's/^/      /' | head -20
    fail=1
fi

# --- Per-repo additions -----------------------------------------------------
# Anything specific to one repo and safe to publish goes in a tracked
# `.privacy-denylist`: one extended-regex per line, "#" comments on their own
# line. Private vocabulary belongs in the untracked
# .privacy-denylist.private instead.
DENYLIST_FILE="$(git rev-parse --show-toplevel)/.privacy-denylist"
if [ -f "$DENYLIST_FILE" ]; then
    load_patterns "$DENYLIST_FILE"
    if [ "$LOADED_N" -gt 0 ]; then
        report FAIL "repo denylist" "$LOADED_PAT"
    else
        echo "  NOTE: .privacy-denylist has 0 usable patterns -- repo rule did NOT run"
    fi
fi

# --- The fiction window -----------------------------------------------------
# Test data uses a year before 2002 and nothing else. Real data sources start
# well after 2001, so a date inside the window provably is not a record of
# anything, and a date outside it in quoted data is a hard signal rather than
# a guess.
#
# Migrate fixtures by shifting every date back exactly 28 years -- the
# Gregorian repeat cycle, which preserves weekday, day-of-year, month/day and
# leap-year structure, so nothing the code observes changes but the year digit
# (an arbitrary offset would move weekdays and seasons).
#
# Without a declared window a warning alone is easy to ignore, so this is a
# hard rule.
#
# Relative dates are untouched and should stay relative: a fixture built from
# `_START + timedelta(...)`, or logic that works from "today", carries no
# calendar fact to leak and pinning it would break the test.
report FAIL "absolute date at or after 2002 (outside the fiction window)" \
    '"(200[2-9]|20[1-9][0-9])-[0-9]{2}-[0-9]{2}'

# Free-text fields are where a verbatim note from a real database ends up --
# an occupancy note, a device label, a description. Default them to a
# placeholder rather than inventing something that reads like a real entry.
report FAIL "free-text field with non-placeholder content" \
    '(notes|note|description|comment|label|title)\s*[=:]\s*"[^"]{4,}"' \
    '"Test Data|placeholder|example|e\.g\.|lorem'

# --- Verdict ----------------------------------------------------------------
echo
if [ "$fail" -ne 0 ]; then
    cat <<'EOF'
FAIL — see docs/PRIVACY.md.

Fix by generalising, not by deleting: say what the code does and why, in
terms a reader with no knowledge of the author's home could have written.
The specific evidence belongs in a private record, not here.
EOF
    exit 1
fi
cat <<'EOF'
PASS (structural checks only)

This does not mean the diff is safe to publish. Still required: a semantic
read by someone with no memory of writing it, answering — could this have
been written by a person who has never seen the author's home?
EOF
