# Open-Omniscience Qubes-OS Edition

## 🚀 Overview

This is the **Qubes-OS compatible** version of Open-Omniscience, specifically adapted for **Debian Trixie (12)** environments in **Qubes OS R4.1+**. This adaptation implements a **multi-VM architecture** that leverages Qubes OS's security features for maximum isolation and protection.

### Key Features

✅ **Full Qubes OS Integration** - Native support for Qubes RPC and VM management
✅ **Multi-VM Architecture** - Components isolated in separate VMs for security
✅ **Debian Trixie Compatible** - Tested and optimized for Debian 12
✅ **Secure Communication** - All inter-VM communication via Qubes RPC
✅ **Automated Deployment** - Single script to deploy across all VMs
✅ **Comprehensive Documentation** - Complete guides for installation and usage

---

## 🏗️ Architecture

### VM Layout

| VM Name | Type | Label | Purpose | Network |
|---------|------|-------|---------|---------|
| `open-omniscience-api` | AppVM | Blue | HTTP API, Coordination | sys-whonix |
| `open-omniscience-db` | AppVM | Green | PostgreSQL Database | None |
| `open-omniscience-scraper` | AppVM | Yellow | Web Scraping | sys-whonix |
| `open-omniscience-ai` | AppVM | Red | LLM Integration | sys-whonix |

### Communication Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   API VM     │    │  Scraper VM  │    │   DB VM      │
│  (Blue)      │◄──►│  (Yellow)    │    │  (Green)     │
│              │    │              │    │              │
│  FastAPI    │    │  Scraper    │    │ PostgreSQL  │
│  Nginx      │    │  Worker     │    │  Database    │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                     │                     │
       ▼                     ▼                     ▼
       └─────────────────────┬─────────────────────┘
                             │
                    Qubes RPC Communication
                             │
                             ▼
              ┌───────────────────────────┐
              │    sys-whonix ProxyVM     │
              │  (Network Access Gateway) │
              └───────────────────────────┘
```

---

## 📦 Quick Start

### Prerequisites

1. **Qubes OS R4.1+** installed and running
2. **Debian 12 (Trixie) template** available
3. **sys-whonix or sys-firewall** ProxyVM available
4. **Root access** in dom0
5. **Git** installed in dom0

### Installation

1. **Clone this repository in dom0:**
   ```bash
   git clone https://github.com/ideotion/Open-Omniscience.git
   cd Open-Omniscience-Qubes
   ```

2. **Run the installer:**
   ```bash
   chmod +x qubes-installer.sh
   sudo ./qubes-installer.sh
   ```

3. **Follow the prompts** to configure and deploy

4. **Start all VMs:**
   ```bash
   qvm-start open-omniscience-api
   qvm-start open-omniscience-db
   qvm-start open-omniscience-scraper
   qvm-start open-omniscience-ai
   ```

5. **Access the API:**
   ```bash
   qvm-run -u open-omniscience-api curl http://localhost:8000
   ```

---

## 📂 Repository Structure

```
Open-Omniscience-Qubes/
├── README-QUBES.md              # This file
├── FINAL_REPORT.md              # Complete debugging & adaptation report
├── QUBES_ADAPTATION_SUMMARY.md  # Detailed adaptation guide
├── INSTALL-QUBES.sh             # Legacy installation script (deprecated)
├── src/
│   └── qubes/                   # Qubes-specific modules
│       ├── __init__.py          # Qubes environment utilities
│       ├── rpc/                 # RPC communication
│       │   ├── __init__.py
│       │   ├── client.py        # RPC client implementation
│       │   └── server.py        # RPC server implementation
│       └── vm/                  # VM-specific modules
│           ├── __init__.py
│           ├── api_vm.py        # API VM management
│           ├── db_vm.py         # Database VM management
│           ├── scraper_vm.py    # Scraper VM management
│           └── ai_vm.py         # AI VM management
└── qubes/
    ├── configs/                 # VM configuration files
    │   ├── api-vm.yaml
    │   ├── db-vm.yaml
    │   ├── scraper-vm.yaml
    │   └── ai-vm.yaml
    └── scripts/                 # Additional scripts
        └── setup-qubes.sh
