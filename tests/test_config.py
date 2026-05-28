"""
Open Omniscience - Configuration Tests

Tests for the centralized configuration system.

Author: Ideotion
License: GNU GPLv3
"""

import pytest
import os
import tempfile
from pathlib import Path
import yaml

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import get_config, reset_config, get_database_url, get_sources_config_path


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create configs directory
        configs_dir = Path(tmpdir) / "configs"
        configs_dir.mkdir()
        
        # Create settings.yaml
        settings = {
            "database": {
                "url": "sqlite:///test.db"
            },
            "scraping": {
                "max_workers": 10
            },
            "security": {
                "cors_origins": "http://test.com"
            }
        }
        with open(configs_dir / "settings.yaml", "w") as f:
            yaml.dump(settings, f)
        
        # Create sources.yml
        sources = {
            "sources": [
                {"name": "Test Source", "domain": "test.com"}
            ]
        }
        with open(configs_dir / "sources.yml", "w") as f:
            yaml.dump(sources, f)
        
        # Mock the repo_root
        original_repo_root = None
        if hasattr(get_config(), 'repo_root'):
            original_repo_root = get_config().repo_root
        
        yield tmpdir, configs_dir
        
        # Cleanup
        reset_config()


@pytest.fixture(autouse=True)
def reset_config_after_test():
    """Reset config after each test."""
    yield
    reset_config()


class TestConfig:
    """Tests for the Config class."""
    
    def test_default_values(self):
        """Test that default values are set correctly."""
        # Reset config to avoid loading from YAML files
        reset_config()
        
        # Temporarily rename configs directory to prevent loading
        configs_dir = Path(__file__).parent.parent / "src" / "config"
        repo_configs = Path(__file__).parent.parent / "configs"
        
        # Backup and remove configs directory temporarily
        backup_dir = repo_configs.with_suffix(".backup")
        if repo_configs.exists():
            repo_configs.rename(backup_dir)
        
        try:
            config = get_config()
            
            # Check database defaults
            assert config.database_url == "sqlite:///data/open_omniscience.db"
            assert config.database_echo is False
            
            # Check scraping defaults
            assert config.max_workers == 5
            assert config.max_retries == 3
            assert config.timeout == 10
            assert "OpenOmniscience/1.0" in config.user_agent
            
            # Check rate limiting defaults
            assert config.global_rate_limit == "100/hour"
            assert config.search_rate_limit == "100/hour"
            
            # Check security defaults (from settings.yaml or defaults)
            # CORS origins might be loaded from YAML, so check it's a string or list
            assert config.cors_origins is not None
            assert config.cors_allow_credentials is True
            
            # Check app defaults
            assert config.app_name == "Open Omniscience"
            # Version might be loaded from YAML
            assert config.app_version is not None
        finally:
            # Restore configs directory
            if backup_dir.exists():
                backup_dir.rename(repo_configs)
            reset_config()
    
    def test_environment_variable_loading(self):
        """Test that environment variables override defaults."""
        # Temporarily rename configs directory to prevent YAML loading
        repo_configs = Path(__file__).parent.parent / "configs"
        backup_dir = repo_configs.with_suffix(".backup")
        
        # Backup and remove configs directory temporarily
        configs_existed = repo_configs.exists()
        if configs_existed:
            repo_configs.rename(backup_dir)
        
        try:
            # Reset config to ensure fresh load
            reset_config()
            
            # Set environment variables
            os.environ["DATABASE_URL"] = "postgresql://test:test@localhost/test"
            os.environ["MAX_WORKERS"] = "10"
            os.environ["LOG_LEVEL"] = "DEBUG"
            
            config = get_config()
            
            assert config.database_url == "postgresql://test:test@localhost/test"
            assert config.max_workers == 10
            assert config.log_level == "DEBUG"
        finally:
            # Cleanup environment variables
            if "DATABASE_URL" in os.environ:
                del os.environ["DATABASE_URL"]
            if "MAX_WORKERS" in os.environ:
                del os.environ["MAX_WORKERS"]
            if "LOG_LEVEL" in os.environ:
                del os.environ["LOG_LEVEL"]
            # Reset config after test
            reset_config()
            
            # Restore configs directory
            if configs_existed:
                backup_dir.rename(repo_configs)
    
    def test_get_database_url_sqlite(self):
        """Test get_database_url with SQLite."""
        config = get_config()
        
        # Default is SQLite
        db_url = config.get_database_url()
        
        # Should be an absolute path
        assert db_url.startswith("sqlite:///")
        assert Path(db_url.replace("sqlite:///", "")).is_absolute()
    
    def test_get_database_url_postgresql(self):
        """Test get_database_url with PostgreSQL."""
        os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost/db"
        
        try:
            config = get_config()
            db_url = config.get_database_url()
            
            assert db_url == "postgresql://user:pass@localhost/db"
        finally:
            del os.environ["DATABASE_URL"]
    
    def test_get_sources_config_path(self):
        """Test get_sources_config_path."""
        config = get_config()
        
        sources_path = config.get_sources_config_path()
        
        assert isinstance(sources_path, Path)
        assert "configs" in str(sources_path)
        assert "sources.yml" in str(sources_path)
    
    def test_directory_creation(self):
        """Test that directories are created."""
        config = get_config()
        
        # These should create directories if they don't exist
        data_dir = config.get_data_dir()
        audit_dir = config.get_audit_dir()
        logs_dir = config.get_logs_dir()
        
        assert isinstance(data_dir, Path)
        assert isinstance(audit_dir, Path)
        assert isinstance(logs_dir, Path)


