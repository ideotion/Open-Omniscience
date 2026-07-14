#!/usr/bin/env bash
#
# Open Omniscience installer  --  friendly, menu-driven, re-runnable.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# Goals:
#   * One command to install: clone (via scripts/bootstrap.sh) then this script
#     puts up a simple menu and does the rest.
#   * Pick what you want: the Core (scrape / store / search / export) is always
#     installed; Analysis tools, storage Compression accelerators and Local-LLM
#     tools are optional and can be added later by simply re-running this script
#     -- it is idempotent.
#   * A double-click launcher so non-technical users never need the terminal.
#
# Modes:
#   ./install.sh                 interactive menu (default)
#   ./install.sh --template      Qubes: install system packages in the TemplateVM
#   ./install.sh --appvm         Qubes: non-interactive Core+Analysis+Compression under $HOME
#   ./install.sh --unattended    scripted install driven by env vars (see below)
#   ./install.sh --help
#
# Unattended env vars (also used by CI):
#   OO_COMPONENTS="analysis"       extras to add on top of core (comma-separated)
#   OO_MAKE_LAUNCHER=1             create the desktop launcher (default yes; 0 to skip)
#   OO_AUTOSTART=1                 enable login autostart (opt-in; default off; boots offline)
#   OO_PYTHON=python3.13           interpreter to use
#   OO_SKIP_PIP=1 / OO_SKIP_DB=1   skip the pip install / db init (testing only)
#
# Safety: set -euo; never an unconfirmed 'rm -rf'; never a blind 'curl | sh' for
# third-party software without showing the command and asking first.

set -euo pipefail

APP_NAME="open-omniscience"
PY="${OO_PYTHON:-python3.13}"
# This script installs the checkout it lives in, in place.
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --------------------------------------------------------------------------- #
# Pretty output (works with or without a TTY)
# --------------------------------------------------------------------------- #
if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
    YLW=$'\033[33m'; BLU=$'\033[36m'; RST=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GRN=""; YLW=""; BLU=""; RST=""
fi
say()   { printf '%s\n' "$*"; }
step()  { printf '%s==>%s %s\n' "$BLU$BOLD" "$RST" "$*"; }
ok()    { printf '%s  ok%s %s\n' "$GRN" "$RST" "$*"; }
warn()  { printf '%s  !!%s %s\n' "$YLW" "$RST" "$*"; }
die()   { printf '%sERROR:%s %s\n' "$RED$BOLD" "$RST" "$*" >&2; exit 1; }

# Where to read interactive answers from. Under `curl | bash`, stdin is the
# script itself (a pipe), not the keyboard -- so reading prompts from stdin would
# get EOF/garbage. Prompt from the controlling terminal (/dev/tty) when stdin is a
# pipe but a terminal is attached (stdout is a TTY). With no terminal at all (CI,
# fully non-interactive), fall back to safe defaults instead of blocking.
INTERACTIVE=0
TTY_IN="/dev/stdin"
if [ -t 0 ]; then
    INTERACTIVE=1
elif [ -t 1 ] && [ -r /dev/tty ]; then
    INTERACTIVE=1; TTY_IN="/dev/tty"
fi

# Use whiptail for a real boxed TUI when available AND we have a terminal to drive it.
HAVE_WHIPTAIL=0
if command -v whiptail >/dev/null 2>&1 && [ "$INTERACTIVE" = "1" ]; then HAVE_WHIPTAIL=1; fi
UNATTENDED="${OO_UNATTENDED:-0}"

banner() {
    if [ -f "$SRC_DIR/assets/logo.txt" ]; then
        printf '%s' "$BOLD"; cat "$SRC_DIR/assets/logo.txt"; printf '%s' "$RST"
    fi
    printf '%s        Open Omniscience%s\n' "$BOLD" "$RST"
    printf '%s  Local-first, ethical intelligence platform for investigative journalism%s\n' "$DIM" "$RST"
}

usage() {
    cat <<EOF
Open Omniscience installer

Usage:
  ./install.sh                 Interactive menu (recommended)
  ./install.sh --appvm         Qubes AppVM: Core + Analysis + Compression under \$HOME (no prompts)
  sudo ./install.sh --template Qubes TemplateVM: install system packages (run once)
  ./install.sh --unattended    Scripted install (driven by OO_* env vars)
  ./install.sh --check         Health check (Python, data, db, LLM, launcher)
  ./install.sh --uninstall     Remove the virtualenv and launcher (data kept by default)
  ./install.sh --help

After install, a "${BOLD}Open Omniscience${RST}" launcher appears in your applications
menu (and on your Desktop) -- double-click it to start the app.
EOF
}

# --------------------------------------------------------------------------- #
# Rough download-size estimates (so the user knows what they're in for)
# --------------------------------------------------------------------------- #
# Approximate DOWNLOADED-wheel sizes per component, in MB. Measured from a clean
# Linux / Python 3.13 install on 2026-06 (the real pip download log). These are
# advisory: actual bytes vary by OS / arch / Python, and pip never re-downloads a
# wheel it already has cached. The unpacked on-disk footprint is larger than the
# download. Keep this dated and refresh when the dependency set changes materially.
SIZES_AS_OF="2026-06"
_CORE_MB=55          # always installed (FastAPI, SQLCipher, lxml, crypto, Pillow…)

