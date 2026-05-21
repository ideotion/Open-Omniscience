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

# Open Omniscience Makefile
# Provides convenient commands for development, testing, and deployment

.PHONY: help install test lint format run clean docker-build docker-run docker-down desktop-launcher-install desktop-launcher-uninstall

# Default target
help:
	@echo "Open Omniscience - Makefile Commands"
	@echo "====================================="
	@echo ""
	@echo "Development:"
	@echo "  make install          - Install Python dependencies"
	@echo "  make install-dev      - Install development dependencies"
	@echo "  make run              - Run the application"
	@echo "  make run-dev          - Run with auto-reload for development"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint             - Run all linting and type checking"
	@echo "  make format           - Format code with black and isort"
	@echo "  make lint-black       - Check Black formatting"
	@echo "  make lint-isort       - Check import sorting"
	@echo "  make lint-flake8      - Run flake8 linting"
	@echo "  make lint-mypy        - Run mypy type checking"
	@echo "  make quality-check     - Run comprehensive quality checks"
	@echo "  make pre-commit-install - Install pre-commit hooks"
	@echo "  make pre-commit-run   - Run pre-commit hooks on all files"
	@echo "  make install-hooks    - Install and update pre-commit hooks"
	@echo ""
	@echo "Testing:"
	@echo "  make test             - Run all tests"
	@echo "  make test-quick       - Run tests without slow tests"
	@echo ""
	@echo "Database:"
	@echo "  make db-init          - Initialize the database"
	@echo "  make db-migrate       - Run database migrations"
	@echo "  make db-reset          - Reset the database (WARNING: deletes data)"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     - Build Docker image"
	@echo "  make docker-run       - Run with Docker"
	@echo "  make docker-down      - Stop Docker containers"
	@echo "  make docker-clean     - Remove Docker containers and volumes"
	@echo ""
	@echo "Packages:"
	@echo "  make package-appimage - Build AppImage package"
	@echo "  make package-deb      - Build Debian package"
	@echo "  make package-all      - Build all packages"
	@echo "  make package-clean    - Clean package build files"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean            - Remove Python cache and temporary files"
	@echo "  make clean-all        - Full cleanup (includes Docker)"
	@echo ""
	@echo "Scraping:"
	@echo "  make scrape           - Run the scraper"
	@echo "  make scrape-all       - Scrape all sources"
	@echo "  make ingest           - Run the ingestion pipeline"
	@echo ""
	@echo "Desktop Launcher:"
	@echo "  make desktop-launcher-install   - Install desktop launcher to user's desktop"
	@echo "  make desktop-launcher-uninstall - Remove desktop launcher from user's desktop"

# Python environment
PYTHON ?= python3
PIP ?= pip3
UVICORN ?= uvicorn

# Directories
SRC_DIR ?= src
DATA_DIR ?= data
AUDIT_DIR ?= audit
LOGS_DIR ?= logs

# Create directories
init-dirs:
	mkdir -p $(DATA_DIR) $(AUDIT_DIR) $(LOGS_DIR)

# Install all dependencies from unified requirements.txt
install:
	$(PIP) install -r requirements.txt

# Install all dependencies (alias for install)
install-all:
	$(PIP) install -r requirements.txt

# Run the application
run:
	$(UVICORN) $(SRC_DIR).api.main:app --host 0.0.0.0 --port 8000

run-dev:
	$(UVICORN) $(SRC_DIR).api.main:app --host 0.0.0.0 --port 8000 --reload

# Run tests
test:
	$(PYTHON) -m pytest tests/ -v

test-quick:
	$(PYTHON) -m pytest tests/ -v -m "not slow"

# Linting and type checking
lint:
	$(PYTHON) -m pip install -q black isort flake8 mypy
	@echo "Running code style checks..."
	black --check $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/ || echo "❌ Black formatting issues found"
	isort --check-only $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/ || echo "❌ Import sorting issues found"
	flake8 $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/ || echo "❌ Linting issues found"
	mypy $(SRC_DIR)/ pillar2/ pillar3/ pillar4/ || echo "❌ Type checking issues found"

# Code formatting
format:
	@echo "Formatting code with black and isort..."
	black $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/
	isort $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/

# Individual quality checks
lint-black:
	@echo "Checking Black formatting..."
	black --check $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/

lint-isort:
	@echo "Checking import sorting..."
	isort --check-only $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/

lint-flake8:
	@echo "Running flake8..."
	flake8 $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/

