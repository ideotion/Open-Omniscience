#!/usr/bin/env bash
#
# Open Omniscience — AIR-GAPPED installer.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# For a machine that has never been, and will never be, connected to a network.
# It makes ZERO network requests: every Python package comes from a dependency
# bundle you prepared earlier on a connected machine with
# scripts/build_offline_bundle.sh.
#
# The normal, connected install (scripts/bootstrap.sh + ./install.sh) is
# untouched by this file and does not need it.
#
#   Double-click  "Install Open Omniscience (offline).desktop"
#   or run        ./install-offline.sh
#
# Where it looks for the dependency bundle, in order:
#   1. $OO_OFFLINE_BUNDLE            (an explicit path always wins)
#   2. ./offline/                    (bundle copied inside this folder)
#   3. any sibling folder            (both zips extracted side by side — the
#      of this one, then any            expected layout)
#      folder beside its parent
# A folder counts as a bundle when it contains offline-manifest.json. When
# several are present, the one matching THIS machine's architecture wins.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
    YLW=$'\033[33m'; BLU=$'\033[36m'; RST=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; BLU=""; RST=""
fi
say()  { printf '%s\n' "$*"; }
step() { printf '%s==>%s %s\n' "$BLU$BOLD" "$RST" "$*"; }
ok()   { printf '%s  ok%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s  !!%s %s\n' "$YLW" "$RST" "$*"; }

# Double-clicked from a file manager, the terminal window dies with the script and
# takes the error message with it. Hold it open on ANY failure so the person
# standing at the air-gapped machine can actually read what went wrong.
HOLD_OPEN=1
hold() {
    [ "$HOLD_OPEN" = "1" ] || return 0
    [ "${OO_NO_HOLD:-0}" = "1" ] && return 0
    # Only pause when a human is actually at a keyboard. A double-click runs this
    # through Terminal=true, which gives stdin a real terminal, so the window is
    # held exactly when it needs to be. Deliberately NOT falling back to /dev/tty:
    # in CI and scripted runs that device can be readable with nobody reading it,
    # and the installer would hang forever waiting for an Enter that never comes.
    [ -t 0 ] || return 0
    say ""
    read -r -p "Press Enter to close this window..." _ || true
}
die() { printf '\n%sERROR:%s %s\n' "$RED$BOLD" "$RST" "$*" >&2; hold; exit 1; }
trap 'rc=$?; [ "$rc" -ne 0 ] && { printf "\n%sThe installer stopped (exit %s).%s\n" "$RED" "$rc" "$RST" >&2; hold; }; exit $rc' EXIT

banner() {
    [ -f "$SRC_DIR/assets/logo.txt" ] && { printf '%s' "$BOLD"; cat "$SRC_DIR/assets/logo.txt"; printf '%s' "$RST"; }
    printf '%s        Open Omniscience — offline install%s\n' "$BOLD" "$RST"
    printf '%s  No network is used. Nothing leaves this machine.%s\n\n' "$DIM" "$RST"
}

# --------------------------------------------------------------------------- #
# 1. Find the dependency bundle
# --------------------------------------------------------------------------- #
ARCH="$(uname -m)"

# A directory is a bundle if it holds offline-manifest.json.
is_bundle() { [ -f "$1/offline-manifest.json" ]; }

# Read a top-level string field out of the manifest without needing python.
manifest_get() {
    # $1=bundle dir  $2=dotted path (arch|kernel|abi_tag|extras|app_version|built_at)
    local f="$1/offline-manifest.json" key="$2"
    grep -oE "\"$key\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$f" 2>/dev/null \
        | head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
}

