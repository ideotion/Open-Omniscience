# Open-Omniscience Deployment Guide

**Version:** 2.0  
**Last Updated:** 2025-05-12  
**Author:** Open-Omniscience Team  
**License:** Open Source (MIT)

---

## 📖 Table of Contents

1. [Introduction](#1-introduction)
2. [Prerequisites](#2-prerequisites)
3. [Quick Start](#3-quick-start)
4. [Production Deployment](#4-production-deployment)
   - [Option A: Docker Compose (Recommended)](#option-a-docker-compose-recommended)
   - [Option B: Manual Deployment](#option-b-manual-deployment)
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
12. [Visual Guides](#12-visual-guides)

---

## 1. Introduction

This comprehensive deployment guide will walk you through deploying Open-Omniscience in production while maintaining the project's open-source and portable nature. The guide covers all aspects of deployment, from basic setup to advanced production configurations.

### 🎯 Deployment Options

| Option | Complexity | Recommended For | Portability |
|--------|------------|-----------------|-------------|
| Docker Compose | ⭐⭐ | Production | ✅ High |
| Manual Deployment | ⭐⭐⭐ | Custom Environments | ✅ High |
| Development Mode | ⭐ | Development | ✅ High |

### 📋 What You'll Need

- Domain name (for production)
- SSL certificates (Let's Encrypt recommended)
- Docker and Docker Compose
- Basic Linux server knowledge
- PostgreSQL (recommended for production)

---

## 2. Prerequisites

### 2.1 System Requirements

#### Minimum Requirements (Development)
- **CPU:** 2 cores
- **RAM:** 4 GB
- **Storage:** 20 GB SSD
- **OS:** Linux (Ubuntu 22.04 LTS recommended)

#### Recommended Requirements (Production)
- **CPU:** 4+ cores
- **RAM:** 8+ GB
- **Storage:** 100+ GB SSD (depends on data volume)
- **OS:** Linux (Ubuntu 22.04 LTS or CentOS 8)

### 2.2 Software Dependencies

#### Required
- [Docker](https://docs.docker.com/engine/install/) (20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (2.20+)
- Git

#### Optional (for full functionality)
- [Ollama](https://ollama.ai/) (for LLM features)
- PostgreSQL client tools
- Node.js (for frontend development)
- Python 3.12+

### 2.3 Installation

#### Ubuntu/Debian
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
sudo apt install -y docker.io docker-compose git

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify installation
docker --version
docker-compose --version
```

#### CentOS/RHEL
```bash
# Update system
sudo yum update -y

# Install Docker
sudo yum install -y docker git
sudo systemctl enable docker --now

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version
```

---

## 3. Quick Start

### 3.1 Clone the Repository

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Check out the latest stable branch
git checkout 0.01
```

### 3.2 Development Mode (Fastest Start)

```bash
# Copy example environment file
cp .env.example .env

# Start the development stack
docker-compose up -d

# Check running services
docker-compose ps

# Access the application
# - API: http://localhost:8000
# - Docs: http://localhost:8000/docs
# - Static files: http://localhost:8000/static/showcase.html
```

### 3.3 Verify Installation

```bash
# Check API health
curl http://localhost:8000/api/llm/health

# List sources
curl http://localhost:8000/api/sources

# Search articles
curl "http://localhost:8000/api/articles?query=test"
```

---

## 4. Production Deployment

### Option A: Docker Compose (Recommended)

This is the recommended approach for production deployment as it ensures portability and maintains the open-source nature of the project.

#### Step 1: Prepare Environment

```bash
# Create production environment file
cp .env.production.example .env.production

# Edit the file with your settings
nano .env.production

# Generate strong secrets
openssl rand -hex 32  # For SECRET_KEY
openssl rand -hex 32  # For JWT_SECRET_KEY
openssl rand -hex 32  # For SESSION_SECRET
```

#### Step 2: Prepare SSL Certificates

##### Option A1: Let's Encrypt (Recommended)

```bash
# Install Certbot
sudo apt install -y certbot

# Obtain certificates (replace with your domain)
sudo certbot certonly --standalone -d yourdomain.com -d www.yourdomain.com

# Copy certificates to project
sudo mkdir -p ssl
sudo cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/privkey.pem ssl/
sudo cp /etc/letsencrypt/live/yourdomain.com/chain.pem ssl/

# Set proper permissions
sudo chown -R $USER:$USER ssl/
sudo chmod -R 755 ssl/
```

##### Option A2: Self-Signed Certificates (Testing Only)

```bash
# Create SSL directory
mkdir -p ssl

# Generate self-signed certificates
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/privkey.pem -out ssl/fullchain.pem \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=yourdomain.com"

# Create chain file (same as fullchain for self-signed)
cp ssl/fullchain.pem ssl/chain.pem
```

#### Step 3: Configure Production Stack

```bash
# Create production network (optional, but recommended)
docker network create open-omniscience-network

# Start production stack
docker-compose -f docker-compose.production.yml --env-file .env.production up -d

# Check running services
docker-compose -f docker-compose.production.yml ps
```

#### Step 4: Verify Production Deployment

```bash
# Check API health through Nginx
curl https://yourdomain.com/health -k

# Check all services
docker-compose -f docker-compose.production.yml ps

# View logs
docker-compose -f docker-compose.production.yml logs -f
```

#### Step 5: Set Up Monitoring (Optional)

```bash
# Access Grafana (default credentials: admin/admin)
# http://yourdomain.com:3000

# Access Prometheus
# http://yourdomain.com:9090
```

### Option B: Manual Deployment

For environments where Docker cannot be used, or for custom setups.

#### Step 1: Install Dependencies

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Create database
sudo -u postgres psql -c "CREATE DATABASE open_omniscience;"
sudo -u postgres psql -c "CREATE USER omniscience WITH PASSWORD 'your_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO omniscience;"
```

#### Step 2: Configure Application

```bash
# Copy and edit configuration
cp .env.example .env
nano .env

# Set DATABASE_URL
DATABASE_URL=postgresql+psycopg2://omniscience:your_password@localhost/open_omniscience
```

#### Step 3: Run Application

```bash
# Start the API
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Or use Gunicorn for production
pip install gunicorn
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
```

#### Step 4: Set Up Nginx

```bash
# Install Nginx
sudo apt install -y nginx

# Copy configuration
sudo cp nginx.production.conf /etc/nginx/nginx.conf

# Test configuration
sudo nginx -t

# Start Nginx
sudo systemctl start nginx
sudo systemctl enable nginx
```

---

## 5. Configuration

### Environment Variables

The application uses environment variables for configuration. See `.env.production.example` for all available options.

#### Required Variables

```bash
# Database
POSTGRES_DB=open_omniscience
POSTGRES_USER=omniscience
POSTGRES_PASSWORD=your_strong_password

# Security
SECRET_KEY=your_strong_secret_key

# Domain
ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

#### Optional Variables

```bash
# LLM Configuration
OLLAMA_BASE_URL=http://localhost:11434
AUTO_DOWNLOAD_MODELS=false

# Rate Limiting
RATE_LIMIT=100/minute

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Monitoring
ENABLE_MONITORING=true
```

### Database Configuration

#### PostgreSQL (Recommended for Production)

```yaml
# In docker-compose.production.yml
postgres:
  image: postgres:15-alpine
  environment:
    POSTGRES_DB: open_omniscience
    POSTGRES_USER: omniscience
    POSTGRES_PASSWORD: your_password
  volumes:
    - postgres_data:/var/lib/postgresql/data
```

#### SQLite (Development Only)

```bash
# In .env file
DATABASE_URL=sqlite:///./data/open_omniscience.db
```

### Security Configuration

#### CORS Settings

```python
# In src/api/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### Rate Limiting

```python
# In src/api/main.py
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
```

---

## 6. Authentication Setup

**⚠️ IMPORTANT:** The API currently does not have authentication implemented. For production use, you MUST implement authentication.

### Option A: JWT Authentication (Recommended)

#### Step 1: Install Dependencies

```bash
pip install python-jose[cryptography] passlib bcrypt
```

#### Step 2: Create Authentication Module

Create `src/api/auth.py`:

```python
"""
JWT Authentication for Open-Omniscience API

This module provides JWT-based authentication for the API.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Annotated
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import os

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default-secret-key-change-in-production")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", 7))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# User model
class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None

class UserInDB(User):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

# Mock user database (replace with real database)
fake_users_db = {
    "admin": {
        "username": "admin",
        "full_name": "Administrator",
        "email": "admin@example.com",
        "disabled": False,
        "hashed_password": pwd_context.hash("admin"),
    }
}

def verify_password(plain_password: str, hashed_password: str):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str):
    return pwd_context.hash(password)

def get_user(db, username: str):
    if username in db:
        user_dict = db[username]
        return UserInDB(**user_dict)

def authenticate_user(fake_db, username: str, password: str):
    user = get_user(fake_db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(token: Annotated[str, Depends(oauth2_scheme)]):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = get_user(fake_users_db, username=token_data.username)
    if user is None:
        raise credentials_exception
    return user

async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
):
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
```

#### Step 3: Update API to Use Authentication

Update `src/api/main.py` to include authentication:

```python
# Add to imports
from api.auth import get_current_active_user, Token

# Add token endpoint
@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()]
):
    user = authenticate_user(fake_users_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

# Protect endpoints
@app.get("/api/articles")
async def get_articles(
    current_user: Annotated[User, Depends(get_current_active_user)]
):
    # Existing implementation
    pass
```

### Option B: API Key Authentication

For simpler authentication needs:

```python
# In src/api/main.py
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def get_api_key(api_key: str = Depends(api_key_header)):
    valid_keys = os.getenv("API_KEYS", "").split(",")
    if api_key not in valid_keys:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key

@app.get("/api/articles")
async def get_articles(api_key: str = Depends(get_api_key)):
    # Existing implementation
    pass
```

---

## 7. Monitoring and Logging

### 7.1 Prometheus Metrics

The application includes built-in Prometheus metrics:

```python
# In src/api/main.py
from prometheus_client import make_asgi_app, Counter, Gauge, Histogram

# Metrics
REQUEST_COUNT = Counter(
    'open_omniscience_requests_total',
    'Total HTTP Requests',
    ['method', 'endpoint', 'http_status']
)
REQUEST_LATENCY = Histogram(
    'open_omniscience_request_latency_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint']
)
ACTIVE_REQUESTS = Gauge(
    'open_omniscience_active_requests',
    'Number of active HTTP requests'
)
ARTICLES_COUNT = Gauge(
    'open_omniscience_articles_count',
    'Total number of articles in database'
)
SOURCES_COUNT = Gauge(
    'open_omniscience_sources_count',
    'Total number of sources configured'
)

# Add to app
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)
```

### 7.2 Access Metrics Endpoint

```bash
# Access metrics (if authentication is disabled)
curl http://localhost:8000/metrics

# Or through Nginx (with basic auth)
curl -u username:password http://yourdomain.com/metrics
```

### 7.3 Grafana Dashboards

#### Import Pre-configured Dashboard

1. Access Grafana at `http://yourdomain.com:3000`
2. Login with default credentials (admin/admin)
3. Go to Dashboards → Import
4. Use dashboard ID `1860` (Node Exporter Full) or create custom

#### Create Custom Dashboard

Create a dashboard with the following panels:

1. **API Request Rate**
   - Query: `rate(open_omniscience_requests_total[1m])`
   - Type: Graph

2. **Request Latency**
   - Query: `histogram_quantile(0.95, sum(rate(open_omniscience_request_latency_seconds_bucket[5m])) by (le))`
   - Type: Graph

3. **Active Requests**
   - Query: `open_omniscience_active_requests`
   - Type: Gauge

4. **Articles Count**
   - Query: `open_omniscience_articles_count`
   - Type: Stat

5. **Sources Count**
   - Query: `open_omniscience_sources_count`
   - Type: Stat

### 7.4 Logging Configuration

The application uses structured JSON logging:

```python
# In src/utils/logging_config.py
import logging
import json
from pythonjsonlogger import jsonlogger

def setup_logging(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    
    # Create JSON formatter
    formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)d'
    )
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    if os.getenv("LOG_FILE"):
        file_handler = logging.FileHandler(os.getenv("LOG_FILE"))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
```

---

## 8. Backup and Recovery

### 8.1 Database Backup

#### PostgreSQL Backup

```bash
# Manual backup
docker exec open-omniscience-postgres pg_dump -U omniscience -d open_omniscience -F c -f /backups/backup_$(date +%Y%m%d_%H%M%S).dump

# Automated backup script
cat > /opt/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=/backups
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
docker exec open-omniscience-postgres pg_dump -U omniscience -d open_omniscience -F c -f ${BACKUP_DIR}/backup_${DATE}.dump

# Clean up old backups (keep last 30 days)
find ${BACKUP_DIR} -name "backup_*.dump" -mtime +30 -delete
EOF

chmod +x /opt/backup.sh

# Add to cron (daily at 2 AM)
0 2 * * * /opt/backup.sh
```

#### SQLite Backup

```bash
# Manual backup
cp data/open_omniscience.db data/open_omniscience.db.backup

# Automated backup
cat > /opt/backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR=/backups
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup
cp data/open_omniscience.db ${BACKUP_DIR}/backup_${DATE}.db

# Clean up old backups
find ${BACKUP_DIR} -name "backup_*.db" -mtime +30 -delete
EOF
```

### 8.2 Database Recovery

#### PostgreSQL Recovery

```bash
# Stop the API service
docker-compose -f docker-compose.production.yml stop api

# Restore from backup
docker exec -i open-omniscience-postgres pg_restore -U omniscience -d open_omniscience -c < /backups/backup_20250512_120000.dump

# Start the API service
docker-compose -f docker-compose.production.yml start api
```

#### SQLite Recovery

```bash
# Stop the API service
docker-compose stop api

# Restore from backup
cp /backups/backup_20250512_120000.db data/open_omniscience.db

# Start the API service
docker-compose start api
```

### 8.3 Volume Backup

```bash
# Backup all Docker volumes
docker run --rm \
  -v open-omniscience-postgres_data:/volume \
  -v $(pwd)/backups:/backup \
  alpine tar cvf /backup/postgres_data_$(date +%Y%m%d_%H%M%S).tar /volume

# Restore Docker volumes
docker run --rm \
  -v open-omniscience-postgres_data:/volume \
  -v $(pwd)/backups:/backup \
  alpine tar xvf /backup/postgres_data_20250512_120000.tar -C /
```

---

## 9. Scaling

### 9.1 Horizontal Scaling

#### Scale API Service

```bash
# Scale to 4 instances
docker-compose -f docker-compose.production.yml up -d --scale api=4

# Check running instances
docker-compose -f docker-compose.production.yml ps
```

#### Load Balancing

The Nginx configuration already includes load balancing. For multiple API instances:

```nginx
# In nginx.production.conf
upstream api_backend {
    server api1:8000;
    server api2:8000;
    server api3:8000;
    server api4:8000;
    
    # Load balancing method
    least_conn;
    
    # Keepalive connections
    keepalive 32;
}

location /api/ {
    proxy_pass http://api_backend;
    # ... rest of configuration
}
```

### 9.2 Database Scaling

#### PostgreSQL Read Replicas

```yaml
# In docker-compose.production.yml
services:
  postgres-primary:
    image: postgres:15-alpine
    # ... primary configuration
    
  postgres-replica:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: open_omniscience
      POSTGRES_USER: omniscience
      POSTGRES_PASSWORD: your_password
    command: >
      bash -c "
        echo 'host replication all 0.0.0.0/0 md5' >> /var/lib/postgresql/data/pg_hba.conf &&
        echo 'primary_conninfo = host=postgres-primary port=5432 user=omniscience password=your_password' >> /var/lib/postgresql/data/postgresql.auto.conf &&
        echo 'hot_standby = on' >> /var/lib/postgresql/data/postgresql.auto.conf &&
        exec docker-entrypoint.sh postgres
      "
    depends_on:
      - postgres-primary
```

### 9.3 Caching Layer

#### Redis Cluster

```yaml
# In docker-compose.production.yml
services:
  redis-master:
    image: redis:7-alpine
    # ... master configuration
    
  redis-replica:
    image: redis:7-alpine
    command: redis-server --replicaof redis-master 6379
    depends_on:
      - redis-master
```

---

## 10. Troubleshooting

### 10.1 Common Issues

#### Issue: Database connection failed

**Symptoms:**
- API returns 500 errors
- Logs show database connection errors

**Solution:**
```bash
# Check database container
docker-compose -f docker-compose.production.yml ps

# Check database logs
docker-compose -f docker-compose.production.yml logs postgres

# Test database connection
docker exec -it open-omniscience-postgres psql -U omniscience -d open_omniscience -c "SELECT 1;"

# Verify environment variables
cat .env.production | grep DATABASE
```

#### Issue: API not responding

**Symptoms:**
- 502 Bad Gateway errors
- Connection refused

**Solution:**
```bash
# Check API container
docker-compose -f docker-compose.production.yml ps

# Check API logs
docker-compose -f docker-compose.production.yml logs api

# Test API directly (bypass Nginx)
curl http://localhost:8000/api/llm/health

# Restart API
docker-compose -f docker-compose.production.yml restart api
```

#### Issue: SSL certificate errors

**Symptoms:**
- Browser shows SSL warnings
- HTTPS connections fail

**Solution:**
```bash
# Verify SSL certificates
openssl x509 -in ssl/fullchain.pem -text -noout
openssl rsa -in ssl/privkey.pem -check

# Check Nginx configuration
sudo nginx -t

# Restart Nginx
docker-compose -f docker-compose.production.yml restart nginx
```

#### Issue: Memory issues

**Symptoms:**
- Containers crash with OOM errors
- Slow performance

**Solution:**
```bash
# Check memory usage
docker stats

# Increase Docker memory allocation
# Edit /etc/docker/daemon.json
{
  "default-ulimits": {
    "memlock": {
      "Name": "memlock",
      "Hard": -1,
      "Soft": -1
    }
  }
}

# Restart Docker
sudo systemctl restart docker

# Limit container memory
# In docker-compose.production.yml
api:
  mem_limit: 2g
  memswap_limit: 2g
```

### 10.2 Debug Mode

Enable debug mode for troubleshooting:

```bash
# In .env.production
DEBUG=true
LOG_LEVEL=DEBUG

# Restart services
docker-compose -f docker-compose.production.yml restart api

# View debug logs
docker-compose -f docker-compose.production.yml logs -f api
```

### 10.3 Health Checks

```bash
# Check all service health
docker-compose -f docker-compose.production.yml ps

# Check API health
curl http://localhost:8000/api/llm/health

# Check database health
docker exec open-omniscience-postgres pg_isready -U omniscience -d open_omniscience

# Check Redis health
docker exec open-omniscience-redis redis-cli ping
```

---

## 11. Maintenance

### 11.1 Regular Maintenance Tasks

#### Database Maintenance

```bash
# Vacuum and analyze (PostgreSQL)
docker exec open-omniscience-postgres vacuumdb -U omniscience -d open_omniscience --analyze

# Reindex (PostgreSQL)
docker exec open-omniscience-postgres reindexdb -U omniscience -d open_omniscience
```

#### Log Rotation

```bash
# Create log rotation configuration
cat > /etc/logrotate.d/open-omniscience << 'EOF'
/var/log/open-omniscience/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 644 nginx nginx
    sharedscripts
    postrotate
        systemctl reload nginx
    endscript
}
EOF
```

#### Certificate Renewal

```bash
# Renew Let's Encrypt certificates
sudo certbot renew --dry-run

# Reload Nginx
docker-compose -f docker-compose.production.yml restart nginx
```

### 11.2 Update Procedure

```bash
# Pull latest changes
git pull origin 0.01

# Rebuild and restart
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml build --no-cache
docker-compose -f docker-compose.production.yml up -d

# Run database migrations (if any)
# docker-compose -f docker-compose.production.yml exec api alembic upgrade head
```

### 11.3 Security Updates

```bash
# Update Docker images
docker-compose -f docker-compose.production.yml pull

# Rebuild and restart
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml up -d --build

# Update system packages
sudo apt update && sudo apt upgrade -y
```

---

## 12. Visual Guides

### 📸 Screenshot Guidance

While we cannot include actual screenshots in this text-based documentation, here are descriptions of what you should see at each step, along with commands to capture your own screenshots.

#### How to Capture Screenshots

**Linux (Command Line):**
```bash
# Install scrot (screenshot tool)
sudo apt install scrot

# Capture full screen
scrot screenshot_$(date +%Y%m%d_%H%M%S).png

# Capture specific window
scrot -u screenshot_window.png

# Capture specific area (select with mouse)
scrot -s screenshot_area.png
```

**Mac:**
- Press `Shift + PrtScn` to select area
- Press `PrtScn` for full screen (saves to Pictures/Screenshots)
- Screenshots save to Pictures/Screenshots by default

### 🎨 Expected Screens

#### 1. Successful Deployment

**Description:** All services running in Docker Compose

**Command to verify:**
```bash
docker-compose -f docker-compose.production.yml ps
```

**Expected Output:**
```
       Name                      Command               State           Ports
----------------------------------------------------------------------------------------------
open-omniscience-api     uvicorn api.main:app --ho ...   Up      0.0.0.0:8000->8000/tcp
open-omniscience-nginx   /docker-entrypoint.sh nginx ...   Up      0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
open-omniscience-postgres docker-entrypoint.sh postgres    Up      0.0.0.0:5432->5432/tcp
open-omniscience-redis   docker-entrypoint.sh redis ...   Up      0.0.0.0:6379->6379/tcp
```

**Screenshot Suggestion:** Capture this output to show all services are running.

#### 2. API Health Check

**Description:** API responding to health check requests

**Command to verify:**
```bash
curl -I https://yourdomain.com/health
```

**Expected Output:**
```
HTTP/2 200 
server: nginx
content-type: application/json
...
```

**Screenshot Suggestion:** Capture the browser showing a successful response.

#### 3. Grafana Dashboard

**Description:** Monitoring dashboard showing API metrics

**URL:** `http://yourdomain.com:3000`

**Expected View:**
- Dashboard with graphs showing:
  - Request rate
  - Response times
  - Error rates
  - Database metrics

**Screenshot Suggestion:** Capture the Grafana dashboard with all panels visible.

#### 4. API Documentation (Swagger/ReDoc)

**Description:** Interactive API documentation

**URL:** `https://yourdomain.com/docs`

**Expected View:**
- Swagger UI or ReDoc interface showing:
  - All API endpoints
  - Request/response schemas
  - Try it out buttons

**Screenshot Suggestion:** Capture the API documentation page.

#### 5. Static Showcase Page

**Description:** Main showcase page

**URL:** `https://yourdomain.com/static/showcase.html`

**Expected View:**
- Professional landing page with:
  - Project description
  - Features list
  - Call-to-action buttons

**Screenshot Suggestion:** Capture the full showcase page.

### 📋 Visual Documentation Template

When creating your own documentation with screenshots, use this template:

```markdown
### [Feature Name]

**Description:** Brief description of what this feature does.

**Screenshot:**
![Description of screenshot](path/to/screenshot.png)

**Caption:** Detailed caption explaining what the screenshot shows.

**Steps to Reproduce:**
1. Step 1
2. Step 2
3. Step 3

**Expected Result:** What should happen when following the steps.
```

### 🎨 Color Scheme for Documentation

When creating visual documentation, use these colors for consistency:

- **Primary:** `#2563eb` (Blue)
- **Secondary:** `#7c3aed` (Purple)
- **Success:** `#10b981` (Green)
- **Warning:** `#f59e0b` (Orange)
- **Danger:** `#ef4444` (Red)
- **Dark:** `#1f2937` (Dark Gray)
- **Light:** `#f9fafb` (Light Gray)

### 📐 Diagram Guidance

For architecture diagrams, use tools like:
- [Draw.io](https://app.diagrams.net/) (Free, open-source)
- [Mermaid.js](https://mermaid.js.org/) (Text-based diagrams)
- [PlantUML](https://plantuml.com/) (Text-based diagrams)

#### Example Mermaid Diagram

```mermaid
graph TD
    A[Client] -->|HTTPS| B[Nginx]
    B -->|Proxy| C[API Service]
    C -->|Query| D[PostgreSQL]
    C -->|Cache| E[Redis]
    F[Prometheus] -->|Scrape| C
    G[Grafana] -->|Query| F
```

This creates a flow diagram showing the architecture.

---

## 📚 Additional Resources

### Official Documentation
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://www.sqlalchemy.org/)
- [Docker Documentation](https://docs.docker.com/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Redis Documentation](https://redis.io/docs/)
- [Prometheus Documentation](https://prometheus.io/docs/introduction/overview/)
- [Grafana Documentation](https://grafana.com/docs/)

### Community Resources
- [Open-Omniscience GitHub](https://github.com/ideotion/Open-Omniscience)
- [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions)
- [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues)

### Tutorials
- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [Docker Compose Tutorial](https://docs.docker.com/compose/gettingstarted/)
- [PostgreSQL with Docker](https://www.postgresqltutorial.com/postgresql-docker/)
- [Prometheus with Docker](https://prometheus.io/docs/introduction/first_steps/)

---

## 🔒 Security Best Practices

### 1. Keep Secrets Secure
- Never commit secrets to version control
- Use environment variables or secret managers
- Rotate secrets regularly (every 90 days)

### 2. Use HTTPS Everywhere
- Always use HTTPS in production
- Use strong TLS configurations
- Keep certificates up to date

### 3. Limit Access
- Use firewalls to restrict access
- Implement IP whitelisting if possible
- Use VPNs for internal services

### 4. Monitor and Audit
- Monitor logs for suspicious activity
- Set up alerts for unusual patterns
- Regularly audit user access

### 5. Keep Software Updated
- Update Docker images regularly
- Update system packages
- Update dependencies

---

## 📄 License

This deployment guide is licensed under the **MIT License**, the same as the Open-Omniscience project itself. You are free to use, copy, modify, and distribute this guide as long as you include the original copyright notice.

---

## 🙏 Contributing

If you find issues with this deployment guide or have suggestions for improvements, please:

1. Open an issue on [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues)
2. Submit a pull request with your improvements
3. Join the discussion on [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions)

---

**Documentation Version:** 2.0  
**Last Updated:** 2025-05-12  
**Maintainer:** Open-Omniscience Team
