"""
LLM Configuration for Open-Omniscience
Handles all configuration related to local LLM support
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
from pathlib import Path


@dataclass
class ModelConfig:
    """Configuration for a single LLM model"""
    name: str
    model_id: str  # Ollama model identifier (e.g., 'llama3:8b', 'mistral:7b')
    description: str
    capabilities: List[str]  # e.g., ['text-generation', 'translation', 'summarization']
    size_gb: float  # Approximate size in GB
    default: bool = False
    

@dataclass
class OllamaConfig:
    """Configuration for Ollama integration"""
    enabled: bool = True
    base_url: str = "http://localhost:11434"
    timeout: int = 120  # seconds
    max_retries: int = 3
    

@dataclass
class LLMConfig:
    """Main LLM configuration"""
    # Ollama settings
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    
    # Model library settings
    model_library_path: str = os.path.join("data", "llm_models")
    auto_download_models: bool = True
    
    # Default models to use
    default_models: Dict[str, ModelConfig] = field(default_factory=dict)
    
    # Feature toggles
    enable_text_extraction: bool = True
    enable_translation: bool = True
    enable_analysis: bool = True
    enable_synthesis: bool = True
    
    # Resource limits
    max_context_length: int = 8192
    max_tokens: int = 4096
    
    def __post_init__(self):
        """Initialize default models"""
        if not self.default_models:
            self.default_models = {
                "llama3-8b": ModelConfig(
                    name="Llama 3 8B",
                    model_id="llama3:8b",
                    description="Meta Llama 3 8B - General purpose model",
                    capabilities=["text-generation", "analysis", "summarization"],
                    size_gb=4.7,
                    default=True
                ),
                "mistral-7b": ModelConfig(
                    name="Mistral 7B",
                    model_id="mistral:7b",
                    description="Mistral AI 7B - Efficient and performant",
                    capabilities=["text-generation", "analysis", "translation"],
                    size_gb=4.1,
                    default=False
                ),
                "phi3-3.8b": ModelConfig(
                    name="Phi-3 3.8B",
                    model_id="phi3:3.8b",
                    description="Microsoft Phi-3 3.8B - Lightweight and efficient",
                    capabilities=["text-generation", "analysis"],
                    size_gb=2.3,
                    default=False
                ),
                "qwen2.5-7b": ModelConfig(
                    name="Qwen 2.5 7B",
                    model_id="qwen2.5:7b",
                    description="Alibaba Qwen 2.5 7B - Multilingual support",
                    capabilities=["text-generation", "translation", "analysis"],
                    size_gb=4.8,
                    default=False
                ),
                "gemma-7b": ModelConfig(
                    name="Gemma 7B",
                    model_id="gemma:7b",
                    description="Google Gemma 7B - Optimized for CPU",
                    capabilities=["text-generation", "analysis"],
                    size_gb=4.8,
                    default=False
                ),
                "llama3-70b": ModelConfig(
                    name="Llama 3 70B",
                    model_id="llama3:70b",
                    description="Meta Llama 3 70B - High capability model",
                    capabilities=["text-generation", "analysis", "translation", "summarization"],
                    size_gb=40.0,
                    default=False
                ),
                # Specialized models
                "llava-7b": ModelConfig(
                    name="LLaVA 7B",
                    model_id="llava:7b",
                    description="Multimodal model for vision and text",
                    capabilities=["text-generation", "analysis", "vision"],
                    size_gb=4.5,
                    default=False
                ),
                "bart-large": ModelConfig(
                    name="BART Large",
                    model_id="bart-large",
                    description="Optimized for translation and summarization",
                    capabilities=["translation", "summarization"],
                    size_gb=1.4,
                    default=False
                ),
            }
    
    def get_default_model(self) -> Optional[ModelConfig]:
        """Get the default model configuration"""
        for model in self.default_models.values():
            if model.default:
                return model
        return None
    
    def get_model_by_id(self, model_id: str) -> Optional[ModelConfig]:
        """Get model configuration by ID or model_id"""
        # First try direct key lookup
        if model_id in self.default_models:
            return self.default_models[model_id]
        # Then try to find by model_id attribute
        for model in self.default_models.values():
            if model.model_id == model_id:
                return model
        return None
    
    def get_models_for_capability(self, capability: str) -> List[ModelConfig]:
        """Get all models that support a specific capability"""
        return [
            model for model in self.default_models.values()
            if capability in model.capabilities
        ]


# Global configuration instance
llm_config = LLMConfig()


def get_llm_config() -> LLMConfig:
    """Get the global LLM configuration"""
    return llm_config


def set_llm_config(config: LLMConfig):
    """Set the global LLM configuration"""
    global llm_config
    llm_config = config
