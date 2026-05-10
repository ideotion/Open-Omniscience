# Open Omniscience - Staging Deployment Guide

## ✅ Staging Environment Ready

This guide provides comprehensive instructions for deploying Open Omniscience to a staging environment for testing and validation.

---

## 🚀 Quick Start

### Deploy to Staging

```bash
# Clone the repository
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience

# Make the deploy script executable
chmod +x scripts/deploy-staging.sh

# Run the interactive deployment
./scripts/deploy-staging.sh
```

The interactive menu will guide you through:
1. Pulling latest changes
2. Creating directories
3. Building Docker images
4. Starting services
5. Verifying deployment
6. Running tests

### Or Use Docker Compose Directly

```bash
# Create directories
mkdir -p data audit logs monitoring/grafana-provisioning/dashboards

# Start staging services
docker-compose -f docker-compose.staging.yml up -d --build

# Check status
docker-compose -f docker-compose.staging.yml ps

# View logs
docker-compose -f docker-compose.staging.yml logs -f
```

---

## 📋 Staging Configuration

### Services Available

| Service | Port | Purpose | Profile | Status |
|---------|------|---------|---------|--------|
| web | 8000 | Main application | Always | ✅ |
| db | 5433 | PostgreSQL | postgres | Optional |
| redis | 6380 | Caching | redis | Optional |
| traefik | 8080/8081 | Reverse proxy | traefik | Optional |
| prometheus | 9090 | Metrics | monitoring | Optional |
| grafana | 3000 | Visualization | monitoring | Optional |
| test-runner | - | Testing | testing | Optional |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| APP_ENV | staging | Environment name |
| DATABASE_URL | sqlite:////app/data/open_omniscience.db | Database connection |
| PYTHONUNBUFFERED | 1 | Python output buffering |
| PYTHONDONTWRITEBYTECODE | 1 | Disable .pyc files |
| LOG_LEVEL | DEBUG | Logging level |

---

## 🎯 Deployment Steps

### Step 1: Prerequisites

Ensure you have the following installed:

```bash
# Docker
curl -fsSL https://get.docker.com | sh

# Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Git
sudo apt-get install git

# Verify installations
docker --version
docker-compose --version
git --version
```

### Step 2: Clone Repository

```bash
git clone https://github.com/ideotion/Open-Omniscience
cd Open-Omniscience
git checkout 0.01
```

### Step 3: Configure Environment

```bash
# Copy environment file
cp .env.example .env

# Edit with your settings (optional)
nano .env

# Create directories
mkdir -p data audit logs
```

### Step 4: Build and Start

```bash
# Build images
docker-compose -f docker-compose.staging.yml build

# Start services
docker-compose -f docker-compose.staging.yml up -d

# Check status
docker-compose -f docker-compose.staging.yml ps
```

### Step 5: Verify Deployment

```bash
# Check if services are running
docker-compose -f docker-compose.staging.yml ps

# Test API endpoint
curl http://localhost:8000/api/sources

# Test metrics endpoint
curl http://localhost:8000/metrics

# Check logs
docker-compose -f docker-compose.staging.yml logs web
```

---

## 🔍 Monitoring & Performance

### Prometheus Metrics

The application exposes Prometheus metrics at `/metrics`:

```bash
# View metrics
curl http://localhost:8000/metrics

# Or use Prometheus (if enabled)
# Access at: http://localhost:9090
```

### Available Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `open_omniscience_requests_total` | Counter | Total HTTP requests |
| `open_omniscience_request_latency_seconds` | Histogram | Request latency |
| `open_omniscience_active_requests` | Gauge | Active requests |
| `open_omniscience_articles_count` | Gauge | Total articles |
| `open_omniscience_sources_count` | Gauge | Total sources |

### Grafana Dashboard

If Grafana is enabled:
1. Access at: http://localhost:3000
2. Login: admin / admin_change_me
3. Add Prometheus data source: http://prometheus:9090
4. Import dashboard (JSON provided in monitoring directory)

### Manual Monitoring

```bash
# Container resource usage
docker stats

# Disk usage
df -h

# Log files
ls -lh audit/ logs/

# Database size
du -sh data/
```

---

## 🧪 Testing in Staging

### Run All Tests

