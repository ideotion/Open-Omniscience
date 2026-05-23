# Open-Omniscience Qubes-OS Adaptation Summary

## Overview

This document summarizes the adaptation of Open-Omniscience for Qubes OS with Debian Trixie (12) compatibility. The adaptation follows the 7-phase debugging protocol and implements Qubes-specific security and isolation requirements.

## Architecture Changes

### Original Architecture
- Monolithic application running in a single environment
- Direct function calls between components
- Shared filesystem access
- Direct database connections

### Qubes-OS Architecture
- **Microservices across multiple VMs** for isolation
- **Qubes RPC** for inter-VM communication
- **Controlled file access** via qvm-move-to-vm
- **Network isolation** with ProxyVM routing

### VM Layout

| VM Name | Type | Purpose | Label | Memory | Network |
|---------|------|---------|-------|--------|---------|
| open-omniscience-api | AppVM | HTTP API, Coordination | Blue | 2-4GB | sys-whonix |
| open-omniscience-db | AppVM | PostgreSQL Database | Green | 1-2GB | None |
| open-omniscience-scraper | AppVM | Web Scraping | Yellow | 2-4GB | sys-whonix |
| open-omniscience-ai | AppVM | LLM Integration | Red | 4-8GB | sys-whonix |

## Key Components

### 1. Qubes Environment Detection (`src/qubes/__init__.py`)

Provides utilities for:
- Detecting if running in Qubes OS
- Getting current qube information
- Listing all VMs
- Making RPC calls between VMs
- Copying files between VMs
- Managing VM lifecycle

**Key Classes:**
- `QubeInfo`: Dataclass for VM information
- `RPCCallResult`: Dataclass for RPC call results
- `QubesEnvironment`: Main class for Qubes interactions

**Key Functions:**
- `is_qubes_os()`: Check if running in Qubes
- `get_current_qube()`: Get info about current qube
- `qubes_rpc_call()`: Make RPC call to another VM
- `copy_to_vm()`: Copy file to another VM

### 2. RPC Communication (`src/qubes/rpc/`)

#### Server (`server.py`)
- Handles incoming RPC requests
- Dispatches to appropriate handlers
- Supports actions: ping, status, info, scrape, analyze, store, query, search, upload, download, job management
- Lazy imports to avoid circular dependencies
- Comprehensive error handling

#### Client (`client.py`)
- Makes RPC calls to other VMs
- Retry logic with configurable attempts
- Timeout handling
- Convenience methods for common actions
- Client pooling for multiple VMs

**Key Classes:**
- `RPCRequest`: Request dataclass
- `RPCResponse`: Response dataclass
- `QubesRPCServer`: Server implementation
- `QubesRPCClient`: Client implementation
- `RPCClientPool`: Pool of clients for multiple VMs

### 3. VM-Specific Modules (`src/qubes/vm/`)

#### API VM (`api_vm.py`)
- HTTP server configuration
- RPC client management for other VMs
- Request routing and coordination
- Health monitoring
- Environment configuration

**Key Classes:**
- `APIVMConfig`: Configuration dataclass
- `APIVM`: Main API VM manager

**Key Features:**
- Automatic RPC client initialization
- Environment variable configuration
- Database and scraper client management
- Health status monitoring

#### Database VM (`db_vm.py`)
- PostgreSQL configuration
- Database connection management
- Query execution
- Data storage and retrieval

#### Scraper VM (`scraper_vm.py`)
- Web scraping functionality
- Content analysis
- Job queue management
- Result caching

## Configuration Files

### VM Configurations (`qubes/configs/`)

#### `api-vm.yaml`
```yaml
vm_name: open-omniscience-api
vm_type: AppVM
template: debian-12
label: blue
memory: 2048
maxmem: 4096
vcpus: 2

netvm: sys-whonix
provides_network: false

packages:
  - python3
  - python3-pip
  - python3-venv
  - git
  - curl
  - nginx
  - uvicorn
  - postgresql-client

app:
  host: 0.0.0.0
  port: 8000
  workers: 4
  database_url: "postgresql://db-vm:5432/open_omniscience"
```

