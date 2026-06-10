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
# Component selection
# --------------------------------------------------------------------------- #
# Echoes a comma-separated extras list (may be empty). Core is always installed.
# Sets the global CHOSEN_EXTRAS (a comma-separated extras string, possibly empty).
# IMPORTANT: this function must NOT be called via command substitution -- it prints
# UI (banners/prompts) to stdout/stderr, so capturing its stdout would fold that UI
# into the result. Returning through a global keeps the menu and the value separate.
CHOSEN_EXTRAS=""
choose_components() {
    if [ "$UNATTENDED" = "1" ] || [ "$INTERACTIVE" = "0" ]; then
        CHOSEN_EXTRAS="${OO_COMPONENTS:-analysis,compression}"
        return
    fi
    if [ "$HAVE_WHIPTAIL" = "1" ]; then
        # Strip whiptail's surrounding quotes and join selections with commas.
        CHOSEN_EXTRAS="$(whiptail --title "Open Omniscience -- choose components" \
            --checklist "Core (scrape, store, search, export) is always installed.\nSelect optional add-ons (Space to toggle, Enter to confirm):" \
            16 74 3 \
            "analysis"    "Quantitative analysis, keywords, framing, sentiment" ON \
            "compression" "Storage compression accelerators (zstandard, lz4)"   ON \
            "llm"         "Local LLM tools (summarize / translate via Ollama)"  OFF \
            3>&1 1>&2 2>&3 < "$TTY_IN" | tr -d '"' | tr ' ' ',')"
        return
    fi
    say ""
    say "${BOLD}Choose components${RST} (Core is always installed):"
    local extras=""
    if ask_yn "Install Analysis tools (keywords, framing, sentiment)?" y; then extras="analysis"; fi
    if ask_yn "Install storage Compression accelerators (zstandard, lz4 -- smaller database)?" y; then
        extras="${extras:+$extras,}compression"
    fi
    if ask_yn "Install Local-LLM tools (summarize / translate via Ollama)?" n; then
        extras="${extras:+$extras,}llm"
    fi
    CHOSEN_EXTRAS="$extras"
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

create_venv() {
    cd "$SRC_DIR"
    if [ ! -d .venv ]; then
        # Preflight: on Debian/Ubuntu the stdlib venv/ensurepip module ships in a
        # SEPARATE apt package. Check now and give actionable guidance instead of
        # leaking the cryptic CPython "ensurepip is not available" error.
        if ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
            venv_pkg="python3-venv"
            case "$PY" in *3.13*) venv_pkg="python3.13-venv";; esac
            die "Python's venv module is missing (no ensurepip).
    Install it, then re-run ./install.sh:
        sudo apt update && sudo apt install -y $venv_pkg
    On Qubes, install it in the TemplateVM (then reboot the AppVM) so DispVMs and
    AppVMs inherit it -- packages installed in an AppVM/DispVM do not persist."
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

    # Honest network notice (0.0.8): provisioning the LLM needs clearnet; using
    # the app afterwards does not. Said once, up front, so an at-risk operator
    # can decide when/where to do this step.
    say ""
    say "  ${DIM}Note: downloading Ollama and a model needs a DIRECT internet connection${RST}"
    say "  ${DIM}— it will NOT work over Tor. This is a one-time provisioning step.${RST}"
    say "  ${DIM}Afterwards the app runs fully offline: the LLM never touches the network,${RST}"
    say "  ${DIM}and source collection can route through your proxy (Settings → Safety →${RST}"
    say "  ${DIM}Protected mode). If this machine can't use clearnet, skip the LLM here and${RST}"
    say "  ${DIM}provision on a connected machine, then copy ~/.ollama/models across (USB).${RST}"

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
                "none"         "Skip — pick from newer models in-app later" 3>&1 1>&2 2>&3) || model="none"
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
Exec=$SRC_DIR/scripts/launch.sh $4
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
Exec=$SRC_DIR/install.sh --uninstall
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
    choose_components            # sets CHOSEN_EXTRAS (does not pollute stdout)
    local extras="$CHOSEN_EXTRAS"
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
          "$mac_file" "$mac_file_desk" "$mac_file_uninstall"
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
        --appvm)                 OO_UNATTENDED=1 OO_COMPONENTS="analysis,compression" OO_MAKE_LAUNCHER="${OO_MAKE_LAUNCHER:-1}" \
                                 UNATTENDED=1 do_install "analysis,compression" ;;
        --unattended)            UNATTENDED=1; do_install "${OO_COMPONENTS-analysis,compression}" ;;
        --check|--doctor)        do_check ;;
        --uninstall)             do_uninstall ;;
        -h|--help)               usage ;;
        *)                       usage; die "unknown option: $1" ;;
    esac
}

main "$@"