# component_mb COMPONENT -> echoes an integer MB estimate (0 if unknown).
component_mb() {
    case "$1" in
        core)        echo 55 ;;   # the always-installed spine
        analysis)    echo 90 ;;   # numpy/pandas/scipy/scikit-learn/statsmodels/nltk…
        compression) echo 7  ;;   # zstandard + lz4
        columnar)    echo 25 ;;   # duckdb (the in-memory rollup serve for large-corpus analytics)
        llm)         echo 1  ;;   # python extra only; Ollama + model are separate (see below)
        nlp)         echo 60 ;;   # spaCy wheels (a language model is fetched separately)
        *)           echo 0  ;;
    esac
}

# human_mb MB -> "~X MB" for <1 GB, "~X.X GB" above.
human_mb() {
    local mb="${1:-0}"
    if [ "$mb" -ge 1024 ]; then
        printf '~%d.%d GB' "$((mb / 1024))" "$(((mb % 1024) * 10 / 1024))"
    else
        printf '~%d MB' "$mb"
    fi
}

# extras_total_mb "a,b" -> echoes core + chosen extras, in MB.
extras_total_mb() {
    local total="$_CORE_MB" e
    local -a arr
    IFS=',' read -ra arr <<<"${1:-}"
    for e in ${arr[@]+"${arr[@]}"}; do
        [ -n "$e" ] && total=$((total + $(component_mb "$e")))
    done
    echo "$total"
}

# Print a friendly "here's roughly how much will download" estimate for the
# selected components. Honest about what it does and doesn't cover.
print_download_estimate() {
    local extras="$1" total e
    total="$(extras_total_mb "$extras")"
    local breakdown="core $(human_mb "$_CORE_MB")"
    local -a arr
    IFS=',' read -ra arr <<<"$extras"
    for e in ${arr[@]+"${arr[@]}"}; do
        [ -n "$e" ] && breakdown="$breakdown + $e $(human_mb "$(component_mb "$e")")"
    done
    say ""
    say "  ${BOLD}Estimated download:${RST} $(human_mb "$total") of Python packages"
    say "    ${DIM}$breakdown${RST}"
    say "    ${DIM}Rough, measured $SIZES_AS_OF; varies by OS/arch; already-cached wheels won't re-download.${RST}"
    case ",$extras," in
        *,llm,*) say "    ${DIM}Local LLM: Ollama adds ~1 GB, plus a model (~0.8–2.7 GB), downloaded separately.${RST}" ;;
    esac
}

# --------------------------------------------------------------------------- #
# Component selection
# --------------------------------------------------------------------------- #
# Echoes a comma-separated extras list (may be empty). Core is always installed.
# Sets the global CHOSEN_EXTRAS (a comma-separated extras string, possibly empty).
# IMPORTANT: this function must NOT be called via command substitution -- it prints
# UI (banners/prompts) to stdout/stderr, so capturing its stdout would fold that UI
# into the result. Returning through a global keeps the menu and the value separate.
CHOSEN_EXTRAS=""
choose_components() {
    # Seamless install (maintainer 2026-06-20): NO component menu, NO prompts. Install
    # the sensible default set -- Core (always) + Analysis + Compression + Columnar.
    # Columnar (duckdb) is included by default (field ask 2026-07-02) so the in-memory
    # rollup serve engages AUTOMATICALLY on a large corpus -- without duckdb the windowed
    # analytics can only scan the multi-GB mentions table and freeze. Power users and CI
    # can still override with OO_COMPONENTS="...". Ollama / local-LLM provisioning is
    # never offered here; it lives entirely in the app's Settings -> AI tab.
    CHOSEN_EXTRAS="${OO_COMPONENTS:-analysis,compression,columnar}"
}

# ask_yn "question" default(y/n) -> returns 0 for yes
ask_yn() {
    local q="$1" def="${2:-n}" ans
    # No terminal (unattended or piped with no tty) -> take the default, never block.
    if [ "$UNATTENDED" = "1" ] || [ "$INTERACTIVE" = "0" ]; then [ "$def" = "y" ]; return; fi
    if [ "$HAVE_WHIPTAIL" = "1" ]; then
        if [ "$def" = "y" ]; then whiptail --yesno "$q" 10 70 < "$TTY_IN"; else whiptail --defaultno --yesno "$q" 10 70 < "$TTY_IN"; fi
        return
    fi
    local hint="[y/N]"; [ "$def" = "y" ] && hint="[Y/n]"
    # Read from the controlling terminal: under `curl | bash` stdin is the script.
    read -r -p "  $q $hint " ans < "$TTY_IN" || true
    ans="${ans:-$def}"
    [ "$ans" = "y" ] || [ "$ans" = "Y" ]
}

