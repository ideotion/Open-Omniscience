#!/usr/bin/env bash
#
# Open Omniscience installer  --  Qubes OS Debian AppVM, Python 3.13, single user.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# Qubes reminder: in an AppVM only /home, /usr/local and /rw persist across a
# reboot; the root filesystem is reset from the TemplateVM every boot. Therefore
# this installer is split into two explicit modes:
#
#   sudo ./install.sh --template     run ONCE in the TEMPLATEVM: installs the
#                                    system packages (python3.13, venv, git, ...)
#                                    so they persist. Then shut down the template
#                                    and reboot the AppVM.
#
#   ./install.sh --appvm             run in the APPVM (no sudo): creates the
#                                    virtualenv and installs the app under /home
#                                    (which persists). This is the normal install.
#
# Safety (vs the legacy installer): never an unconfirmed 'rm -rf'; never a blind
# 'curl | sh'; never '2>/dev/null' that hides package-manager errors. Set -euo.

set -euo pipefail

APP_NAME="open-omniscience"
# Default install root lives under the persistent AppVM /home.
INSTALL_DIR="${OO_INSTALL_DIR:-$HOME/$APP_NAME}"
PY="${OO_PYTHON:-python3.13}"

c_red()  { printf '\033[31m%s\033[0m\n' "$*"; }
c_grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }
info()   { printf '  %s\n' "$*"; }
die()    { c_red "ERROR: $*"; exit 1; }

usage() {
    cat <<EOF
Open Omniscience installer

Usage:
  sudo ./install.sh --template   Install system packages in the TemplateVM (run once)
       ./install.sh --appvm      Install the app + venv under \$HOME in the AppVM
       ./install.sh --help

Env overrides: OO_INSTALL_DIR (default \$HOME/$APP_NAME), OO_PYTHON (default python3.13)
EOF
}

# --------------------------------------------------------------------------- #
# TemplateVM: system packages (persist only when installed in the template)
# --------------------------------------------------------------------------- #
install_template() {
    [ "$(id -u)" -eq 0 ] || die "--template must be run as root (sudo) in the TemplateVM."
    command -v apt-get >/dev/null 2>&1 || die "apt-get not found; this targets a Debian TemplateVM."

    c_grn "Installing system packages in the TemplateVM..."
    # No 2>/dev/null: we WANT to see apt errors.
    apt-get update
    apt-get install -y \
        python3.13 python3.13-venv python3.13-dev \
        build-essential git sqlite3 ca-certificates curl

    if "$PY" --version >/dev/null 2>&1; then
        c_grn "OK: $("$PY" --version) is available."
    else
        c_ylw "WARNING: $PY is not on PATH on this Debian release."
        info  "Install Python 3.13 from a trusted backport/source and re-run, or set"
        info  "OO_PYTHON to the 3.13 interpreter path."
    fi

    cat <<EOF

$(c_grn "TemplateVM step complete.")
Next:
  1. Shut down this TemplateVM.
  2. Reboot the AppVM so the new system packages are visible.
  3. In the AppVM, run:  ./install.sh --appvm
EOF
}

# --------------------------------------------------------------------------- #
# AppVM: virtualenv + app under /home (persistent)
# --------------------------------------------------------------------------- #
install_appvm() {
    [ "$(id -u)" -ne 0 ] || die "--appvm should NOT be run as root; run it as your user in the AppVM."
    command -v "$PY" >/dev/null 2>&1 || die "$PY not found. Run 'sudo ./install.sh --template' in the TemplateVM first, then reboot the AppVM."

    case "$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')" in
        3.13|3.14) : ;;
        *) die "$PY is $("$PY" --version); Python 3.13+ is required." ;;
    esac

    # Locate the repo: prefer the directory this script lives in.
    local src_dir
    src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [ "$src_dir" != "$INSTALL_DIR" ]; then
        if [ -e "$INSTALL_DIR" ]; then
            # NEVER silently destroy an existing install. Back it up, with consent.
            c_ylw "An install already exists at: $INSTALL_DIR"
            read -r -p "Move it aside to a timestamped backup and continue? [y/N] " ans
            [ "$ans" = "y" ] || [ "$ans" = "Y" ] || die "Aborted by user (nothing changed)."
            local backup="${INSTALL_DIR}.bak.$(date +%Y%m%d-%H%M%S)"
            mv "$INSTALL_DIR" "$backup"
            c_grn "Backed up previous install to: $backup"
        fi
        c_grn "Copying source to $INSTALL_DIR ..."
        mkdir -p "$INSTALL_DIR"
        cp -a "$src_dir/." "$INSTALL_DIR/"
    fi

    cd "$INSTALL_DIR"

    c_grn "Creating virtualenv (.venv) under \$HOME ..."
    [ -d .venv ] || "$PY" -m venv .venv
    # shellcheck disable=SC1091
    . .venv/bin/activate

    c_grn "Installing the app (core + analysis extras) ..."
    python -m pip install --upgrade pip setuptools wheel
    python -m pip install -e ".[analysis]"

    c_grn "Initialising the database ..."
    python -c "from src.database.session import init_db; init_db(); print('  database ready')"

    c_grn "Seeding curated starter sources (idempotent; nothing is fetched yet) ..."
    python scripts/seed_sources.py || c_ylw "  (seeding skipped; you can add sources in the UI)"

    cat <<EOF

$(c_grn "AppVM install complete.")  App + data live under: $INSTALL_DIR

To run (loopback only):
  cd "$INSTALL_DIR" && . .venv/bin/activate && open-omniscience
  # then open http://127.0.0.1:8000 in the AppVM browser

Optional local LLM (Phase 2): install Ollama in the TEMPLATEVM (verify its
checksum first -- do not pipe curl straight to a shell), then pull a small model.
EOF
}

main() {
    case "${1:-}" in
        --template) install_template ;;
        --appvm)    install_appvm ;;
        -h|--help|"") usage ;;
        *) usage; die "unknown option: $1" ;;
    esac
}

main "$@"
