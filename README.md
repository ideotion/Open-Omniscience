# Open-Omniscience

A local, portable article intelligence and source tracking system for investigative journalism.

## Features

- **Keyword Extraction**: Automatic extraction of important keywords from articles
- **Source Tracking**: Detect and track all links/sources referenced in articles
- **Article Similarity**: Find similar articles using multiple algorithms
- **Citation Network**: Build and visualize networks of how sources cite each other
- **Temporal Analysis**: Track relationships between article dates and source dates
- **Customizable Dashboard**: Drag-and-drop widgets with real-time updates

## Quick Start

### 1. Setup

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Run setup script
./scripts/setup.sh
```

### 2. Run the Application

```bash
# Start the backend
./scripts/run.sh
```

Then open your browser to [http://localhost:8000](http://localhost:8000)

## Project Structure

```
open-omniscience/
├── backend/          # FastAPI backend
│   ├── src/          # Source code
│   │   ├── database/ # Database models and session
│   │   ├── services/ # Core services
│   │   ├── api/      # API endpoints
│   │   └── main.py   # Application entry point
│   └── requirements.txt
│
├── frontend/         # React frontend
│   ├── src/          # Source code
│   └── package.json
│
├── data/             # Local data storage
│   ├── database.sqlite
│   ├── logs/
│   ├── scraped_content/
│   └── exports/
│
├── scripts/          # Utility scripts
│   ├── setup.sh
│   └── run.sh
│
└── README.md
```

## Local Development

### Backend

```bash
cd backend
source venv/bin/activate
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm start
```

## Configuration

Create a `.env` file in the root directory:

```env
# Backend configuration
DATABASE_URL=sqlite:///./data/database.sqlite
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

# Scraping configuration
SCRAPE_TIMEOUT=30
SCRAPE_DELAY=2
MAX_SCRAPE_RETRIES=3
```

## Data Storage

All data is stored locally in the `data/` directory:

- `database.sqlite`: SQLite database
- `logs/`: Application logs
- `scraped_content/`: Cached scraped content
- `exports/`: Exported data files

## Backup

To backup your data:

```bash
tar -czvf open_omniscience_backup_$(date +%Y%m%d_%H%M%S).tar.gz data/
```

## License

MIT License