find_bundle() {
    local -a cands=()
    local d

    if [ -n "${OO_OFFLINE_BUNDLE:-}" ]; then
        is_bundle "$OO_OFFLINE_BUNDLE" \
            || die "OO_OFFLINE_BUNDLE='$OO_OFFLINE_BUNDLE' does not contain offline-manifest.json."
        printf '%s' "$(cd "$OO_OFFLINE_BUNDLE" && pwd)"; return 0
    fi

    is_bundle "$SRC_DIR/offline" && cands+=("$SRC_DIR/offline")
    # Siblings of this folder, then folders beside its parent (covers "I extracted
    # both zips into ~/Downloads" and "…onto the USB stick root").
    for d in "$SRC_DIR"/../*/ "$SRC_DIR"/../../*/; do
        [ -d "$d" ] || continue
        is_bundle "$d" && cands+=("${d%/}")
    done

    [ "${#cands[@]}" -gt 0 ] || return 1

    # Prefer a bundle built for THIS architecture; otherwise take the first and let
    # the compatibility check below explain the mismatch properly.
    for d in "${cands[@]}"; do
        [ "$(manifest_get "$d" arch)" = "$ARCH" ] && { printf '%s' "$(cd "$d" && pwd)"; return 0; }
    done
    printf '%s' "$(cd "${cands[0]}" && pwd)"
}

banner
step "Looking for the dependency bundle"
BUNDLE="$(find_bundle || true)"
if [ -z "$BUNDLE" ]; then
    die "No dependency bundle found.

  This installer needs the companion download — the folder that holds the
  Python packages. It is a separate zip because it is much larger than the
  application itself.

  Put the two folders SIDE BY SIDE, like this:

      $(dirname "$SRC_DIR")/
        ├── $(basename "$SRC_DIR")/          <- you are here
        └── open-omniscience-offline-linux-$ARCH-cp313/

  then double-click the offline installer again.

  Already have it somewhere else? Point at it directly:
      OO_OFFLINE_BUNDLE=/path/to/bundle ./install-offline.sh"
fi
ok "Bundle: $BUNDLE"
B_ARCH="$(manifest_get "$BUNDLE" arch)"
B_ABI="$(manifest_get "$BUNDLE" abi_tag)"
B_EXTRAS="$(manifest_get "$BUNDLE" extras)"
B_BUILT="$(manifest_get "$BUNDLE" built_at)"
say "  ${DIM}built $B_BUILT · $B_ARCH · $B_ABI · components: core${B_EXTRAS:+, $B_EXTRAS}${RST}"

# --------------------------------------------------------------------------- #
# 2. Refuse a bundle that cannot possibly install here
# --------------------------------------------------------------------------- #
# A wheel is compiled for one CPU architecture. Catching this now beats failing
# halfway through with a pip error nobody can read.
if [ -n "$B_ARCH" ] && [ "$B_ARCH" != "$ARCH" ]; then
    die "This bundle was built for '$B_ARCH', but this machine is '$ARCH'.

  Python packages contain compiled code and cannot cross architectures.
  Rebuild the bundle on a $ARCH machine:
      scripts/build_offline_bundle.sh"
fi

# --------------------------------------------------------------------------- #
# 3. Prove the bytes survived the trip
# --------------------------------------------------------------------------- #
# USB sticks and zip round-trips corrupt files quietly. Verify before installing;
# a truncated wheel otherwise surfaces as a baffling failure much later.
if [ "${OO_OFFLINE_SKIP_VERIFY:-0}" = "1" ]; then
    warn "OO_OFFLINE_SKIP_VERIFY=1 — skipping the integrity check."
elif [ -f "$BUNDLE/SHA256SUMS" ] && command -v sha256sum >/dev/null 2>&1; then
    step "Checking the bundle is intact ($(grep -c . "$BUNDLE/SHA256SUMS") files)"
    if ( cd "$BUNDLE" && sha256sum --quiet -c SHA256SUMS ) 2>/dev/null; then
        ok "Every file matches its checksum"
    else
        die "The dependency bundle is damaged — at least one file does not match
  its checksum. This usually means an incomplete copy or a failing USB stick.

  Copy the bundle again and retry. Nothing has been installed."
    fi
else
    warn "No SHA256SUMS in the bundle — installing without an integrity check."
fi

