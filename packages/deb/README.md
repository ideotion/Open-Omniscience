# Open-Omniscience Debian Package

This directory contains the Debian package (.deb) for Open-Omniscience, allowing for easy installation on Debian-based systems (Ubuntu, Debian, etc.).

## Package Information

- **Package Name**: open-omniscience
- **Version**: 0.02-1
- **Architecture**: all
- **Maintainer**: Open-Omniscience Team <team@ideotion.com>
- **Dependencies**: docker.io, docker-compose, git, curl, python3, python3-venv, python3-pip

## Installation

### Method 1: Direct Download and Install

```bash
# Download the .deb package
wget https://github.com/ideotion/Open-Omniscience/raw/main/packages/deb/open-omniscience_0.02-1_all.deb

# Install the package
sudo dpkg -i open-omniscience_0.02-1_all.deb

# Fix any missing dependencies
sudo apt-get install -f
```

### Method 2: Clone Repository and Install

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Install the package
sudo dpkg -i packages/deb/open-omniscience_0.02-1_all.deb

# Fix any missing dependencies
sudo apt-get install -f
```

## Post-Installation

After installation:

1. The package installs all files to `/opt/open-omniscience/`
2. The post-installation script automatically runs the `install` script
3. All dependencies (Docker, Docker Compose, Git, Python, etc.) are automatically installed
4. A symlink is created at `/usr/local/bin/open-omniscience` for easy access

## Starting Open-Omniscience

```bash
# Navigate to the installation directory
cd /opt/open-omniscience

# Start the application (without LLM)
docker-compose up -d --build

# OR start with LLM support (requires more resources)
docker-compose -f docker-compose.yml -f docker-compose.llm.yml up -d --build

# Access the application at: http://localhost:8000
```

## Uninstallation

```bash
# Remove the package
sudo dpkg -r open-omniscience

# Optionally remove the installation directory
sudo rm -rf /opt/open-omniscience
```

## Building the Package

To rebuild the .deb package:

```bash
# Navigate to the packages/deb directory
cd packages/deb

# Run the build script
./build-deb.sh
```

The build script will create a new .deb file in the current directory.

## Package Contents

The .deb package includes:

- All source code from the Open-Omniscience repository
- Configuration files (`configs/`)
- Docker files (`Dockerfile`, `docker-compose.yml`, etc.)
- Documentation (`docs/`)
- Installation script (`install`)
- All pillar modules (pillar2, pillar3, pillar4)
- Requirements files
- Static web assets

## Dependencies

The package requires the following dependencies to be installed:

- `docker.io` - Docker engine
- `docker-compose` - Docker Compose
- `git` - Version control system
- `curl` - URL transfer utility
- `python3` - Python 3 interpreter
- `python3-venv` - Python virtual environment support
- `python3-pip` - Python package installer

These dependencies will be automatically installed when you run `sudo apt-get install -f` after installing the .deb package.

## Troubleshooting

### Dependency Issues

If you encounter dependency issues during installation:

```bash
sudo apt-get install -f
```

### Permission Issues

If you encounter permission issues:

```bash
sudo chown -R $USER:$USER /opt/open-omniscience
```

### Docker Not Starting

If Docker doesn't start automatically:

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

### Port Already in Use

If port 8000 is already in use:

```bash
# Edit docker-compose.yml and change the port
# Or stop the conflicting service
sudo lsof -i :8000
sudo kill <PID>
```

## License

This package is distributed under the same license as Open-Omniscience: GNU GPLv3.

See the [LICENSE](../../LICENSE) file for more details.
