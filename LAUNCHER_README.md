# Open-Omniscience Smart Installer Launcher

## Overview

The **Smart Installer Launcher** (`launch_gui_installer.sh`) provides an intelligent installation experience that:

1. **Automatically detects** if a GUI environment is available
2. **Automatically installs** required dependencies (`python3-tk`, `psutil`)
3. **Launches the appropriate installer** (GUI or text-based)
4. **Works in all environments**: Virtual machines, XEN, Docker, bare metal, etc.

## Features

### Automatic Environment Detection

The launcher checks for:
- **DISPLAY** environment variable (X11)
- **WAYLAND_DISPLAY** environment variable (Wayland)
- **xset** command availability (X11 server)
- **XDG_CURRENT_DESKTOP** (Desktop environment)

### Automatic Dependency Installation

If GUI is available, the launcher automatically installs:
- **python3-tk**: System package for Tkinter GUI (via apt-get, dnf, or yum)
- **psutil**: Python package for system monitoring (via pip)

### Graceful Fallback

If any dependency cannot be installed or GUI is not available, the launcher automatically falls back to the text-based installer.

## Usage

### Option 1: Direct Download and Run

```bash
# Download and run the smart launcher
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.02/launch_gui_installer.sh | bash
```

### Option 2: Clone and Run

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience

# Make executable
chmod +x launch_gui_installer.sh

# Run it
./launch_gui_installer.sh
```

### Option 3: Manual Installation

```bash
# Install dependencies manually
sudo apt-get install python3-tk
pip install psutil

# Run GUI installer directly
python3 installer/gui_installer.py
```

## How It Works

### Decision Flow

```
Start
  │
  ▼
Is Debian-based Linux? ──NO──► Fall back to text installer
  │ YES
  ▼
Is GUI available? ──NO──► Fall back to text installer
  │ YES
  ▼
Is python3-tk installed? ──NO──► Install python3-tk
  │ YES
  ▼
Is psutil installed? ──NO──► Install psutil
  │ YES
  ▼
Clone repository (if needed)
  │
  ▼
Launch GUI installer
```

### Environment Support

| Environment | GUI Detection | Works? |
|-------------|---------------|--------|
| **Bare Metal Debian/Ubuntu** | ✅ Yes | ✅ Yes |
| **Virtual Machine (X11)** | ✅ Yes | ✅ Yes |
| **XEN with X11 passthrough** | ✅ Yes | ✅ Yes |
| **Docker with X11 socket** | ✅ Yes | ✅ Yes |
| **Headless Server** | ❌ No | ✅ Falls back to text |
| **SSH Terminal** | ❌ No | ✅ Falls back to text |
| **WSL (Windows)** | ❌ No | ❌ Not supported |
| **macOS** | ❌ No | ❌ Not supported |

## Requirements

### For GUI Mode
- Debian-based Linux (Ubuntu, Debian, etc.)
- X11 or Wayland display server
- `python3-tk` package (auto-installed)
- `psutil` Python package (auto-installed)

### For Text Mode (Fallback)
- Debian-based Linux
- curl, bash, git
- Docker (optional, for containerized deployment)

## Customization

### Force GUI Mode

```bash
# Even if GUI detection fails, you can force GUI mode
DISPLAY=:0 ./launch_gui_installer.sh
```

### Force Text Mode

```bash
# Skip GUI detection and use text installer
NO_GUI=1 ./launch_gui_installer.sh
```

### Custom Installation Directory

```bash
# Set custom installation directory
INSTALL_DIR=/custom/path ./launch_gui_installer.sh
```

## Troubleshooting

### "python3-tk not found"

**Solution**: The launcher will automatically install it. If automatic installation fails:

```bash
# Debian/Ubuntu
sudo apt-get install python3-tk

# Fedora/RHEL
sudo dnf install python3-tk

# OpenSUSE
sudo zypper install python3-tk
```

### "psutil not found"

**Solution**: The launcher will automatically install it. If automatic installation fails:

```bash
pip install psutil
# OR
python3 -m pip install psutil
```

### "No GUI environment detected"

**Solution**: You're running in a headless environment. The launcher will automatically use the text-based installer. To use GUI, you need:

1. A display server (X11 or Wayland)
2. X11 forwarding if using SSH: `ssh -X user@host`
3. Docker with X11 socket mounted: `docker run -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix ...`

### "Not a Debian-based system"

**Solution**: This installer only supports Debian-based Linux (Ubuntu, Debian, etc.). Use the manual installation method for other distributions.

## Files

- `launch_gui_installer.sh`: Main smart launcher script
- `installer/gui_installer.py`: GUI installer (launched by smart launcher)
- `install`: Text-based installer (fallback)

## License

GNU GPLv3 - See the main [LICENSE](LICENSE) file for details.

## Support

For issues or questions, please open an issue on GitHub:
https://github.com/ideotion/Open-Omniscience/issues