lint-mypy:
	@echo "Running mypy type checking..."
	mypy $(SRC_DIR)/ pillar2/ pillar3/ pillar4/

# Pre-commit setup
pre-commit-install:
	@echo "Installing pre-commit hooks..."
	$(PIP) install -q pre-commit
	pre-commit install

pre-commit-run:
	@echo "Running pre-commit hooks on all files..."
	pre-commit run --all-files

# Code quality metrics
quality-check:
	@echo "Running comprehensive code quality checks..."
	@echo "=== Black ==="
	black --check $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/ 2>/dev/null || echo "Black: FAILED"
	@echo "=== isort ==="
	isort --check-only $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/ 2>/dev/null || echo "isort: FAILED"
	@echo "=== flake8 ==="
	flake8 $(SRC_DIR)/ tests/ pillar2/ pillar3/ pillar4/ 2>/dev/null || echo "flake8: FAILED"
	@echo "=== mypy ==="
	mypy $(SRC_DIR)/ pillar2/ pillar3/ pillar4/ 2>/dev/null || echo "mypy: FAILED"
	@echo "=== Quality check complete ==="

# Install development dependencies
install-dev:
	$(PIP) install -r requirements.txt
	$(PIP) install -e ".[dev]"

# Install pre-commit hooks
install-hooks:
	$(PIP) install -q pre-commit
	pre-commit install
	pre-commit autoupdate

# Database operations
db-init:
	@echo "Initializing database..."
	$(PYTHON) -c "import sys; sys.path.insert(0, '$(SRC_DIR)'); from database.models import Base, engine; Base.metadata.create_all(engine); print('Database initialized')"

db-migrate:
	@echo "Running database migrations..."
	cd $(SRC_DIR)/database && alembic upgrade head

db-reset:
	@echo "WARNING: This will delete all data!"
	@read -p "Are you sure? (y/N) " -n 1 -r; echo; if [[ $$REPLY =~ ^[Yy]$$ ]]; then rm -f $(DATA_DIR)/*.db; $(PYTHON) -c "import sys; sys.path.insert(0, '$(SRC_DIR)'); from database.models import Base, engine; Base.metadata.create_all(engine); print('Database reset')"; fi

# Scraping operations
scrape:
	$(PYTHON) -c "import sys; sys.path.insert(0, '$(SRC_DIR)'); from scraper.scraper import Scraper; s = Scraper(max_workers=5); articles = s.scrape_all_sources(); print(f'Scraped {len(articles)} articles')"

scrape-all:
	$(PYTHON) -c "import sys; sys.path.insert(0, '$(SRC_DIR)'); from scraper.scraper import Scraper; s = Scraper(max_workers=10); articles = s.scrape_all_sources(); print(f'Scraped {len(articles)} articles')"

ingest:
	$(PYTHON) -c "import sys; sys.path.insert(0, '$(SRC_DIR)'); from ingestor.pipeline import IngestionPipeline; p = IngestionPipeline(); total = p.ingest_all_sources(); print(f'Ingested {total} articles'); p.close()"

# Docker operations
docker-build:
	docker build -t ideotion/open-omniscience .

docker-run:
	docker-compose up -d

docker-down:
	docker-compose down

docker-clean:
	docker-compose down -v
	docker system prune -f

# Cleanup
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type f -name "*~" -delete 2>/dev/null || true
	find . -type f -name "*.swp" -delete 2>/dev/null || true

clean-all: clean docker-clean
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov/

# Package building
package-appimage:
	@echo "Building AppImage..."
	chmod +x package/appimage/OpenOmniscience.AppImageBuilder
	./package/appimage/OpenOmniscience.AppImageBuilder

package-deb:
	@echo "Building Debian package..."
	chmod +x package/deb/build-deb.sh
	./package/deb/build-deb.sh

package-all: package-appimage package-deb

package-clean:
	@echo "Cleaning package build files..."
	rm -rf AppDir build-deb dist *.AppImage *.deb

# Desktop launcher installation
desktop-launcher-install:
	@echo "Installing desktop launcher..."
	chmod +x package/launcher/install-desktop-launcher.sh
	./package/launcher/install-desktop-launcher.sh install

desktop-launcher-uninstall:
	@echo "Uninstalling desktop launcher..."
	chmod +x package/launcher/install-desktop-launcher.sh
	./package/launcher/install-desktop-launcher.sh uninstall

# Default target
all: help
