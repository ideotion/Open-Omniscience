"""
Pillar 1: Data Ingestion - HTTrack Python Wrapper

Provides a Python interface to the HTTrack C library for web scraping and data collection.
This wrapper enables Python code to use HTTrack's powerful web crawling capabilities.
"""

import os
import sys
import ctypes
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set, Tuple
from enum import Enum
import logging
from urllib.parse import urlparse
import tempfile
import shutil


class HTTrackStatus(Enum):
    SUCCESS = 0
    ERROR = 1
    WARNING = 2
    RUNNING = 3
    PAUSED = 4


class HTTrackLogLevel(Enum):
    QUIET = 0
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4


@dataclass
class HTTrackConfig:
    """Configuration for HTTrack."""
    # Basic settings
    base_path: str = tempfile.mkdtemp(prefix="httrack_")
    project_name: str = "open_omniscience"
    
    # URL settings
    urls: List[str] = field(default_factory=list)
    depth: int = 3
    max_pages: int = 1000
    
    # Connection settings
    connection_timeout: int = 30
    max_connections: int = 8
    retry_count: int = 3
    
    # User agent and headers
    user_agent: str = "OpenOmniscience/1.0"
    accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    accept_language: str = "en-US,en;q=0.5"
    
    # Filtering
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)
    
    # Robots.txt
    respect_robots_txt: bool = True
    
    # Rate limiting
    delay: float = 1.0  # seconds between requests
    
    # Logging
    log_level: HTTrackLogLevel = HTTrackLogLevel.INFO
    log_file: Optional[str] = None
    
    # Proxy
    use_proxy: bool = False
    proxy_host: str = ""
    proxy_port: int = 8080
    
    # Authentication
    auth_username: str = ""
    auth_password: str = ""
    
    # SSL
    verify_ssl: bool = True
    
    # Cleanup
    cleanup_on_exit: bool = True