```bash
# Using the deploy script
./scripts/deploy-staging.sh
# Select option 3: Run tests

# Or manually
pip install -q pytest pytest-mock
python -m pytest tests/ -v
```

### Test API Endpoints

```bash
# Test sources endpoint
curl http://localhost:8000/api/sources | jq

# Test articles search
curl "http://localhost:8000/api/articles?query=test&limit=5" | jq

# Test export
curl "http://localhost:8000/api/articles/export?format=csv&limit=10" > articles.csv

# Test with specific source
curl "http://localhost:8000/api/articles?source=BBC News&limit=5" | jq
```

### Test Scraping

```bash
# Run the scraper manually
docker-compose -f docker-compose.staging.yml exec web python -c "
import sys
sys.path.insert(0, 'src')
from scraper.scraper import Scraper
s = Scraper(max_workers=2)
articles = s.scrape_all_sources()
print(f'Scraped {len(articles)} articles')
"

# Or use the ingestion pipeline
docker-compose -f docker-compose.staging.yml exec web python -c "
import sys
sys.path.insert(0, 'src')
from ingestor.pipeline import IngestionPipeline
p = IngestionPipeline()
total = p.ingest_all_sources()
print(f'Ingested {total} articles')
p.close()
"
```

---

## 🐛 Common Issues & Fixes

### Issue 1: Port Already in Use

**Error:** `Error: Address already in use`

**Solution:**
```bash
# Find and kill the process using the port
sudo lsof -i :8000
kill -9 <PID>

# Or use a different port
# Edit docker-compose.staging.yml and change the port
```

### Issue 2: Docker Permission Denied

**Error:** `Got permission denied while trying to connect to the Docker daemon socket`

**Solution:**
```bash
# Add your user to the docker group
sudo usermod -aG docker $USER

# Log out and log back in
# Or restart the session
newgrp docker
```

### Issue 3: Missing Dependencies

**Error:** `ModuleNotFoundError: No module named 'prometheus_client'`

**Solution:**
```bash
# Rebuild the Docker image
docker-compose -f docker-compose.staging.yml build --no-cache

# Or install manually
pip install prometheus-client
```

### Issue 4: Database Connection Error

**Error:** `sqlite3.OperationalError: unable to open database file`

**Solution:**
```bash
# Ensure the data directory exists and has correct permissions
mkdir -p data
chmod 777 data

# Restart the container
docker-compose -f docker-compose.staging.yml restart web
```

### Issue 5: Health Check Failing

**Error:** `unhealthy` status in docker ps

**Solution:**
```bash
# Check the logs
docker-compose -f docker-compose.staging.yml logs web

# Increase health check timeout in docker-compose.staging.yml
healthcheck:
  test: ["CMD", "python", "-c", "import sys; sys.path.insert(0, 'src'); from database.models import engine; print('DB OK')"]
  interval: 30s
  timeout: 10s  # Increased from 3s
  retries: 5
  start_period: 10s
```

---

## 📊 Performance Optimization

### Database Optimization

```bash
# Add indexes (already in models.py)
# Vacuum SQLite database
docker-compose -f docker-compose.staging.yml exec web python -c "
import sys
sys.path.insert(0, 'src')
from database.models import engine
from sqlalchemy import text
with engine.connect() as conn:
    conn.execute(text('VACUUM'))
    conn.execute(text('ANALYZE'))
    conn.commit()
print('Database optimized')
"
```

### Scraping Optimization

```bash
# Adjust rate limits in configs/sources.yml
# Example: Increase rate_limit_ms for slow sources
- name: "BBC News"
  domain: "bbc.com"
  rss_url: "http://feeds.bbci.co.uk/news/rss.xml"
  rate_limit_ms: 2000  # Increased from 1000
  enabled: true
  priority: 1

# Adjust max_workers in scraper
# Edit src/scraper/scraper.py
self.max_workers = 10  # Increased from 5
```

### Caching

Enable Redis for caching:

```bash
# Start with Redis profile
docker-compose -f docker-compose.staging.yml --profile redis up -d

# Update API to use Redis (future enhancement)
```

---

## 🔄 Update & Maintenance

### Update to Latest Version