# --------------------------------------------------------------------------- #
# Build steps
# --------------------------------------------------------------------------- #
ensure_python() {
    command -v "$PY" >/dev/null 2>&1 || die "$PY not found. Install Python 3.13 (on Qubes: 'sudo ./install.sh --template' in the TemplateVM, then reboot)."
    case "$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')" in
        3.13|3.14) ok "Using $("$PY" --version)";;
        *) die "$PY is $("$PY" --version); this project targets Python 3.13+.";;
    esac
}

# Best-effort Tails detection -- only tailors guidance, so a miss just yields the
# generic (still correct) message. Tails is amnesic Debian: sudo needs an
# administration password set at the Welcome Screen, apt runs over Tor, and any apt
# package is lost on reboot unless added to Persistent Storage -> Additional Software.
is_tails() {
    { [ -e /etc/amnesia/version ] || [ -d /etc/amnesia ]; } && return 0
    grep -qiE '^(ID|NAME|PRETTY_NAME)=.*tails|^TAILS_' /etc/os-release 2>/dev/null
}

# Install the apt package that provides the stdlib venv/ensurepip for $PY, so a
# fresh Debian/Ubuntu/Tails box installs seamlessly instead of stopping at the
# cryptic CPython "ensurepip is not available" error. Returns 0 only when ensurepip
# is importable afterwards. Seamless by default; opt out with OO_NO_APT=1. Never
# blocks on a sudo password prompt that nothing can answer (CI / --unattended / no TTY).
try_apt_install_venv() {
    local pkg="$1" sudo=""
    [ "${OO_NO_APT:-0}" = "1" ] && return 1
    command -v apt-get >/dev/null 2>&1 || return 1
    if [ "$(id -u)" -ne 0 ]; then
        command -v sudo >/dev/null 2>&1 || return 1
        # Passwordless sudo -> run apt with `sudo -n` (never prompts). Otherwise a
        # password prompt is only acceptable when a human is at the terminal (an
        # interactive, non-scripted session; sudo reads /dev/tty, fine under
        # `curl | bash`). Everywhere else (CI / --unattended / no TTY) keep `sudo -n`
        # so apt FAILS FAST instead of blocking on a prompt nothing can answer.
        if sudo -n true 2>/dev/null; then
            sudo="sudo -n"
        elif [ "$INTERACTIVE" = "1" ] && [ "$UNATTENDED" != "1" ]; then
            sudo="sudo"
        else
            return 1
        fi
    fi
    step "Installing the missing venv package: $pkg (needs administrator rights)"
    if is_tails; then
        say "  ${DIM}On Tails this needs an administration password (set at the Welcome"
        say "  Screen -- it is off by default) and a Tor connection; apt downloads over Tor.${RST}"
    fi
    # DEBIAN_FRONTEND=noninteractive (via `env`, so it survives sudo's env reset) means a
    # debconf prompt can never hang a tty-less run. A flaky `apt-get update` -- a partial
    # mirror, common on Tails over Tor -- must NOT fail an otherwise-installable package,
    # so it is best-effort; only the install gates success.
    $sudo env DEBIAN_FRONTEND=noninteractive apt-get update >/dev/null 2>&1 || true
    $sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" || return 1
    "$PY" -c 'import ensurepip' >/dev/null 2>&1
}

create_venv() {
    cd "$SRC_DIR"
    if [ ! -d .venv ]; then
        # On Debian/Ubuntu/Tails the stdlib venv/ensurepip module ships in a SEPARATE
        # apt package. If it is missing, install it AUTOMATICALLY (seamless on Tails),
        # and only fall back to manual guidance when that can't be done here -- never
        # leak the cryptic CPython "ensurepip is not available" error.
        if ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
            venv_pkg="python3-venv"
            case "$PY" in *3.13*) venv_pkg="python3.13-venv";; esac
            if try_apt_install_venv "$venv_pkg"; then
                ok "Installed $venv_pkg"
            else
                tails_note=""
                if is_tails; then
                    tails_note="
    On Tails: set an administration password at the Welcome Screen (it is off by
    default) and connect to Tor, then re-run ./install.sh. Tails is amnesic, so to
    keep $venv_pkg across reboots add it via Persistent Storage -> Additional
    Software. (Tails ships Python 3.11; a versioned package for a separately
    installed Python may not be in the default repositories.)"
                fi
                die "Python's venv module is missing (no ensurepip) and it could not be
    installed automatically. Install it, then re-run ./install.sh:
        sudo apt update && sudo apt install -y $venv_pkg
    On Qubes, install it in the TemplateVM (then reboot the AppVM) so DispVMs and
    AppVMs inherit it -- packages installed in an AppVM/DispVM do not persist.${tails_note}"
            fi
        fi
        step "Creating virtual environment (.venv)"
        "$PY" -m venv .venv
    fi
    # shellcheck disable=SC1091
    . .venv/bin/activate
    ok "Virtual environment ready"
}

