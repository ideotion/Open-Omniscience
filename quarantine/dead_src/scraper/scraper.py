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

import concurrent.futures
import csv
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import ParseResult, urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

# Configure logging using shared config
from src.utils.logging_config import setup_logging

logger = setup_logging("scraper")


class Status(Enum):
    """Status enum for download results."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


@dataclass
class DownloadResult:
    """Result of a download operation."""
    status: Status
    content: str = ""
    url: str = ""
    headers: dict[str, str] | None = None
    error: str = ""


class Scraper:
    def __init__(self, config_path: str | None = None, max_workers: int = 5) -> None:
        """
        Initialize the Scraper with configuration and settings.
        
        Args:
            config_path: Path to the sources configuration YAML file.
                        Defaults to configs/sources.yml in the repository root.
            max_workers: Maximum number of parallel threads for scraping.
        """
        # Get the absolute path to the repository root
        self.repo_root: Path = Path(__file__).parent.parent.parent.resolve()
        
        # Use dynamic path for config
        if config_path is None:
            config_path = str(self.repo_root / "configs" / "sources.yml")
        
        try:
            with open(config_path) as f:
                self.sources: list[dict[str, Any]] = yaml.safe_load(f)["sources"]
        except FileNotFoundError:
            logger.error(f"Config file not found at {config_path}")
            self.sources: list[dict[str, Any]] = []
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in config file: {e}")
            self.sources: list[dict[str, Any]] = []
        
        # Use dynamic path for audit log
        self.audit_dir: Path = self.repo_root / "audit"
        self.audit_dir.mkdir(exist_ok=True, parents=True)
        self.audit_log: Path = self.audit_dir / "scrape_log.csv"
        self.error_log: Path = self.audit_dir / "errors.log"
        self._init_audit_log()
        self.session: requests.Session = requests.Session()
        self.session.headers.update({"User-Agent": "OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)"})
        self.max_workers: int = max_workers  # Number of parallel threads

    def _init_audit_log(self) -> None:
        """Initialize the audit log CSV file with headers if it doesn't exist."""
        if not self.audit_log.exists():
            with open(self.audit_log, "w", newline="") as f:
                writer: csv.Writer = csv.writer(f)
                writer.writerow(["Timestamp", "URL", "Source", "Status", "Rate_Limit_ms", "Retries"])

    def _log_error(self, error_msg: str) -> None:
        """Log an error message to the error log file."""
        with open(self.error_log, "a") as f:
            f.write(f"{datetime.now(UTC).isoformat() + 'Z'}, {error_msg}\n")

    def _get_domain(self, source: dict[str, Any]) -> str:
        """
        Extract domain from source config, handling both 'domain' and 'url' fields.
        
        Args:
            source: Source configuration dictionary.
            
        Returns:
            The domain name as a string, or empty string if not found.
        """
        if "domain" in source:
            return str(source["domain"])
        elif "url" in source:
            # Extract domain from URL
            parsed: ParseResult = urlparse(source["url"])
            return parsed.netloc
        else:
            logger.warning(f"Source {source.get('name', 'unknown')} has no domain or url field")
            return ""

    def _get_rate_limit(self, source: dict[str, Any]) -> int:
        """
        Get rate limit from source config, with default fallback.
        
        Args:
            source: Source configuration dictionary.
            
        Returns:
            Rate limit in milliseconds.
        """
        return source.get("rate_limit_ms", source.get("scan_config", {}).get("frequency_ms", 2000))

    def _is_enabled(self, source: dict[str, Any]) -> bool:
        """
        Check if source is enabled, with default fallback.
        
        Args:
            source: Source configuration dictionary.
            
        Returns:
            True if source is enabled, False otherwise.
        """
        return source.get("enabled", source.get("scan_config", {}).get("enabled", True))

    def _can_scrape(self, url: str) -> bool:
        """
        Check if a URL can be scraped according to robots.txt.
        
        Args:
            url: The URL to check.
            
        Returns:
            True if scraping is allowed, False otherwise.
        """
        rp: RobotFileParser = RobotFileParser()
        domain: str = urlparse(url).netloc
        rp.set_url(f"https://{domain}/robots.txt")
        try:
            rp.read()
            return rp.can_fetch("OpenOmniscience/1.0", url)
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt for {domain}: {e}")
            return True  # Assume allowed if robots.txt is unreachable

    def _retry_request(self, url: str, max_retries: int = 3, initial_delay: float = 1) -> requests.Response | None:
        """
        Retry a request with exponential backoff.
        
        Args:
            url: The URL to request.
            max_retries: Maximum number of retry attempts.
            initial_delay: Initial delay in seconds between retries.
            
        Returns:
            The response object if successful, None otherwise.
            
        Raises:
            requests.exceptions.RequestException: If all retries fail.
        """
        for retry in range(max_retries):
            try:
                response: requests.Response = self.session.get(url, timeout=10)
                return response
            except requests.exceptions.RequestException as e:
                if retry == max_retries - 1:
                    raise e
                delay: float = initial_delay * (2 ** retry)
                logger.warning(f"Retry {retry + 1}/{max_retries} for {url} after {delay}s. Error: {e}")
                time.sleep(delay)
        return None

    def download_page(self, url: str) -> DownloadResult:
        """
        Download a single page from a URL.
        
        This method is used by the pipeline to ingest data from URLs.
        
        Args:
            url: URL to download.
            
        Returns:
            DownloadResult object with status, content, and metadata.
        """
        # Check robots.txt first
        if not self._can_scrape(url):
            return DownloadResult(
                status=Status.BLOCKED,
                url=url,
                error="Blocked by robots.txt"
            )
        
        try:
            response: requests.Response | None = self._retry_request(url)
            if response and response.status_code == 200:
                return DownloadResult(
                    status=Status.SUCCESS,
                    content=response.text,
                    url=url,
                    headers=dict(response.headers) if response.headers else None
                )
            else:
                return DownloadResult(
                    status=Status.FAILED,
                    url=url,
                    error=f"HTTP {response.status_code if response else 'N/A'}"
                )
        except Exception as e:
            return DownloadResult(
                status=Status.FAILED,
                url=url,
                error=str(e)
            )

    def _parse_rss(self, rss_url, source_name):
        """Parse an RSS feed and return articles."""
        try:
            response = self._retry_request(rss_url)
            if response and response.status_code == 200:
                feed = feedparser.parse(response.content)
                articles = []
                for entry in feed.entries:
                    # Extract or default values
                    title = entry.get("title", "No Title")
                    content = entry.get("description", "") or entry.get("summary", "") or "No Content"
                    published_at = entry.get("published", datetime.now(UTC).isoformat())
                    url = entry.get("link", rss_url)

                    # Clean content: remove HTML tags if present
                    if "<" in content and ">" in content:
                        content = BeautifulSoup(content, "html.parser").get_text(separator=" ", strip=True)

                    articles.append({
                        "url": url,
                        "title": title,
                        "content": content,
                        "published_at": published_at,
                        "language": entry.get("language", "en"),
                        "source": source_name
                    })
                logger.info(f"Parsed {len(articles)} articles from RSS feed: {source_name}")
                return articles
            else:
                logger.warning(f"Failed to fetch RSS feed for {source_name}: {rss_url}")
                return []
        except Exception as e:
            logger.error(f"Error parsing RSS feed for {source_name}: {e}")
            self._log_error(f"RSS parsing error for {source_name}: {e}")
            return []

    def _parse_html(self, domain_url, source_name):
        """Parse HTML content and return articles."""
        try:
            response = self._retry_request(domain_url)
            if response and response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                articles = []

                # Example: Extract articles from common news site structures
                for article in soup.select("article, .article, .post, .news-item"):
                    title_element = article.select_one("h1, h2, h3, .title, .headline")
                    title = title_element.text.strip() if title_element else "No Title"

                    content_element = article.select_one(".content, .body, .text, [itemprop='articleBody']")
                    content = content_element.get_text(separator=" ", strip=True) if content_element else "No Content"

                    # Try to extract publication date
                    time_element = article.select_one("time, .date, .published")
                    published_at = time_element.get("datetime") if time_element and time_element.has_attr("datetime") else datetime.now(UTC).isoformat()

                    # Try to extract language from HTML lang attribute or meta
                    language = soup.html.get("lang", "en") if soup.html else "en"

                    # Try to extract URL
                    link_element = article.select_one("a[href]")
                    url = link_element["href"] if link_element else domain_url
                    if not url.startswith(("http://", "https://")):
                        url = f"https://{urlparse(domain_url).netloc}{url}"

                    if content:  # Only add if content is not empty
                        articles.append({
                            "url": url,
                            "title": title,
                            "content": content,
                            "published_at": published_at,
                            "language": language,
                            "source": source_name
                        })

                logger.info(f"Parsed {len(articles)} articles from HTML: {source_name}")
                return articles
            else:
                logger.warning(f"Failed to fetch HTML for {source_name}: {domain_url}")
                return []
        except Exception as e:
            logger.error(f"Error parsing HTML for {source_name}: {e}")
            self._log_error(f"HTML parsing error for {source_name}: {e}")
            return []

    def scrape_source(self, source):
        if not self._is_enabled(source):
            logger.info(f"Skipping disabled source: {source.get('name', 'unknown')}")
            return []

        domain = self._get_domain(source)
        if not domain:
            logger.warning(f"Skipping source {source.get('name', 'unknown')}: no valid domain")
            return []

        source_name = source.get("name", "unknown")
        domain_url = f"https://{domain}"
        rss_url = source.get("rss_url", "")

        if not self._can_scrape(domain_url):
            self.log_request(domain_url, source_name, "BLOCKED_BY_ROBOTS", self._get_rate_limit(source))
            logger.warning(f"Scraping blocked by robots.txt for {source_name}")
            return []

        # Try RSS first if available
        if rss_url:
            articles = self._parse_rss(rss_url, source_name)
            if articles:
                self.log_request(rss_url, source_name, "SUCCESS_RSS", self._get_rate_limit(source))
                time.sleep(self._get_rate_limit(source) / 1000)  # Rate limiting
                return articles

        # Fallback to HTML scraping
        articles = self._parse_html(domain_url, source_name)
        self.log_request(domain_url, source_name, "SUCCESS_HTML" if articles else "NO_ARTICLES", self._get_rate_limit(source))
        time.sleep(self._get_rate_limit(source) / 1000)  # Rate limiting
        return articles

    def log_request(self, url, source, status, rate_limit_ms, retries=0):
        with open(self.audit_log, "a") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now(UTC).isoformat() + "Z",
                url,
                source,
                status,
                rate_limit_ms,
                retries
            ])

    def scrape_all_sources(self):
        """Scrape all sources in parallel using ThreadPoolExecutor."""
        all_articles = []
        enabled_sources = [s for s in self.sources if self._is_enabled(s)]

        # Sort sources by priority (lower priority first)
        enabled_sources.sort(key=lambda x: x.get("priority", 2))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_source = {
                executor.submit(self.scrape_source, source): source
                for source in enabled_sources
            }

            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    articles = future.result()
                    all_articles.extend(articles)
                except Exception as e:
                    source_name = source.get("name", "unknown")
                    logger.error(f"Error scraping {source_name}: {e}")
                    self._log_error(f"Scraping error for {source_name}: {e}")

        return all_articles


if __name__ == "__main__":
    scraper = Scraper(max_workers=5)
    articles = scraper.scrape_all_sources()
    logger.info(f"Total articles scraped: {len(articles)}")