# Pillar 5 - Financial Intelligence Deployment Guide

## Overview

This guide provides instructions for deploying Open-Omniscience Pillar 5 in various environments, from local development to production.

## Prerequisites

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Python | 3.10 | 3.11+ |
| RAM | 4 GB | 8 GB+ |
| CPU | 2 cores | 4 cores+ |
| Disk Space | 10 GB | 50 GB+ (for data storage) |
| OS | Linux, macOS, Windows | Linux (Ubuntu/Debian) |

### Dependencies

**Python Packages:**
- fastapi
- uvicorn
- sqlalchemy
- alembic
- requests
- beautifulsoup4
- lxml
- numpy
- pyyaml
- python-multipart

**System Dependencies:**
- Git
- Python 3.10+
- pip
- SQLite (included with Python) or PostgreSQL

## Installation

### 1. Clone the Repository

```bash
# Clone the main Open-Omniscience repository
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience

# Checkout the desired branch (e.g., 0.03)
git checkout 0.03
```

### 2. Set Up Python Environment

**Option A: Virtual Environment (Recommended)**

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Pillar 5 specific dependencies
cd pillar5
pip install -r requirements.txt
cd ..
```

**Option B: System-wide Installation**

```bash
# Install dependencies system-wide
pip install --upgrade pip
pip install -r requirements.txt
pip install -r pillar5/requirements.txt
```

**Option C: Docker (Recommended for Production)**

See the [Docker Deployment](#docker-deployment) section below.

### 3. Configure Database

Pillar 5 supports both SQLite (default) and PostgreSQL.

#### SQLite Configuration (Default)

No additional configuration is needed. SQLite will automatically create a database file at `open_omniscience.db`.

**Custom SQLite Location:**

Edit `pillar5/src/models/base.py`:

```python
SQLALCHEMY_DATABASE_URL = "sqlite:////path/to/your/database.db"
```

#### PostgreSQL Configuration

1. Install PostgreSQL:
   - **Ubuntu/Debian:** `sudo apt-get install postgresql postgresql-contrib`
   - **macOS:** `brew install postgresql`
   - **Windows:** Download from [PostgreSQL website](https://www.postgresql.org/download/)

2. Create database and user:
   ```bash
   sudo -u postgres psql
   CREATE DATABASE open_omniscience;
   CREATE USER pillar5 WITH PASSWORD 'your_password';
   GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO pillar5;
   \q
   ```

3. Configure Pillar 5 to use PostgreSQL:
   
   Edit `pillar5/src/models/base.py`:
   
   ```python
   SQLALCHEMY_DATABASE_URL = "postgresql://pillar5:your_password@localhost/open_omniscience"
   ```

4. Install PostgreSQL Python adapter:
   ```bash
   pip install psycopg2-binary
   ```

### 4. Initialize Database

```bash
cd pillar5

# Initialize Alembic (if not already initialized)
alembic revision --autogenerate -m "Initial schema"

# Apply migrations
alembic upgrade head

# Populate with sample data (optional)
python scripts/migrate_company_to_instrument.py

cd ..
```

### 5. Configure Scraping

Edit `pillar5/configs/scraping.yaml` to customize scraping behavior:

```yaml
# Rate limiting (seconds between requests)
rate_limits:
  default: 2.0
  yahoo.com: 2.5
  investing.com: 3.0

# Caching
cache:
  enabled: true
  expiration: 86400  # 24 hours
  directory: .cache/pillar5

# User agent
user_agent: "OpenOmniscience/2.0 (Financial Intelligence; +https://github.com/ideotion/Open-Omniscience)"

# Timeout (seconds)
timeout: 30

# Retry settings
max_retries: 3
retry_delay: 1.0
```

## Deployment Options

### Local Development Deployment

**Start the application:**

```bash
# From the main Open-Omniscience directory
uvicorn main:app --reload --port 8000
```

**Access the application:**
- Open your browser and navigate to `http://localhost:8000`
- API endpoints are available at `http://localhost:8000/api/v1/financial`

**Features:**
- Auto-reload on code changes (`--reload`)
- Debug mode enabled
- Development logging

### Production Deployment

#### Option A: Uvicorn with Gunicorn

**Install Gunicorn:**

```bash
pip install gunicorn
```

**Create a Gunicorn configuration file (`gunicorn.conf.py`):**

```python
bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 2
```

**Start the application:**

```bash
# From the main Open-Omniscience directory
gunicorn -c gunicorn.conf.py main:app
```