```bash
# Pull latest changes
git pull origin 0.01

# Rebuild and restart
docker-compose -f docker-compose.staging.yml down
docker-compose -f docker-compose.staging.yml build --no-cache
docker-compose -f docker-compose.staging.yml up -d
```

### Backup Data

```bash
# Backup database
cp data/open_omniscience.db data/open_omniscience.db.backup

# Backup all data
zip -r open-omniscience-backup-$(date +%Y%m%d).zip data/ audit/ logs/
```

### Restore Data

```bash
# Stop services
docker-compose -f docker-compose.staging.yml down

# Restore database
cp data/open_omniscience.db.backup data/open_omniscience.db

# Start services
docker-compose -f docker-compose.staging.yml up -d
```

---

## 📝 Staging Checklist

### Pre-Deployment
- [ ] Docker installed
- [ ] Docker Compose installed
- [ ] Git installed
- [ ] Repository cloned
- [ ] Branch checked out (0.01)
- [ ] Directories created (data, audit, logs)

### Deployment
- [ ] Docker images built
- [ ] Services started
- [ ] Health checks passing
- [ ] API responding
- [ ] Metrics endpoint working

### Testing
- [ ] All Python tests passing
- [ ] API endpoints responding
- [ ] Scraping working
- [ ] Database connectivity verified
- [ ] Data ingestion working

### Monitoring
- [ ] Prometheus metrics available
- [ ] Grafana dashboard accessible (if enabled)
- [ ] Container resource usage normal
- [ ] Logs being written

### Validation
- [ ] All sources have valid RSS URLs
- [ ] No empty RSS URLs in sources.yml
- [ ] Icon files present
- [ ] Documentation complete

---

## 🎨 Customization

### Change Port

Edit `docker-compose.staging.yml`:
```yaml
ports:
  - "9000:8000"  # Change first number to desired port
```

### Enable/Disable Services

Use profiles to enable optional services:

```bash
# Enable PostgreSQL and Redis
docker-compose -f docker-compose.staging.yml --profile postgres --profile redis up -d

# Enable monitoring stack
docker-compose -f docker-compose.staging.yml --profile monitoring up -d

# Enable all services
docker-compose -f docker-compose.staging.yml --profile postgres --profile redis --profile traefik --profile monitoring up -d
```

### Change Database

Edit `.env` or `docker-compose.staging.yml`:
```yaml
environment:
  - DATABASE_URL=postgresql://open_omniscience:password@db:5432/open_omniscience_staging
```

### Change Logging Level

Edit `docker-compose.staging.yml`:
```yaml
environment:
  - LOG_LEVEL=INFO  # Change to DEBUG, WARNING, ERROR, etc.
```

---

## 📚 Additional Documentation

- **[README.md](README.md)** - Main project documentation
- **[ANALYSIS_AND_PLAN.md](ANALYSIS_AND_PLAN.md)** - Repository analysis
- **[DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md)** - Deployment summary
- **[PACKAGING_SUMMARY.md](PACKAGING_SUMMARY.md)** - Packaging summary
- **[package/BUILD_INSTRUCTIONS.md](package/BUILD_INSTRUCTIONS.md)** - Package build instructions

---

## 🙏 Support

For issues with staging deployment:

1. **Check logs:** `docker-compose -f docker-compose.staging.yml logs`
2. **Check status:** `docker-compose -f docker-compose.staging.yml ps`
3. **Check resources:** `docker stats`
4. **Review documentation:** See links above
5. **Create issue:** [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues)

---

## 📊 Success Metrics

### Deployment Success
- [ ] Services start without errors
- [ ] Health checks pass
- [ ] API responds to requests
- [ ] Metrics endpoint works
- [ ] All tests pass

### Performance Metrics
- [ ] API response time < 2 seconds
- [ ] Scraping completes successfully
- [ ] Database queries efficient
- [ ] Memory usage stable
- [ ] CPU usage < 80%

### Data Quality
- [ ] All sources have valid RSS URLs
- [ ] Articles are being scraped
- [ ] Duplicates are detected
- [ ] Data is stored correctly

---

**Last Updated:** 2026-05-08  
**Version:** 0.2.0  
**Environment:** Staging  
**Branch:** 0.01  
**Author:** Mistral Vibe Code (Autonomous Agent)  
**Repository:** ideotion/Open-Omniscience
