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
=======
#!/bin/bash
#
# Open-Omniscience Installer (LEGACY)
# ========================
#
# ⚠️ DEPRECATED: This script is kept for backward compatibility.
# Please use UNIFIED_INSTALL.sh instead for all new installations.
#
# The unified installer automatically detects your environment (Qubes OS vs regular Linux)
# and adapts the installation method accordingly.
#
# Usage (LEGACY): curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/install.sh | bash
# Usage (RECOMMENDED): curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
#
# Author: Open-Omniscience Team
# License: GPLv3
#

# DEPRECATION WARNING
echo "⚠️  DEPRECATION NOTICE: This installer is deprecated."
echo "✅ Please use: curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash"
echo ""

# Check if we're running from within the repository (local launch_gui_installer.sh exists)========================
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
    exec curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/launch_gui_installer.sh | bash
fi
