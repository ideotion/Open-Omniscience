import requests
from bs4 import BeautifulSoup
import yaml
import csv
from urllib.robotparser import RobotFileParser
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime
import time
import logging
import sys

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging using shared config
from utils.logging_config import setup_logging
logger = setup_logging("scraper")


class Scraper:
    def __init__(self, config_path=None):
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
        self._init_audit_log()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "OpenOmniscience/1.0"})

    def _init_audit_log(self):
        self.audit_log.parent.mkdir(exist_ok=True, parents=True)
        if not self.audit_log.exists():
            with open(self.audit_log, "w") as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "URL", "Source", "Status", "Rate_Limit_ms"])

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

    def scrape_source(self, source):
        if not self._is_enabled(source):
            logger.info(f"Skipping disabled source: {source.get('name', 'unknown')}")
            return []

        domain = self._get_domain(source)
        if not domain:
            logger.warning(f"Skipping source {source.get('name', 'unknown')}: no valid domain")
            return []
            
        domain_url = f"https://{domain}"
        if not self._can_scrape(domain_url):
            self.log_request(domain_url, source.get("name", "unknown"), "BLOCKED_BY_ROBOTS", self._get_rate_limit(source))
            logger.warning(f"Scraping blocked by robots.txt for {source.get('name', 'unknown')}")
            return []

        try:
            response = self.session.get(domain_url, timeout=10)
            self.log_request(response.url, source.get("name", "unknown"), response.status_code, self._get_rate_limit(source))
            time.sleep(self._get_rate_limit(source) / 1000)  # Rate limiting

            soup = BeautifulSoup(response.text, "html.parser")
            articles = []

            # Example: Extract articles from common news site structures
            # This is a generic approach; you may need to customize for specific sources
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

                if content:  # Only add if content is not empty
                    articles.append({
                        "url": response.url,
                        "title": title,
                        "content": content,
                        "published_at": published_at,
                        "language": language,
                        "source": source.get("name", "unknown")
                    })

            logger.info(f"Scraped {len(articles)} articles from {source.get('name', 'unknown')}")
            return articles

        except requests.exceptions.RequestException as e:
            self.log_request(domain_url, source.get("name", "unknown"), f"ERROR: {str(e)}", self._get_rate_limit(source))
            logger.error(f"Error scraping {source.get('name', 'unknown')}: {e}")
            return []

    def log_request(self, url, source, status, rate_limit_ms):
        self.audit_log.parent.mkdir(exist_ok=True, parents=True)
        with open(self.audit_log, "a") as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.utcnow().isoformat() + "Z",
                url,
                source,
                status,
                rate_limit_ms
            ])

    def scrape_all_sources(self):
        all_articles = []
        for source in self.sources:
            if self._is_enabled(source):
                articles = self.scrape_source(source)
                all_articles.extend(articles)
        return all_articles


if __name__ == "__main__":
    scraper = Scraper()
    articles = scraper.scrape_all_sources()
    logger.info(f"Total articles scraped: {len(articles)}")