pip_install() {
    local extras="$1" spec=".[$extras]"
    [ -n "$extras" ] || spec="."
    # Defense in depth: extras must be a simple comma-separated token list. If
    # anything else slipped in (e.g. captured UI text), fail loudly with a clear
    # message instead of handing pip a malformed '.[...]' spec.
    if [ -n "$extras" ] && ! printf '%s' "$extras" | grep -qE '^[A-Za-z0-9_.,-]+$'; then
        die "Internal error: invalid component spec '$extras'. Please report this."
    fi
    # Tell the user roughly how much will download before the long step begins.
    print_download_estimate "$extras"
    if [ "${OO_SKIP_PIP:-0}" = "1" ]; then warn "OO_SKIP_PIP=1 -- skipping pip install ($spec)"; return; fi
    step "Installing the app: $spec"
    # Resilience for two field-test failures (Qubes disposable VMs especially):
    #  * NETWORK: a flaky link drops DNS mid-resolution; pip's default 15s timeout
    #    then BACKTRACKS through every version and emits a MISLEADING
    #    "ResolutionImpossible / no matching distribution". -> longer timeout + retries.
    #  * DISK: pip unpacks big scientific wheels (scipy/numpy/pandas) in TMPDIR, which
    #    on Qubes is /tmp = a SMALL RAM-backed tmpfs, so it hits "No space left on
    #    device (Errno 28)" even though the private (home) volume has plenty of room.
    #    -> point TMPDIR at the install volume so unpacking has space.
    local pip_opts="--retries 5 --timeout 60"
    local pip_tmp="${XDG_CACHE_HOME:-$HOME/.cache}/oo-pip-build"
    mkdir -p "$pip_tmp"
    local log; log="$(mktemp "${pip_tmp}/pip-log-XXXXXX" 2>/dev/null || echo "${pip_tmp}/pip.log")"
    TMPDIR="$pip_tmp" python -m pip install $pip_opts --upgrade pip setuptools wheel >/dev/null 2>&1 || true
    local attempt delay=4
    for attempt in 1 2 3; do
        if TMPDIR="$pip_tmp" python -m pip install $pip_opts -e "$spec" 2>&1 | tee "$log"; then
            rm -f "$log"; ok "Python packages installed"; return 0
        fi
        # Disk-full will NOT clear by retrying the same install -- diagnose + stop.
        if grep -qiE "No space left on device|Errno 28" "$log" 2>/dev/null; then
            echo ""
            warn "Out of disk space while installing (pip: 'No space left on device')."
            echo "     pip unpacks large packages in a temp dir. On Qubes, /tmp is a small"
            echo "     RAM-backed volume, so this can hit even when your home volume is fine."
            echo "     This installer already points pip's temp at: $pip_tmp"
            echo "     Check what is actually full (look at the 'Avail' column):"
            echo "         df -h /tmp \"$pip_tmp\" \"$SRC_DIR\""
            echo "     Fixes: free space on the FULL volume, or in Qubes increase this VM's"
            echo "       private storage (Qube Settings -> Disk storage), then re-run:"
            echo "         cd \"$SRC_DIR\" && ./install.sh --unattended"
            rm -f "$log"
            die "Python package installation failed: out of disk space (see guidance above)."
        fi
        if [ "$attempt" -lt 3 ]; then
            warn "pip install failed (attempt $attempt/3) -- likely a network hiccup; retrying in ${delay}s..."
            sleep "$delay"; delay=$((delay * 4))
        fi
    done
    rm -f "$log"
    # Persistent NON-disk failure: be HONEST about the most common cause (network)
    # instead of echoing pip's confusing resolver error.
    echo ""
    warn "Could not install the Python packages after 3 attempts."
    echo "     This is almost always a NETWORK problem, not a dependency conflict:"
    echo "       • pip messages like 'Temporary failure in name resolution',"
    echo "         'Read timed out', or 'ResolutionImpossible / no matching distribution'"
    echo "         usually mean the connection dropped mid-download."
    echo "     Try:"
    echo "       1. Check connectivity + DNS:  getent hosts files.pythonhosted.org"
    echo "       2. Re-run the installer -- downloaded wheels are cached, so it resumes:"
    echo "            cd \"$SRC_DIR\" && ./install.sh --unattended"
    die "Python package installation failed (see network guidance above)."
}

init_database() {
    if [ "${OO_SKIP_DB:-0}" = "1" ]; then warn "OO_SKIP_DB=1 -- skipping database init"; return; fi
    step "Preparing the database"
    # Encryption is ON BY DEFAULT (SQLCipher). A FRESH store needs THE user's
    # passphrase choice -- and that choice belongs to the app's first-launch
    # screen IN THE BROWSER (language -> terms & conditions -> passphrase), NOT
    # the installer. So the installer never prompts for a passphrase: it only
    # initialises when the choice is ALREADY made -- an existing store, or an
    # explicit headless env choice (OO_DB_PASSPHRASE / OO_DB_PLAINTEXT). In every
    # other case it DEFERS silently to first launch. Never a prompt here, never a
    # traceback, never a silent default. (Field-tested: a blind init on a fresh
    # encrypted-by-default store would crash; deferral seeds at first unlocked boot.)
    if _try_db_init; then
        _seed_sources
        return 0
    fi
    warn "Database setup deferred to first launch."
    echo "     When the app starts it walks you through a short setup IN YOUR"
    echo "     BROWSER -- choose your language, accept the terms, then create THE"
    echo "     passphrase (encrypted at rest by default; there is NO recovery -- the"
    echo "     app explains before you confirm). Starter sources seed themselves at"
    echo "     that first unlocked start; nothing is lost by deferring."
}

