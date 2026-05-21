# Open-Omniscience Deployment Guide

**Version:** 2.0  
**Last Updated:** 2025-05-21  
**Author:** Open-Omniscience Team  
**License:** GNU GPLv3

---

## 📖 Table of Contents

1. [Introduction](#1-introduction)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start](#3-quick-start)
4. [Production Deployment](#4-production-deployment)
5. [Configuration](#5-configuration)
   - [Environment Variables](#environment-variables)
   - [Database Configuration](#database-configuration)
   - [Security Configuration](#security-configuration)
6. [Authentication Setup](#6-authentication-setup)
7. [Monitoring and Logging](#7-monitoring-and-logging)
8. [Backup and Recovery](#8-backup-and-recovery)
9. [Scaling](#9-scaling)
10. [Troubleshooting](#10-troubleshooting)
11. [Maintenance](#11-maintenance)

---

## 1. Introduction

This comprehensive deployment guide will walk you through deploying Open-Omniscience in production using direct Python installation. The application is designed to be portable and can run on any system with Python 3.8+.

### 🎯 Deployment Options

| Option | Complexity | Recommended For | Portability |
|--------|------------|-----------------|-------------|
| Direct Python Installation | ⭐ | Production | ✅ High |
| Manual Deployment | ⭐⭐ | Custom Environments | ✅ High |

### 📋 What You'll Need

- Domain name (for production)
- SSL certificates (Let's Encrypt recommended)
- Python 3.8+ and pip
- Basic Linux server knowledge
- PostgreSQL (recommended for production)

---

## 2. Prerequisites

### 2.1 System Requirements

#### Minimum Requirements (Development)
- **CPU:** 2 cores
- **RAM:** 4 GB
- **Storage:** 20 GB SSD
- **OS:** Linux (Debian/Ubuntu recommended), macOS, or Windows (WSL2)

#### Recommended Requirements (Production)
- **CPU:** 4+ cores
- **RAM:** 8+ GB
- **Storage:** 100+ GB SSD (depends on data volume)
- **OS:** Linux (Debian 12+ or Ubuntu 22.04+ recommended)

### 2.2 Software Dependencies

#### Required
- Python 3.8+
- pip (Python package manager)
- Git

#### Optional (for full functionality)
- [Ollama](https://ollama.ai/) (for LLM features)
- PostgreSQL (recommended for production)
- PostgreSQL client tools

### 2.3 Installation

#### Ubuntu/Debian
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and Git
sudo apt install -y python3 python3-pip python3-venv git

# Verify installation
python3 --version
pip3 --version
```

#### CentOS/RHEL
```bash
# Update system
sudo yum update -y

# Install Python and Git
sudo yum install -y python3 python3-pip git

# Verify installation
python3 --version
pip3 --version
```

#### macOS
```bash
# Install Python using Homebrew
brew install python git

# Verify installation
python3 --version
pip3 --version
```

---

## 3. Quick Start

The fastest way to get Open-Omniscience running:

### Using Direct Python Installation
```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the application
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Access the application
# Open http://localhost:8000 in your browser
```

---

## 4. Production Deployment

### Option A: Direct Python Installation (Recommended)

For most users, direct Python installation provides the simplest deployment method.

#### Step 1: Clone Repository
```bash
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
```

#### Step 2: Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

#### Step 3: Install Dependencies
```bash
# Install core dependencies
pip install -r requirements.txt

# For LLM features (optional)
pip install -r requirements.txt
```

#### Step 4: Configure Environment
Edit the `.env` file to configure your database and other settings:
```bash
cp .env.example .env
nano .env  # or use your preferred editor
```

#### Step 5: Set Up Database

##### SQLite (Default - for development)
No setup required. The application will create a SQLite database automatically.

##### PostgreSQL (Recommended for production)
```bash
# Install PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Create database and user
sudo -u postgres psql -c "CREATE DATABASE open_omniscience;"
sudo -u postgres psql -c "CREATE USER omniscience WITH PASSWORD 'your_secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO omniscience;"

# Update .env file
DATABASE_URL=postgresql+psycopg2://omniscience:your_secure_password@localhost/open_omniscience
```

#### Step 6: Start the Application

For development:
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

For production (using Gunicorn):
```bash
# Install Gunicorn
pip install gunicorn

# Start with Gunicorn
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
```

#### Step 7: Verify Application
Access the application at `http://localhost:8000`

---

## 5. Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# Database configuration
DATABASE_URL=sqlite:///./data/open_omniscience.db  # or postgresql://...

# Server configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000
SERVER_DEBUG=false

# LLM configuration (if using Ollama)
LLM_ENABLED=true
OLLAMA_HOST=http://localhost:11434
DEFAULT_MODEL=gemma4:e2b

# Scraping configuration
SCRAPING_RATE_LIMIT_MS=1000
SCRAPING_USER_AGENT="OpenOmniscience/1.0"
SCRAPING_RESPECT_ROBOTS_TXT=true
```

### Database Configuration

#### SQLite
- Default configuration
- No additional setup required
- File stored in `data/open_omniscience.db`

#### PostgreSQL
- Recommended for production
- Better performance for large datasets
- Supports concurrent access

### Security Configuration

#### SSL/TLS (Recommended for Production)
Use a reverse proxy like Nginx or Caddy to handle HTTPS:

**Nginx Example:**
```nginx
server {
    listen 443 ssl;
    server_name yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 6. Authentication Setup

Open-Omniscience uses API key authentication. Generate a secure API key:

```bash
# Generate a random API key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Add to your .env file
API_KEY=your_generated_key_here
```

---

## 7. Monitoring and Logging

### Application Logs
Logs are written to the `logs/` directory by default.

### System Monitoring

#### Using systemd (Recommended for Production)

Create a systemd service file at `/etc/systemd/system/open-omniscience.service`:

```ini
[Unit]
Description=Open-Omniscience
After=network.target

[Service]
User=your_user
WorkingDirectory=/path/to/open-omniscience
Environment="PATH=/path/to/open-omniscience/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStart=/path/to/open-omniscience/venv/bin/gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable open-omniscience
sudo systemctl start open-omniscience
sudo systemctl status open-omniscience
```

View logs:
```bash
journalctl -u open-omniscience -f
```

---

## 8. Backup and Recovery

### Database Backup

#### SQLite
```bash
# Create backup
sqlite3 data/open_omniscience.db ".backup /path/to/backup/open_omniscience_$(date +%Y%m%d_%H%M%S).sql"

# Restore backup
sqlite3 data/open_omniscience.db ".restore /path/to/backup/open_omniscience.sql"
```

#### PostgreSQL
```bash
# Create backup
pg_dump -U omniscience -d open_omniscience -F c -f /backups/open_omniscience_$(date +%Y%m%d_%H%M%S).dump

# Restore backup
pg_restore -U omniscience -d open_omniscience -c /backups/open_omniscience.dump
```

### Full Application Backup
```bash
# Backup entire application directory
tar -czvf open_omniscience_backup_$(date +%Y%m%d_%H%M%S).tar.gz /path/to/open-omniscience

# Restore
# Extract to desired location
tar -xzvf open_omniscience_backup.tar.gz -C /path/to/restore
```

---

## 9. Scaling

### Vertical Scaling
- Increase server resources (CPU, RAM)
- Use Gunicorn with more workers:
  ```bash
  gunicorn -k uvicorn.workers.UvicornWorker -w 8 -b 0.0.0.0:8000 api.main:app
  ```

### Horizontal Scaling
For horizontal scaling, use a load balancer (Nginx, HAProxy) in front of multiple instances:

```bash
# Instance 1
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8001 api.main:app

# Instance 2
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8002 api.main:app

# Nginx load balancer configuration
upstream open_omniscience {
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    listen 80;
    server_name yourdomain.com;
    
    location / {
        proxy_pass http://open_omniscience;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 10. Troubleshooting

### Common Issues

#### Application won't start
- Check that Python 3.8+ is installed
- Verify all dependencies are installed: `pip list`
- Check for syntax errors in configuration files

#### Database connection errors
- Verify database credentials in `.env` file
- Ensure database server is running
- Check firewall settings

#### Port already in use
- Check what's using port 8000: `ss -tulnp | grep 8000`
- Either stop the conflicting service or change the port in `.env`

#### Module not found errors
- Activate virtual environment: `source venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`

### Debug Mode
Run with debug mode for detailed error messages:
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --debug
```

---

## 11. Maintenance

### Updating the Application
```bash
# Pull latest changes
cd /path/to/open-omniscience
git pull origin main

# Update dependencies
source venv/bin/activate
pip install -r requirements.txt

# Restart the application
# If using systemd:
sudo systemctl restart open-omniscience
```

### Checking Application Health
```bash
# Check if application is running
curl -I http://localhost:8000

# Check API health endpoint
curl http://localhost:8000/api/health
```

### Cleaning Up
```bash
# Remove old logs (keep last 30 days)
find logs/ -name "*.log" -mtime +30 -delete

# Remove old backups (keep last 7)
ls -t /backups/*.dump | tail -n +8 | xargs rm -f
```

---

## Additional Resources

- [Official Documentation](https://github.com/ideotion/Open-Omniscience)
- [LLM Setup Guide](LLM_SETUP_GUIDE.md)
- [Developer Guide](DEVELOPER_GUIDE.md)
- [API Documentation](API_DOCUMENTATION.md)

---

*Last updated: 2025-05-21*