```

---

## 🔧 Configuration

### Environment Variables

Each VM can be configured via environment variables:

**API VM:**
```bash
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4
DB_VM=open-omniscience-db
SCRAPER_VM=open-omniscience-scraper
SECRET_KEY=your-secret-key
CSRF_SECRET=your-csrf-secret
```

**Database VM:**
```bash
DB_NAME=open_omniscience
DB_USER=omniscience
DB_PASSWORD=your-db-password
```

### Configuration Files

Configuration files are stored in `/etc/open-omniscience/` in each VM:

- `api-vm.yaml` - API VM settings
- `db-vm.yaml` - Database VM settings
- `scraper-vm.yaml` - Scraper VM settings
- `ai-vm.yaml` - AI VM settings
- `settings.yaml` - Application settings
- `sources.yaml` - News sources configuration

---

## 🚀 Usage

### Starting the System

```bash
# Start all VMs
qvm-start open-omniscience-api
qvm-start open-omniscience-db
qvm-start open-omniscience-scraper
qvm-start open-omniscience-ai

# Check status
qvm-ls
```

### Accessing the API

From dom0:
```bash
# Ping the API
qvm-run -u open-omniscience-api curl http://localhost:8000/ping

# Get status
qvm-run -u open-omniscience-api curl http://localhost:8000/status

# Make a request
qvm-run -u open-omniscience-api curl -X POST http://localhost:8000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

### Direct RPC Calls

```bash
# Ping the API VM
qvm-run -u open-omniscience-api python3 -c "
from src.qubes.rpc.server import main
import sys
main()
" <<< '{"action": "ping"}'

# Get status
qvm-run -u open-omniscience-api python3 -c "
from src.qubes.rpc.server import main
main()
" <<< '{"action": "status"}'
```

### Python Usage

From within a VM:
```python
# Query database via API VM
from src.qubes.vm import get_api_vm

result = get_api_vm().query_database(
    {'query': 'SELECT * FROM articles LIMIT 10'},
    'articles'
)
print(result)

# Start a scrape job
job = get_api_vm().start_scrape_job('https://example.com')
print(f"Job ID: {job['job_id']}")

# Get job status
status = get_api_vm().get_scrape_status(job['job_id'])
print(status)
```

---

## 🔍 Monitoring

### Logs

Each VM maintains its own logs:

- **API VM:** `/var/log/open-omniscience/api.log`
- **Database VM:** `/var/log/postgresql/postgresql-15-main.log`
- **Scraper VM:** `/var/log/open-omniscience/scraper.log`
- **AI VM:** `/var/log/open-omniscience/ai.log`

View logs:
```bash
# View API VM logs
qvm-run -u open-omniscience-api tail -f /var/log/open-omniscience/api.log

# View database logs
qvm-run -u open-omniscience-db tail -f /var/log/postgresql/postgresql-15-main.log
```

### Health Checks

```bash
# Check API VM health
qvm-run -u open-omniscience-api curl http://localhost:8000/health

# Check database connection
qvm-run -u open-omniscience-api python3 -c "
from src.qubes.vm import get_api_vm
print(get_api_vm().get_health_status())
"
```

---

## 🛠️ Management

### Service Commands

```bash
# In API VM
sudo systemctl start open-omniscience-api
sudo systemctl stop open-omniscience-api
sudo systemctl restart open-omniscience-api
sudo systemctl status open-omniscience-api
sudo systemctl enable open-omniscience-api

# View logs
sudo journalctl -u open-omniscience-api -f
```

### Updates

```bash
# In each VM
cd /opt/open-omniscience
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart open-omniscience-api
```

