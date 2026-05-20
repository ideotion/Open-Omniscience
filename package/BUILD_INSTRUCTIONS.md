# Open Omniscience - Package Build Instructions

This directory contains scripts and configuration files for building portable packages of Open Omniscience for Linux distribution.

## Available Package Formats

1. **AppImage** - Portable, runs on most Linux distributions without installation
2. **.deb Package** - For Debian, Ubuntu, and derivatives

## Prerequisites

### For All Builds
- Git
- Python 3.10+
- pip
- Basic build tools (make, gcc, etc.)

### For AppImage
- [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy)
- [appimagetool](https://github.com/AppImage/AppImageKit)

Install on Ubuntu/Debian:
```bash
# Install linuxdeploy
wget https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
chmod +x linuxdeploy-x86_64.AppImage
sudo mv linuxdeploy-x86_64.AppImage /usr/local/bin/linuxdeploy

# Install appimagetool
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
```

### For .deb Package
- dpkg-dev
- debhelper (>= 11)
- fakeroot

Install on Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install dpkg-dev debhelper fakeroot build-essential
```

---

## Building AppImage

### Quick Build
```bash
# Make the build script executable
chmod +x package/appimage/OpenOmniscience.AppImageBuilder

# Run the build
./package/appimage/OpenOmniscience.AppImageBuilder
```

### Manual Build
```bash
# Create AppDir structure
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/open-omniscience/src
mkdir -p AppDir/usr/share/open-omniscience/configs
mkdir -p AppDir/usr/share/open-omniscience/docs

# Copy files
cp -r src/* AppDir/usr/share/open-omniscience/src/
cp -r configs/* AppDir/usr/share/open-omniscience/configs/
cp -r docs/* AppDir/usr/share/open-omniscience/docs/
cp README.md LICENSE ETHICS.md SECURITY.md CONTRIBUTING.md AppDir/usr/share/open-omniscience/
cp requirements.txt AppDir/usr/share/open-omniscience/

# Create wrapper script (see OpenOmniscience.AppImageBuilder for details)
# ...

# Build with linuxdeploy
linuxdeploy \
    --appdir AppDir \
    --desktop-file package/appimage/open-omniscience.desktop \
    --icon-filename package/appimage/open-omniscience.png \
    --executable AppDir/AppRun \
    --output appimage

# The AppImage will be created in the current directory
```

### Output
- `dist/OpenOmniscience-0.02-x86_64.AppImage`

### Running the AppImage
```bash
# Make executable
chmod +x OpenOmniscience-0.02-x86_64.AppImage

# Run
./OpenOmniscience-0.02-x86_64.AppImage

# Access at: http://localhost:8000
```

---

## Building .deb Package

### Quick Build
```bash
# Make the build script executable
chmod +x package/deb/build-deb.sh

# Run the build
./package/deb/build-deb.sh
```

### Manual Build
```bash
# Create build directory
mkdir -p build-deb/open-omniscience-0.02
cp -r package/deb/debian build-deb/open-omniscience-0.02/

# Build the package
cd build-deb/open-omniscience-0.02
dpkg-buildpackage -us -uc -b

# The .deb will be created in the parent directory
cd ../..
```

### Output
- `dist/open-omniscience_0.02_all.deb`

### Installing the .deb Package
```bash
# Install the package
sudo dpkg -i open-omniscience_0.02_all.deb

# Fix any missing dependencies
sudo apt-get install -f

# Run the application
open-omniscience

# Or run directly
/usr/bin/open-omniscience

# Access at: http://localhost:8000
```

### Uninstalling
```bash
sudo dpkg -r open-omniscience
```

---

## Build All Packages

To build both AppImage and .deb package:

```bash
# Build AppImage
./package/appimage/OpenOmniscience.AppImageBuilder

# Build .deb
./package/deb/build-deb.sh
```

Both packages will be created in the `dist/` directory.

---

## Package Contents

Both package formats include:

### Application Files
- All Python source code (`src/`)
- Configuration files (`configs/`)
- Documentation (`docs/`, README.md, LICENSE, etc.)
- Requirements file (`requirements.txt`)

### Data Directories
- `~/.open-omniscience/data/` - SQLite database
- `~/.open-omniscience/audit/` - Audit logs
- `~/.open-omniscience/logs/` - Application logs

### Features
- Automatic dependency installation (Python packages)
- Automatic database initialization
- Environment variable configuration
- Desktop integration (menu entry, icon)
- Python version checking (requires 3.10+)

---

## Cross-Platform Compatibility

### AppImage
- ✅ Works on most modern Linux distributions
- ✅ No installation required
- ✅ Portable (single file)
- ✅ No root access needed
- ⚠️ Requires FUSE (usually enabled by default)

### .deb Package
- ✅ Debian 10+ (Buster)
- ✅ Ubuntu 20.04+ (Focal Fossa)
- ✅ Linux Mint 20+
- ✅ Other Debian-based distributions
- ⚠️ Requires Python 3.10+
- ⚠️ Requires pip and Python development headers

---

## Troubleshooting

### AppImage Issues

**"No such file or directory" when running:**
```bash
chmod +x OpenOmniscience-*.AppImage
```

**"FUSE: device not found" error:**
```bash
# Enable FUSE
sudo modprobe fuse
sudo usermod -aG fuse $USER

# Or run with --no-sandbox
./OpenOmniscience-*.AppImage --no-sandbox
```

**AppImage doesn't start:**
```bash
# Check if it's an executable
file OpenOmniscience-*.AppImage

# Try running with --appimage-extract
./OpenOmniscience-*.AppImage --appimage-extract
cd squashfs-root
./AppRun
```

### .deb Package Issues

**Dependency errors during installation:**
```bash
sudo apt-get install -f
```

**Python version too old:**
```bash
# Upgrade Python
sudo apt-get install python3.10 python3.10-venv python3.10-dev
```

**Missing pip:**
```bash
sudo apt-get install python3-pip
```

---

## Customization

### Changing Version Number
Edit the version in:
- `package/appimage/OpenOmniscience.AppImageBuilder` (line 10)
- `package/deb/debian/changelog` (line 1)
- `package/deb/debian/control` (line 1)
- `package/deb/build-deb.sh` (line 10)

### Adding/Removing Files
Edit the copy commands in:
- `package/appimage/OpenOmniscience.AppImageBuilder` (copy_files function)
- `package/deb/debian/rules` (override_dh_auto_install target)

### Changing Dependencies
Edit:
- `package/deb/debian/control` (Depends, Recommends, Suggests fields)
- `requirements.txt` (Python dependencies)

---

## Testing Packages

### Test AppImage
```bash
# Build
./package/appimage/OpenOmniscience.AppImageBuilder

# Run
./dist/OpenOmniscience-0.02-x86_64.AppImage &

# Wait a few seconds, then test
curl http://localhost:8000/api/sources

# Stop
pkill -f uvicorn
```

### Test .deb Package
```bash
# Build
./package/deb/build-deb.sh

# Install
sudo dpkg -i dist/open-omniscience_0.02_all.deb

# Run
open-omniscience &

# Wait a few seconds, then test
curl http://localhost:8000/api/sources

# Stop
pkill -f uvicorn

# Uninstall
sudo dpkg -r open-omniscience
```

---

## Notes

1. **First Run**: On first run, the package will install Python dependencies automatically. This may take a few minutes.

2. **Database**: The SQLite database is stored in `~/.open-omniscience/data/open_omniscience.db`

3. **Port**: The application runs on port 8000 by default. Change this in the wrapper script if needed.

4. **User Data**: All user data (database, logs, audit) is stored in `~/.open-omniscience/`

5. **Icon**: The packages include a placeholder icon. Replace with the actual Open Omniscience logo for production.

---

## License

All build scripts and configuration files are licensed under the MIT License, same as the main project.

See [LICENSE](../../LICENSE) for details.
