#!/usr/bin/env bash
# Structural half of the public-repo privacy rule (see docs/PRIVACY.md).
#
# WHAT THIS IS FOR
# This repo documents its own design in comments, and the evidence behind
# those decisions came from one real household. That is what makes the
# comments worth reading -- and it is also how a specific home's dates,
# absences and occupants end up in a public repo. Two separate leaks of
# exactly that shape have already happened here.
#
# WHAT THIS CANNOT DO
# This is NOT a keyword scanner pretending to be complete. A denylist only
# ever encodes what someone already thought of, and both real leaks here
# were phrases nobody would have listed in advance: one quoted an occupancy
# note naming a relative, the other named a trade working in the house.
# Do not read a pass from this script as "safe to publish". It is the cheap
# half. The other half is a semantic read of the diff by someone -- or
# something -- with no memory of writing it, answering one question: could
# this have been written by a person who has never seen the author's home?
#
# This script excludes itself from its own scan, because it necessarily
# contains the patterns it searches for. Its first real catch was its own
# documentation: docs/PRIVACY.md originally illustrated the rule by quoting
# the actual removed text, which would have republished all of it.
#
# WHY IT CHECKS THE DIFF, NOT THE TREE
# The tree carries ~950 dates, almost all legitimate synthetic fixtures.
# Flagging those buries the signal and the check gets switched off within a
# week. Added lines are few, so even a loose rule stays quiet there.
#
#   scripts/check_privacy.sh              # added lines vs origin/main
#   scripts/check_privacy.sh --staged     # added lines, staged only
#   scripts/check_privacy.sh --all        # whole tree (audit; noisy by design)
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
                      git diff -U0 -- . "$SELF_EXCLUDE" | grep '^+' | grep -v '^+++') ;;
esac

report() {  # report <severity> <label> <pattern> [inverse-filter]
    local sev="$1" label="$2" pat="$3" drop="${4:-__nomatch__}"
    local hits
    hits=$(printf '%s\n' "$ADDED" | grep -inE "$pat" 2>/dev/null | grep -viE "$drop" || true)
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
report FAIL "internal host / site names" \
    '\bct-2[0-9][0-9]\b|\bnucbox\b|\bnanopi\b|\bpve-g3\b|\bd17\b|\bamstelveen\b|\bha-green\b|\bvaultwarden\b|\binfisical\b' \
    'modelcontract'

report FAIL "people, relationships, places" \
    "\b(mom|mum|dad|mother|father|wife|husband|son|daughter|sister|brother)\b|Philip's|by Philip|\b(contractor|plumber|electrician|handyman|nanny|tenant|landlord)\b" \
    't-philip|tphilip'

# --- Network and contact ----------------------------------------------------
# RFC 5737 documentation ranges (192.0.2/24, 198.51.100/24, 203.0.113/24) and
# loopback are the correct things to publish, so they are excluded.
# 192.168.4.1 is WiFiManager's fixed captive-portal AP address, the same on
# every ESP32 ever flashed -- it says nothing about anyone's network, and
# excluding it keeps the ESP32 repos from failing on their own setup docs.
report FAIL "real IP addresses" \
    '\b(10|127|172|192)\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\b' \
    '192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|127\.0\.0\.1|0\.0\.0\.0|192\.168\.4\.1\b'

report FAIL "email addresses" \
    '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' \
    'example\.com|noreply|@param|@return|@type'

# --- The actual pattern that leaks -----------------------------------------
# Not a word: a real date sitting in PROSE. That is what turns a line from
# "how this behaves" into "what happened in this house on this day".
#
# Do not detect prose by a leading '#'. Most of this repo's narrative is in
# docstrings, which carry no marker -- an earlier version of this check keyed
# on '#' and silently missed three of the lines that actually leaked.
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

# A bare year on a line about absence -- catches the case where a month and
# its year are split across two wrapped comment lines, which is exactly how
# one real leak slipped past an earlier month-year rule.
report FAIL "year on a line describing an absence" \
    '\b20[0-9]{2}\b.*(absence|nobody there|empty house|house was empty)|(absence|nobody there|empty house|house was empty).*\b20[0-9]{2}\b' \
    '20[0-9]{2}-[0-9]{2}-[0-9]{2}'

# A quoted phrase whose first word is a proper noun is very often a verbatim
# occupancy note copied out of the database -- precisely how a relative's name
# and a travel destination reached this repo.
#
# Case-SENSITIVE on purpose, and therefore not run through report(), which
# forces -i. With -i this matched "latest reading", "empty house", "no
# information" -- five false positives in a single release's diff, which is
# how a check earns itself an --no-verify habit.
hits=$(printf '%s\n' "$ADDED" | grep -nE '"[A-Z][a-z]+ [a-z]+( [A-Z]{2})?"' 2>/dev/null \
       | grep -viE 'e\.g\.|for example|SELECT|INSERT|UPDATE|CREATE|ALTER|PRAGMA|Content-Type|User-Agent' || true)
if [ -n "$hits" ]; then
    printf '\n  [FAIL] quoted proper-noun phrase (verbatim log note?)\n'
    printf '%s\n' "$hits" | sed 's/^/      /' | head -20
    fail=1
fi

# --- Per-repo additions -----------------------------------------------------
# This script is meant to be byte-identical across every public repo, so that
# a fix or a new rule can be copied once rather than diverging nine ways.
# Anything specific to one repo goes in its own `.privacy-denylist`: one
# extended-regex per line, '#' for comments. A WiFi tool might list SSIDs; a
# traffic inspector might list internal domains.
DENYLIST_FILE="$(git rev-parse --show-toplevel)/.privacy-denylist"
if [ -f "$DENYLIST_FILE" ]; then
    while IFS= read -r pat; do
        case "$pat" in ''|'#'*) continue ;; esac
        report FAIL "repo denylist: $pat" "$pat"
    done < "$DENYLIST_FILE"
fi

# --- The fiction window -----------------------------------------------------
# Test data uses 1999-2001 and nothing else. This is the rule that makes the
# whole check work: every real data source here begins well after 2001, so a
# date inside that window provably is not a record of anything, and a date
# outside it in quoted data is a hard signal rather than a guess.
#
# Before this convention there was no mechanical way to tell a fixture date
# from a real one, so the rule could only warn -- and a warning is what let a
# real household's dates sit in the test suite through several releases.
#
# Relative dates are untouched and should stay relative: a fixture built from
# `_START + timedelta(...)`, or logic that works from "today", carries no
# calendar fact to leak and pinning it would break the test.
report FAIL "absolute date outside the 1999-2001 fiction window" \
    '"(19[0-8][0-9]|199[0-8]|200[2-9]|20[1-9][0-9])-[0-9]{2}-[0-9]{2}'

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
The specific evidence belongs in the private action register, not here.
EOF
    exit 1
fi
cat <<'EOF'
PASS (structural checks only)

This does not mean the diff is safe to publish. Still required: a semantic
read by someone with no memory of writing it, answering — could this have
been written by a person who has never seen the author's home?
EOF
