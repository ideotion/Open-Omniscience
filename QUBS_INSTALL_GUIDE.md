# Open-Omniscience Qubes-OS Installation Guide (LEGACY)

## Version 2.0.0 - Compatible with Qubes OS R4.1+ and Debian Trixie (12)
**Status:** ⚠️ **DEPRECATED** - Use [UNIFIED_DOCUMENTATION.md](UNIFIED_DOCUMENTATION.md) instead

> 📚 **PLEASE USE:** [UNIFIED_DOCUMENTATION.md](UNIFIED_DOCUMENTATION.md) - Single documentation for all users

> ⚠️ **DEPRECATION NOTICE**: This file is kept for backward compatibility but all new users should use the unified documentation and installer. The unified installer automatically detects Qubes OS and adapts accordingly.

### 🔗 Quick Link to Unified Documentation
**→ [UNIFIED_DOCUMENTATION.md](UNIFIED_DOCUMENTATION.md)**

### 🚀 Quick Start with Unified Installer
```bash
# This single command works for Qubes OS too!
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/0.03/UNIFIED_INSTALL.sh | bash
```

The unified installer will:
- ✅ Automatically detect Qubes OS
- ✅ Ask "Are you installing on Qubes OS?" if uncertain
- ✅ Create the 4 isolated VMs with proper configuration
- ✅ Install Open-Omniscience in each VM
- ✅ Configure network isolation correctly

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation Methods](#installation-methods)
4. [Main Installer (qubes-installer.sh)](#main-installer-qubes-installersh)
5. [Disposable VM Launcher (qubes-disp-launcher.sh)](#disposable-vm-launcher-qubes-disp-launchersh)
6. [Architecture](#architecture)
7. [Configuration](#configuration)
8. [Usage Examples](#usage-examples)
9. [Troubleshooting](#troubleshooting)
10. [Security Considerations](#security-considerations)
11. [Disposable VM Constraints](#disposable-vm-constraints)
12. [Python venv Limitations](#python-venv-limitations)
13. [Cleanup and Maintenance](#cleanup-and-maintenance)

---

## Overview

This guide provides comprehensive instructions for installing and using Open-Omniscience in Qubes OS with full support for:

- **Disposable VMs (default-dvm)**: Temporary, isolated environments that are automatically cleaned up
- **Persistent VMs**: Long-running VMs for services like API, Database, Scraping, and AI
- **Qubes RPC Communication**: Secure inter-VM communication
- **Network Isolation**: Database VM has no network access
- **Debian Trixie Compatibility**: Full support for Debian 12 in Qubes OS R4.1+

---

## Prerequisites

### Qubes OS Requirements

- **Qubes OS Version**: R4.1 or later
- **Template VM**: Debian 12 (Trixie) template must be installed
- **NetVM**: A network-providing VM (recommended: `sys-whonix` for Tor, `sys-firewall` for direct)
- **Disk Space**: Minimum 20GB free space across VMs
- **Memory**: Minimum 8GB RAM (16GB recommended for AI operations)

### Install Debian 12 Template

If you don't have the Debian 12 template installed:

```bash
# In dom0
sudo qubesctl state.sls qvm.template-debian-12
```

Wait for the template to download and install. This may take several minutes depending on your internet connection.

### Verify Template Installation

```bash
# In dom0
qvm-ls --templates
```

You should see `debian-12` in the list of available templates.

---

## Installation Methods

Open-Omniscience provides two installation methods for Qubes OS:

### 1. Full Installation (Recommended)

Creates 4 persistent VMs with full Open-Omniscience functionality:
- API VM (Blue): HTTP API and coordination
- Database VM (Green): PostgreSQL database (no network)
- Scraper VM (Yellow): Web scraping workers
- AI VM (Red): AI/LLM integration

**Use**: `sudo ./qubes-installer.sh`

### 2. Disposable VM Installation

Creates temporary VMs for testing and development:
- Disposable Template: Pre-configured environment
- Disposable VMs: Temporary instances created on-demand

**Use**: `./qubes-disp-launcher.sh`

---

## Main Installer (qubes-installer.sh)

### Quick Start

```bash
# Clone the repository (in any AppVM with network access)
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
git checkout 0.03_Qubes

# Run the installer (must be run as root in dom0)
sudo ./qubes-installer.sh
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--help, -h` | Show help message | - |
| `--dry-run, -n` | Show what would be done without making changes | - |
| `--clean, -c` | Remove all Open-Omniscience VMs | - |
| `--template, -t NAME` | Use specific template VM | debian-12 |
| `--netvm, -N NAME` | Use specific NetVM | sys-whonix |
| `--memory, -m SIZE` | Base memory in MB | 2048 |
| `--verbose, -v` | Enable verbose output | - |

### Installation Process

The installer performs the following steps:

1. **Environment Validation**
   - Checks for Qubes OS
   - Verifies root privileges
   - Validates template and NetVM existence

2. **VM Creation**
   - Creates 4 AppVMs with appropriate labels and resources
   - Configures network settings (DB VM has no network)

3. **Package Installation**
   - Installs PostgreSQL 15 in Database VM
   - Installs Python 3, pip, venv, and dependencies in all VMs
   - Installs nginx and uvicorn in API VM
   - Installs scraping libraries in Scraper VM

4. **Repository Setup**
   - Clones Open-Omniscience repository in each VM
   - Checks out the `0.03_Qubes` branch

5. **Python Environment Setup**
   - Creates virtual environments in persistent VMs
   - Installs Python requirements

6. **Service Configuration**
   - Configures PostgreSQL in Database VM
   - Sets up nginx reverse proxy in API VM
   - Creates systemd services for all components

7. **Qubes RPC Configuration**
   - Configures RPC policies for inter-VM communication
   - Sets up secure communication channels

8. **Verification**
   - Validates all VMs are created and running
   - Checks network isolation
   - Verifies service status

### Resource Allocation

| VM | Memory | Max Memory | VCPUs | Label | Network |
|----|--------|------------|-------|-------|---------|
| API VM | 2048 MB | 4096 MB | 2 | Blue | Yes (via NetVM) |
| Database VM | 1024 MB | 2048 MB | 1 | Green | No |
| Scraper VM | 2048 MB | 4096 MB | 2 | Yellow | Yes (via NetVM) |
| AI VM | 4096 MB | 8192 MB | 4 | Red | Yes (via NetVM) |

### Customizing Resources

To adjust resource allocation:

```bash
# Increase AI VM resources
sudo ./qubes-installer.sh --memory 4096

# Use a different NetVM
sudo ./qubes-installer.sh --netvm sys-firewall

# Use a custom template
sudo ./qubes-installer.sh --template my-custom-debian-12
```

### Dry Run Mode

To see what the installer will do without making changes:

```bash
sudo ./qubes-installer.sh --dry-run
```

### Cleanup

To remove all Open-Omniscience VMs:

```bash
sudo ./qubes-installer.sh --clean
```

---

## Disposable VM Launcher (qubes-disp-launcher.sh)

### Overview

The disposable VM launcher provides a convenient way to create and use temporary VMs for:

- Testing and development
- One-off analysis tasks
- Security-sensitive operations
- Temporary experimentation

**Key Features:**
- Automatic VM creation from pre-configured template
- Automatic cleanup after use
- No persistent state (all changes are lost)
- System-wide Python installation (no venv persistence issues)

### Prerequisites

The disposable template must be created first by running the main installer:

```bash
sudo ./qubes-installer.sh
```

This creates the `open-omniscience-disp-template` TemplateVM with all dependencies pre-installed.

### Commands

| Command | Description |
|---------|-------------|
| `start` | Start Open-Omniscience in a new disposable VM |
| `run COMMAND` | Run a command in a disposable VM |
| `exec SCRIPT` | Execute a Python script in a disposable VM |
| `shell` | Open a shell in a disposable VM |
| `clean [VM...]` | Clean up disposable VMs |
| `list` | List active disposable VMs |
| `help` | Show help message |

### Usage Examples

#### Start Open-Omniscience

```bash
./qubes-disp-launcher.sh start
```

This creates a disposable VM, starts Open-Omniscience, and displays connection information.

#### Run a Command

```bash
./qubes-disp-launcher.sh run "python3 -c 'from src.qubes import get_qubes_environment; print(get_qubes_environment())'"
```

#### Execute a Python Script

```bash
./qubes-disp-launcher.sh exec src/scripts/analyze.py input.txt
```

#### Open a Shell

```bash
./qubes-disp-launcher.sh shell
```

This opens an xterm window in a disposable VM. The VM is automatically cleaned up when you exit the shell.

#### List Disposable VMs

```bash
./qubes-disp-launcher.sh list
```

#### Clean Up

```bash
# Clean all disposable VMs
./qubes-disp-launcher.sh clean

# Clean specific VM
./qubes-disp-launcher.sh clean open-omniscience-disp-12345678
```

---

## Architecture

### VM Layout

```
┌─────────────────────────────────────────────────────────────────┐
│                        Qubes OS R4.1+                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   API VM      │    │  Scraper VM  │    │   AI VM      │      │
│  │  (Blue)       │    │  (Yellow)    │    │  (Red)       │      │
│  │  FastAPI      │    │  Workers     │    │  LLM Models  │      │
│  │  Nginx        │    │  Requests    │    │  Analysis    │      │
│  │  Coordination │    │              │    │              │      │
│  └──────┬────────┘    └──────┬────────┘    └──────┬────────┘      │
│         │                     │                     │               │
│         ▼                     ▼                     ▼               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Qubes RPC Communication                   │    │
│  │  (JSON-RPC over qvm-run)                                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│         │                     │                     │               │
│         ▼                     ▼                     ▼               │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   DB VM       │    │  sys-whonix  │    │  sys-whonix  │      │
│  │  (Green)      │    │  (ProxyVM)    │    │  (ProxyVM)    │      │
│  │  PostgreSQL   │    │  Network      │    │  Network      │      │
│  │  No Network   │    │  Access       │    │  Access       │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│                                                                     │
└─────────────────────────────────────────────────────────────────┘
```

### Communication Flow

1. **User Request**: User sends request to API VM via HTTP
2. **API Processing**: API VM processes request and determines required operations
3. **RPC Calls**: API VM uses Qubes RPC to call appropriate VMs:
   - Database operations → DB VM
   - Scraping operations → Scraper VM
   - AI operations → AI VM
4. **Response Aggregation**: API VM collects responses from all VMs
5. **User Response**: API VM returns final response to user

### Qubes RPC Configuration

The installer configures the following RPC policies:

**API VM can call:**
- `open-omniscience.db.query` → DB VM
- `open-omniscience.db.store` → DB VM
- `open-omniscience.scrape.start` → Scraper VM
- `open-omniscience.scrape.status` → Scraper VM
- `open-omniscience.ai.analyze` → AI VM
- `open-omniscience.ai.generate` → AI VM

**Scraper VM can be called by:**
- `open-omniscience.scrape.start` ← Any VM
- `open-omniscience.scrape.status` ← Any VM

**AI VM can be called by:**
- `open-omniscience.ai.analyze` ← Any VM
- `open-omniscience.ai.generate` ← Any VM

---

## Configuration

### Environment Variables

The following environment variables can be set in each VM:

| Variable | Description | Default |
|----------|-------------|---------|
| `INSTALL_DIR` | Installation directory | /opt/open-omniscience |
| `LOG_DIR` | Log directory | /var/log/open-omniscience |
| `DATA_DIR` | Data directory | /var/lib/open-omniscience |
| `CONFIG_DIR` | Configuration directory | /etc/open-omniscience |

### Configuration Files

Each VM has configuration files in `/etc/open-omniscience/`:

- **API VM**: `rpc.conf` - RPC policy configuration
- **Database VM**: `database.conf` - Database credentials and settings
- **All VMs**: `config.yaml` - General Open-Omniscience configuration

### Custom Configuration

To customize the configuration:

1. Edit the configuration files in each VM:
   ```bash
   qvm-run -u open-omniscience-api 'nano /etc/open-omniscience/config.yaml'
   ```

2. Restart the services:
   ```bash
   qvm-run -u open-omniscience-api 'systemctl restart open-omniscience-api.service'
   ```

---

## Usage Examples

### Starting the System

```bash
# Full installation
sudo ./qubes-installer.sh

# Verify installation
sudo ./qubes-installer.sh --dry-run
```

### Accessing the API

```bash
# From dom0 or any VM with network access to API VM
curl http://open-omniscience-api

# Or use qvm-run to access from another VM
qvm-run -u open-omniscience-api 'curl http://localhost'
```

### Running a Scrape Job

```bash
# Start a scrape job via RPC
qvm-run -u open-omniscience-api 'python3 -c "from src.qubes.rpc import QubesRPCClient; client = QubesRPCClient(\"open-omniscience-scraper\"); print(client.scrape(\"https://example.com\"))"'
```

### Using AI Analysis

```bash
# Analyze content using AI VM
qvm-run -u open-omniscience-api 'python3 -c "from src.qubes.rpc import QubesRPCClient; client = QubesRPCClient(\"open-omniscience-ai\"); print(client.analyze(\"Analyze this text...\"))"'
```

### Database Operations

```bash
# Query the database (from API VM)
qvm-run -u open-omniscience-api 'psql -h open-omniscience-db -U omniscience -d open_omniscience -c "SELECT * FROM documents LIMIT 10;"'
```

### Disposable VM Usage

```bash
# Start a disposable VM for testing
./qubes-disp-launcher.sh start

# Run a quick test
./qubes-disp-launcher.sh run "python3 -c 'import sys; print(sys.version)'"

# Execute a script
./qubes-disp-launcher.sh exec src/scripts/test.py

# Open a shell for development
./qubes-disp-launcher.sh shell
```

---

## Troubleshooting

### Common Issues

#### Template VM Not Found

**Error**: `Template VM 'debian-12' not found`

**Solution**: Install the Debian 12 template:
```bash
sudo qubesctl state.sls qvm.template-debian-12
```

#### NetVM Not Found

**Error**: `NetVM 'sys-whonix' not found`

**Solution**: Install sys-whonix or use an existing NetVM:
```bash
# Install sys-whonix
sudo qubesctl state.sls qvm.sys-whonix

# Or use a different NetVM
sudo ./qubes-installer.sh --netvm sys-firewall
```

#### Permission Denied

**Error**: `This script must be run as root`

**Solution**: Run the installer with sudo:
```bash
sudo ./qubes-installer.sh
```

#### VM Creation Failed

**Error**: `Failed to create VM`

**Solution**: Check available resources and try again:
```bash
# Check available memory
qvm-prefs

# Check disk space
df -h

# Try with reduced resources
sudo ./qubes-installer.sh --memory 1024
```

#### Package Installation Failed

**Error**: `Failed to install packages in VM`

**Solution**: Check the VM's package sources and try manually:
```bash
# Update package lists in the VM
qvm-run -u open-omniscience-api 'apt-get update'

# Install packages manually
qvm-run -u open-omniscience-api 'apt-get install -y python3-pip'

# Then retry the installer
sudo ./qubes-installer.sh
```

#### Database Connection Failed

**Error**: `Failed to connect to database`

**Solution**: Verify database VM is running and PostgreSQL is configured:
```bash
# Check if DB VM is running
qvm-ls | grep open-omniscience-db

# Check PostgreSQL status
qvm-run -u open-omniscience-db 'systemctl status postgresql@15-main'

# Check database configuration
qvm-run -u open-omniscience-db 'cat /etc/open-omniscience/database.conf'
```

### Debug Mode

Enable verbose output for detailed debugging:

```bash
sudo ./qubes-installer.sh --verbose
```

### Manual Verification

Check each component manually:

```bash
# Check VMs exist
qvm-ls | grep open-omniscience

# Check VMs are running
qvm-ls | grep -E "open-omniscience-.*Running"

# Check network configuration
qvm-prefs open-omniscience-db | grep netvm
# Should show empty (no network)

qvm-prefs open-omniscience-api | grep netvm
# Should show your NetVM

# Check services
qvm-run -u open-omniscience-api 'systemctl status open-omniscience-api.service'
qvm-run -u open-omniscience-db 'systemctl status postgresql@15-main'
```

---

## Security Considerations

### Network Isolation

- **Database VM**: Has NO network access. All database operations are isolated.
- **API VM**: Has network access via NetVM for external API calls.
- **Scraper VM**: Has network access via NetVM for web scraping.
- **AI VM**: Has network access via NetVM for downloading models.

### Qubes RPC Security

- All inter-VM communication uses Qubes RPC with explicit policies.
- RPC calls are restricted to specific VMs and methods.
- No direct filesystem sharing between VMs.
- File transfer uses `qvm-move-to-vm` for controlled access.

### Data Protection

- Database credentials are stored in the Database VM only.
- API keys and sensitive data should be stored in appropriate VMs.
- Use Qubes' file copying mechanisms for data transfer:
  ```bash
  # Copy file from dom0 to API VM
  qvm-move-to-vm open-omniscience-api data.json
  
  # Copy file from API VM to dom0
  qvm-run -u open-omniscience-api 'cat /path/to/file' > output.txt
  ```

### Firewall Rules

- The Database VM has no network access by design.
- All external traffic goes through the configured NetVM.
- Use `sys-whonix` for Tor-based anonymity.
- Use `sys-firewall` for direct network access.

---

## Disposable VM Constraints

### What Works in Disposable VMs

✅ **Supported:**
- Running Python scripts
- Using system-wide Python packages
- Accessing the Open-Omniscience codebase
- Making RPC calls to other VMs
- Temporary file storage (lost on cleanup)
- Network access (via NetVM)

### What Doesn't Work in Disposable VMs

❌ **Not Supported:**
- Persistent Python virtual environments (venv)
- Persistent data storage
- Systemd services (won't start automatically)
- Background processes (killed on VM shutdown)
- Installation of new system packages (not persisted)

### Workarounds

#### Python Dependencies

For disposable VMs, dependencies must be installed in the TemplateVM:

```bash
# Install in TemplateVM (persists for all disposable VMs)
qvm-run -u open-omniscience-disp-template 'pip3 install package-name'
```

#### Persistent Data

For persistent data, use the persistent VMs:

```bash
# Store data in API VM
qvm-run -u open-omniscience-api 'echo "data" > /var/lib/open-omniscience/data.txt'

# Access from disposable VM via RPC
# (Implement custom RPC calls to fetch/store data)
```

#### System Services

For long-running processes, use persistent VMs:

```bash
# Start service in API VM (persistent)
qvm-run -u open-omniscience-api 'systemctl start open-omniscience-api.service'
```

---

## Python venv Limitations

### The Problem

Python virtual environments (venv) don't work well in disposable VMs because:

1. **No Persistence**: venv is created in the disposable VM and lost on cleanup
2. **No Restart**: Services that need to restart (like uvicorn) can't in disposables
3. **Resource Overhead**: Creating venv on each disposable VM start is slow

### Our Solution

The Qubes installer handles this in two ways:

#### 1. Persistent VMs: Use venv

For persistent VMs (API, DB, Scraper, AI), the installer creates venv:

```bash
# In persistent VMs
cd /opt/open-omniscience
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. Disposable VMs: System-wide Python

For disposable VMs, the installer uses system-wide Python:

```bash
# In disposable template
apt-get install -y python3-pip
pip3 install -r /opt/open-omniscience/requirements.txt
```

This ensures:
- ✅ Dependencies are pre-installed in the template
- ✅ All disposable VMs inherit the dependencies
- ✅ No venv creation overhead on each start
- ✅ Works with disposable VM constraints

### Manual venv Setup (If Needed)

If you need venv in a disposable VM for testing:

```bash
# In disposable VM
cd /opt/open-omniscience
python3 -m venv /tmp/omniscience-venv
source /tmp/omniscience-venv/bin/activate
pip install -r requirements.txt

# Use the venv
python src/main.py
```

Note: This venv will be lost when the disposable VM is cleaned up.

---

## Cleanup and Maintenance

### Full Cleanup

To remove all Open-Omniscience VMs and data:

```bash
sudo ./qubes-installer.sh --clean
```

This removes:
- API VM
- Database VM
- Scraper VM
- AI VM
- Disposable Template VM

### Partial Cleanup

To remove specific VMs:

```bash
# Remove a single VM
qvm-remove open-omniscience-api

# Remove multiple VMs
for vm in open-omniscience-api open-omniscience-db; do
    qvm-remove $vm
Done
```

### Update Open-Omniscience

To update to the latest version:

```bash
# In each VM
for vm in open-omniscience-api open-omniscience-db open-omniscience-scraper open-omniscience-ai; do
    qvm-run -u $vm 'cd /opt/open-omniscience && git pull origin 0.03_Qubes'
done

# Restart services
qvm-run -u open-omniscience-api 'systemctl restart open-omniscience-api.service'
qvm-run -u open-omniscience-scraper 'systemctl restart open-omniscience-scraper.service'
qvm-run -u open-omniscience-ai 'systemctl restart open-omniscience-ai.service'
```

### Backup Configuration

To backup configuration files:

```bash
# From dom0
mkdir -p ~/open-omniscience-backup

for vm in open-omniscience-api open-omniscience-db; do
    qvm-run -u $vm 'tar czf /home/user/config-backup.tar.gz /etc/open-omniscience'
    qvm-move-to-vm dom0 /home/user/config-backup.tar.gz
    mv user:config-backup.tar.gz ~/open-omniscience-backup/${vm}-config.tar.gz
    qvm-remove -f user:config-backup.tar.gz
done
```

### Restore Configuration

To restore configuration files:

```bash
# From dom0
for vm in open-omniscience-api open-omniscience-db; do
    cp ~/open-omniscience-backup/${vm}-config.tar.gz user:
    qvm-move-to-vm $vm user:config-backup.tar.gz
    qvm-run -u $vm 'tar xzf /home/user/config-backup.tar.gz -C / && rm /home/user/config-backup.tar.gz'
    qvm-remove -f user:config-backup.tar.gz
done
```

---

## Summary

This guide provides comprehensive instructions for installing and using Open-Omniscience in Qubes OS with full support for:

- ✅ **Automated Installation**: Single command to deploy all VMs
- ✅ **Disposable VM Support**: Temporary VMs for testing and development
- ✅ **Network Isolation**: Database VM has no network access
- ✅ **Qubes RPC**: Secure inter-VM communication
- ✅ **Debian Trixie Compatibility**: Full support for Debian 12
- ✅ **Python venv Workarounds**: Solutions for disposable VM constraints
- ✅ **Comprehensive Documentation**: Complete guide for all scenarios

For more information, see:
- [README-QUBES.md](README-QUBES.md) - Quick start guide
- [QUBES_ADAPTATION_SUMMARY.md](QUBES_ADAPTATION_SUMMARY.md) - Technical details
- [qubes-installer.sh](qubes-installer.sh) - Main installer script
- [qubes-disp-launcher.sh](qubes-disp-launcher.sh) - Disposable VM launcher

---

*Last Updated: 2024*
*Compatible with Qubes OS R4.1+ and Debian Trixie (12)*