_try_db_init() {
    python -c "from src.database.session import init_db; init_db(); print('  database ready')" 2>/dev/null
}

_seed_sources() {
    step "Seeding curated starter sources (idempotent; nothing is fetched)"
    python scripts/seed_sources.py || warn "seeding skipped; you can add sources in the UI"
}

# --------------------------------------------------------------------------- #
# Local LLM (Ollama): NOT provisioned by the installer (maintainer 2026-06-20).
# Installing Ollama, pulling/removing models and choosing the active model all live
# in the app's Settings -> AI tab. The helper below only makes an ALREADY-installed
# model store readable for in-app backup; it is retained (and pinned by
# tests/test_installer.py) but NOT called by the default install -- the AI tab owns
# provisioning, so the installer never runs a third-party installer or prompts.
# --------------------------------------------------------------------------- #
# Make Ollama's model store readable so the in-app "Back up models" works without
# the user touching systemd (maintainer 2026-06-18: this app targets journalists,
# not people who hand-edit OLLAMA_MODELS). The official Linux installer runs the
# service as the 'ollama' system user, so models land under /usr/share/ollama (that
# user's home, mode 0700) — unreadable by the human user, so the backup silently
# finds nothing. We grant READ-only access to the model blobs (public data, never
# made writable) and traverse rights to the parent dirs, while deliberately LEAVING
# the service's private key (id_ed25519) untouched. Best-effort + non-fatal: on any
# failure Ollama keeps working and the app still shows in-app guidance (PR #354).
# Opt out with OO_OLLAMA_READABLE=0.
configure_ollama_store_access() {
    [ "${OO_OLLAMA_READABLE:-1}" = "0" ] && return 0
    local models="/usr/share/ollama/.ollama/models"
    [ -d "$models" ] || return 0   # only the protected systemd-service store needs this

    step "Making the Ollama model store readable for in-app backup"
    say "  ${DIM}The Ollama service keeps models under /usr/share/ollama (the 'ollama'${RST}"
    say "  ${DIM}user's home, mode 0700), so the app can't read them to back them up.${RST}"
    say "  ${DIM}Granting READ-only access to the model blobs (public data, never made${RST}"
    say "  ${DIM}writable); the service's private key is left untouched.${RST}"

    local SUDO=""
    if [ "$(id -u)" != "0" ]; then
        if command -v sudo >/dev/null 2>&1; then
            SUDO="sudo"
        else
            warn "Need root to adjust permissions; to enable model backup later, run:"
            say  "    chmod a+x /usr/share/ollama /usr/share/ollama/.ollama"
            say  "    chmod -R a+rX $models"
            return 0
        fi
    fi
    # a+x on the parent dirs = traverse only (does NOT expose the private key file,
    # which keeps its own 0600); a+rX on the models tree = read the public blobs.
    if $SUDO chmod a+x /usr/share/ollama /usr/share/ollama/.ollama 2>/dev/null \
       && $SUDO chmod -R a+rX "$models" 2>/dev/null; then
        ok "Ollama models are now readable for in-app backup."
    else
        warn "Couldn't set permissions automatically. To enable model backup, run:"
        say  "    sudo chmod a+x /usr/share/ollama /usr/share/ollama/.ollama"
        say  "    sudo chmod -R a+rX $models"
        say  "  ${DIM}Or relocate the store via OLLAMA_MODELS (Settings → Models explains).${RST}"
    fi
}

# --------------------------------------------------------------------------- #
# Double-click launcher (desktop integration)
# --------------------------------------------------------------------------- #
# A11 (DispVM durability): persist an opt-in OO_DATA_DIR into the launcher env so the corpus
# lives on a bind-mounted/external volume and SURVIVES on a disposable/ephemeral VM (the
# 2026-07-09 field event: a disposable-VM crash vaporized a ~60K-article corpus). Seamless:
# no prompt -- a user runs `OO_DATA_DIR=/mnt/persist/oo ./install.sh`. The path is validated
# (creatable + writable) and recorded 0600 in oo.env, which launch.sh sources on every start.
persist_data_dir() {
    local dd="${OO_DATA_DIR:-}"
    [ -n "$dd" ] || return 0
    case "$dd" in "~/"*) dd="$HOME/${dd#\~/}" ;; esac
    if ! mkdir -p "$dd" 2>/dev/null || [ ! -w "$dd" ]; then
        warn "OO_DATA_DIR='$dd' is not usable (not creatable/writable) — keeping the default data location."
        return 0
    fi
    local abs envf tmp
    abs="$(cd "$dd" && pwd)"
    envf="$SRC_DIR/oo.env"
    tmp="$(mktemp "${SRC_DIR}/.oo-env-XXXXXX" 2>/dev/null || echo "${envf}.tmp")"
    { [ -f "$envf" ] && grep -v '^export OO_DATA_DIR=' "$envf" 2>/dev/null; } > "$tmp" || true
    printf 'export OO_DATA_DIR=%q\n' "$abs" >> "$tmp"
    mv "$tmp" "$envf"
    chmod 600 "$envf" 2>/dev/null || true
    ok "Persistent data location recorded: $abs — the corpus will survive restarts there."
}