**With systemd (Ubuntu/Debian):**

1. Create a systemd service file (`/etc/systemd/system/open-omniscience.service`):
   
   ```ini
   [Unit]
   Description=Open-Omniscience Pillar 5
   After=network.target
   
   [Service]
   User=your_user
   Group=your_group
   WorkingDirectory=/path/to/Open-Omniscience
   Environment="PATH=/path/to/venv/bin"
   ExecStart=/path/to/venv/bin/gunicorn -c /path/to/gunicorn.conf.py main:app
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```

2. Enable and start the service:
   
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable open-omniscience
   sudo systemctl start open-omniscience
   ```

3. Check status:
   
   ```bash
   sudo systemctl status open-omniscience
   ```

4. View logs:
   
   ```bash
   journalctl -u open-omniscience -f
   ```

#### Option B: Docker Deployment

**Create a Dockerfile:**

```dockerfile
# Use official Python image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY requirements.txt ./
COPY pillar5/requirements.txt ./pillar5/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r pillar5/requirements.txt

# Copy application code
COPY . .

# Initialize database
RUN cd pillar5 && \
    alembic upgrade head && \
    python scripts/migrate_company_to_instrument.py && \
    cd ..

# Expose port
EXPOSE 8000

# Start the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Create a docker-compose.yml file:**

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./pillar5/.cache:/app/pillar5/.cache
    environment:
      - SQLALCHEMY_DATABASE_URL=sqlite:////app/data/open_omniscience.db
    restart: unless-stopped

  # Optional PostgreSQL service
  postgres:
    image: postgres:15
    environment:
      - POSTGRES_DB=open_omniscience
      - POSTGRES_USER=pillar5
      - POSTGRES_PASSWORD=your_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

volumes:
  postgres_data:
```

**Build and run with Docker:**

```bash
# Build the image
docker-compose build

# Start the services
docker-compose up -d

# View logs
docker-compose logs -f web

# Stop the services
docker-compose down
```

**Access the application:**
- Open your browser and navigate to `http://localhost:8000`

#### Option C: Kubernetes Deployment

**Create a Kubernetes deployment file (`pillar5-deployment.yaml`):**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pillar5
  labels:
    app: pillar5
spec:
  replicas: 2
  selector:
    matchLabels:
      app: pillar5
  template:
    metadata:
      labels:
        app: pillar5
    spec:
      containers:
      - name: pillar5
        image: your-registry/open-omniscience-pillar5:latest
        ports:
        - containerPort: 8000
        env:
        - name: SQLALCHEMY_DATABASE_URL
          value: "postgresql://pillar5:your_password@postgres/open_omniscience"
        volumeMounts:
        - name: cache
          mountPath: /app/pillar5/.cache
        - name: data
          mountPath: /app/data
      volumes:
      - name: cache
        emptyDir: {}
      - name: data
        persistentVolumeClaim:
          claimName: pillar5-data
---
apiVersion: v1
kind: Service
metadata:
  name: pillar5
spec:
  selector:
    app: pillar5
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: LoadBalancer
```

**Create a persistent volume claim (`pillar5-pvc.yaml`):**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pillar5-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
```

**Deploy to Kubernetes:**

```bash
# Apply the persistent volume claim
kubectl apply -f pillar5-pvc.yaml

# Apply the deployment
kubectl apply -f pillar5-deployment.yaml

# Check deployment status
kubectl get deployments
kubectl get pods

# Get service IP
kubectl get services
```

**Access the application:**
- Use the external IP provided by the LoadBalancer service

## Configuration

### Environment Variables

Pillar 5 can be configured using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SQLALCHEMY_DATABASE_URL` | Database connection URL | `sqlite:///./open_omniscience.db` |
| `DEBUG` | Enable debug mode | `False` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `CACHE_ENABLED` | Enable caching | `True` |
| `CACHE_DIRECTORY` | Cache directory | `.cache/pillar5` |
| `RATE_LIMIT_DEFAULT` | Default rate limit (seconds) | `2.0` |
| `USER_AGENT` | User agent string | `OpenOmniscience/2.0` |

**Example .env file:**

```bash
# Database
SQLALCHEMY_DATABASE_URL=postgresql://pillar5:password@localhost/open_omniscience

# Debug
DEBUG=True
LOG_LEVEL=DEBUG

# Caching
CACHE_ENABLED=True
CACHE_DIRECTORY=.cache/pillar5

# Scraping
RATE_LIMIT_DEFAULT=2.0
USER_AGENT=OpenOmniscience/2.0 (Financial Intelligence)
```

