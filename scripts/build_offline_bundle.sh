#!/usr/bin/env bash
#
# Open Omniscience — offline dependency-bundle builder.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# Run this ON A MACHINE WITH INTERNET. It produces the "dependency payload" that
# install-offline.sh consumes on an AIR-GAPPED machine: every Python wheel the app
# needs, the three wheels required to bootstrap pip into a fresh virtualenv, an
# optional self-contained CPython, and a manifest of SHA-256 digests so the
# air-gapped side can prove the bytes survived the USB stick intact.
#
#   scripts/build_offline_bundle.sh                      # default extras, no runtime
#   scripts/build_offline_bundle.sh --with-python URL    # also bundle a CPython 3.13
#   scripts/build_offline_bundle.sh --extras ""          # core only (smallest)
#   scripts/build_offline_bundle.sh --zip                # also emit a .zip
#
# THE ONE CONSTRAINT THIS CANNOT PAPER OVER: a wheel is built for a specific
# Python ABI (cp313), CPU architecture (x86_64 / aarch64) and glibc floor. Build
# the bundle on a machine whose architecture matches the target and whose glibc is
# NO NEWER than the target's, or the wheels will not install there. The manifest
# records all three so install-offline.sh can refuse loudly instead of failing
# halfway through with a confusing pip error.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${OO_PYTHON:-python3.13}"

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
die()  { printf '%sERROR:%s %s\n' "$RED$BOLD" "$RST" "$*" >&2; exit 1; }

# The default set MUST match install.sh's choose_components(), or an offline
# install would silently ship a different app than the online one.
EXTRAS="${OO_COMPONENTS:-analysis,compression,columnar}"
OUT_ROOT="$SRC_DIR/dist"
PYTHON_URL=""
MAKE_ZIP=0

usage() {
    cat <<EOF
Open Omniscience — offline bundle builder (run me online)

Usage:
  scripts/build_offline_bundle.sh [options]

Options:
  --extras "a,b,c"   Extras to bundle (default: "$EXTRAS"; "" = core only)
  --with-python URL  Also bundle a self-contained CPython 3.13 from URL.
                     Use this when the AIR-GAPPED machine has no Python 3.13
                     (Debian 12 ships 3.11; Debian 13 ships 3.13). The digest of
                     whatever is downloaded is recorded in the manifest — this
                     script never invents a checksum.
  --out DIR          Output directory (default: $OUT_ROOT)
  --zip              Also produce a .zip next to the bundle directory
  -h, --help         This message

The bundle is self-describing: it carries offline-manifest.json (build metadata +
digests), SHA256SUMS, and a README.txt for whoever carries the stick.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --extras)      EXTRAS="${2-}"; shift 2 ;;
        --with-python) PYTHON_URL="${2-}"; [ -n "$PYTHON_URL" ] || die "--with-python needs a URL"; shift 2 ;;
        --out)         OUT_ROOT="${2-}"; [ -n "$OUT_ROOT" ] || die "--out needs a directory"; shift 2 ;;
        --zip)         MAKE_ZIP=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *)             usage; die "unknown option: $1" ;;
    esac
done

# Same defence-in-depth as install.sh: extras is a token list, never free text.
if [ -n "$EXTRAS" ] && ! printf '%s' "$EXTRAS" | grep -qE '^[A-Za-z0-9_.,-]+$'; then
    die "invalid --extras value '$EXTRAS' (expected a comma-separated token list)"
fi

command -v "$PY" >/dev/null 2>&1 || die "$PY not found. The bundle's wheels must be built by the SAME Python minor version the target will run (3.13)."
PY_FULL="$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')"
PY_TAG="$("$PY" -c 'import sys; print("cp%d%d" % sys.version_info[:2])')"
case "$PY_TAG" in cp313|cp314) : ;; *) die "$PY is $PY_FULL; the project targets Python 3.13+ and wheels are ABI-specific." ;; esac

ARCH="$(uname -m)"
KERNEL="$(uname -s)"
[ "$KERNEL" = "Linux" ] || warn "Building on $KERNEL — the target is Debian/Linux, so these wheels will NOT match it."
LIBC="$(ldd --version 2>&1 | head -1 | grep -oE '[0-9]+\.[0-9]+$' || echo unknown)"

BUNDLE_NAME="open-omniscience-offline-$(printf '%s' "$KERNEL" | tr '[:upper:]' '[:lower:]')-${ARCH}-${PY_TAG}"
BUNDLE="$OUT_ROOT/$BUNDLE_NAME"

say ""
say "${BOLD}Open Omniscience — offline bundle builder${RST}"
say "  Python:  $PY_FULL ($PY_TAG)"
say "  Target:  $KERNEL/$ARCH, glibc $LIBC"
say "  Extras:  ${EXTRAS:-<core only>}"
say "  Output:  $BUNDLE"
say ""

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/wheels" "$BUNDLE/bootstrap"