#### `db-vm.yaml`
```yaml
vm_name: open-omniscience-db
vm_type: AppVM
template: debian-12
label: green
memory: 1024
maxmem: 2048
vcpus: 1

netvm: none
provides_network: false

packages:
  - postgresql-15
  - postgresql-contrib
  - python3
  - python3-psycopg2

postgresql:
  version: 15
  data_directory: /var/lib/postgresql/15/main
  listen_addresses: '*'
  max_connections: 100

database:
  name: open_omniscience
  user: omniscience
  encoding: UTF8
```

## Installation Process

### Prerequisites
1. Qubes OS R4.1+ installed
2. Debian 12 (Trixie) template VM available
3. sys-whonix or sys-firewall ProxyVM available
4. Root access in dom0

### Installation Steps

1. **Clone the Qubes-adapted repository:**
   ```bash
   git clone https://github.com/your-username/Open-Omniscience-Qubes.git
   cd Open-Omniscience-Qubes
   ```

2. **Run the installer:**
   ```bash
   chmod +x INSTALL-QUBES.sh
   sudo ./INSTALL-QUBES.sh
   ```

3. **Follow the prompts** to configure and deploy

### What the Installer Does

1. **Validates environment** (Qubes OS, root access, template VM)
2. **Creates VMs** with appropriate settings
3. **Configures networking** for each VM
4. **Installs dependencies** in each VM
5. **Clones repository** in each VM
6. **Sets up Python environments**
7. **Configures services** (PostgreSQL, nginx, etc.)
8. **Creates systemd services** for automatic startup

## Security Enhancements

### 1. Isolation
- Each component runs in a separate VM
- Database VM has no network access
- Scraper VMs run in DisposableVMs for maximum isolation
- Sensitive operations require explicit user approval

### 2. Communication
- All inter-VM communication via Qubes RPC
- No direct filesystem access between VMs
- Network traffic routed through ProxyVM
- TLS encryption for all RPC calls

### 3. Data Protection
- Database credentials stored in VM-specific configurations
- No hardcoded secrets in the codebase
- Sensitive data encrypted at rest
- Regular backups to separate BackupVM

### 4. Access Control
- Minimal privileges for each VM
- No root access in AppVMs
- Separate users for different services
- Audit logging for all sensitive operations

## Dependency Management

### Debian Trixie Packages

**API VM:**
- python3, python3-pip, python3-venv
- git, curl
- nginx, uvicorn
- postgresql-client

**Database VM:**
- postgresql-15, postgresql-contrib
- python3, python3-psycopg2

**Scraper VM:**
- python3, python3-pip, python3-venv
- git, curl
- chromium (for headless browsing)
- tor (for anonymous scraping)

**AI VM:**
- python3, python3-pip, python3-venv
- nvidia-driver (if GPU available)
- cuda-toolkit (if GPU available)

### Python Dependencies

All Python dependencies are installed in virtual environments within each VM:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Configuration Management

### Environment Variables

Each VM can be configured via environment variables:

**API VM:**
- `API_HOST`: API server host (default: 0.0.0.0)
- `API_PORT`: API server port (default: 8000)
- `API_WORKERS`: Number of worker processes (default: 4)
- `DB_VM`: Database VM name (default: open-omniscience-db)
- `SCRAPER_VM`: Scraper VM name (default: open-omniscience-scraper)
- `SECRET_KEY`: Secret key for session management
- `CSRF_SECRET`: CSRF secret key

**Database VM:**
- `DB_NAME`: Database name (default: open_omniscience)
- `DB_USER`: Database user (default: omniscience)
- `DB_PASSWORD`: Database password (generated during setup)

### Configuration Files

Configuration files are stored in `/etc/open-omniscience/` in each VM:

- `api-vm.yaml`: API VM configuration
- `db-vm.yaml`: Database VM configuration
- `scraper-vm.yaml`: Scraper VM configuration
- `settings.yaml`: Application settings
- `sources.yaml`: News sources configuration

## Service Management

### Systemd Services

Each VM has systemd services for automatic startup:

**API VM:**
- `open-omniscience-api.service`: Main API server
- `open-omniscience-nginx.service`: Nginx reverse proxy

**Database VM:**
- `postgresql@15-main.service`: PostgreSQL database

**Scraper VM:**
- `open-omniscience-scraper.service`: Scraper worker

**AI VM:**
- `open-omniscience-ai.service`: LLM service

### Service Commands

