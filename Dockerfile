# Open Omniscience - Global Intelligence Platform for Investigative Journalism
#
# Copyright (C) 2026 Ideotion
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# For inquiries, contact: open-omniscience@ideotion.com

# Open Omniscience Dockerfile
# Multi-stage build for production deployment

# Stage 1: Build stage
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy unified requirements file
COPY configs/python/requirements.txt /app/requirements.txt

# Install Python dependencies into system site-packages
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies (curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and group for security
RUN groupadd -r appgroup && useradd -r --create-home --shell /bin/bash -g appgroup appuser

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Make sure scripts in .local are usable
ENV PATH=/home/appuser/.local/bin:$PATH

# Copy application code
COPY . .

# Change ownership to non-root user
RUN chown -R appuser:appgroup /app

# Create necessary directories
RUN mkdir -p /app/data /app/audit /app/logs /app/tmp
RUN chown -R appuser:appgroup /app/data /app/audit /app/logs /app/tmp

# Set proper permissions
RUN chmod -R 750 /app/data /app/audit /app/logs /app/tmp

# Switch to non-root user
USER appuser

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    DATABASE_URL=sqlite:////app/data/open_omniscience.db \
    TMPDIR=/app/tmp

# Security labels
LABEL maintainer="Ideotion <open-omniscience@ideotion.com>" \
      description="Open Omniscience - Global Intelligence Platform" \
      version="0.02" \
      license="GPLv3"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Default command - use module path that works with PYTHONPATH
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
