#!/usr/bin/env bash
#
# Open Omniscience one-command bootstrap.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# This is the target of the convenience installer:
#
#     curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
#
# (The "HEAD" segment always resolves to the repository's default branch, so the
# link keeps working regardless of how that branch is named.)
#
# It is deliberately small and readable so you can inspect it before trusting it
# (and you should -- piping any script into a shell is a privileged act). It does
# only this: ensure git + Python 3.13 exist, clone (or update) the repository into
# a directory you control, then hand off to the in-repo, menu-driven ./install.sh,
# which is where the real work -- and your component choices -- happen.
#
# Override the install location with OO_INSTALL_DIR (default: $HOME/open-omniscience).
# By default we track the repository's own default branch; pin a branch or tag with
# OO_BRANCH (e.g. OO_BRANCH=v0.4.0 for a release, once one is tagged).

set -euo pipefail

REPO_URL="${OO_REPO_URL:-https://github.com/ideotion/Open-Omniscience.git}"
INSTALL_DIR="${OO_INSTALL_DIR:-$HOME/open-omniscience}"
BRANCH="${OO_BRANCH:-}"          # empty -> use the remote's default branch
PY="${OO_PYTHON:-python3.13}"

red=$'\033[31m'; grn=$'\033[32m'; ylw=$'\033[33m'; bold=$'\033[1m'; rst=$'\033[0m'
die() { printf '%sERROR:%s %s\n' "$red$bold" "$rst" "$*" >&2; exit 1; }

printf '%s\n' "${bold}Open Omniscience bootstrap${rst}"
printf '  Repo:    %s (ref: %s)\n' "$REPO_URL" "${BRANCH:-default branch}"
printf '  Install: %s\n\n' "$INSTALL_DIR"

command -v git >/dev/null 2>&1 || die "git is required. Install it (Debian: sudo apt-get install git) and re-run."
if ! command -v "$PY" >/dev/null 2>&1; then
    printf '%s%s not found.%s\n' "$ylw" "$PY" "$rst"
    die "Python 3.13 is required. On Debian/Qubes, run the TemplateVM step first:
       sudo ./install.sh --template   (after cloning), or install Python 3.13 by hand."
fi

if [ -d "$INSTALL_DIR/.git" ]; then
    printf '%sExisting checkout found -- updating...%s\n' "$grn" "$rst"
    # Default to whatever branch the checkout is already on.
    ref="${BRANCH:-$(git -C "$INSTALL_DIR" rev-parse --abbrev-ref HEAD)}"
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$ref"
    git -C "$INSTALL_DIR" checkout "$ref"
    git -C "$INSTALL_DIR" pull --ff-only origin "$ref"
elif [ -e "$INSTALL_DIR" ]; then
    die "$INSTALL_DIR exists but is not a git checkout. Move it aside or set OO_INSTALL_DIR, then re-run."
else
    printf '%sCloning...%s\n' "$grn" "$rst"
    if [ -n "$BRANCH" ]; then
        git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    else
        # No ref pinned: clone the remote's default branch.
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    fi
fi

printf '\n%sStarting the installer...%s\n\n' "$grn" "$rst"
cd "$INSTALL_DIR"
exec ./install.sh "$@"