@dataclass
class HTTrackResult:
    """Result of an HTTrack operation."""
    status: HTTrackStatus
    message: str
    pages_downloaded: int = 0
    files_downloaded: int = 0
    bytes_downloaded: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class HTTrackWrapper:
    """
    Python wrapper for HTTrack C library.
    
    This class provides a Python interface to HTTrack's web crawling functionality,
    allowing for integration with the Open-Omniscience pipeline.
    """

    def __init__(self, config: Optional[HTTrackConfig] = None):
        """
        Initialize the HTTrack wrapper.
        
        Args:
            config: HTTrack configuration (defaults to standard settings).
        """
        self.config = config if config else HTTrackConfig()
        self.logger = logging.getLogger("HTTrackWrapper")
        self._lib = None
        self._initialized = False
        self._load_library()

    def _load_library(self) -> bool:
        """Load the HTTrack C library."""
        try:
            # Try to load the HTTrack library
            # On Linux, it's typically libhttrack.so
            # On Windows, it's httrack.dll
            # On macOS, it's libhttrack.dylib
            
            lib_names = [
                "libhttrack.so",
                "libhttrack.so.2",
                "httrack.dll",
                "libhttrack.dylib",
            ]
            
            for lib_name in lib_names:
                try:
                    self._lib = ctypes.CDLL(lib_name)
                    self.logger.info(f"Loaded HTTrack library: {lib_name}")
                    return True
                except OSError:
                    continue
            
            # If we get here, we didn't find the library
            self.logger.error("Could not load HTTrack library. Please ensure HTTrack is installed.")
            return False
            
        except Exception as e:
            self.logger.error(f"Error loading HTTrack library: {e}")
            return False

    def _initialize(self) -> bool:
        """Initialize HTTrack."""
        if self._lib is None:
            return False
        
        if self._initialized:
            return True
        
        try:
            # Initialize HTTrack
            # This is a placeholder - actual HTTrack C API calls would go here
            # The HTTrack C API is not well-documented, so this is a simplified interface
            
            # For now, we'll use the command-line interface via subprocess
            # In a production implementation, we would use the C API directly
            self._initialized = True
            self.logger.info("HTTrack initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Error initializing HTTrack: {e}")
            return False

    def _cleanup(self) -> None:
        """Clean up HTTrack resources."""
        if self.config.cleanup_on_exit and os.path.exists(self.config.base_path):
            try:
                shutil.rmtree(self.config.base_path)
                self.logger.info(f"Cleaned up HTTrack directory: {self.config.base_path}")
            except Exception as e:
                self.logger.error(f"Error cleaning up HTTrack directory: {e}")
        
        self._initialized = False

    def __enter__(self):
        """Context manager entry."""
        self._initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self._cleanup()

    def crawl(self, urls: Optional[List[str]] = None) -> HTTrackResult:
        """
        Crawl one or more URLs using HTTrack.
        
        Args:
            urls: List of URLs to crawl (overrides config.urls if provided).
        
        Returns:
            HTTrackResult with the crawl outcome.
        """
        start_time = time.time()
        
        if urls:
            self.config.urls = urls
        
        if not self.config.urls:
            return HTTrackResult(
                status=HTTrackStatus.ERROR,
                message="No URLs specified for crawling",
                start_time=start_time,
                end_time=time.time(),
            )
        
        # Validate URLs
        valid_urls = []
        for url in self.config.urls:
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                valid_urls.append(url)
            else:
                self.logger.warning(f"Invalid URL: {url}")
        
        if not valid_urls:
            return HTTrackResult(
                status=HTTrackStatus.ERROR,
                message="No valid URLs to crawl",
                start_time=start_time,
                end_time=time.time(),
            )
        
        # Create a temporary directory for this crawl
        crawl_dir = tempfile.mkdtemp(dir=self.config.base_path, prefix="crawl_")
        
        try:
            # Build HTTrack command
            cmd = self._build_command(crawl_dir, valid_urls)
            
            # Execute HTTrack
            result = self._execute_command(cmd, crawl_dir)
            
            # Process results
            result.start_time = start_time
            result.end_time = time.time()
            
            return result
            
        except Exception as e:
            self.logger.error(f"Error during crawl: {e}")
            return HTTrackResult(
                status=HTTrackStatus.ERROR,
                message=str(e),
                start_time=start_time,
                end_time=time.time(),
            )
        finally:
            # Clean up if requested
            if self.config.cleanup_on_exit and os.path.exists(crawl_dir):
                try:
                    shutil.rmtree(crawl_dir)
                except Exception as e:
                    self.logger.error(f"Error cleaning up crawl directory: {e}")

    def _build_command(self, output_dir: str, urls: List[str]) -> List[str]:
        """Build the HTTrack command line."""
        cmd = ["httrack"]
        
        # Add URLs
        for url in urls:
            cmd.extend([url, "+*." + urlparse(url).netloc + "/*"])
        
        # Add output directory
        cmd.extend(["-O", output_dir, "--path", self.config.project_name])
        
        # Add depth
        cmd.extend(["-%v", f"depth={self.config.depth}"])
        
        # Add max pages
        cmd.extend(["--max-pages", str(self.config.max_pages)])
        
        # Add connection settings
        cmd.extend(["--connection-per-second", str(int(1.0 / self.config.delay))])
        cmd.extend(["--max-rate", str(self.config.max_connections)])
        
        # Add user agent
        cmd.extend(["--user-agent", self.config.user_agent])
        
        # Add headers
        cmd.extend(["--header", f"Accept: {self.config.accept}"])
        cmd.extend(["--header", f"Accept-Language: {self.config.accept_language}"])
        
        # Add robots.txt setting
        if self.config.respect_robots_txt:
            cmd.append("--robots=0")  # 0 = respect robots.txt
        else:
            cmd.append("--robots=1")  # 1 = ignore robots.txt
        
        # Add include patterns
        for pattern in self.config.include_patterns:
            cmd.extend(["+" + pattern])
        
        # Add exclude patterns
        for pattern in self.config.exclude_patterns:
            cmd.extend(["-" + pattern])
        
        # Add connection timeout
        cmd.extend(["--timeout", str(self.config.connection_timeout)])
        
        # Add retry count
        cmd.extend(["--retry", str(self.config.retry_count)])
        
        # Add SSL verification
        if not self.config.verify_ssl:
            cmd.append("--ssl=0")
        
        # Add logging
        if self.config.log_level == HTTrackLogLevel.QUIET:
            cmd.append("-q")
        elif self.config.log_level == HTTrackLogLevel.ERROR:
            cmd.extend(["-v", "0"])
        elif self.config.log_level == HTTrackLogLevel.WARNING:
            cmd.extend(["-v", "1"])
        elif self.config.log_level == HTTrackLogLevel.INFO:
            cmd.extend(["-v", "2"])
        elif self.config.log_level == HTTrackLogLevel.DEBUG:
            cmd.extend(["-v", "3"])
        
        # Add log file if specified
        if self.config.log_file:
            cmd.extend(["--logfile", self.config.log_file])
        
        # Add proxy if specified
        if self.config.use_proxy and self.config.proxy_host:
            cmd.extend(["--proxy", f"{self.config.proxy_host}:{self.config.proxy_port}"])
        
        # Add authentication if specified
        if self.config.auth_username and self.config.auth_password:
            cmd.extend([
                "--username", self.config.auth_username,
                "--password", self.config.auth_password
            ])
        
        return cmd

    def _execute_command(self, cmd: List[str], output_dir: str) -> HTTrackResult:
        """Execute the HTTrack command."""
        import subprocess
        
        result = HTTrackResult(
            status=HTTrackStatus.RUNNING,
            message="Crawl in progress",
            start_time=time.time(),
        )
        
        try:
            # Run the command
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=output_dir,
            )
            
            # Wait for completion
            stdout, stderr = process.communicate()
            
            # Parse output
            if process.returncode == 0:
                result.status = HTTrackStatus.SUCCESS
                result.message = "Crawl completed successfully"
            else:
                result.status = HTTrackStatus.ERROR
                result.message = f"Crawl failed with return code {process.returncode}"
            
            # Parse HTTrack output for statistics
            result = self._parse_output(stdout, stderr, result)
            
            return result
            
        except subprocess.TimeoutExpired:
            result.status = HTTrackStatus.ERROR
            result.message = "Crawl timed out"
            return result
        except Exception as e:
            result.status = HTTrackStatus.ERROR
            result.message = str(e)
            return result

    def _parse_output(self, stdout: str, stderr: str, result: HTTrackResult) -> HTTrackResult:
        """Parse HTTrack output to extract statistics."""
        # HTTrack outputs statistics at the end
        # Example: "12345678 bytes received in 123.45 seconds (123.45 KB/s)"
        # Example: "123 links scanned, 456 files written"
        
        lines = (stdout + "\n" + stderr).split('\n')
        
        for line in lines:
            line = line.strip()
            
            # Parse bytes received
            if "bytes received" in line:
                parts = line.split()
                for part in parts:
                    if part.isdigit():
                        result.bytes_downloaded = int(part)
                        break
            
            # Parse files written
            if "files written" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "files" and i > 0:
                        try:
                            result.files_downloaded = int(parts[i-1])
                        except ValueError:
                            pass
            
            # Parse links scanned
            if "links scanned" in line:
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == "links" and i > 0:
                        try:
                            result.pages_downloaded = int(parts[i-1])
                        except ValueError:
                            pass
            
            # Parse errors
            if "error" in line.lower() or "failed" in line.lower():
                result.errors.append(line)
            
            # Parse warnings
            if "warning" in line.lower():
                result.warnings.append(line)
        
        return result

    def download_page(self, url: str) -> HTTrackResult:
        """
        Download a single page.
        
        Args:
            url: URL to download.
        
        Returns:
            HTTrackResult with the download outcome.
        """
        return self.crawl([url])

    def download_site(self, url: str, depth: Optional[int] = None) -> HTTrackResult:
        """
        Download an entire site.
        
        Args:
            url: Base URL of the site.
            depth: Crawl depth (defaults to config.depth).
        
        Returns:
            HTTrackResult with the download outcome.
        """
        if depth is not None:
            original_depth = self.config.depth
            self.config.depth = depth
        
        try:
            result = self.crawl([url])
            return result
        finally:
            if depth is not None:
                self.config.depth = original_depth

    def get_downloaded_files(self, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get a list of downloaded files.
        
        Args:
            output_dir: Directory to scan (defaults to config.base_path).
        
        Returns:
            List of file information dictionaries.
        """
        if output_dir is None:
            output_dir = self.config.base_path
        
        files = []
        
        if os.path.exists(output_dir):
            for root, dirs, filenames in os.walk(output_dir):
                for filename in filenames:
                    filepath = os.path.join(root, filename)
                    try:
                        stat = os.stat(filepath)
                        files.append({
                            "path": filepath,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                            "is_html": filename.endswith(".html") or filename.endswith(".htm"),
                            "is_image": filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")),
                            "is_css": filename.endswith(".css"),
                            "is_js": filename.endswith(".js"),
                        })
                    except OSError:
                        continue
        
        return files

    def get_page_content(self, url: str) -> Optional[str]:
        """
        Get the content of a specific page.
        
        Args:
            url: URL of the page.
        
        Returns:
            Page content as string, or None if not found.
        """
        # First, crawl the page
        result = self.download_page(url)
        
        if result.status != HTTrackStatus.SUCCESS:
            return None
        
        # Find the downloaded file
        files = self.get_downloaded_files()
        for file_info in files:
            if file_info["is_html"]:
                try:
                    with open(file_info["path"], 'r', encoding='utf-8') as f:
                        return f.read()
                except (UnicodeDecodeError, OSError):
                    try:
                        with open(file_info["path"], 'r', encoding='latin-1') as f:
                            return f.read()
                    except OSError:
                        continue
        
        return None

    def extract_links(self, url: str) -> List[str]:
        """
        Extract all links from a page.
        
        Args:
            url: URL of the page.
        
        Returns:
            List of absolute URLs found on the page.
        """
        from bs4 import BeautifulSoup
        
        content = self.get_page_content(url)
        if not content:
            return []
        
        try:
            soup = BeautifulSoup(content, 'html.parser')
            links = []
            
            for tag in soup.find_all(['a', 'link']):
                href = tag.get('href')
                if href:
                    # Make absolute URL
                    absolute_url = self._make_absolute_url(url, href)
                    if absolute_url:
                        links.append(absolute_url)
            
            return list(set(links))  # Remove duplicates
            
        except Exception as e:
            self.logger.error(f"Error extracting links: {e}")
            return []

    def _make_absolute_url(self, base_url: str, relative_url: str) -> Optional[str]:
        """Convert a relative URL to an absolute URL."""
        from urllib.parse import urljoin
        
        try:
            return urljoin(base_url, relative_url)
        except Exception:
            return None

    def get_config(self) -> HTTrackConfig:
        """Get the current configuration."""
        return self.config

    def set_config(self, config: HTTrackConfig) -> None:
        """Set the configuration."""
        self.config = config

    def cleanup(self) -> None:
        """Clean up all HTTrack resources."""
        self._cleanup()

    def __del__(self):
        """Destructor."""
        self.cleanup()


# Convenience function for simple crawling
def crawl_urls(
    urls: List[str],
    depth: int = 3,
    max_pages: int = 1000,
    delay: float = 1.0,
    respect_robots_txt: bool = True,
) -> HTTrackResult:
    """
    Simple function to crawl a list of URLs.
    
    Args:
        urls: List of URLs to crawl.
        depth: Crawl depth.
        max_pages: Maximum number of pages to download.
        delay: Delay between requests in seconds.
        respect_robots_txt: Whether to respect robots.txt.
    
    Returns:
        HTTrackResult with the crawl outcome.
    """
    config = HTTrackConfig(
        urls=urls,
        depth=depth,
        max_pages=max_pages,
        delay=delay,
        respect_robots_txt=respect_robots_txt,
        cleanup_on_exit=True,
    )
    
    with HTTrackWrapper(config) as crawler:
        return crawler.crawl()