# pip unpacks large scientific wheels in TMPDIR; on Qubes /tmp is a small tmpfs.
# Point it at the output volume (the same lesson install.sh already encodes).
PIP_TMP="$OUT_ROOT/.pip-build"
mkdir -p "$PIP_TMP"
export TMPDIR="$PIP_TMP"
PIP_OPTS="--retries 5 --timeout 60"

# --------------------------------------------------------------------------- #
# 1. The pip bootstrap trio.
# --------------------------------------------------------------------------- #
# On Debian the stdlib `ensurepip` lives in a SEPARATE apt package, which an
# air-gapped box will not have — so install-offline.sh creates the venv with
# `--without-pip` and installs pip FROM THESE WHEELS instead. That removes the
# only apt dependency the offline install would otherwise have.
step "Fetching the pip bootstrap wheels (pip, setuptools, wheel)"
"$PY" -m pip download $PIP_OPTS --only-binary=:all: --dest "$BUNDLE/bootstrap" \
    pip setuptools wheel >/dev/null || die "could not download the pip bootstrap wheels"
ok "Bootstrap wheels: $(find "$BUNDLE/bootstrap" -name '*.whl' | wc -l | tr -d ' ')"

# --------------------------------------------------------------------------- #
# 2. Every runtime dependency, as a wheel.
# --------------------------------------------------------------------------- #
SPEC="$SRC_DIR"
[ -n "$EXTRAS" ] && SPEC="$SRC_DIR[$EXTRAS]"

step "Resolving and downloading dependencies for: ${EXTRAS:-core}"
say "  ${DIM}This can take a few minutes and a few hundred MB.${RST}"
if ! "$PY" -m pip download $PIP_OPTS --only-binary=:all: --dest "$BUNDLE/wheels" "$SPEC" > "$PIP_TMP/download.log" 2>&1; then
    # A dependency that publishes no wheel (jieba, in the `segmentation` extra) makes
    # --only-binary fail. `pip wheel` BUILDS such an sdist into a wheel here, on the
    # online machine, so the air-gapped side still only ever sees wheels — it must
    # never need a compiler or a network to build anything.
    if grep -q "from versions: none" "$PIP_TMP/download.log"; then
        warn "Some dependencies publish no wheel — building them from source here."
        "$PY" -m pip wheel $PIP_OPTS --wheel-dir "$BUNDLE/wheels" "$SPEC" \
            || { tail -20 "$PIP_TMP/download.log" >&2; die "could not build the dependency set"; }
        # `pip wheel` also builds the project itself; the air-gapped install is
        # editable from the source tree, so that wheel is dead weight.
        rm -f "$BUNDLE"/wheels/open_omniscience-*.whl
    else
        tail -20 "$PIP_TMP/download.log" >&2
        die "dependency download failed (see above)"
    fi
fi
WHEEL_N="$(find "$BUNDLE/wheels" -name '*.whl' | wc -l | tr -d ' ')"
[ "$WHEEL_N" -gt 0 ] || die "no wheels were downloaded — refusing to write an empty bundle"
ok "Dependency wheels: $WHEEL_N"

# --------------------------------------------------------------------------- #
# 3. Optional: a self-contained CPython for targets that have no Python 3.13.
# --------------------------------------------------------------------------- #
if [ -n "$PYTHON_URL" ]; then
    mkdir -p "$BUNDLE/runtime"
    step "Downloading the self-contained CPython runtime"
    say "  ${DIM}$PYTHON_URL${RST}"
    rt_name="$(basename "${PYTHON_URL%%\?*}")"
    curl -fL --retry 3 --proto '=https' --tlsv1.2 -o "$BUNDLE/runtime/$rt_name" "$PYTHON_URL" \
        || die "could not download the runtime from $PYTHON_URL"
    # We record the digest of what we ACTUALLY received. We do not carry an
    # upstream checksum we did not verify ourselves — the manifest's job is to
    # prove the bytes reached the air-gapped machine unaltered, and it says so.
    rt_sha="$(sha256sum "$BUNDLE/runtime/$rt_name" | awk '{print $1}')"
    ok "Runtime: $rt_name"
    say "  ${DIM}sha256 $rt_sha${RST}"
    say "  ${YLW}Verify this against the publisher's own checksum before you trust the stick.${RST}"
fi

# --------------------------------------------------------------------------- #
# 4. Manifest + checksums.
# --------------------------------------------------------------------------- #
step "Writing the manifest and checksums"
( cd "$BUNDLE" && find . -type f \( -name '*.whl' -o -name '*.tar.gz' -o -name '*.tar.zst' \) \
    -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )

APP_VERSION="$(grep -m1 '^version *= *"' "$SRC_DIR/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/')"
BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RUNTIME_FILE=""
if [ -n "$PYTHON_URL" ]; then RUNTIME_FILE="$(cd "$BUNDLE/runtime" && ls | head -1)"; fi

# The manifest generator receives its values through the ENVIRONMENT, and the
# heredoc below is quoted ('PYEOF') so the shell expands nothing inside it.
# Interpolating shell values into program source is how a stray character in a
# version string becomes a syntax error in a generated file — the same class of
# mistake as building SQL by concatenation. Passing data as data cannot break,
# whatever `ldd` or a future field happens to contain.
OO_M_APP_VERSION="$APP_VERSION" \
OO_M_BUILT_AT="$BUILT_AT" \
OO_M_EXTRAS="$EXTRAS" \
OO_M_PY_FULL="$PY_FULL" \
OO_M_PY_TAG="$PY_TAG" \
OO_M_KERNEL="$KERNEL" \
OO_M_ARCH="$ARCH" \
OO_M_LIBC="$LIBC" \
OO_M_RUNTIME="$RUNTIME_FILE" \
"$PY" - "$BUNDLE" <<'PYEOF'
import hashlib, json, os, sys

bundle = sys.argv[1]
env = os.environ.get


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


files, total = {}, 0
for sub in ("bootstrap", "wheels", "runtime"):
    d = os.path.join(bundle, sub)
    if not os.path.isdir(d):
        continue
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            files["%s/%s" % (sub, name)] = {"sha256": digest(p), "bytes": os.path.getsize(p)}
            total += os.path.getsize(p)

manifest = {
    "schema": 1,
    "app_version": env("OO_M_APP_VERSION", ""),
    "built_at": env("OO_M_BUILT_AT", ""),
    "extras": env("OO_M_EXTRAS", ""),
    "python": {"version": env("OO_M_PY_FULL", ""), "abi_tag": env("OO_M_PY_TAG", "")},
    "platform": {
        "kernel": env("OO_M_KERNEL", ""),
        "arch": env("OO_M_ARCH", ""),
        "glibc": env("OO_M_LIBC", ""),
    },
    "bundled_runtime": env("OO_M_RUNTIME") or None,
    "totals": {"files": len(files), "bytes": total},
    "files": files,
}
with open(os.path.join(bundle, "offline-manifest.json"), "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
    fh.write("\n")
print("  manifest: %d files, %.1f MB" % (len(files), total / 1048576.0))
PYEOF

cat > "$BUNDLE/README.txt" <<EOF
Open Omniscience — offline dependency bundle
============================================

Built : $BUILT_AT
For   : $KERNEL / $ARCH, Python $PY_FULL ($PY_TAG), glibc $LIBC or newer
App   : version $APP_VERSION, components: core${EXTRAS:+, $EXTRAS}

WHAT THIS IS
  Every Python package Open Omniscience needs, downloaded ahead of time so the
  application can be installed on a machine that has never been, and will never
  be, connected to a network.

HOW TO USE IT
  1. Copy BOTH folders onto the air-gapped machine, side by side:
         Open-Omniscience-<something>/     <- the application
         $BUNDLE_NAME/   <- this folder
  2. Open the application folder.
  3. Double-click "Install Open Omniscience (offline)".
     (No terminal? From a shell:  ./install-offline.sh )

  The installer finds this folder on its own, checks every file against
  SHA256SUMS, and installs without making a single network request.

WHAT IT DOES NOT CONTAIN
  These are downloaded separately, in the app, and are never required to install:
    * Ollama and any local AI model
    * Wikipedia dumps, OpenStreetMap regions
  The app runs fully without them.
EOF

TOTAL_H="$(du -sh "$BUNDLE" | awk '{print $1}')"
ok "Bundle ready: $BUNDLE ($TOTAL_H)"

if [ "$MAKE_ZIP" = "1" ]; then
    command -v zip >/dev/null 2>&1 || die "zip not found (Debian: sudo apt-get install zip)"
    step "Creating the zip"
    ( cd "$OUT_ROOT" && rm -f "$BUNDLE_NAME.zip" && zip -qr "$BUNDLE_NAME.zip" "$BUNDLE_NAME" )
    ok "Zip: $OUT_ROOT/$BUNDLE_NAME.zip ($(du -sh "$OUT_ROOT/$BUNDLE_NAME.zip" | awk '{print $1}'))"
fi

rm -rf "$PIP_TMP"

say ""
say "${BOLD}Next:${RST} carry this folder and the application folder to the air-gapped"
say "machine, put them side by side, and double-click the offline installer."
