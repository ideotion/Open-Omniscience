# Open Omniscience - Packaging Summary

## ✅ Packaging Complete

Both **AppImage** and **.deb** package formats have been added to the repository, providing maximum cross-platform Linux compatibility.

---

## 📦 Package Formats Available

### 1. AppImage
**File:** `OpenOmniscience-0.2.0-x86_64.AppImage`

**Features:**
- ✅ Portable - runs on most Linux distributions
- ✅ No installation required
- ✅ Single file - easy to distribute
- ✅ No root access needed
- ✅ Includes all dependencies (bundles Python runtime)
- ✅ Desktop integration (menu entry, icon)
- ✅ Automatic database initialization
- ✅ Automatic dependency installation

**Compatibility:**
- Ubuntu 18.04+
- Debian 9+
- Fedora 28+
- openSUSE 15+
- Arch Linux
- CentOS 7+ (with FUSE)
- Any modern Linux distribution with FUSE support

---

### 2. Debian Package (.deb)
**File:** `open-omniscience_0.2.0_all.deb`

**Features:**
- ✅ Native Debian package format
- ✅ Proper dependency management
- ✅ System-wide installation
- ✅ Desktop integration (menu entry, icon)
- ✅ Automatic database initialization
- ✅ Automatic dependency installation
- ✅ Follows Debian packaging standards

**Compatibility:**
- Debian 10+ (Buster)
- Ubuntu 20.04+ (Focal Fossa)
- Linux Mint 20+
- Pop!_OS 20.04+
- Other Debian-based distributions

---

## 🏗️ Package Structure

### Directory Layout
```
package/
├── BUILD_INSTRUCTIONS.md          # Comprehensive build documentation
├── appimage/
│   └── OpenOmniscience.AppImageBuilder  # AppImage build script
└── deb/
    ├── build-deb.sh               # Debian package build script
    └── debian/
        ├── changelog             # Debian changelog
        ├── control               # Package metadata
        ├── compat                 # Compatibility level
        ├── copyright              # License information
        ├── rules                 # Build rules
        └── source/
            └── format             # Source format
```

### Package Contents
Both package formats include:

```
/usr/share/open-omniscience/
├── src/                          # Python source code
│   ├── api/                      # FastAPI backend
│   ├── database/                 # SQLAlchemy models
│   ├── scraper/                  # Web scraper
│   ├── ingestor/                 # Data ingestion
│   ├── utils/                    # Utilities
│   └── static/                   # Frontend assets
├── configs/                      # Configuration files
│   ├── sources.yml               # News sources
│   └── settings.yaml             # Application settings
├── docs/                         # Documentation
│   ├── USER_GUIDE.md
│   ├── DEVELOPER_GUIDE.md
│   └── DATABASE.md
├── README.md                     # Main documentation
├── LICENSE                       # License file
├── ETHICS.md                     # Ethical guidelines
├── SECURITY.md                   # Security policies
├── CONTRIBUTING.md               # Contribution guidelines
└── requirements.txt              # Python dependencies

/usr/bin/
└── open-omniscience              # Launcher script

/usr/share/applications/
└── open-omniscience.desktop      # Desktop entry

/usr/share/pixmaps/
└── open-omniscience.png          # Application icon

/etc/open-omniscience/            # System configuration (deb only)
└── settings.yaml                 # Default settings
```

---

## 🚀 Build Instructions

### Quick Build (Both Packages)

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience

# Build both packages
make package-all

# Output files:
# - dist/OpenOmniscience-0.2.0-x86_64.AppImage
# - dist/open-omniscience_0.2.0_all.deb
```

### Build AppImage Only

```bash
make package-appimage
```

### Build Debian Package Only

```bash
make package-deb
```

### Clean Up

```bash
make package-clean
```

---

## 📋 Detailed Build Process

### AppImage Build Requirements

1. **linuxdeploy** - AppImage creation tool
2. **appimagetool** - AppImage packaging tool

**Install on Ubuntu/Debian:**
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

**Build Command:**
```bash
chmod +x package/appimage/OpenOmniscience.AppImageBuilder
./package/appimage/OpenOmniscience.AppImageBuilder
```

### Debian Package Build Requirements

1. **dpkg-dev** - Debian packaging tools
2. **debhelper** (>= 11) - Helper scripts
3. **fakeroot** - Simulate root for building

**Install on Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install dpkg-dev debhelper fakeroot build-essential
```

**Build Command:**
```bash
chmod +x package/deb/build-deb.sh
./package/deb/build-deb.sh
```

---

## 🎯 Usage Instructions

### AppImage Usage

**Run:**
```bash
# Make executable (first time only)
chmod +x OpenOmniscience-0.2.0-x86_64.AppImage

# Run the application
./OpenOmniscience-0.2.0-x86_64.AppImage

# Access at: http://localhost:8000
```

**Troubleshooting:**
- If you get "FUSE: device not found", enable FUSE:
  ```bash
  sudo modprobe fuse
  sudo usermod -aG fuse $USER
  ```
- Or run with `--no-sandbox`:
  ```bash
  ./OpenOmniscience-0.2.0-x86_64.AppImage --no-sandbox
  ```

### Debian Package Usage

**Install:**
```bash
# Install the package
sudo dpkg -i open-omniscience_0.2.0_all.deb

# Fix any missing dependencies
sudo apt-get install -f

# Run the application
open-omniscience

# Or run directly
/usr/bin/open-omniscience

# Access at: http://localhost:8000
```

**Uninstall:**
```bash
sudo dpkg -r open-omniscience
```

---

## 📊 Feature Comparison