---

## 🔒 Security

### Security Features

✅ **VM Isolation** - Each component in separate VM
✅ **No Network for DB** - Database VM has no network access
✅ **Controlled Access** - File access via qvm-move-to-vm
✅ **Qubes RPC** - Secure inter-VM communication
✅ **ProxyVM Routing** - All network traffic through sys-whonix
✅ **Minimal Privileges** - Each VM has only necessary permissions
✅ **No Hardcoded Secrets** - All credentials in secure configurations

### Security Best Practices

1. **Keep VMs Updated**
   ```bash
   sudo qubes-dom0-update
   qvm-run -u <vm> apt-get update && apt-get upgrade -y
   ```

2. **Use Strong Passwords**
   - Generate strong passwords for all services
   - Rotate credentials regularly
   - Use Qubes password manager

3. **Monitor Activity**
   - Regularly review logs
   - Set up alerts for unusual activity
   - Use Qubes built-in security features

4. **Backup Regularly**
   ```bash
   qvm-backup
   ```

---

## 🐛 Troubleshooting

### Common Issues

**1. VM creation fails**
- Ensure template VM exists: `qvm-ls`
- Check available memory: `qvm-prefs sys-whonix available_memory`
- Try with smaller memory settings

**2. Package installation fails**
- Update package lists: `qvm-run -u <vm> apt-get update`
- Check for held packages: `qvm-run -u <vm> apt-mark showhold`
- Try installing packages individually

**3. RPC calls fail**
- Verify VM is running: `qvm-ls`
- Check VM logs: `qvm-run -u <vm> journalctl -f`
- Test with simple command: `qvm-run -u <vm> echo test`

**4. Database connection fails**
- Verify database VM is running
- Check PostgreSQL is running: `qvm-run -u open-omniscience-db systemctl status postgresql@15-main`
- Test connection: `qvm-run -u open-omniscience-db su - postgres -c "psql -c 'SELECT 1;'"`

### Debug Mode

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
python3 -c "from src.qubes import get_qubes_environment; print(get_qubes_environment().is_qubes)"
```

---

## 📚 Documentation

- **[FINAL_REPORT.md](FINAL_REPORT.md)** - Complete debugging and adaptation report
- **[QUBES_ADAPTATION_SUMMARY.md](QUBES_ADAPTATION_SUMMARY.md)** - Detailed adaptation guide
- **[INSTALL-QUBES.sh](INSTALL-QUBES.sh)** - Legacy installation script (deprecated, use `qubes-installer.sh` instead)

### Original Documentation

The original Open-Omniscience documentation is available in the `docs/` directory of the main repository:
- [Open-Omniscience GitHub](https://github.com/ideotion/Open-Omniscience)

---

## 🤝 Contributing

### Development Setup

1. Clone the repository in dom0
2. Make changes in the appropriate files
3. Test in a Qubes environment
4. Submit pull requests

### Testing

Run tests in each VM:
```bash
cd /opt/open-omniscience
source venv/bin/activate
python3 -m pytest tests/ -v
```

### Code Style

Follow the existing code style:
- PEP 8 compliance
- Type hints where appropriate
- Comprehensive docstrings
- Clear variable names

---

## 📜 License

This project is licensed under the same license as the original Open-Omniscience project. See the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- [Qubes OS](https://qubes-os.org/) - The secure operating system
- [Open-Omniscience](https://github.com/ideotion/Open-Omniscience) - The original project
- [Debian](https://www.debian.org/) - The universal operating system

---

## 📞 Support

For issues and questions:

1. Check the [documentation](#-documentation)
2. Review the [troubleshooting](#-troubleshooting) section
3. Open an issue on GitHub
4. Ask in the Qubes OS forums

---

*Last updated: 2026-05-23*
*Compatible with: Qubes OS R4.1+, Debian 12 (Trixie)*