make_launcher() {
    # Seamless: create the launcher by default, no prompt (maintainer 2026-06-20).
    # OO_MAKE_LAUNCHER=0 still opts out (tests + power users).
    local want="${OO_MAKE_LAUNCHER:-1}"
    [ "$want" = "1" ] || return 0

    chmod +x "$SRC_DIR/scripts/launch.sh" 2>/dev/null || true

    # ONE launcher, ONE interface (maintainer verdict 2026-06-10) — the
    # experimental "Desk" UI was retired; see docs/DESIGN.md for the history.
    local os; os="$(uname -s)"
    if [ "$os" = "Darwin" ]; then
        # macOS: a double-clickable .command file on the Desktop.
        mkdir -p "$HOME/Desktop"
        local cmd_console="$HOME/Desktop/Open Omniscience.command"
        cat > "$cmd_console" <<EOF
#!/usr/bin/env bash
exec "$SRC_DIR/scripts/launch.sh" console
EOF
        # An Uninstall icon next to the launcher (runs the confirmed --uninstall flow).
        local cmd_uninstall="$HOME/Desktop/Uninstall Open Omniscience.command"
        cat > "$cmd_uninstall" <<EOF
#!/usr/bin/env bash
exec "$SRC_DIR/install.sh" --uninstall
EOF
        chmod +x "$cmd_console" "$cmd_uninstall"
        # Consolidation: remove the Desk launcher from older installs.
        rm -f "$HOME/Desktop/Open Omniscience — Desk.command" 2>/dev/null || true
        ok "Created launchers: 'Open Omniscience' and 'Uninstall Open Omniscience' on your Desktop."
        say "  ${BOLD}To start:${RST} double-click the app icon."
        return 0
    fi

    # Linux: one .desktop entry in the applications menu (+ a copy on the Desktop).
    local apps="$HOME/.local/share/applications"
    mkdir -p "$apps"
    local desk; desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
    # PNG renders more reliably than SVG on minimal desktops (notably some Qubes
    # AppVMs); fall back to the SVG source if no PNG is present.
    local icon_console="$SRC_DIR/assets/icon.png";   [ -f "$icon_console" ] || icon_console="$SRC_DIR/assets/icon.svg"

    # $1=basename  $2=Name  $3=Comment  $4=launch variant  $5=icon
    _mk_desktop() {
        local f="$apps/$1.desktop"
        cat > "$f" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$2
GenericName=Intelligence Platform
Comment=$3
Exec="$SRC_DIR/scripts/launch.sh" $4
Icon=$5
Terminal=true
Categories=Utility;News;Office;
Keywords=news;intelligence;journalism;research;osint;
StartupNotify=false
EOF
        chmod +x "$f"
        if [ -d "$desk" ]; then
            cp "$f" "$desk/$1.desktop"; chmod +x "$desk/$1.desktop"
            gio set "$desk/$1.desktop" metadata::trusted true 2>/dev/null || true
        fi
    }
    _mk_desktop "$APP_NAME" "Open Omniscience" "Local-first intelligence platform for investigative journalism" "console" "$icon_console"
    # Desk was retired entirely: remove its launcher from older installs.
    rm -f "$apps/$APP_NAME-desk.desktop" "$desk/$APP_NAME-desk.desktop" 2>/dev/null || true

    # An "Uninstall" entry alongside the launchers. It runs install.sh --uninstall in a
    # terminal (Terminal=true) so the existing confirmation prompts are shown; it removes
    # the virtualenv + launchers and keeps your data unless you separately confirm.
    local uf="$apps/$APP_NAME-uninstall.desktop"
    cat > "$uf" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Uninstall Open Omniscience
GenericName=Uninstaller
Comment=Remove the Open Omniscience virtualenv and launchers (your data is kept unless you confirm)
Exec="$SRC_DIR/install.sh" --uninstall
Icon=$icon_console
Terminal=true
Categories=Utility;
Keywords=uninstall;remove;
StartupNotify=false
EOF
    chmod +x "$uf"
    if [ -d "$desk" ]; then
        cp "$uf" "$desk/$APP_NAME-uninstall.desktop"; chmod +x "$desk/$APP_NAME-uninstall.desktop"
        gio set "$desk/$APP_NAME-uninstall.desktop" metadata::trusted true 2>/dev/null || true
    fi
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" 2>/dev/null || true

    ok "Created the 'Open Omniscience' launcher in your applications menu${desk:+ and on the Desktop}"
    say ""
    say "  ${BOLD}How to start the app:${RST} double-click ${BOLD}Open Omniscience${RST}."
    say "    A terminal window opens, the app starts, and your browser opens to"
    say "    ${BLU}http://127.0.0.1:8000${RST}. Close that window to stop the app."
}

