#!/bin/bash
#
# Open-Omniscience Installer
# ========================
#
# This script launches the Open-Omniscience GUI installer.
# For a fully graphical installation experience on Debian-based Linux systems.
#
# Usage: curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/install.sh | bash
#
# Author: Open-Omniscience Team
# License: GPLv3
#

# Check if we're running from within the repository (local launch_gui_installer.sh exists)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/launch_gui_installer.sh" ]; then
    # Use the local version if available
    exec bash "$SCRIPT_DIR/launch_gui_installer.sh"
else
    # Otherwise, fetch the latest version from GitHub
    exec curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/launch_gui_installer.sh | bash
fi