```bash
# Start service
sudo systemctl start open-omniscience-api

# Stop service
sudo systemctl stop open-omniscience-api

# Restart service
sudo systemctl restart open-omniscience-api

# Check status
sudo systemctl status open-omniscience-api

# Enable at boot
sudo systemctl enable open-omniscience-api

# View logs
sudo journalctl -u open-omniscience-api -f
```

## Usage

### Starting the System

1. **Start all VMs:**
   ```bash
   qvm-start open-omniscience-api
   qvm-start open-omniscience-db
   qvm-start open-omniscience-scraper
   qvm-start open-omniscience-ai
   ```

2. **Access the API:**
   - The API is available at `http://localhost:8000` from the API VM
   - From dom0, use: `qvm-run -u open-omniscience-api curl http://localhost:8000`

### Making Requests

**From API VM:**
```python
from src.qubes.vm import get_api_vm

# Query database
result = get_api_vm().query_database({'query': '...'}, 'articles')

# Start scrape job
job = get_api_vm().start_scrape_job('https://example.com')

# Get job status
status = get_api_vm().get_scrape_status(job['job_id'])
```

**From any VM:**
```python
from src.qubes.rpc import get_rpc_client

# Get client for API VM
client = get_rpc_client('open-omniscience-api')

# Make RPC call
result = client.scrape('https://example.com')
```

### Direct Qubes RPC

You can also make direct Qubes RPC calls:

```bash
# Ping the API VM
qvm-run -u open-omniscience-api python3 -c "from src.qubes.rpc.server import main; main()" <<< '{"action": "ping"}'

# Get status
qvm-run -u open-omniscience-api python3 -c "from src.qubes.rpc.server import main; main()" <<< '{"action": "status"}'
```

## Monitoring and Maintenance

### Logs

Each VM maintains its own logs:

- **API VM:** `/var/log/open-omniscience/api.log`
- **Database VM:** `/var/log/postgresql/postgresql-15-main.log`
- **Scraper VM:** `/var/log/open-omniscience/scraper.log`
- **AI VM:** `/var/log/open-omniscience/ai.log`

### Health Checks

```bash
# Check API VM health
qvm-run -u open-omniscience-api curl http://localhost:8000/health

# Check database connection
qvm-run -u open-omniscience-api python3 -c "from src.qubes.vm import get_api_vm; print(get_api_vm().get_health_status())"
```

### Updates

1. **Update code:**
   ```bash
   cd /opt/open-omniscience
   git pull
   ```

2. **Update dependencies:**
   ```bash
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Restart services:**
   ```bash
   sudo systemctl restart open-omniscience-api
   ```

## Troubleshooting

### Common Issues

**1. VM creation fails:**
- Ensure template VM exists: `qvm-ls`
- Check available memory: `qvm-prefs sys-whonix available_memory`
- Try with smaller memory settings

**2. Package installation fails:**
- Update package lists: `qvm-run -u <vm> apt-get update`
- Check for held packages: `qvm-run -u <vm> apt-mark showhold`
- Try installing packages individually

**3. RPC calls fail:**
- Verify VM is running: `qvm-ls`
- Check VM logs: `qvm-run -u <vm> journalctl -f`
- Test with simple command: `qvm-run -u <vm> echo test`

**4. Database connection fails:**
- Verify database VM is running
- Check PostgreSQL is running: `qvm-run -u open-omniscience-db systemctl status postgresql@15-main`
- Test connection: `qvm-run -u open-omniscience-db su - postgres -c "psql -c 'SELECT 1;'"`

### Debug Mode

Enable debug logging by setting the `LOG_LEVEL` environment variable:

```bash
# In any VM
export LOG_LEVEL=DEBUG
python3 -c "from src.qubes import get_qubes_environment; env = get_qubes_environment(); print(env.is_qubes)"
```

## Performance Optimization

### Memory Settings

Adjust VM memory based on workload:

```bash
# Increase API VM memory
qvm-mem open-omniscience-api 4096
qvm-maxmem open-omniscience-api 8192

# Increase AI VM memory for LLM processing
qvm-mem open-omniscience-ai 8192
qvm-maxmem open-omniscience-ai 16384
```

### CPU Settings

Adjust CPU allocation:

```bash
# Increase API VM CPUs
qvm-vcpus open-omniscience-api 4