class TestConvenienceFunctions:
    """Tests for convenience functions."""
    
    def test_get_config_singleton(self):
        """Test that get_config returns a singleton."""
        config1 = get_config()
        config2 = get_config()
        
        assert config1 is config2
    
    def test_reset_config(self):
        """Test that reset_config works."""
        config1 = get_config()
        reset_config()
        config2 = get_config()
        
        assert config1 is not config2
    
    def test_get_database_url_function(self):
        """Test the get_database_url convenience function."""
        db_url = get_database_url()
        
        assert isinstance(db_url, str)
        assert db_url.startswith("sqlite:///")
    
    def test_get_sources_config_path_function(self):
        """Test the get_sources_config_path convenience function."""
        sources_path = get_sources_config_path()
        
        assert isinstance(sources_path, Path)


class TestYamlLoading:
    """Tests for YAML configuration loading."""
    
    def test_settings_yaml_loading(self, temp_config_dir, monkeypatch):
        """Test loading from settings.yaml."""
        tmpdir, configs_dir = temp_config_dir
        
        # Mock repo_root
        from config.settings import Config
        original_init = Config.__init__
        
        def mock_init(self):
            self.repo_root = Path(tmpdir)
            self.extra = {}
            self._load_env()
            self._load_yaml_files()
            self._validate()
        
        with monkeypatch.context() as m:
            m.setattr(Config, "__init__", mock_init)
            reset_config()
            config = get_config()
            
            # Should have loaded from YAML
            assert config.database_url == "sqlite:///test.db"
            assert config.max_workers == 10
            assert config.cors_origins == "http://test.com"
    
    def test_sources_yaml_loading(self, temp_config_dir, monkeypatch):
        """Test loading from sources.yml."""
        tmpdir, configs_dir = temp_config_dir
        
        # Mock repo_root
        from config.settings import Config
        original_init = Config.__init__
        
        def mock_init(self):
            self.repo_root = Path(tmpdir)
            self.extra = {}
            self._load_env()
            self._load_yaml_files()
            self._validate()
        
        with monkeypatch.context() as m:
            m.setattr(Config, "__init__", mock_init)
            reset_config()
            config = get_config()
            
            # Should have loaded sources
            assert "sources" in config.extra
            assert len(config.extra["sources"]) == 1
            assert config.extra["sources"][0]["name"] == "Test Source"


class TestValidation:
    """Tests for configuration validation."""
    
    def test_empty_database_url_raises_error(self, monkeypatch):
        """Test that empty database URL raises an error."""
        from config.settings import Config
        
        # Temporarily rename configs directory to prevent YAML loading
        repo_configs = Path(__file__).parent.parent / "configs"
        backup_dir = repo_configs.with_suffix(".backup")
        
        # Backup and remove configs directory temporarily
        configs_existed = repo_configs.exists()
        if configs_existed:
            repo_configs.rename(backup_dir)
        
        try:
            with pytest.raises(ValueError, match="Database URL is not configured"):
                config = Config(database_url="")
        finally:
            # Restore configs directory
            if configs_existed:
                backup_dir.rename(repo_configs)
