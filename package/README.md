# Open Omniscience Packaging

This directory contains configuration files and build scripts for creating distributable packages of Open Omniscience.

## Available Package Types

### 1. Debian Package (.deb)
**Location:** `package/deb/`

**Build Script:** `package/deb/build-deb.sh`

**Configuration Files:**
- `package/deb/debian/changelog` - Version history
- `package/deb/debian/control` - Package metadata
- `package/deb/debian/copyright` - License information
- `package/deb/debian/rules` - Build rules
- `package/deb/debian/source/` - Source package configuration

**Dependencies Required:**
```bash
sudo apt-get install dpkg-dev debhelper dh-make fakeroot build-essential
```

**Build Command:**
```bash
cd package/deb
chmod +x build-deb.sh
./build-deb.sh
```

**Output:** `package/deb/dist/open-omniscience_0.02_all.deb`

**Installation:**
```bash
sudo dpkg -i package/deb/dist/open-omniscience_0.02_all.deb
```

---

### 2. AppImage
**Location:** `package/appimage/`

**Build Script:** `package/appimage/OpenOmniscience.AppImageBuilder`

**Configuration Files:**
- `OpenOmniscience.AppImageBuilder` - Main build script
- `open-omniscience.svg` - Application icon

**Dependencies Required:**
```bash
# Download appimagetool
wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
chmod +x appimagetool-x86_64.AppImage
sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool
```

**Build Command:**
```bash
cd package/appimage
chmod +x OpenOmniscience.AppImageBuilder
./OpenOmniscience.AppImageBuilder
```

**Output:** `package/appimage/dist/OpenOmniscience-0.02-x86_64.AppImage`

**Usage:**
```bash
chmod +x OpenOmniscience-0.02-x86_64.AppImage
./OpenOmniscience-0.02-x86_64.AppImage
```

---

## Package Contents

Both package types include:

### Core Application
- `src/` - All Python source code
- `configs/` - Configuration files (sources.yml, settings.yaml)
- `requirements.txt` - Python dependencies

### Documentation
- `README.md` - Main documentation
- `LICENSE` - License file
- `ETHICS.md` - Ethical guidelines
- `SECURITY.md` - Security policy
- `CONTRIBUTING.md` - Contribution guidelines
- `docs/` - Additional documentation

### Data Directories
- `data/` - Database storage (created at runtime)
- `audit/` - Audit logs (created at runtime)
- `logs/` - Application logs (created at runtime)

---

## Version Information

- **Current Version:** 0.02
- **Maintainer:** Ideotion <open-omniscience@ideotion.com>
- **Homepage:** https://github.com/ideotion/Open-Omniscience

---

## Dependencies

### Python Dependencies (included in requirements.txt)
```
fastapi
uvicorn
sqlalchemy
requests
beautifulsoup4
feedparser
pyyaml
slowapi
prometheus-client
```

### System Dependencies
- Python 3.10 or later
- SQLite (included in Python standard library)
- Optional: PostgreSQL for production use

---

## Building from Source

If you prefer not to use the pre-built packages, you can run Open Omniscience directly from source:

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Install dependencies
pip install -r requirements.txt

# Run the application
python -m src.api.main

# Or use uvicorn directly
uvicorn src.api.main:app --reload
```

---

## Notes

1. **Debian Package:** The .deb package installs Open Omniscience system-wide and creates a command-line executable.

2. **AppImage:** The AppImage is a portable, self-contained application that runs on most Linux distributions without installation.

3. **Data Storage:** Both packages store data in the user's home directory:
   - Configuration: `~/.open-omniscience/`
   - Database: `~/.open-omniscience/data/`
   - Logs: `~/.open-omniscience/logs/`
   - Audit: `~/.open-omniscience/audit/`

4. **Permissions:** The application requires internet access to scrape news sources and network permissions to listen on the configured port (default: 8000).

---

## Troubleshooting

### Debian Package Issues
- **Dependency errors:** Run `sudo apt-get install -f` to fix missing dependencies
- **Permission errors:** Ensure you have sudo privileges for installation
- **Python version:** The package requires Python 3.10 or later

### AppImage Issues
- **No execute permission:** Run `chmod +x OpenOmniscience-*.AppImage`
- **Missing libraries:** AppImage should include all required libraries
- **FUSE required:** Some systems require FUSE to run AppImages (usually pre-installed)

### General Issues
- **Port conflicts:** Change the port in `configs/settings.yaml` if port 8000 is in use
- **Database errors:** Ensure SQLite is available or configure PostgreSQL in `DATABASE_URL`
- **Scraping issues:** Check `audit/` directory for detailed scraping logs

---

## Contributing to Packaging

To contribute improvements to the packaging:

1. Fork the repository
2. Make changes to the packaging configuration files
3. Test the build process locally
4. Submit a pull request with your changes

For Debian packages, follow the [Debian Policy Manual](https://www.debian.org/doc/debian-policy/).

For AppImages, follow the [AppImage specification](https://appimage.org/).
