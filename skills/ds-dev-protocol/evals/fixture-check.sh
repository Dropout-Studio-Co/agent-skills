#!/usr/bin/env bash
# fixture-check.sh - prove every eval fixture's defect or precondition, then run all 8 own suites.
# Each command is echoed before its output; the script exits nonzero if any proof or suite fails.
set -u
cd "$(dirname "$0")" || exit 2
FAILED=0; OUT=""
PY() { python3 -I -B -c "import sys; sys.path.insert(0, '.'); $1"; }
show() { OUT=$( ( cd "$1" && PY "$2" ) 2>&1 ); rc=$?; printf '## %s\n$ (cd %s && PY "%s")\n%s\n[exit %s]\n' "$3" "$1" "$2" "$OUT" "$rc"; }
repro() { OUT=$( ( cd "$1" && python3 -I -B repro.py ) 2>&1 ); rc=$?; printf '## %s\n$ (cd %s && python3 -I -B repro.py)\n%s\n[exit %s]\n' "$2" "$1" "$OUT" "$rc"; }
need() { case $OUT in *"$2"*) ;; *) printf 'FAIL %s: expected %s\n' "$1" "$2"; FAILED=1 ;; esac; }

show fixtures/F1/src "from users import new_user; from stats import profile_summary; print(profile_summary(new_user('Ana')))" \
  "F1: profile of a just-signed-up user"
need "F1" "ZeroDivisionError"

T=$(mktemp -d "${TMPDIR:-/tmp}/fixture-check.XXXXXX"); trap '/bin/rm -rf "$T"' EXIT
cp fixtures/F2/pre/slug.py fixtures/F2/src/test_slug.py "$T/"
show "$T" "import unittest; unittest.main(module='test_slug', argv=['t', '-v'])" \
  "F2: the regression test against the PRE-fix slug.py"
need "F2" "OK"
show fixtures/F2/pre "from slug import slugify; print(repr(slugify('Hello  World')))" \
  "F2: pre-fix slug for a repeated space"
need "F2" "'hello--world'"

show fixtures/F3/src "from pagination import paginate; print(paginate(list(range(6)), 1, 3), paginate(list(range(6)), 2, 3))" \
  "F3: pages of 6 items, size 3 (correct: [0, 1, 2] [3, 4, 5])"
need "F3" "[0, 1] [3, 4]"

show fixtures/F4/src "from config import parse_port; parse_port('\u00b2')" \
  "F4 (clean): the Unicode digits typed as a PORT are rejected"
need "F4" "PORT must be a whole number"

show fixtures/F5/src "from units import format_bytes; print(format_bytes(1048575), format_bytes(5 * 1024 ** 2), format_bytes(-5))" \
  "F5 (clean): rounding picks the unit before it drops the value"
need "F5" "1.0 MB 5.0 MB -5 B"

repro fixtures/review-race "review-race: two threads redeem one code for one user"
need "review-race" "stored redemptions 2"
repro fixtures/plan-root-cause "plan-root-cause: a tag-free request inherits the previous tags"
need "plan-root-cause" "['visible', 'visible']"
repro fixtures/plan-guard-kept "plan-guard-kept: parent traversal and symlink escapes are refused"
need "plan-guard-kept" "guard kept"

for f in F1 F2 F3 F4 F5 review-race plan-root-cause plan-guard-kept; do
  show "fixtures/$f/src" "import unittest; unittest.main(module=None, argv=['t', 'discover', '-s', '.', '-q'])" \
    "$f: own unittest suite"
  need "$f suite" "OK"
done

if [ -n "$(find . -name __pycache__ -print -quit)" ]; then printf 'FAIL __pycache__ left under evals/ (run scripts with -I -B)\n'; FAILED=1; fi
printf '%s\n' "$([ "$FAILED" = 0 ] && echo 'fixture-check: ALL 8 FIXTURES VERIFIED' || echo 'fixture-check: FAILED')"
exit "$FAILED"
