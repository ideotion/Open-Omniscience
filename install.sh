#!/usr/bin/env bash
#
# Open Omniscience installer  --  friendly, menu-driven, re-runnable.
# Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
#
# Goals:
#   * One command to install: clone (via scripts/bootstrap.sh) then this script
#     puts up a simple menu and does the rest.
#   * Pick what you want: the Core (scrape / store / search / export) is always
#     installed; Analysis tools and Local-LLM tools are optional and can be added
#     later by simply re-running this script -- it is idempotent.
#   * A double-click launcher so non-technical users never need the terminal.
#
# Modes:
#   ./install.sh                 interactive menu (default)
#   ./install.sh --template      Qubes: install system packages in the TemplateVM
#   ./install.sh --appvm         Qubes: non-interactive Core+Analysis under $HOME
#   ./install.sh --unattended    scripted install driven by env vars (see below)
#   ./install.sh --help
#
# Unattended env vars (also used by CI):
#   OO_COMPONENTS="analysis,llm"   extras to add on top of core (comma-separated)
#   OO_WITH_OLLAMA=1               install Ollama if missing (asks consent unless unattended)
#   OO_OLLAMA_MODEL="llama3.2:1b"  model to pull (empty = none)
#   OO_MAKE_LAUNCHER=1             create the desktop launcher
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

# Use whiptail for a real boxed TUI when available; otherwise plain prompts.
HAVE_WHIPTAIL=0
if command -v whiptail >/dev/null 2>&1 && [ -t 0 ]; then HAVE_WHIPTAIL=1; fi
UNATTENDED="${OO_UNATTENDED:-0}"

banner() {
    if [ -f "$SRC_DIR/assets/logo.txt" ]; then
        printf '%s' "$BLU$BOLD"; cat "$SRC_DIR/assets/logo.txt"; printf '%s' "$RST"
    fi
    printf '%s        Open Omniscience%s\n' "$BOLD" "$RST"
    printf '%s  Local-first, ethical intelligence platform for investigative journalism%s\n' "$DIM" "$RST"
}

