"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

"""
Bulk Data Import for Open Omniscience

This module provides functionality to import articles from CSV or JSON files
into the Open Omniscience database. It handles:
- Duplicate detection (via URL and content hash)
- Source matching/creation
- Batch processing

Author: Ideotion
"""

import csv
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Union

from src.database.models import Article, Source, get_session
from src.utils.url_utils import canonicalize_url, generate_content_hash

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("import.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("import")

class ArticleImporter:
    def __init__(self):
        self.session = get_session()

    def _get_or_create_source(self, source_name: str, domain: str = None, **kwargs) -> Source:
        """Get an existing source or create a new one."""
        source = self.session.query(Source).filter_by(name=source_name).first()
        if source:
            return source

        # Create new source
        source = Source(
            name=source_name,
            domain=domain or source_name.lower().replace(" ", ""),
            **kwargs
        )
        self.session.add(source)
        self.session.commit()
        logger.info(f"Created new source: {source_name}")
        return source

    def _article_exists(self, url: str, content: str) -> bool:
        """Check if an article already exists by URL or content hash."""
        canonical_url = canonicalize_url(url)
        content_hash = generate_content_hash(content)

        # Check by hash first (most reliable)
        existing = self.session.query(Article).filter_by(hash=content_hash).first()
        if existing:
            return True

        # Check by canonical URL
        existing = self.session.query(Article).filter_by(canonical_url=canonical_url).first()
        return existing is not None

    def _parse_date(self, date_str: str) -> datetime:
        """Parse a date string into a datetime object."""
        if not date_str:
            return None

        # Try common date formats
        formats = [
            "%Y-%m-%dT%H:%M:%SZ",  # ISO 8601 UTC
            "%Y-%m-%dT%H:%M:%S",   # ISO 8601 without timezone
            "%Y-%m-%d %H:%M:%S",   # Common datetime
            "%Y-%m-%d",            # Date only
            "%d/%m/%Y",           # European format
            "%m/%d/%Y",           # US format
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        logger.warning(f"Could not parse date: {date_str}")
        return None

    def import_from_csv(self, file_path: Union[str, Path], source_name: str = None) -> Dict:
        """
        Import articles from a CSV file.

        Args:
            file_path: Path to the CSV file.
            source_name: Optional source name to assign to all articles.

        Returns:
            Dictionary with import statistics.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"CSV file not found: {file_path}")

        stats = {
            "total": 0,
            "imported": 0,
            "skipped": 0,
            "errors": 0
        }

        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stats["total"] += 1
                try:
                    # Extract fields (with fallbacks)
                    url = row.get("url", row.get("URL", ""))
                    title = row.get("title", row.get("Title", "No Title"))
                    content = row.get("content", row.get("Content", ""))
                    published_at = row.get("published_at", row.get("Published At", ""))
                    language = row.get("language", row.get("Language", "en"))
                    source = row.get("source", row.get("Source", source_name or "Unknown"))

                    if not url or not content:
                        stats["skipped"] += 1
                        continue

                    # Check for duplicates
                    if self._article_exists(url, content):
                        stats["skipped"] += 1
                        continue

                    # Get or create source
                    source_obj = self._get_or_create_source(source)

                    # Create article
                    article = Article(
                        url=url,
                        canonical_url=canonicalize_url(url),
                        source_id=source_obj.id,
                        title=title,
                        content=content,
                        published_at=self._parse_date(published_at),
                        language=language,
                        hash=generate_content_hash(content)
                    )
                    self.session.add(article)
                    stats["imported"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Error importing row {stats['total']}: {e}")

        self.session.commit()
        logger.info(f"Import from CSV complete: {stats}")
        return stats

    def import_from_json(self, file_path: Union[str, Path], source_name: str = None) -> Dict:
        """
        Import articles from a JSON file.

        Args:
            file_path: Path to the JSON file.
            source_name: Optional source name to assign to all articles.

        Returns:
            Dictionary with import statistics.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"JSON file not found: {file_path}")

        stats = {
            "total": 0,
            "imported": 0,
            "skipped": 0,
            "errors": 0
        }

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

            # Handle both list of articles and nested structure
            if isinstance(data, dict):
                articles = data.get("articles", data.get("results", []))
            else:
                articles = data

            for article_data in articles:
                stats["total"] += 1
                try:
                    # Extract fields (with fallbacks)
                    url = article_data.get("url", article_data.get("URL", ""))
                    title = article_data.get("title", article_data.get("Title", "No Title"))
                    content = article_data.get("content", article_data.get("Content", ""))
                    published_at = article_data.get("published_at", article_data.get("Published At", ""))
                    language = article_data.get("language", article_data.get("Language", "en"))
                    source = article_data.get("source", article_data.get("Source", source_name or "Unknown"))

                    if not url or not content:
                        stats["skipped"] += 1
                        continue

                    # Check for duplicates
                    if self._article_exists(url, content):
                        stats["skipped"] += 1
                        continue

                    # Get or create source
                    source_obj = self._get_or_create_source(source)

                    # Create article
                    article = Article(
                        url=url,
                        canonical_url=canonicalize_url(url),
                        source_id=source_obj.id,
                        title=title,
                        content=content,
                        published_at=self._parse_date(published_at),
                        language=language,
                        hash=generate_content_hash(content)
                    )
                    self.session.add(article)
                    stats["imported"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Error importing article {stats['total']}: {e}")

        self.session.commit()
        logger.info(f"Import from JSON complete: {stats}")
        return stats

    def close(self):
        """Close the database session."""
        self.session.close()

# Command-line interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import articles into Open Omniscience")
    parser.add_argument("file", help="Path to CSV or JSON file to import")
    parser.add_argument("--source", help="Source name to assign to all articles", default=None)
    parser.add_argument("--type", choices=["csv", "json"], help="File type (auto-detected if not specified)")

    args = parser.parse_args()

    importer = ArticleImporter()
    try:
        if args.type == "csv" or (not args.type and args.file.endswith(".csv")):
            stats = importer.import_from_csv(args.file, args.source)
        else:
            stats = importer.import_from_json(args.file, args.source)

        print(f"Import complete: {stats}")
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise
    finally:
        importer.close()