setup_autostart() {
    # OPT-IN ONLY (maintainer 2026-06-21: never add login-autostart silently). The
    # app boots in AIRPLANE mode (zero network) so launching at login is safe; going
    # online still passes the one consent popup inside the app.
    [ "${OO_AUTOSTART:-0}" = "1" ] || return 0

    local os; os="$(uname -s)"
    if [ "$os" = "Darwin" ]; then
        local la="$HOME/Library/LaunchAgents"
        mkdir -p "$la"
        local plist="$la/com.open-omniscience.autostart.plist"
        cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.open-omniscience.autostart</string>
  <key>ProgramArguments</key><array>
    <string>$SRC_DIR/scripts/launch.sh</string><string>console</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
        ok "Enabled login autostart (launches in airplane mode). Remove: rm '$plist'"
        return 0
    fi

    # Linux: an XDG autostart entry (~/.config/autostart). Honoured by GNOME/KDE/etc.
    local ad="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
    mkdir -p "$ad"
    local af="$ad/$APP_NAME.desktop"
    local icon_console="$SRC_DIR/assets/icon.png"; [ -f "$icon_console" ] || icon_console="$SRC_DIR/assets/icon.svg"
    cat > "$af" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Open Omniscience
Comment=Start Open Omniscience at login (boots offline / airplane mode)
Exec="$SRC_DIR/scripts/launch.sh" console
Icon=$icon_console
Terminal=true
X-GNOME-Autostart-enabled=true
EOF
    chmod +x "$af"
    ok "Enabled login autostart (launches in airplane mode). Remove: rm '$af'"
}

# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
do_install() {
    local extras="$1"
    ensure_python
    create_venv
    pip_install "$extras"
    persist_data_dir   # record an opt-in persistent OO_DATA_DIR before the DB is initialised there
    init_database
    make_launcher
    setup_autostart
    say ""
    ok "${BOLD}Install complete.${RST} App + data live under: $SRC_DIR"
    say "  Re-launch any time from your applications menu, or with:"
    say "    ${DIM}cd '$SRC_DIR' && ./scripts/launch.sh${RST}"
    say "  Add components later by re-running: ${DIM}./install.sh${RST}"
}

# End the install "inside the running app": start the local server and open the
# browser, so the first thing the user sees is the app's own first-launch setup
# (language -> terms -> passphrase). Interactive installs only -- never CI /
# --unattended / --appvm, and never when there is nothing installed to run.
# Opt out with OO_AUTOLAUNCH=0.
maybe_launch() {
    [ "${OO_AUTOLAUNCH:-1}" = "1" ]   || return 0
    [ "$UNATTENDED" = "1" ]           && return 0
    [ "$INTERACTIVE" = "1" ]          || return 0
    [ "${OO_SKIP_PIP:-0}" = "1" ]     && return 0   # nothing was installed (tests)
    [ -x "$SRC_DIR/scripts/launch.sh" ] || return 0
    say ""
    step "Starting Open Omniscience…"
    say "  Your browser opens at ${BLU}http://127.0.0.1:8000${RST} (offline by default)."
    say "  ${DIM}To stop: close that window (or press Ctrl-C).${RST}"
    # Hand off to the launcher (it starts the server, waits for health, opens the
    # browser, and holds the server until the window closes). exec so closing the
    # window cleanly stops the app.
    exec "$SRC_DIR/scripts/launch.sh" console
}

run_interactive() {
    banner
    choose_components            # sets CHOSEN_EXTRAS (does not pollute stdout)
    local extras="$CHOSEN_EXTRAS"
    step "Selected components: core${extras:+, $extras}"
    do_install "$extras"
    maybe_launch
}

# --------------------------------------------------------------------------- #
# Qubes TemplateVM (system packages persist only when installed in the template)
# --------------------------------------------------------------------------- #
install_template() {
    [ "$(id -u)" -eq 0 ] || die "--template must be run as root (sudo) in the TemplateVM."
    command -v apt-get >/dev/null 2>&1 || die "apt-get not found; this targets a Debian TemplateVM."
    step "Installing system packages in the TemplateVM"
    apt-get update
    apt-get install -y \
        python3.13 python3.13-venv python3.13-dev \
        build-essential git sqlite3 ca-certificates curl whiptail
    cat <<EOF

$(ok "TemplateVM step complete.")
Next:
  1. Shut down this TemplateVM.
  2. Reboot the AppVM so the new system packages are visible.
  3. In the AppVM, run:  ./install.sh
EOF
}

# --------------------------------------------------------------------------- #
# Health check -- delegates to `open-omniscience doctor` inside the venv.
# --------------------------------------------------------------------------- #
do_check() {
    cd "$SRC_DIR"
    [ -d .venv ] || die "Not installed yet (no .venv). Run ./install.sh first."
    # shellcheck disable=SC1091
    . .venv/bin/activate
    exec open-omniscience doctor
}