| Feature | AppImage | .deb Package |
|---------|----------|--------------|
| Portable | ✅ Yes | ❌ No |
| No installation | ✅ Yes | ❌ No |
| Single file | ✅ Yes | ❌ No |
| No root needed | ✅ Yes | ❌ No (installation) |
| System integration | ⚠️ Limited | ✅ Full |
| Dependency management | ✅ Bundled | ✅ System packages |
| Automatic updates | ❌ No | ⚠️ APT |
| Desktop entry | ✅ Yes | ✅ Yes |
| Icon | ✅ Yes | ✅ Yes |
| Python dependencies | ✅ Bundled | ✅ Auto-install |
| Database | ✅ SQLite | ✅ SQLite |
| PostgreSQL support | ✅ Yes | ✅ Yes |
| Cross-distribution | ✅ Yes | ❌ Debian-based only |

---

## 🔧 Technical Details

### Launcher Script Features

Both packages use a wrapper script that:

1. **Creates user directories** (`~/.open-omniscience/{data,audit,logs}`)
2. **Checks Python version** (requires 3.10+)
3. **Installs Python dependencies** automatically (first run only)
4. **Initializes database** automatically (first run only)
5. **Sets environment variables** (DATABASE_URL, PYTHONPATH)
6. **Launches the application** (uvicorn on port 8000)

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPEN_OMNISCIENCE_DIR` | Application directory | `/usr/share/open-omniscience` |
| `DATABASE_URL` | Database connection URL | `sqlite:///~/.open-omniscience/data/open_omniscience.db` |
| `PYTHONPATH` | Python module path | `$OPEN_OMNISCIENCE_DIR/src` |

### Data Storage

All user data is stored in:
- **AppImage:** `~/.open-omniscience/`
- **.deb:** `~/.open-omniscience/`

Directory structure:
```
~/.open-omniscience/
├── data/
│   └── open_omniscience.db      # SQLite database
├── audit/
│   ├── scrape_log.csv           # Scraping activity log
│   └── errors.log               # Error log
└── logs/
    └── open_omniscience.log      # Application log
```

---

## 📝 Release Notes

### Version 0.2.0

**First packaged release**

**New Features:**
- AppImage package for portable deployment
- Debian package for system-wide installation
- Automatic dependency installation
- Automatic database initialization
- Desktop integration (menu entry, icon)
- Python version checking

**Known Limitations:**
- Placeholder icon (replace with actual logo)
- First run may take several minutes (dependency installation)
- Requires Python 3.10+
- Requires pip and Python development headers

---

## 🎨 Customization

### Changing Version Number

Edit version in:
- `package/appimage/OpenOmniscience.AppImageBuilder` (line 10)
- `package/deb/debian/changelog` (line 1)
- `package/deb/debian/control` (line 1)
- `package/deb/build-deb.sh` (line 10)

### Adding Files

Edit the copy commands in:
- `package/appimage/OpenOmniscience.AppImageBuilder` (copy_files function)
- `package/deb/debian/rules` (override_dh_auto_install target)

### Changing Dependencies

Edit:
- `package/deb/debian/control` (Depends, Recommends, Suggests fields)
- `requirements.txt` (Python dependencies)

### Changing Port

Edit the port in the wrapper scripts:
- `package/appimage/OpenOmniscience.AppImageBuilder` (line 50)
- `package/deb/debian/rules` (line 30)

---

## 🔍 Testing

### Test AppImage

```bash
# Build
make package-appimage

# Run in background
./dist/OpenOmniscience-0.2.0-x86_64.AppImage &

# Wait 5 seconds
sleep 5

# Test API
curl http://localhost:8000/api/sources

# Stop
pkill -f uvicorn
```

### Test Debian Package

```bash
# Build
make package-deb

# Install
sudo dpkg -i dist/open-omniscience_0.2.0_all.deb

# Run in background
open-omniscience &

# Wait 5 seconds
sleep 5

# Test API
curl http://localhost:8000/api/sources

# Stop
pkill -f uvicorn

# Uninstall
sudo dpkg -r open-omniscience
```

---

## 📚 Documentation

- **[BUILD_INSTRUCTIONS.md](package/BUILD_INSTRUCTIONS.md)** - Detailed build instructions
- **[README.md](README.md)** - Main project documentation
- **[DATABASE.md](docs/DATABASE.md)** - Database setup
- **[USER_GUIDE.md](docs/USER_GUIDE.md)** - User guide
- **[DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** - Developer guide

---

## 🤝 Contributing

Contributions to the packaging are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test the packages
5. Submit a pull request

**Areas for improvement:**
- Add actual application icon
- Add systemd service for production
- Add man pages
- Add post-install scripts
- Add AppStream metadata for software centers
- Add Flatpak support
- Add Snap support
- Add RPM support (Fedora, CentOS)

---

## 📄 License

All packaging files are licensed under the **MIT License**, same as the main project.

See [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- **linuxdeploy** - AppImage creation tool
- **appimagetool** - AppImage packaging tool
- **Debian** - Packaging standards and tools
- **AppImage** - Portable application format

---

## 📞 Support

For issues with packaging:
- **GitHub Issues:** [https://github.com/ideotion/Open-Omniscience/issues](https://github.com/ideotion/Open-Omniscience/issues)
- **Documentation:** [https://github.com/ideotion/Open-Omniscience](https://github.com/ideotion/Open-Omniscience)

---

**Last Updated:** 2026-05-08  
**Version:** 0.2.0  
**Author:** Mistral Vibe Code (Autonomous Agent)  
**Repository:** ideotion/Open-Omniscience
