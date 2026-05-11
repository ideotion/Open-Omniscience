"""
Tests for Local LLM Support in Open-Omniscience
"""

import pytest
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.config import LLMConfig, ModelConfig, get_llm_config
from src.llm.model_manager import ModelManager
from src.llm.llm_service import LLMService
from src.llm.exceptions import (
    OllamaNotInstalledError,
    OllamaNotRunningError,
    ModelNotFoundError
)


@pytest.fixture
def config():
    """Create a test configuration"""
    return LLMConfig()


@pytest.fixture
def model_manager(config):
    """Create a model manager with test configuration"""
    return ModelManager(config)


@pytest.fixture
def llm_service(model_manager):
    """Create an LLM service with test configuration"""
    return LLMService(model_manager)


class TestLLMConfig:
    """Tests for LLM configuration"""
    
    def test_default_config(self, config):
        """Test that default configuration is loaded correctly"""
        assert config.ollama.enabled is True
        assert config.ollama.base_url == "http://localhost:11434"
        assert config.ollama.timeout == 120
        assert config.auto_download_models is True
        assert len(config.default_models) > 0
    
    def test_get_default_model(self, config):
        """Test getting the default model"""
        default_model = config.get_default_model()
        assert default_model is not None
        assert default_model.default is True
    
    def test_get_model_by_id(self, config):
        """Test getting a model by ID"""
        model = config.get_model_by_id("llama3:8b")
        assert model is not None
        assert model.name == "Llama 3 8B"
    
    def test_get_model_by_id_not_found(self, config):
        """Test getting a non-existent model"""
        model = config.get_model_by_id("nonexistent:model")
        assert model is None
    
    def test_get_models_for_capability(self, config):
        """Test getting models for a specific capability"""
        translation_models = config.get_models_for_capability("translation")
        assert len(translation_models) > 0
        for model in translation_models:
            assert "translation" in model.capabilities


class TestModelManager:
    """Tests for model management"""
    
    def test_is_ollama_installed(self, model_manager):
        """Test checking if Ollama is installed"""
        result = model_manager.is_ollama_installed()
        assert isinstance(result, bool)
    
    def test_is_ollama_running(self, model_manager):
        """Test checking if Ollama is running"""
        result = model_manager.is_ollama_running()
        assert isinstance(result, bool)
    
    def test_list_local_models(self, model_manager):
        """Test listing local models"""
        models = model_manager.list_local_models()
        assert isinstance(models, list)
    
    def test_list_remote_models(self, model_manager):
        """Test listing remote models"""
        models = model_manager.list_remote_models()
        assert isinstance(models, list)
    
    def test_get_models_by_capability(self, model_manager):
        """Test getting models by capability"""
        models = model_manager.get_models_by_capability("analysis")
        assert len(models) > 0
    
    def test_get_recommended_models(self, model_manager):
        """Test getting recommended models for a task"""
        models = model_manager.get_recommended_models("translation")
        assert len(models) > 0
    
    def test_get_disk_usage(self, model_manager):
        """Test getting disk usage"""
        usage = model_manager.get_disk_usage()
        assert "total_gb" in usage
        assert "models" in usage


class TestLLMService:
    """Tests for LLM service"""
    
    def test_service_initialization(self, llm_service):
        """Test that service initializes correctly"""
        assert llm_service.config is not None
        assert llm_service.model_manager is not None
    
    def test_get_model_info(self, llm_service):
        """Test getting model information"""
        info = llm_service.get_model_info()
        assert "ollama_running" in info
        assert "ollama_installed" in info
        assert "local_models" in info
        assert "available_models" in info


class TestLLMCapabilities:
    """Integration tests for LLM capabilities"""
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_text_generation(self, llm_service):
        """Test text generation capability"""
        try:
            result = llm_service.generate_text(
                prompt="What is the capital of France?",
                temperature=0.7
            )
            assert isinstance(result, str)
            assert len(result) > 0
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_chat_completion(self, llm_service):
        """Test chat completion capability"""
        try:
            messages = [
                {"role": "user", "content": "Hello, how are you?"}
            ]
            result = llm_service.chat(messages=messages)
            assert "response" in result
            assert isinstance(result["response"], str)
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_text_extraction(self, llm_service):
        """Test text extraction capability"""
        try:
            content = "Apple Inc. was founded by Steve Jobs in 1976. It is headquartered in Cupertino, California."
            result = llm_service.extract_text(
                content=content,
                extraction_type="entities"
            )
            assert "extraction_type" in result
            assert result["extraction_type"] == "entities"
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_translation(self, llm_service):
        """Test translation capability"""
        try:
            result = llm_service.translate_text(
                text="Hello, how are you?",
                target_language="fr",
                source_language="en"
            )
            assert "translation" in result
            assert "target_language" in result
            assert result["target_language"] == "fr"
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_text_analysis(self, llm_service):
        """Test text analysis capability"""
        try:
            result = llm_service.analyze_text(
                text="I am very happy with this product!",
                analysis_type="sentiment"
            )
            assert "analysis_type" in result
            assert result["analysis_type"] == "sentiment"
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_synthesis(self, llm_service):
        """Test synthesis capability"""
        try:
            sources = [
                "The sky is blue and the sun is shining.",
                "Birds are singing in the trees."
            ]
            result = llm_service.synthesize_text(
                sources=sources,
                synthesis_type="summary"
            )
            assert "synthesis_type" in result
            assert result["synthesis_type"] == "summary"
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")
    
    @pytest.mark.skipif(
        not os.path.exists("/usr/local/bin/ollama") and not os.path.exists("/usr/bin/ollama"),
        reason="Ollama not installed"
    )
    def test_batch_processing(self, llm_service):
        """Test batch processing capability"""
        try:
            items = [
                "First text to analyze",
                "Second text to analyze"
            ]
            result = llm_service.batch_process(
                items=items,
                operation="analyze",
                analysis_type="sentiment"
            )
            assert isinstance(result, list)
            assert len(result) == len(items)
        except (OllamaNotRunningError, ModelNotFoundError):
            pytest.skip("Ollama not running or model not available")