### Load Environment Variables

Create a `.env` file in the main directory and load it:

```python
# In main.py or wherever you create the FastAPI app
from dotenv import load_dotenv
import os

load_dotenv()

# Access environment variables
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
```

## Scaling

### Horizontal Scaling

Pillar 5 can be scaled horizontally by running multiple instances behind a load balancer.

**Considerations:**
- Use a shared database (PostgreSQL recommended)
- Configure a shared cache directory or use Redis
- Ensure rate limiting is coordinated across instances

### Vertical Scaling

For CPU-intensive operations (metric calculations, scraping):
- Increase CPU cores
- Allocate more memory
- Use faster storage (SSD/NVMe)

### Database Scaling

For PostgreSQL:
- Configure connection pooling
- Optimize indexes
- Consider read replicas for read-heavy workloads
- Use partitioning for large tables

## Monitoring

### Logging

Pillar 5 provides comprehensive logging:

```python
# Configure logging in main.py
import logging

logging.basicConfig(
    level=os.getenv('LOG_LEVEL', 'INFO'),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pillar5.log'),
        logging.StreamHandler()
    ]
)
```

**Log levels:**
- `DEBUG`: Detailed information for debugging
- `INFO`: General information about operations
- `WARNING`: Warning messages
- `ERROR`: Error messages
- `CRITICAL`: Critical errors

### Metrics

**Prometheus Integration:**

```python
# In main.py
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()
Instrumentator().instrument(app).expose(app)
```

**Key metrics to monitor:**
- Request count and duration
- Error rates
- Database query performance
- Cache hit/miss ratios
- Scraping success/failure rates
- Memory usage
- CPU usage

### Health Checks

**Add health check endpoint:**

```python
# In financial_routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()

@router.get("/health")
async def health_check(db: Session = Depends(get_db)):
    # Check database connection
    try:
        db.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    
    return {
        "status": "healthy",
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat()
    }
```

**Check health:**

```bash
curl -X GET "http://localhost:8000/api/v1/financial/health"
```

## Security

### HTTPS

**Use a reverse proxy with HTTPS:**

**Nginx Configuration:**

```nginx
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name your-domain.com;
    
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

**Use Let's Encrypt for free SSL certificates:**

```bash
# Install Certbot
sudo apt-get install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d your-domain.com

# Auto-renew certificates
sudo certbot renew --dry-run
```

### Rate Limiting

**Add rate limiting to API endpoints:**

```python
# In main.py
from fastapi import FastAPI
from fastapi.middleware import Middleware
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(middleware=[Middleware(limiter)])

# In financial_routes.py
from fastapi import Depends
from slowapi import Limiter

@router.get("/instruments")
@limiter.limit("100/minute")
async def list_instruments(request: Request):
    return await get_instruments()
```

### Authentication

**Add API key authentication:**

```python
# In main.py
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import APIKeyHeader

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key: str = Depends(api_key_header)):
    if api_key != "your-secret-key":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key"
        )
    return api_key

app = FastAPI(dependencies=[Depends(get_api_key)])
```

### CORS

**Configure CORS:**

```python
# In main.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

## Backup and Recovery

### Database Backup

**SQLite Backup:**

```bash
# Create backup
sqlite3 open_omniscience.db ".backup backup_$(date +%Y%m%d_%H%M%S).db"

# Or copy the file
cp open_omniscience.db backup/open_omniscience_$(date +%Y%m%d_%H%M%S).db
```

**PostgreSQL Backup:**

```bash
# Create backup
pg_dump -U pillar5 -d open_omniscience -F c -f backup_$(date +%Y%m%d_%H%M%S).dump

# Restore backup
pg_restore -U pillar5 -d open_omniscience backup_file.dump
```

### Automated Backups

**Cron Job for Daily Backups:**

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /path/to/backup_script.sh
```

**Backup Script (`backup_script.sh`):**

```bash
#!/bin/bash

# Set variables
BACKUP_DIR="/path/to/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_FILE="/path/to/open_omniscience.db"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Create backup
cp "$DB_FILE" "$BACKUP_DIR/open_omniscience_$DATE.db"

# Keep only the last 7 backups
ls -t "$BACKUP_DIR"/open_omniscience_*.db | tail -n +8 | xargs rm -f

