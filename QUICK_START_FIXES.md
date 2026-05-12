# Open-Omniscience Quick Start Fixes

**Priority: CRITICAL - Apply these fixes immediately to address security vulnerabilities**

---

## 🚨 IMMEDIATE ACTION REQUIRED

This document contains the **most critical fixes** that must be applied before using Open-Omniscience in any environment. These fixes address **SQL injection vulnerabilities, authentication bypass, and remote code execution risks**.

---

## Quick Fix Summary

### 1. SQL Injection Fix (CRITICAL - Apply First!)

**File:** `src/api/main.py`

**Issue:** The `build_sqlalchemy_filter` function uses string interpolation with `ilike()`, allowing SQL injection.

**Fix:** Replace string interpolation with SQLAlchemy's `bindparam()` for safe parameter binding.

```bash
# Apply the fix
cd /workspace/Open-Omniscience
patch -p1 < patches/fix_sql_injection.patch
```

**OR manually edit:**
- Lines 255, 259: Use `bindparam()` instead of f-strings in `ilike()`
- Lines 355, 474: Same fix for tag filtering

---

### 2. Pickle Security Fix (CRITICAL)

**File:** `src/scraper/source_monitor.py`

**Issue:** Pickle deserialization can execute arbitrary code. Cache files use pickle without integrity checks.

**Fix:** Replace pickle with JSON for caching.

```bash
# Apply the fix
python patches/fix_pickle_security.py
```

**OR manually edit:**
- Line 13: Replace `import pickle` with `import json`
- Lines 180, 183: Change file extension from `.pkl` to `.json`
- Lines 183, 193: Replace `pickle.load()` with `json.load()` and `pickle.dump()` with `json.dump()`

---

### 3. Add Missing Dependencies (HIGH)

**File:** `requirements.txt`

**Issue:** Missing dependencies cause import errors when running the application.

**Fix:** Install missing dependencies:

```bash
# Install all missing dependencies
pip install numpy scikit-learn nltk spacy textblob networkx matplotlib python-dateutil jose passlib python-jose[cryptography]
```

**OR update requirements.txt:**
```text
# Add to requirements.txt
numpy>=1.24.0
scikit-learn>=1.3.0
nltk>=3.8.0
spacy>=3.5.0
textblob>=0.17.0
networkx>=3.1.0
matplotlib>=3.7.0
python-dateutil>=2.8.0
jose>=1.0.0
passlib>=1.7.0
python-jose[cryptography]>=3.3.0
```

---

### 4. Docker Fixes (HIGH)

**File:** `Dockerfile.llm`

**Issue:** References non-existent base image `ideotion/open-omniscience:latest`

**Fix:** Use the base Python image instead:

```dockerfile
# Replace line 3 in Dockerfile.llm
# FROM ideotion/open-omniscience:latest
FROM python:3.12-slim

# Add these lines after FROM
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
COPY . .
RUN chown -R appuser:appuser /app
USER appuser
WORKDIR /app
```

---

### 5. Entrypoint Fix (HIGH)

**File:** `docker-entrypoint.sh`

**Issue:** Uses `nc` (netcat) which may not be installed in the container.

**Fix:** Replace with Python-based port checking:

```bash
# Replace the port_in_use function
port_in_use() {
    python3 -c "import socket; s = socket.socket(); s.settimeout(1); result = s.connect_ex(('localhost', $1)); s.close(); print('yes' if result == 0 else 'no')"
}
```

---

### 6. Add Missing Files (HIGH)

**Missing:** `nginx.conf` and `ssl/` directory

**Fix:** Create these files:

```bash
# Create nginx.conf
cp patches/nginx.conf .

# Create SSL directory and self-signed certificate
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout ssl/privkey.pem -out ssl/fullchain.pem \
    -subj "/CN=localhost/O=Open Omniscience/C=US"
```

---

## Verification Checklist

After applying all fixes, verify the following:

- [ ] SQL injection attempts are blocked
- [ ] No pickle usage in source_monitor.py
- [ ] All dependencies can be imported
- [ ] Docker builds successfully
- [ ] Docker containers start without errors
- [ ] API endpoints respond correctly

---

## Testing Commands

### Test SQL Injection Fix
```bash
# This should NOT return all articles
curl "http://localhost:8000/api/articles?query=' OR '1'='1"
```

### Test Pickle Fix
```bash
# Check that source_monitor.py uses json, not pickle
grep -n "import json" src/scraper/source_monitor.py
grep -n "import pickle" src/scraper/source_monitor.py  # Should return nothing
```

### Test Dependencies
```bash
# Test imports
python3 -c "import sys; sys.path.insert(0, 'src'); from api.main import app; print('✅ All imports successful')"
```

### Test Docker Build
```bash
# Build the Docker image
docker-compose build

# Start the containers
docker-compose up -d

# Check health
curl http://localhost:8000/health
```

---

## Rollback Instructions

If any fix causes issues, you can rollback:

```bash
# For git-tracked files
git checkout -- src/api/main.py src/scraper/source_monitor.py

# For new files
rm -f nginx.conf
rm -rf ssl/
```

---

## Next Steps

After applying these critical fixes:

1. **Add Authentication** (See AUDIT_REPORT.md Patch 2)
2. **Add CSRF Protection** (See AUDIT_REPORT.md Patch 4)
3. **Add Rate Limiting to LLM Endpoints** (See AUDIT_REPORT.md Patch 11)
4. **Implement Proper Error Handling** (See AUDIT_REPORT.md Patch 10)

---

## Support

For questions or issues with these fixes:
- Check the full audit report: `AUDIT_REPORT.md`
- Review the detailed patches in the `patches/` directory
- Consult the security documentation: `SECURITY.md`

---

**⚠️ WARNING: Do not use Open-Omniscience in production without applying these security fixes first!**

*Generated by Vibe Code Agent - 2025-05-12*