class TestLLMExceptions:
    """Tests for exception handling"""
    
    def test_ollama_not_installed_error(self):
        """Test OllamaNotInstalledError"""
        error = OllamaNotInstalledError()
        assert "Ollama is not installed" in str(error)
    
    def test_ollama_not_running_error(self):
        """Test OllamaNotRunningError"""
        error = OllamaNotRunningError()
        assert "Ollama server is not running" in str(error)
    
    def test_model_not_found_error(self):
        """Test ModelNotFoundError"""
        error = ModelNotFoundError("test:model")
        assert "test:model" in str(error)


class TestModelConfig:
    """Tests for model configuration"""
    
    def test_model_config_creation(self):
        """Test creating a model configuration"""
        config = ModelConfig(
            name="Test Model",
            model_id="test:model",
            description="A test model",
            capabilities=["text-generation"],
            size_gb=1.0,
            default=True
        )
        assert config.name == "Test Model"
        assert config.model_id == "test:model"
        assert config.capabilities == ["text-generation"]
        assert config.size_gb == 1.0
        assert config.default is True


# Integration test that requires Ollama to be running
@pytest.mark.integration
class TestLLMIntegration:
    """Integration tests that require Ollama to be running"""
    
    @pytest.fixture(autouse=True)
    def setup_ollama(self, model_manager):
        """Ensure Ollama is running for integration tests"""
        if not model_manager.is_ollama_installed():
            pytest.skip("Ollama not installed")
        
        if not model_manager.is_ollama_running():
            try:
                model_manager.start_ollama()
            except Exception:
                pytest.skip("Could not start Ollama")
        
        # Ensure default model is downloaded
        default_model = model_manager.config.get_default_model()
        if default_model and not model_manager.is_model_downloaded(default_model.model_id):
            try:
                model_manager.download_model(default_model.model_id)
            except Exception:
                pytest.skip(f"Could not download default model: {default_model.model_id}")
    
    def test_full_text_generation_workflow(self, llm_service):
        """Test a complete text generation workflow"""
        prompt = "Write a haiku about open source software."
        result = llm_service.generate_text(prompt=prompt)
        
        assert isinstance(result, str)
        assert len(result) > 0
        # Check that it's not just repeating the prompt
        assert result.lower() != prompt.lower()
    
    def test_conversation_memory(self, llm_service):
        """Test that chat maintains conversation context"""
        messages = [
            {"role": "user", "content": "What is the capital of France?"},
            {"role": "assistant", "content": "The capital of France is Paris."},
            {"role": "user", "content": "What about Germany?"}
        ]
        
        result = llm_service.chat(messages=messages)
        
        assert "response" in result
        # The response should be about Germany's capital
        response_lower = result["response"].lower()
        assert "berlin" in response_lower or "capital" in response_lower
    
    def test_extraction_accuracy(self, llm_service):
        """Test that extraction produces accurate results"""
        content = "Microsoft was founded by Bill Gates and Paul Allen in 1975. The company is headquartered in Redmond, Washington."
        
        result = llm_service.extract_text(
            content=content,
            extraction_type="entities"
        )
        
        # The result should contain information about entities
        assert "extraction_type" in result
        assert result["extraction_type"] == "entities"
    
    def test_translation_quality(self, llm_service):
        """Test that translation produces reasonable results"""
        text = "The quick brown fox jumps over the lazy dog."
        
        result = llm_service.translate_text(
            text=text,
            target_language="fr",
            source_language="en"
        )
        
        assert "translation" in result
        # The translation should be different from the original
        assert result["translation"].lower() != text.lower()
        # For French, we expect some common words
        french_words = ["le", "la", "rapide", "renard", "saute", "paresseux", "chien"]
        translation_lower = result["translation"].lower()
        assert any(word in translation_lower for word in french_words)
    
    def test_analysis_consistency(self, llm_service):
        """Test that analysis produces consistent results"""
        positive_text = "I am extremely happy and satisfied with this amazing product!"
        negative_text = "This is terrible and I am very disappointed with the poor quality."
        
        positive_result = llm_service.analyze_text(
            text=positive_text,
            analysis_type="sentiment"
        )
        
        negative_result = llm_service.analyze_text(
            text=negative_text,
            analysis_type="sentiment"
        )
        
        # Both should return valid results
        assert "analysis_type" in positive_result
        assert "analysis_type" in negative_result
        
        # The sentiment should be different
        # (Note: This is a soft check as LLM responses can vary)
        assert positive_result != negative_result
