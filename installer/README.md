# Open-Omniscience GUI Installer

A graphical installer for non-technical users to install Open-Omniscience on Debian-based Linux systems (Ubuntu, Debian, etc.).

## Features

- **Interactive GUI**: Easy-to-use graphical interface with Tkinter
- **System Requirements Check**: Automatically checks for required dependencies
- **Customizable Installation**: Choose installation options:
  - Installation directory
  - Install Ollama for LLM support
  - Database type (SQLite or PostgreSQL)
  - Auto-start services
  - Create application launcher
- **Progress Tracking**: Real-time progress bar and installation log
- **Application Launcher**: Creates a .desktop file for easy launching from the application menu

## Requirements

- **Operating System**: Debian-based Linux (Ubuntu, Debian, etc.)
- **Python**: 3.8+
- **Dependencies**:
  - `python3-tk` (for GUI)
  - `psutil` (for system checks)
  - `git`, `curl`, `wget` (for installation)
  - `python3`, `python3-venv` (for Python environment)

## Installation

### Option 1: Run Directly

```bash
# Navigate to the installer directory
cd installer

# Install required Python packages
pip install psutil

# Run the installer
python3 gui_installer.py
```

### Option 2: Make Executable

```bash
# Make the installer executable
chmod +x gui_installer.py

# Run it
./gui_installer.py
```

### Option 3: Install as a Package

```bash
# Create a setup.py (optional)
# Then install with pip
pip install -e .

# Run the installed command
open-omniscience-gui-installer
```

## Usage

1. **Welcome Page**: Displays information about Open-Omniscience
2. **Requirements Check**: Verifies system requirements and dependencies
3. **Options Page**: Select installation preferences
4. **Installation**: Shows progress and logs
5. **Complete**: Installation summary and next steps

## Configuration

The installer uses the following defaults:

- **Repository URL**: https://github.com/ideotion/Open-Omniscience.git
- **Branch**: 0.02
- **Installation Directory**: ~/open-omniscience
- **Database Type**: SQLite
- **Default Model**: gemma4:e2b

## Troubleshooting

### Tkinter Not Found

If you get an error about Tkinter not being available:

```bash
sudo apt-get install python3-tk
```

### psutil Not Found

```bash
pip install psutil
```

### Not a Debian-based System

This installer is designed specifically for Debian-based Linux systems. If you're running a different distribution, please use the manual installation method.

### Permission Issues

Make sure you have sudo privileges for installing system packages.

## Files

- `gui_installer.py`: Main GUI installer script
- `open-omniscience.desktop`: Template for application launcher
- `README.md`: This file

## License

GNU GPLv3 - See the main [LICENSE](../LICENSE) file for details.

## Support

For issues or questions, please open an issue on the main repository:
https://github.com/ideotion/Open-Omniscience/issues
