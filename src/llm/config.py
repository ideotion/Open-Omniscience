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
                # Original models
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
                # NEWEST MODELS (2025-2026)
                "gemma4-9b": ModelConfig(
                    name="Gemma 4 9B",
                    model_id="gemma4:9b",
                    description="Google Gemma 4 9B - Latest generation with improved reasoning",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning"],
                    size_gb=5.5,
                    default=False
                ),
                "gemma4-27b": ModelConfig(
                    name="Gemma 4 27B",
                    model_id="gemma4:27b",
                    description="Google Gemma 4 27B - High-capability model with advanced reasoning",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning", "coding"],
                    size_gb=17.0,
                    default=False
                ),
                "llama4-9b": ModelConfig(
                    name="Llama 4 9B",
                    model_id="llama4:9b",
                    description="Meta Llama 4 9B - Next generation with improved performance",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning"],
                    size_gb=5.2,
                    default=False
                ),
                "llama4-70b": ModelConfig(
                    name="Llama 4 70B",
                    model_id="llama4:70b",
                    description="Meta Llama 4 70B - Flagship model with state-of-the-art performance",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning", "coding"],
                    size_gb=40.0,
                    default=False
                ),
                "mistral-large-2": ModelConfig(
                    name="Mistral Large 2",
                    model_id="mistral-large-2",
                    description="Mistral AI Large 2 - Latest flagship model",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning", "coding"],
                    size_gb=24.0,
                    default=False
                ),
                "phi4": ModelConfig(
                    name="Phi-4",
                    model_id="phi4",
                    description="Microsoft Phi-4 - Latest in Phi series with reasoning",
                    capabilities=["text-generation", "analysis", "reasoning", "coding"],
                    size_gb=14.0,
                    default=False
                ),
                "qwen3-8b": ModelConfig(
                    name="Qwen 3 8B",
                    model_id="qwen3:8b",
                    description="Alibaba Qwen 3 8B - Latest with improved multilingual support",
                    capabilities=["text-generation", "analysis", "translation", "summarization"],
                    size_gb=5.0,
                    default=False
                ),
                "qwen3-72b": ModelConfig(
                    name="Qwen 3 72B",
                    model_id="qwen3:72b",
                    description="Alibaba Qwen 3 72B - High-capacity multilingual model",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning"],
                    size_gb=45.0,
                    default=False
                ),
                # LIGHTWEIGHT MODELS
                "tinyllama-1.1b": ModelConfig(
                    name="TinyLlama 1.1B",
                    model_id="tinyllama:1.1b",
                    description="TinyLlama 1.1B - Extremely lightweight, runs on CPU",
                    capabilities=["text-generation", "analysis"],
                    size_gb=0.7,
                    default=False
                ),
                "phi3-mini-4k": ModelConfig(
                    name="Phi-3 Mini 4K",
                    model_id="phi3:mini-4k",
                    description="Microsoft Phi-3 Mini with 4K context window",
                    capabilities=["text-generation", "analysis", "reasoning"],
                    size_gb=1.8,
                    default=False
                ),
                "gemma2-2b": ModelConfig(
                    name="Gemma 2 2B",
                    model_id="gemma2:2b",
                    description="Google Gemma 2 2B - Ultra-lightweight model",
                    capabilities=["text-generation", "analysis"],
                    size_gb=1.4,
                    default=False
                ),
                "gemma2-9b": ModelConfig(
                    name="Gemma 2 9B",
                    model_id="gemma2:9b",
                    description="Google Gemma 2 9B - Improved over v1",
                    capabilities=["text-generation", "analysis", "translation"],
                    size_gb=5.0,
                    default=False
                ),
                # TEXT ANALYSIS SPECIALIZED
                "bert-base-uncased": ModelConfig(
                    name="BERT Base Uncased",
                    model_id="bert-base-uncased",
                    description="BERT base model for text classification and analysis",
                    capabilities=["analysis", "classification", "embeddings"],
                    size_gb=0.5,
                    default=False
                ),
                "distilbert-base-uncased": ModelConfig(
                    name="DistilBERT Base",
                    model_id="distilbert-base-uncased",
                    description="Distilled BERT - 40% smaller, 60% faster, 97% performance",
                    capabilities=["analysis", "classification", "embeddings"],
                    size_gb=0.25,
                    default=False
                ),
                "all-mpnet-base-v2": ModelConfig(
                    name="MPNet Base v2",
                    model_id="all-mpnet-base-v2",
                    description="MPNet model optimized for semantic similarity",
                    capabilities=["analysis", "embeddings", "similarity"],
                    size_gb=0.4,
                    default=False
                ),
                # TRANSLATION SPECIALIZED
                "nllb-200-distilled-600m": ModelConfig(
                    name="NLLB 200 Distilled 600M",
                    model_id="nllb-200-distilled-600m",
                    description="No Language Left Behind - 200 language translation (distilled)",
                    capabilities=["translation"],
                    size_gb=1.1,
                    default=False
                ),
                "nllb-200-1.3b": ModelConfig(
                    name="NLLB 200 1.3B",
                    model_id="nllb-200-1.3b",
                    description="No Language Left Behind - 200 language translation",
                    capabilities=["translation"],
                    size_gb=2.5,
                    default=False
                ),
                "mbart-large-50-many-to-many": ModelConfig(
                    name="mBART Large 50",
                    model_id="mbart-large-50-many-to-many",
                    description="Multilingual BART for 50 languages",
                    capabilities=["translation", "summarization"],
                    size_gb=1.4,
                    default=False
                ),
                "t5-small": ModelConfig(
                    name="T5 Small",
                    model_id="t5-small",
                    description="T5 Small - Text-to-text for translation and summarization",
                    capabilities=["translation", "summarization", "text-generation"],
                    size_gb=0.3,
                    default=False
                ),
                "t5-base": ModelConfig(
                    name="T5 Base",
                    model_id="t5-base",
                    description="T5 Base - Larger T5 model for better quality",
                    capabilities=["translation", "summarization", "text-generation"],
                    size_gb=0.9,
                    default=False
                ),
                "t5-large": ModelConfig(
                    name="T5 Large",
                    model_id="t5-large",
                    description="T5 Large - High-quality text-to-text model",
                    capabilities=["translation", "summarization", "text-generation"],
                    size_gb=3.0,
                    default=False
                ),
                # MULTILINGUAL & ADDITIONAL
                "qwen2.5-1.5b": ModelConfig(
                    name="Qwen 2.5 1.5B",
                    model_id="qwen2.5:1.5b",
                    description="Qwen 2.5 1.5B - Compact multilingual model",
                    capabilities=["text-generation", "translation", "analysis"],
                    size_gb=1.8,
                    default=False
                ),
                "qwen2.5-0.5b": ModelConfig(
                    name="Qwen 2.5 0.5B",
                    model_id="qwen2.5:0.5b",
                    description="Qwen 2.5 0.5B - Ultra-lightweight multilingual",
                    capabilities=["text-generation", "translation"],
                    size_gb=0.6,
                    default=False
                ),
                "mistral-7b-instruct": ModelConfig(
                    name="Mistral 7B Instruct",
                    model_id="mistral:7b-instruct",
                    description="Mistral 7B with instruction fine-tuning",
                    capabilities=["text-generation", "analysis", "translation", "summarization"],
                    size_gb=4.1,
                    default=False
                ),
                "llama3.2-3b": ModelConfig(
                    name="Llama 3.2 3B",
                    model_id="llama3.2:3b",
                    description="Llama 3.2 3B - Balanced size and performance",
                    capabilities=["text-generation", "analysis", "translation"],
                    size_gb=1.8,
                    default=False
                ),
                "llama3.2-11b": ModelConfig(
                    name="Llama 3.2 11B",
                    model_id="llama3.2:11b",
                    description="Llama 3.2 11B - High performance model",
                    capabilities=["text-generation", "analysis", "translation", "summarization"],
                    size_gb=6.5,
                    default=False
                ),
                "llama3.2-1b": ModelConfig(
                    name="Llama 3.2 1B",
                    model_id="llama3.2:1b",
                    description="Llama 3.2 1B - Compact model with improved efficiency",
                    capabilities=["text-generation", "analysis"],
                    size_gb=0.6,
                    default=False
                ),
                "llama3.2-90b": ModelConfig(
                    name="Llama 3.2 90B",
                    model_id="llama3.2:90b",
                    description="Llama 3.2 90B - Flagship model with state-of-the-art performance",
                    capabilities=["text-generation", "analysis", "translation", "summarization", "reasoning", "coding"],
                    size_gb=55.0,
                    default=False
                ),
                "phi3-small-8k": ModelConfig(
                    name="Phi-3 Small 8K",
                    model_id="phi3:small-8k",
                    description="Microsoft Phi-3 Small with 8K context",
                    capabilities=["text-generation", "analysis", "reasoning"],
                    size_gb=2.7,
                    default=False
                ),
                "phi3-medium-16k": ModelConfig(
                    name="Phi-3 Medium 16K",
                    model_id="phi3:medium-16k",
                    description="Microsoft Phi-3 Medium with 16K context",
                    capabilities=["text-generation", "analysis", "reasoning", "coding"],
                    size_gb=4.2,
                    default=False
                ),
                "roberta-base": ModelConfig(
                    name="RoBERTa Base",
                    model_id="roberta-base",
                    description="Robustly optimized BERT approach for analysis",
                    capabilities=["analysis", "classification", "embeddings"],
                    size_gb=0.5,
                    default=False
                ),
                "sentence-t5-base": ModelConfig(
                    name="Sentence T5 Base",
                    model_id="sentence-t5-base",
                    description="T5-based sentence encoder for embeddings",
                    capabilities=["analysis", "embeddings", "similarity"],
                    size_gb=0.5,
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
