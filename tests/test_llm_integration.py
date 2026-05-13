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
Integration Tests for Local LLM Support
Tests the complete LLM module integration with FastAPI
"""

import pytest
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Test if we can import the modules
try:
    from src.llm.config import LLMConfig, get_llm_config, ModelConfig
    from src.llm.exceptions import (
        LLMError, OllamaNotInstalledError, OllamaNotRunningError,
        ModelNotFoundError, ModelDownloadError, LLMTimeoutError,
        LLMProcessingError, InvalidModelConfigError, InsufficientResourcesError
    )
    from src.llm.model_manager import ModelManager
    from src.llm.llm_service import LLMService
    print("✅ All LLM module imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    pytest.skip(f"Cannot import LLM modules: {e}", allow_module_level=True)


class TestLLMConfigIntegration:
    """Test LLM configuration integration"""
    
    def test_config_singleton(self):
        """Test that config is a singleton"""
        config1 = get_llm_config()
        config2 = get_llm_config()
        assert config1 is config2
    
    def test_default_models_populated(self):
        """Test that default models are populated"""
        config = get_llm_config()
        assert len(config.default_models) > 0
        # Check that llama3:8b model exists (key is llama3-8b, model_id is llama3:8b)
        assert 'llama3-8b' in config.default_models
        assert config.default_models['llama3-8b'].model_id == 'llama3:8b'
    
    def test_get_default_model(self):
        """Test getting default model"""
        config = get_llm_config()
        default = config.get_default_model()
        assert default is not None
        assert default.model_id == 'llama3:8b'
    
    def test_get_model_by_id(self):
        """Test getting model by ID"""
        config = get_llm_config()
        model = config.get_model_by_id('mistral:7b')
        assert model is not None
        assert model.name == 'Mistral 7B'
    
    def test_get_models_for_capability(self):
        """Test getting models for capability"""
        config = get_llm_config()
        translation_models = config.get_models_for_capability('translation')
        assert len(translation_models) > 0


class TestModelManagerIntegration:
    """Test model manager integration"""
    
    def test_model_manager_initialization(self):
        """Test model manager initialization"""
        mm = ModelManager()
        assert mm.config is not None
    
    def test_is_ollama_installed(self):
        """Test checking if Ollama is installed"""
        mm = ModelManager()
        result = mm.is_ollama_installed()
        assert isinstance(result, bool)
    
    def test_is_ollama_running(self):
        """Test checking if Ollama is running"""
        mm = ModelManager()
        result = mm.is_ollama_running()
        assert isinstance(result, bool)
    
    def test_list_local_models(self):
        """Test listing local models"""
        mm = ModelManager()
        models = mm.list_local_models()
        assert isinstance(models, list)
    
    def test_list_remote_models(self):
        """Test listing remote models"""
        mm = ModelManager()
        models = mm.list_remote_models()
        assert isinstance(models, list)
    
    def test_get_models_by_capability(self):
        """Test getting models by capability"""
        mm = ModelManager()
        models = mm.get_models_by_capability('analysis')
        assert len(models) > 0
    
    def test_get_recommended_models(self):
        """Test getting recommended models"""
        mm = ModelManager()
        models = mm.get_recommended_models('translation')
        assert len(models) > 0
    
    def test_get_disk_usage(self):
        """Test getting disk usage"""
        mm = ModelManager()
        usage = mm.get_disk_usage()
        assert 'total_gb' in usage
        assert 'models' in usage


class TestLLMServiceIntegration:
    """Test LLM service integration"""
    
    def test_service_initialization(self):
        """Test service initialization"""
        service = LLMService()
        assert service.config is not None
        assert service.model_manager is not None
    
    def test_get_model_info(self):
        """Test getting model info"""
        service = LLMService()
        info = service.get_model_info()
        assert 'ollama_running' in info
        assert 'ollama_installed' in info
        assert 'local_models' in info
        assert 'available_models' in info


class TestLLMExceptions:
    """Test LLM exception classes"""
    
    def test_ollama_not_installed_error(self):
        """Test OllamaNotInstalledError"""
        error = OllamaNotInstalledError()
        assert 'Ollama is not installed' in str(error)
    
    def test_ollama_not_running_error(self):
        """Test OllamaNotRunningError"""
        error = OllamaNotRunningError()
        assert 'Ollama server is not running' in str(error)
    
    def test_model_not_found_error(self):
        """Test ModelNotFoundError"""
        error = ModelNotFoundError('test:model')
        assert 'test:model' in str(error)
    
    def test_model_download_error(self):
        """Test ModelDownloadError"""
        error = ModelDownloadError('test:model', 'Test reason')
        assert 'test:model' in str(error)
        assert 'Test reason' in str(error)
    
    def test_llm_timeout_error(self):
        """Test LLMTimeoutError"""
        error = LLMTimeoutError('test operation', 30)
        assert 'test operation' in str(error)
        assert '30' in str(error)
    
    def test_llm_processing_error(self):
        """Test LLMProcessingError"""
        error = LLMProcessingError('test operation', 'Test details')
        assert 'test operation' in str(error)
        assert 'Test details' in str(error)
    
    def test_invalid_model_config_error(self):
        """Test InvalidModelConfigError"""
        error = InvalidModelConfigError('test:model', 'Invalid config')
        assert 'test:model' in str(error)
        assert 'Invalid config' in str(error)
    
    def test_insufficient_resources_error(self):
        """Test InsufficientResourcesError"""
        error = InsufficientResourcesError('10GB', '5GB')
        assert '10GB' in str(error)
        assert '5GB' in str(error)


class TestModelConfig:
    """Test model configuration"""
    
    def test_model_config_creation(self):
        """Test creating model config"""
        config = ModelConfig(
            name='Test Model',
            model_id='test:model',
            description='A test model',
            capabilities=['text-generation'],
            size_gb=1.0,
            default=True
        )
        assert config.name == 'Test Model'
        assert config.model_id == 'test:model'
        assert config.capabilities == ['text-generation']
        assert config.size_gb == 1.0
        assert config.default is True


# Run basic tests
if __name__ == '__main__':
    print("\n" + "="*60)
    print("Running LLM Integration Tests")
    print("="*60 + "\n")
    
    # Test configuration
    print("Testing Configuration...")
    try:
        config = get_llm_config()
        print(f"✅ Config loaded with {len(config.default_models)} models")
        default_model = config.get_default_model()
        print(f"✅ Default model: {default_model.name} ({default_model.model_id})")
    except Exception as e:
        print(f"❌ Config test failed: {e}")
    
    # Test model manager
    print("\nTesting Model Manager...")
    try:
        mm = ModelManager()
        installed = mm.is_ollama_installed()
        running = mm.is_ollama_running()
        print(f"✅ Ollama installed: {installed}, running: {running}")
        local_models = mm.list_local_models()
        print(f"✅ Local models: {len(local_models)}")
    except Exception as e:
        print(f"❌ Model manager test failed: {e}")
    
    # Test service
    print("\nTesting LLM Service...")
    try:
        service = LLMService()
        info = service.get_model_info()
        print(f"✅ Service initialized")
        print(f"   - Ollama running: {info['ollama_running']}")
        print(f"   - Local models: {len(info['local_models'])}")
    except Exception as e:
        print(f"❌ Service test failed: {e}")
    
    # Test exceptions
    print("\nTesting Exceptions...")
    try:
        error = OllamaNotInstalledError()
        print(f"✅ OllamaNotInstalledError: {str(error)}")
        error = ModelNotFoundError('test:model')
        print(f"✅ ModelNotFoundError: {str(error)}")
        error = LLMProcessingError('test', 'details')
        print(f"✅ LLMProcessingError: {str(error)}")
    except Exception as e:
        print(f"❌ Exception test failed: {e}")
    
    print("\n" + "="*60)
    print("LLM Integration Tests Complete")
    print("="*60 + "\n")