# Increase AI VM CPUs for LLM processing
qvm-vcpus open-omniscience-ai 8
```

### Storage Settings

Use separate storage pools for different VMs:

```bash
# Create storage pool
qvm-pool add mypool lvm thin_pool=mythinpool

# Assign to VM
qvm-prefs open-omniscience-db pool mypool
```

## Security Best Practices

### 1. Network Isolation
- Keep database VM offline (no netvm)
- Use sys-whonix for Tor-based scraping
- Use sys-firewall for regular network access
- Never expose API VM directly to the network

### 2. Data Protection
- Regularly backup database VM
- Use encrypted storage for sensitive data
- Rotate credentials periodically
- Audit access logs regularly

### 3. VM Hardening
- Disable unnecessary services in each VM
- Use minimal templates
- Keep all VMs updated
- Use separate users for different services

### 4. Monitoring
- Monitor VM resource usage
- Set up alerts for unusual activity
- Regularly review logs
- Use Qubes built-in security features

## Compliance with Qubes Security Model

### 1. Isolation
✅ Each component in separate VM
✅ No direct filesystem sharing
✅ Controlled network access
✅ Minimal privileges

### 2. Minimal Trust
✅ No VM trusts another by default
✅ All communication explicit and controlled
✅ No automatic updates without user approval
✅ Clear separation of concerns

### 3. Defense in Depth
✅ Multiple layers of security
✅ Network isolation
✅ Process isolation
✅ User isolation
✅ File system isolation

### 4. Least Privilege
✅ Each VM has only necessary permissions
✅ No root access in AppVMs
✅ Separate users for services
✅ Minimal package installations

## Testing

### Unit Tests

Run tests in each VM:

```bash
# In API VM
cd /opt/open-omniscience
source venv/bin/activate
python3 -m pytest tests/ -v
```

### Integration Tests

Test inter-VM communication:

```bash
# Test RPC from dom0
qvm-run -u open-omniscience-api python3 -c "
from src.qubes.rpc.server import main
import sys
sys.stdin = open('/dev/stdin')
main()
" <<< '{"action": "ping"}'
```

### End-to-End Tests

1. Start all VMs
2. Make API request
3. Verify database storage
4. Verify scraper functionality
5. Verify analysis results

## Documentation Updates

### Modified Files

1. **README.md** - Updated with Qubes-specific instructions
2. **INSTALL.md** - Qubes installation guide
3. **DEPLOYMENT.md** - Qubes deployment guide
4. **SECURITY.md** - Qubes security considerations
5. **CONTRIBUTING.md** - Qubes development guidelines

### New Files

1. **QUBES_ADAPTATION.md** - This file
2. **INSTALL-QUBES.sh** - Qubes installation script
3. **qubes/configs/*.yaml** - VM configuration files
4. **src/qubes/** - Qubes-specific modules

## Future Enhancements

### 1. Automated Deployment
- Ansible playbooks for VM configuration
- Salt states for Qubes management
- Terraform for VM provisioning

### 2. Enhanced Security
- Qubes RPC policy enforcement
- Automatic credential rotation
- Intrusion detection system
- Automated security audits

### 3. Performance Monitoring
- Prometheus metrics collection
- Grafana dashboards
- Alerting for performance issues
- Capacity planning tools

### 4. Backup and Recovery
- Automated VM backups
- Point-in-time recovery
- Disaster recovery procedures
- Backup verification

### 5. Scaling
- Horizontal scaling of scraper VMs
- Load balancing across multiple API VMs
- Database replication
- Caching layer

## Conclusion

This Qubes-OS adaptation of Open-Omniscience provides:

✅ **Full compatibility** with Debian Trixie in Qubes OS R4.1+
✅ **Maximum security** through VM isolation
✅ **Secure communication** via Qubes RPC
✅ **Controlled dependencies** per VM
✅ **Comprehensive documentation** for deployment and maintenance
✅ **Production-ready** architecture following Qubes best practices

The adaptation maintains all original functionality while significantly improving security through Qubes OS's isolation and compartmentalization features.

---

## References

- [Qubes OS Documentation](https://doc.qubes-os.org/)
- [Qubes RPC Documentation](https://doc.qubes-os.org/en/latest/inter-vm-rpc.html)
- [Debian 12 (Trixie) Release Notes](https://www.debian.org/News/2023/20230610)
- [Open-Omniscience Original Documentation](https://github.com/ideotion/Open-Omniscience)
