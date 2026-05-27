"""
API VM module for Open-Omniscience.

This module contains the configuration and logic specific to the API VM,
which handles HTTP requests, authentication, and coordination between other VMs.
"""

import os
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

from src.qubes import get_qubes_environment, QubeInfo
from src.qubes.rpc import QubesRPCClient, RPCClientConfig


logger = logging.getLogger(__name__)


@dataclass
class APIVMConfig:
    """Configuration for the API VM."""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    log_level: str = "INFO"
    
    # Database connection (to DB VM)
    db_vm: str = "open-omniscience-db"
    db_host: str = "localhost"  # Will be mapped via Qubes
    db_port: int = 5432
    db_name: str = "open_omniscience"
    db_user: str = "omniscience"
    db_password: str = ""  # Should be set via environment
    
    # Scraper VM
    scraper_vm: str = "open-omniscience-scraper"
    
    # Rate limiting
    rate_limit: str = "100/hour"
    
    # CORS settings
    cors_origins: list = field(default_factory=lambda: ['*'])
    cors_allow_credentials: bool = True
    cors_allow_methods: list = field(default_factory=lambda: ['*'])
    cors_allow_headers: list = field(default_factory=lambda: ['*'])
    
    # Security
    secret_key: Optional[str] = None
    csrf_secret: Optional[str] = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


class APIVM:
    """
    API VM manager.
    
    This class manages the API VM functionality, including:
    - HTTP server configuration
    - Request routing to other VMs
    - Authentication and authorization
    - Rate limiting
    - Error handling
    """
    
    def __init__(self, config: Optional[APIVMConfig] = None):
        self.config = config or APIVMConfig()
        self.qubes_env = get_qubes_environment()
        self.rpc_clients: Dict[str, QubesRPCClient] = {}
        self._initialized = False
    
    def initialize(self):
        """Initialize the API VM."""
        if self._initialized:
            return
        
        logger.info("Initializing API VM")
        
        # Initialize RPC clients
        self._init_rpc_clients()
        
        # Load configuration from environment
        self._load_env_config()
        
        self._initialized = True
        logger.info("API VM initialized")
    
    def _init_rpc_clients(self):
        """Initialize RPC clients for other VMs."""
        # Database VM client
        self.rpc_clients['db'] = QubesRPCClient(
            RPCClientConfig(
                target_vm=self.config.db_vm,
                timeout=60
            )
        )
        
        # Scraper VM client
        self.rpc_clients['scraper'] = QubesRPCClient(
            RPCClientConfig(
                target_vm=self.config.scraper_vm,
                timeout=120  # Scraping can take longer
            )
        )
        
        logger.info(f"RPC clients initialized for: {list(self.rpc_clients.keys())}")
    
    def _load_env_config(self):
        """Load configuration from environment variables."""
        # Database configuration
        if 'DB_PASSWORD' in os.environ:
            self.config.db_password = os.environ['DB_PASSWORD']
        
        if 'DB_HOST' in os.environ:
            self.config.db_host = os.environ['DB_HOST']
        
        if 'DB_PORT' in os.environ:
            self.config.db_port = int(os.environ['DB_PORT'])
        
        if 'DB_NAME' in os.environ:
            self.config.db_name = os.environ['DB_NAME']
        
        if 'DB_USER' in os.environ:
            self.config.db_user = os.environ['DB_USER']
        
        # API configuration
        if 'API_HOST' in os.environ:
            self.config.host = os.environ['API_HOST']
        
        if 'API_PORT' in os.environ:
            self.config.port = int(os.environ['API_PORT'])
        
        if 'API_WORKERS' in os.environ:
            self.config.workers = int(os.environ['API_WORKERS'])
        
        # Security
        if 'SECRET_KEY' in os.environ:
            self.config.secret_key = os.environ['SECRET_KEY']
        
        if 'CSRF_SECRET' in os.environ:
            self.config.csrf_secret = os.environ['CSRF_SECRET']
        
        logger.info("Environment configuration loaded")
    
    def get_db_client(self) -> QubesRPCClient:
        """Get the database RPC client."""
        return self.rpc_clients.get('db')
    
    def get_scraper_client(self) -> QubesRPCClient:
        """Get the scraper RPC client."""
        return self.rpc_clients.get('scraper')
    
    def query_database(self, query: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Query the database via RPC."""
        client = self.get_db_client()
        if not client:
            raise RuntimeError("Database RPC client not initialized")
        
        return client.query(query, collection)
    
    def store_data(self, data: Any, collection: str) -> Dict[str, Any]:
        """Store data in the database via RPC."""
        client = self.get_db_client()
        if not client:
            raise RuntimeError("Database RPC client not initialized")
        
        return client.store(data, collection)
    
    def start_scrape_job(self, url: str, depth: int = 1) -> Dict[str, Any]:
        """Start a scraping job on the scraper VM."""
        client = self.get_scraper_client()
        if not client:
            raise RuntimeError("Scraper RPC client not initialized")
        
        return client.start_job('scrape', {'url': url, 'depth': depth})
    
    def get_scrape_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of a scraping job."""
        client = self.get_scraper_client()
        if not client:
            raise RuntimeError("Scraper RPC client not initialized")
        
        return client.get_job_status(job_id)
    
    def analyze_content(self, content: str, analysis_type: str) -> Dict[str, Any]:
        """Analyze content using the scraper VM."""
        client = self.get_scraper_client()
        if not client:
            raise RuntimeError("Scraper RPC client not initialized")
        
        return client.analyze(content, analysis_type)
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of the API VM and its dependencies."""
        status = {
            'api': 'healthy',
            'dependencies': {}
        }
        
        # Check database connection
        try:
            db_client = self.get_db_client()
            if db_client:
                db_status = db_client.get_status()
                status['dependencies']['database'] = db_status.get('status', 'unknown')
        except Exception as e:
            status['dependencies']['database'] = f'unhealthy: {str(e)}'
        
        # Check scraper connection
        try:
            scraper_client = self.get_scraper_client()
            if scraper_client:
                scraper_status = scraper_client.get_status()
                status['dependencies']['scraper'] = scraper_status.get('status', 'unknown')
        except Exception as e:
            status['dependencies']['scraper'] = f'unhealthy: {str(e)}'
        
        return status
    
    def get_config(self) -> APIVMConfig:
        """Get the current configuration."""
        return self.config


# Global instance
_api_vm: Optional[APIVM] = None


def get_api_vm() -> APIVM:
    """Get the global API VM instance."""
    global _api_vm
    if _api_vm is None:
        _api_vm = APIVM()
        _api_vm.initialize()
    return _api_vm


def query_database(query: Dict[str, Any], collection: str) -> Dict[str, Any]:
    """Query the database via the API VM."""
    return get_api_vm().query_database(query, collection)


def store_data(data: Any, collection: str) -> Dict[str, Any]:
    """Store data via the API VM."""
    return get_api_vm().store_data(data, collection)


def start_scrape_job(url: str, depth: int = 1) -> Dict[str, Any]:
    """Start a scrape job via the API VM."""
    return get_api_vm().start_scrape_job(url, depth)