usage() {
    cat <<EOF
Open Omniscience installer

Usage:
  ./install.sh                 Interactive menu (recommended)
  ./install.sh --appvm         Qubes AppVM: Core + Analysis under \$HOME (no prompts)
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
# Component selection
# --------------------------------------------------------------------------- #
# Echoes a comma-separated extras list (may be empty). Core is always installed.
choose_components() {
    if [ "$UNATTENDED" = "1" ]; then
        printf '%s' "${OO_COMPONENTS:-analysis}"
        return
    fi
    if [ "$HAVE_WHIPTAIL" = "1" ]; then
        whiptail --title "Open Omniscience -- choose components" \
            --checklist "Core (scrape, store, search, export) is always installed.\nSelect optional add-ons (Space to toggle, Enter to confirm):" \
            14 72 2 \
            "analysis" "Quantitative analysis, keywords, framing, sentiment" ON \
            "llm"      "Local LLM tools (summarize / translate via Ollama)"  OFF \
            3>&1 1>&2 2>&3 | tr ' ' ','
    else
        say ""
        say "${BOLD}Choose components${RST} (Core is always installed):"
        local extras=""
        if ask_yn "Install Analysis tools (keywords, framing, sentiment)?" y; then extras="analysis"; fi
        if ask_yn "Install Local-LLM tools (summarize / translate via Ollama)?" n; then
            extras="${extras:+$extras,}llm"
        fi
        printf '%s' "$extras"
    fi
}

# ask_yn "question" default(y/n) -> returns 0 for yes
ask_yn() {
    local q="$1" def="${2:-n}" ans
    if [ "$UNATTENDED" = "1" ]; then [ "$def" = "y" ]; return; fi
    if [ "$HAVE_WHIPTAIL" = "1" ]; then
        if [ "$def" = "y" ]; then whiptail --yesno "$q" 10 70; else whiptail --defaultno --yesno "$q" 10 70; fi
        return
    fi
    local hint="[y/N]"; [ "$def" = "y" ] && hint="[Y/n]"
    read -r -p "  $q $hint " ans || true
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

create_venv() {
    cd "$SRC_DIR"
    if [ ! -d .venv ]; then
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
    if [ "${OO_SKIP_PIP:-0}" = "1" ]; then warn "OO_SKIP_PIP=1 -- skipping pip install ($spec)"; return; fi
    step "Installing the app: $spec"
    python -m pip install --upgrade pip setuptools wheel >/dev/null
    python -m pip install -e "$spec"
    ok "Python packages installed"
}

init_database() {
    if [ "${OO_SKIP_DB:-0}" = "1" ]; then warn "OO_SKIP_DB=1 -- skipping database init"; return; fi
    step "Initialising the database"
    python -c "from src.database.session import init_db; init_db(); print('  database ready')"
    step "Seeding curated starter sources (idempotent; nothing is fetched)"
    python scripts/seed_sources.py || warn "seeding skipped; you can add sources in the UI"
}

# --------------------------------------------------------------------------- #
# Optional: local LLM (Ollama). Transparent and opt-in -- we show the exact
# command and ask before running any third-party installer.
# --------------------------------------------------------------------------- #
maybe_setup_ollama() {
    local extras="$1"
    case ",$extras," in *,llm,*) : ;; *) return 0 ;; esac

    if command -v ollama >/dev/null 2>&1; then
        ok "Ollama is already installed ($(ollama --version 2>/dev/null | head -1))"
    else
        local want="${OO_WITH_OLLAMA:-}"
        if [ -z "$want" ]; then
            say ""
            say "  Ollama runs the local language models. Its official installer is:"
            say "    ${DIM}curl -fsSL https://ollama.com/install.sh | sh${RST}"
            if ask_yn "Install Ollama now (downloads & runs the official installer)?" n; then want=1; else want=0; fi
        fi
        if [ "$want" = "1" ]; then
            step "Installing Ollama (official installer)"
            if command -v curl >/dev/null 2>&1; then
                curl -fsSL https://ollama.com/install.sh | sh || warn "Ollama install failed; you can install it later and re-run with the LLM option."
            else
                warn "curl not found; install Ollama manually from https://ollama.com then re-run."
            fi
        else
            warn "Skipping Ollama. The LLM tools will return a clear 'unavailable' until Ollama is running."
            return 0
        fi
    fi

    # Pull a model.
    local model="${OO_OLLAMA_MODEL:-}"
    if [ -z "$model" ] && [ "$UNATTENDED" != "1" ]; then
        if [ "$HAVE_WHIPTAIL" = "1" ]; then
            model=$(whiptail --title "Download a local model" --menu \
                "Pick a small model to download now (you can pull others later):" 15 72 4 \
                "llama3.2:1b"  "~1.3 GB  fast, low-RAM (good default)" \
                "llama3.2:3b"  "~2.0 GB  better quality" \
                "qwen2.5:0.5b" "~0.4 GB  tiny, fastest" \
                "none"         "Skip for now" 3>&1 1>&2 2>&3) || model="none"
        else
            if ask_yn "Download a small default model now (llama3.2:1b, ~1.3 GB)?" y; then
                model="llama3.2:1b"; else model="none"; fi
        fi
    fi
    if [ -n "$model" ] && [ "$model" != "none" ]; then
        if command -v ollama >/dev/null 2>&1; then
            step "Pulling model: $model"
            ollama pull "$model" || warn "Could not pull $model; you can run 'ollama pull $model' later."
        else
            warn "Ollama not available; skipping model download."
        fi
    fi
}