# Log the backup
echo "Backup created: $DATE" >> "$BACKUP_DIR/backup.log"
```

### Disaster Recovery

1. **Restore from backup:**
   ```bash
   # For SQLite
   cp /path/to/backup/open_omniscience.db /path/to/live/open_omniscience.db
   
   # For PostgreSQL
   pg_restore -U pillar5 -d open_omniscience /path/to/backup.dump
   ```

2. **Reinitialize database:**
   ```bash
   cd pillar5
   alembic downgrade base
   alembic upgrade head
   python scripts/migrate_company_to_instrument.py
   ```

3. **Re-scrape data:**
   ```python
   from pillar5.src.scraping.exchange_discovery import ExchangeDiscovery
   from pillar5.src.scraping.instrument_discovery import InstrumentDiscovery
   
   # Re-discover exchanges and instruments
   exchange_discovery = ExchangeDiscovery()
   instrument_discovery = InstrumentDiscovery()
   
   exchanges = exchange_discovery.get_all_exchanges()
   instruments = instrument_discovery.get_all_instruments()
   
   # Store in database
   # ...
   ```

## Performance Optimization

### Database Optimization

**Add indexes:**

```python
# In your SQLAlchemy models
from sqlalchemy import Index

class FinancialInstrumentDB(Base):
    # ... fields ...
    
    __table_args__ = (
        Index('idx_financial_instrument_symbol', 'symbol'),
        Index('idx_financial_instrument_type', 'type'),
        Index('idx_financial_instrument_sector', 'sector'),
        Index('idx_financial_instrument_exchange_id', 'exchange_id'),
    )
```

**Optimize queries:**

```python
# Use selectinload for relationships
from sqlalchemy.orm import selectinload

instruments = db.query(FinancialInstrumentDB).options(
    selectinload(FinancialInstrumentDB.exchange),
    selectinload(FinancialInstrumentDB.data_points)
).all()
```

### Caching

**Use Redis for distributed caching:**

```python
# In scraping/base.py
import redis

class CacheManager:
    def __init__(self):
        self.redis = redis.Redis(host='localhost', port=6379, db=0)
    
    def get(self, key):
        return self.redis.get(key)
    
    def set(self, key, value, ttl=86400):
        self.redis.setex(key, ttl, value)
```

### Asynchronous Processing

**Use Celery for background tasks:**

```python
# tasks.py
from celery import Celery

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task
def scrape_ohlc_data(symbol, timeframe, limit):
    from pillar5.src.scraping.ohlc_scraper import OHLCScraper
    scraper = OHLCScraper()
    return scraper.get_ohlc_data(symbol, timeframe, limit)

@app.task
def calculate_metrics(instrument_id, timeframe):
    from pillar5.src.services.metric_calculator import MetricCalculator
    from pillar5.src.models.financial_data import FinancialDataPointDB
    
    calculator = MetricCalculator()
    ohlc_data = FinancialDataPointDB.query.filter_by(
        instrument_id=instrument_id,
        timeframe=timeframe
    ).all()
    
    return calculator.calculate_all_metrics(ohlc_data, instrument_id, timeframe)
```

**Start Celery worker:**

```bash
celery -A tasks worker --loglevel=info
```

## Upgrading

### Version Upgrades

1. **Backup your data:**
   ```bash
   # Create backup
   cp open_omniscience.db open_omniscience_backup.db
   ```

2. **Pull the latest code:**
   ```bash
   git pull origin 0.03
   ```

3. **Update dependencies:**
   ```bash
   pip install -r requirements.txt
   pip install -r pillar5/requirements.txt
   ```

4. **Run migrations:**
   ```bash
   cd pillar5
   alembic upgrade head
   cd ..
   ```

5. **Restart the application:**
   ```bash
   # If using systemd
   sudo systemctl restart open-omniscience
   
   # If using Docker
   docker-compose down && docker-compose up -d
   ```

### Migration from Older Versions

If upgrading from a version before Pillar 5's unified instrument model:

1. **Run the migration script:**
   ```bash
   python pillar5/scripts/migrate_company_to_instrument.py
   ```

2. **Verify data integrity:**
   ```bash
   # Check that all companies were migrated
   from pillar5.src.models.financial_instrument import FinancialInstrumentDB
   from pillar5.src.models.company import CompanyDB
   
   companies = CompanyDB.query.count()
   instruments = FinancialInstrumentDB.query.count()
   
   print(f"Companies: {companies}, Instruments: {instruments}")
   ```

## Troubleshooting

### Common Issues

**1. Database connection errors**

**Symptoms:**
- `sqlalchemy.exc.OperationalError: unable to open database file`
- `psycopg2.OperationalError: connection to server at "localhost" (::1) failed`

**Solutions:**
- Verify database file exists and is writable (SQLite)
- Check PostgreSQL connection credentials
- Ensure PostgreSQL server is running
- Verify network connectivity to database server

**2. Migration errors**

**Symptoms:**
- `alembic.util.exc.CommandError: Can't locate revision identified by 'head'`
- `sqlalchemy.exc.ProgrammingError: (sqlite3.ProgrammingError) no such table`