# --------------------------------------------------------------------------- #
# Uninstall -- remove only what we created. Never deletes data without an
# explicit, separate confirmation; never touches the cloned repo itself.
# --------------------------------------------------------------------------- #
do_uninstall() {
    banner
    step "Uninstalling Open Omniscience"

    # Discover the data dir (best-effort) before we remove the venv.
    local data_dir=""
    if [ -d "$SRC_DIR/.venv" ]; then
        data_dir="$("$SRC_DIR/.venv/bin/python" -c 'from src.paths import data_dir; print(data_dir())' 2>/dev/null || true)"
    fi

    # Collect launcher files that exist (Console + Desk, apps menu + Desktop + macOS).
    local desk; desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
    local apps="$HOME/.local/share/applications/$APP_NAME.desktop"
    local apps_desk="$HOME/.local/share/applications/$APP_NAME-desk.desktop"
    local desk_file="$desk/$APP_NAME.desktop"
    local desk_file_desk="$desk/$APP_NAME-desk.desktop"
    local mac_file="$HOME/Desktop/Open Omniscience.command"
    local mac_file_desk="$HOME/Desktop/Open Omniscience — Desk.command"
    local apps_uninstall="$HOME/.local/share/applications/$APP_NAME-uninstall.desktop"
    local desk_file_uninstall="$desk/$APP_NAME-uninstall.desktop"
    local mac_file_uninstall="$HOME/Desktop/Uninstall Open Omniscience.command"
    local autostart_file="${XDG_CONFIG_HOME:-$HOME/.config}/autostart/$APP_NAME.desktop"
    local mac_autostart="$HOME/Library/LaunchAgents/com.open-omniscience.autostart.plist"

    say ""
    say "  The following will be ${BOLD}removed${RST}:"
    [ -d "$SRC_DIR/.venv" ]      && say "    • virtualenv:  $SRC_DIR/.venv"
    [ -f "$apps" ]               && say "    • launcher:    $apps"
    [ -f "$apps_desk" ]          && say "    • launcher:    $apps_desk"
    [ -f "$apps_uninstall" ]     && say "    • launcher:    $apps_uninstall"
    [ -f "$desk_file" ]          && say "    • launcher:    $desk_file"
    [ -f "$desk_file_desk" ]     && say "    • launcher:    $desk_file_desk"
    [ -f "$desk_file_uninstall" ] && say "    • launcher:    $desk_file_uninstall"
    [ -f "$mac_file" ]           && say "    • launcher:    $mac_file"
    [ -f "$mac_file_desk" ]      && say "    • launcher:    $mac_file_desk"
    [ -f "$mac_file_uninstall" ] && say "    • launcher:    $mac_file_uninstall"
    [ -f "$autostart_file" ]     && say "    • autostart:   $autostart_file"
    [ -f "$mac_autostart" ]      && say "    • autostart:   $mac_autostart"
    say "  Your repository ($SRC_DIR) and your data will be ${BOLD}kept${RST} unless you choose otherwise."
    say ""

    # OO_ASSUME_YES=1 confirms the venv/launcher removal non-interactively (for
    # scripted uninstalls). It deliberately does NOT auto-confirm data deletion
    # below -- destroying data always requires a real, interactive yes.
    if [ "${OO_ASSUME_YES:-0}" != "1" ] && ! ask_yn "Proceed with removing the virtualenv and launcher?" n; then
        warn "Aborted; nothing was removed."
        return 0
    fi

    rm -f "$apps" "$apps_desk" "$apps_uninstall" \
          "$desk_file" "$desk_file_desk" "$desk_file_uninstall" \
          "$mac_file" "$mac_file_desk" "$mac_file_uninstall" \
          "$autostart_file" "$mac_autostart"
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    [ -d "$SRC_DIR/.venv" ] && rm -rf "$SRC_DIR/.venv"
    ok "Removed virtualenv and launcher."

    # Data is precious -- ask separately, defaulting to keep.
    if [ -n "$data_dir" ] && [ -d "$data_dir" ]; then
        say ""
        say "  Your data (database, signing keys, exports) lives at:"
        say "    ${BOLD}$data_dir${RST}"
        if ask_yn "Also DELETE this data directory? This cannot be undone." n; then
            if ask_yn "Are you sure? Permanently delete $data_dir ?" n; then
                rm -rf "$data_dir"
                ok "Deleted data directory."
            else
                warn "Kept data directory."
            fi
        else
            warn "Kept data directory ($data_dir)."
        fi
    fi

    say ""
    ok "${BOLD}Uninstall complete.${RST}"
    say "  To remove the app entirely, delete the folder: ${DIM}rm -rf '$SRC_DIR'${RST}"
}

main() {
    case "${1:-}" in
        ""|--menu|--interactive) run_interactive ;;
        --template)              install_template ;;
        --appvm)                 OO_UNATTENDED=1 OO_COMPONENTS="analysis,compression,columnar" OO_MAKE_LAUNCHER="${OO_MAKE_LAUNCHER:-1}" \
                                 UNATTENDED=1 do_install "analysis,compression,columnar" ;;
        --unattended)            UNATTENDED=1; do_install "${OO_COMPONENTS-analysis,compression,columnar}" ;;
        --check|--doctor)        do_check ;;
        --uninstall)             do_uninstall ;;
        -h|--help)               usage ;;
        *)                       usage; die "unknown option: $1" ;;
    esac
}

main "$@"