# --------------------------------------------------------------------------- #
# Double-click launcher (desktop integration)
# --------------------------------------------------------------------------- #
make_launcher() {
    local want="${OO_MAKE_LAUNCHER:-}"
    if [ -z "$want" ]; then
        if ask_yn "Create a double-click 'Open Omniscience' launcher (apps menu + Desktop)?" y; then want=1; else want=0; fi
    fi
    [ "$want" = "1" ] || return 0

    chmod +x "$SRC_DIR/scripts/launch.sh" 2>/dev/null || true

    local os; os="$(uname -s)"
    if [ "$os" = "Darwin" ]; then
        # macOS: a double-clickable .command on the Desktop.
        local cmd="$HOME/Desktop/Open Omniscience.command"
        mkdir -p "$HOME/Desktop"
        cat > "$cmd" <<EOF
#!/usr/bin/env bash
exec "$SRC_DIR/scripts/launch.sh"
EOF
        chmod +x "$cmd"
        ok "Created launcher: $cmd"
        say "  ${BOLD}To start:${RST} double-click 'Open Omniscience' on your Desktop."
        return 0
    fi

    # Linux: a .desktop entry in the applications menu (+ a copy on the Desktop).
    local apps="$HOME/.local/share/applications"
    local desktop_file="$apps/$APP_NAME.desktop"
    mkdir -p "$apps"
    # PNG is rendered far more reliably than SVG by file managers / minimal desktops
    # (notably some Qubes AppVMs); fall back to the SVG source if the PNG is missing.
    local icon="$SRC_DIR/assets/icon.png"
    [ -f "$icon" ] || icon="$SRC_DIR/assets/icon.svg"
    cat > "$desktop_file" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Open Omniscience
GenericName=Intelligence Platform
Comment=Local-first intelligence platform for investigative journalism
Exec=$SRC_DIR/scripts/launch.sh
Icon=$icon
Terminal=true
Categories=Utility;News;Office;
Keywords=news;intelligence;journalism;research;osint;
StartupNotify=false
EOF
    chmod +x "$desktop_file"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$apps" 2>/dev/null || true

    # Also drop a copy on the Desktop and mark it trusted where supported.
    local desk; desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
    if [ -d "$desk" ]; then
        cp "$desktop_file" "$desk/$APP_NAME.desktop"
        chmod +x "$desk/$APP_NAME.desktop"
        gio set "$desk/$APP_NAME.desktop" metadata::trusted true 2>/dev/null || true
    fi

    ok "Created launcher in your applications menu${desk:+ and on the Desktop}"
    say ""
    say "  ${BOLD}How to start the app:${RST}"
    say "    • Open your applications menu and search for ${BOLD}Open Omniscience${RST}, or"
    say "    • Double-click the ${BOLD}Open Omniscience${RST} icon on your Desktop."
    say "    A terminal window opens, the app starts, and your browser opens to"
    say "    ${BLU}http://127.0.0.1:8000${RST}. Close that window to stop the app."
}

# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
do_install() {
    local extras="$1"
    ensure_python
    create_venv
    pip_install "$extras"
    init_database
    maybe_setup_ollama "$extras"
    make_launcher
    say ""
    ok "${BOLD}Install complete.${RST} App + data live under: $SRC_DIR"
    say "  Run from a terminal any time with: ${DIM}cd '$SRC_DIR' && ./scripts/launch.sh${RST}"
    say "  Add components later by re-running: ${DIM}./install.sh${RST}"
}

run_interactive() {
    banner
    local extras; extras="$(choose_components)"
    step "Selected components: core${extras:+, $extras}"
    do_install "$extras"
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

    # Collect launcher files that exist.
    local apps="$HOME/.local/share/applications/$APP_NAME.desktop"
    local desk; desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
    local desk_file="$desk/$APP_NAME.desktop"
    local mac_file="$HOME/Desktop/Open Omniscience.command"

    say ""
    say "  The following will be ${BOLD}removed${RST}:"
    [ -d "$SRC_DIR/.venv" ] && say "    • virtualenv:  $SRC_DIR/.venv"
    [ -f "$apps" ]          && say "    • launcher:    $apps"
    [ -f "$desk_file" ]     && say "    • launcher:    $desk_file"
    [ -f "$mac_file" ]      && say "    • launcher:    $mac_file"
    say "  Your repository ($SRC_DIR) and your data will be ${BOLD}kept${RST} unless you choose otherwise."
    say ""

    if ! ask_yn "Proceed with removing the virtualenv and launcher?" n; then
        warn "Aborted; nothing was removed."
        return 0
    fi

    rm -f "$apps" "$desk_file" "$mac_file"
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
        --appvm)                 OO_UNATTENDED=1 OO_COMPONENTS="analysis" OO_MAKE_LAUNCHER="${OO_MAKE_LAUNCHER:-1}" \
                                 UNATTENDED=1 do_install "analysis" ;;
        --unattended)            UNATTENDED=1; do_install "${OO_COMPONENTS-analysis}" ;;
        --check|--doctor)        do_check ;;
        --uninstall)             do_uninstall ;;
        -h|--help)               usage ;;
        *)                       usage; die "unknown option: $1" ;;
    esac
}

main "$@"
