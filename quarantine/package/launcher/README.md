# Open Omniscience Desktop Launcher

This directory contains the desktop launcher files for Open Omniscience.

## Files

- `open-omniscience.desktop` - Desktop entry file template for system-wide installation
- `open-omniscience-user.desktop` - Desktop entry file for user-specific installation
- `install-desktop-launcher.sh` - Script to install/uninstall the desktop launcher

## Usage

### Manual Installation

To manually install the desktop launcher:

```bash
# Make the script executable
chmod +x install-desktop-launcher.sh

# Install the launcher
./install-desktop-launcher.sh install

# Check if installed
./install-desktop-launcher.sh check

# Uninstall the launcher
./install-desktop-launcher.sh uninstall
```

### Using Makefile

The Makefile provides convenient targets:

```bash
# Install desktop launcher
make desktop-launcher-install

# Uninstall desktop launcher
make desktop-launcher-uninstall
```

### Debian Package Installation

When installing via the Debian package (`make package-deb`), the desktop launcher will be automatically installed to:

1. The user's desktop directory (`~/Desktop/`)
2. The user's applications menu (`~/.local/share/applications/`)
3. System applications menu (`/usr/share/applications/`) when installed as root

The launcher will appear as "Open Omniscience" with the application icon.

## Desktop Entry Format

The `.desktop` files follow the [Freedesktop Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/desktop-entry-spec-latest.html).

Key fields:
- `Name`: Open Omniscience
- `Exec`: /usr/bin/open-omniscience
- `Icon`: /usr/share/pixmaps/open-omniscience.png
- `Type`: Application
- `Categories`: Utility;News;Journalism;InformationManagement;
- `Terminal`: true (application runs in terminal)

## Customization

To customize the launcher:

1. Edit `open-omniscience-user.desktop` to modify the desktop entry
2. Replace the icon by modifying `package/deb/open-omniscience.svg`
3. Update the `Exec` field if the application path changes

## Troubleshooting

### Launcher not appearing

1. Check if the `.desktop` file exists on your desktop:
   ```bash
   ls ~/Desktop/open-omniscience-user.desktop
   ```

2. Check if the file is executable:
   ```bash
   ls -la ~/Desktop/open-omniscience-user.desktop
   ```

3. Make it executable:
   ```bash
   chmod +x ~/Desktop/open-omniscience-user.desktop
   ```

4. Update desktop database:
   ```bash
   update-desktop-database ~/.local/share/applications
   ```

### Icon not showing

1. Check if the icon file exists:
   ```bash
   ls ~/.local/share/icons/open-omniscience.png
   ```

2. Verify the icon path in the desktop file:
   ```bash
   cat ~/Desktop/open-omniscience-user.desktop | grep Icon
   ```

3. Update the icon cache:
   ```bash
   gtk-update-icon-cache ~/.local/share/icons
   ```

## Platform Support

The launcher installation script supports:

- Linux (all major distributions)
- XDG compliant desktop environments (GNOME, KDE, XFCE, etc.)
- Multiple languages (English, French, German, Spanish desktop directories)
- Both system-wide and user-specific installation