# --------------------------------------------------------------------------- #
# 4. Find a Python 3.13, or use the one in the bundle
# --------------------------------------------------------------------------- #
# Debian 13 (trixie) ships Python 3.13; Debian 12 (bookworm) ships 3.11, which
# this project cannot run on. When the bundle carries a self-contained runtime we
# use that instead of asking an offline machine to install one.
py_ok() {
    command -v "$1" >/dev/null 2>&1 || return 1
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 13) else 1)' 2>/dev/null
}

step "Looking for Python 3.13"
CHOSEN_PY=""
for cand in "${OO_PYTHON:-}" python3.14 python3.13 python3; do
    [ -n "$cand" ] || continue
    if py_ok "$cand"; then CHOSEN_PY="$cand"; break; fi
done

if [ -n "$CHOSEN_PY" ]; then
    ok "Using $("$CHOSEN_PY" --version) ($(command -v "$CHOSEN_PY"))"
elif [ -d "$BUNDLE/runtime" ] && compgen -G "$BUNDLE/runtime/*.tar.*" >/dev/null; then
    step "This machine has no Python 3.13 — unpacking the one from the bundle"
    RT_DIR="$SRC_DIR/.python-runtime"
    if [ ! -x "$RT_DIR/bin/python3" ] && [ ! -x "$RT_DIR/python/bin/python3" ]; then
        rm -rf "$RT_DIR"; mkdir -p "$RT_DIR"
        tar -xf "$(compgen -G "$BUNDLE/runtime/*.tar.*" | head -1)" -C "$RT_DIR" \
            || die "could not unpack the bundled Python runtime"
    fi
    # Self-contained CPython tarballs unpack either flat or under python/.
    for c in "$RT_DIR/bin/python3" "$RT_DIR/python/bin/python3"; do
        [ -x "$c" ] && { CHOSEN_PY="$c"; break; }
    done
    [ -n "$CHOSEN_PY" ] || die "the bundled runtime unpacked, but no bin/python3 was found inside it"
    py_ok "$CHOSEN_PY" || die "the bundled runtime is not Python 3.13+"
    ok "Using the bundled $("$CHOSEN_PY" --version)"
else
    die "Python 3.13 or newer is required, and this machine does not have it.

  Two ways forward, both without a network on THIS machine:

  1. Rebuild the bundle WITH a self-contained Python (on the connected machine):
         scripts/build_offline_bundle.sh --with-python <url-of-a-cpython-3.13-tarball>
     The installer will then use that copy and nothing needs installing here.

  2. Install Python 3.13 from your distribution's packages.
     Debian 13 (trixie) ships it; Debian 12 (bookworm) ships only 3.11."
fi

# --------------------------------------------------------------------------- #
# 5. Somewhere to install to
# --------------------------------------------------------------------------- #
# The app installs into its own folder. Straight off a read-only USB stick that
# cannot work, and the resulting error is opaque — say so plainly instead.
if [ ! -w "$SRC_DIR" ]; then
    die "This folder is not writable: $SRC_DIR

  The application installs into its own folder, so it cannot be run directly
  from a read-only medium. Copy it to your home folder first, then double-click
  the offline installer there."
fi

# --------------------------------------------------------------------------- #
# 6. Hand over to the normal installer, in offline mode
# --------------------------------------------------------------------------- #
# install.sh owns the venv, the database, the launcher and the uninstaller. It
# already understands OO_OFFLINE_BUNDLE: it installs from the bundle's wheels
# with pip's index disabled, and bootstraps pip from the bundle when Debian's
# separate venv package is missing. Reusing it means the offline and online
# installs cannot drift apart.
say ""
step "Installing"
say "  ${DIM}Components: core${B_EXTRAS:+, $B_EXTRAS} — from the bundle, no network.${RST}"
say ""

export OO_OFFLINE_BUNDLE="$BUNDLE"
export OO_PYTHON="$CHOSEN_PY"
[ -n "$B_EXTRAS" ] && export OO_COMPONENTS="$B_EXTRAS" || export OO_COMPONENTS=""

# From here install.sh prints its own progress and, on an interactive run, ends
# inside the started app. Its exit code is ours.
HOLD_OPEN=0   # install.sh/launch.sh own the window from this point
"$SRC_DIR/install.sh" "${@:---interactive}"