**Solutions:**
- Check current migration state: `alembic current`
- List all migrations: `alembic history`
- Downgrade and upgrade: `alembic downgrade base && alembic upgrade head`
- Check for manual database changes that conflict with migrations

**3. Scraping failures**

**Symptoms:**
- `requests.exceptions.ConnectionError`
- `requests.exceptions.Timeout`
- `beautifulsoup4.BeautifulSoup` parsing errors

**Solutions:**
- Check internet connectivity
- Verify target website is accessible
- Check rate limits are not being exceeded
- Review `robots.txt` for the target domain
- Increase timeout in `configs/scraping.yaml`
- Add fallback sources

**4. Import errors**

**Symptoms:**
- `ModuleNotFoundError: No module named '...'`
- `ImportError: cannot import name '...'`

**Solutions:**
- Verify all dependencies are installed: `pip list`
- Check for version conflicts
- Reinstall dependencies: `pip install -r requirements.txt`
- Check Python path: `import sys; print(sys.path)`
- Verify package is installed in the correct environment

**5. Performance issues**

**Symptoms:**
- Slow API responses
- High CPU/memory usage
- Database query timeouts

**Solutions:**
- Enable caching
- Add database indexes
- Optimize queries with `selectinload`
- Increase resources (CPU, memory)
- Use pagination for large datasets
- Consider horizontal scaling

### Debug Mode

Enable debug mode for more detailed error messages:

```python
# In main.py
app = FastAPI(debug=True)
```

Or via environment variable:

```bash
export DEBUG=True
uvicorn main:app --reload
```

### Logs

Check application logs for detailed error information:

**Console logs:**
```bash
# View logs when running with uvicorn
uvicorn main:app --reload
```

**File logs:**
```bash
# View log file
tail -f pillar5.log

# Filter for errors
grep -i error pillar5.log
```

**System logs:**
```bash
# For systemd
journalctl -u open-omniscience -f

# For Docker
docker-compose logs -f web
```

## Support

For additional support:

1. **GitHub Issues:** https://github.com/ideotion/Open-Omniscience/issues
2. **Documentation:** https://github.com/ideotion/Open-Omniscience/tree/main/pillar5/docs
3. **Community:** Join the Open-Omniscience community

## Appendix

### Configuration Reference

**Database Configuration:**
- `SQLALCHEMY_DATABASE_URL`: Database connection URL
- Supported formats:
  - SQLite: `sqlite:///path/to/database.db`
  - PostgreSQL: `postgresql://user:password@host/database`

**Scraping Configuration:**
- `rate_limits`: Rate limits per domain (seconds)
- `cache.enabled`: Enable/disable caching
- `cache.expiration`: Cache expiration time (seconds)
- `cache.directory`: Cache directory path
- `user_agent`: User agent string
- `timeout`: Request timeout (seconds)
- `max_retries`: Maximum number of retries
- `retry_delay`: Delay between retries (seconds)

**API Configuration:**
- `DEBUG`: Enable debug mode
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `CORS_ORIGINS`: Allowed CORS origins

### Port Reference

| Service | Default Port | Description |
|---------|--------------|-------------|
| FastAPI | 8000 | Main application |
| PostgreSQL | 5432 | Database server |
| Redis | 6379 | Cache server |
| Nginx | 80/443 | Reverse proxy |

### File Locations

| File/Directory | Purpose |
|---------------|---------|
| `pillar5/src/` | Source code |
| `pillar5/migrations/` | Database migrations |
| `pillar5/configs/` | Configuration files |
| `pillar5/scripts/` | Utility scripts |
| `pillar5/tests/` | Test files |
| `pillar5/docs/` | Documentation |
| `open_omniscience.db` | SQLite database (default) |
| `.cache/pillar5/` | Scraping cache |
| `alembic.ini` | Alembic configuration |
