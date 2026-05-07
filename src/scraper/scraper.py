import requests
from bs4 import BeautifulSoup
import yaml
import csv
import feedparser
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime
import time
import logging
import sys
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging using shared config
from utils.logging_config import setup_logging
logger = setup_logging("scraper")


class Scraper:
    def __init__(self, config_path=None, max_workers=5):
        # Use dynamic path for config
        if config_path is None:
            config_path = Path(__file__).parent.parent / "configs" / "sources.yml"

        try:
            with open(config_path, "r") as f:
                self.sources = yaml.safe_load(f)["sources"]
        except FileNotFoundError:
            logger.error(f"Config file not found at {config_path}")
            self.sources = []
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in config file: {e}")
            self.sources = []

        # Use dynamic path for audit log
        self.audit_log = Path(__file__).parent.parent / "audit" / "scrape_log.csv"
        self.error_log = Path(__file__).parent.parent / "audit" / "errors.log"
        self._init_audit_log()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "OpenOmniscience/1.0"})
        self.max_workers = max_workers  # Number of parallel threads

    def _init_audit_log(self):
        self.audit_log.parent.mkdir(exist_ok=True, parents=True)
        if not self.audit_log.exists():
            with open(self.audit_log, "w") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "URL", "Source", "Status", "Rate_Limit_ms", "Retries"])

    def _log_error(self, error_msg):
        self.error_log.parent.mkdir(exist_ok=True, parents=True)
        with open(self.error_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat() + 'Z'}, {error_msg}\n")

    def _get_domain(self, source):
        """Extract domain from source config, handling both 'domain' and 'url' fields."""
        if "domain" in source:
            return source["domain"]
        elif "url" in source:
            # Extract domain from URL
            parsed = urlparse(source["url"])
            return parsed.netloc
        else:
            logger.warning(f"Source {source.get('name', 'unknown')} has no domain or url field")
            return ""

    def _get_rate_limit(self, source):
        """Get rate limit from source config, with default fallback."""
        return source.get("rate_limit_ms", source.get("scan_config", {}).get("frequency_ms", 2000))

    def _is_enabled(self, source):
        """Check if source is enabled, with default fallback."""
        return source.get("enabled", source.get("scan_config", {}).get("enabled", True))

    def _can_scrape(self, url):
        rp = RobotFileParser()
        domain = urlparse(url).netloc
        rp.set_url(f"https://{domain}/robots.txt")
        try:
            rp.read()
            return rp.can_fetch("OpenOmniscience/1.0", url)
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt for {domain}: {e}")
            return True  # Assume allowed if robots.txt is unreachable

    def _retry_request(self, url, max_retries=3, initial_delay=1):
        """Retry a request with exponential backoff."""
        for retry in range(max_retries):
            try:
                response = self.session.get(url, timeout=10)
                return response
            except requests.exceptions.RequestException as e:
                if retry == max_retries - 1:
                    raise e
                delay = initial_delay * (2 ** retry)
                logger.warning(f"Retry {retry + 1}/{max_retries} for {url} after {delay}s. Error: {e}")
                time.sleep(delay)
        return None

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
                    published_at = entry.get("published", datetime.utcnow().isoformat())
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
                    published_at = time_element.get("datetime") if time_element and time_element.has_attr("datetime") else datetime.utcnow().isoformat()

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
        self.audit_log.parent.mkdir(exist_ok=True, parents=True)
        with open(self.audit_log, "a") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat() + "Z",
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