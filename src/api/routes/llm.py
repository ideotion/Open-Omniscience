"""
LLM API Routes for Open-Omniscience
Exposes LLM capabilities through REST API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field

from ...llm.llm_service import LLMService
from ...llm.model_manager import ModelManager
from ...llm.config import get_llm_config
from ...llm.exceptions import (
    OllamaNotInstalledError,
    OllamaNotRunningError,
    ModelNotFoundError,
    LLMProcessingError,
    LLMTimeoutError
)

router = APIRouter(prefix="/api/llm", tags=["LLM"])


# Dependency to get LLM service
async def get_llm_service():
    return LLMService()


class TextGenerationRequest(BaseModel):
    prompt: str = Field(..., description="The user prompt")
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use (defaults to default model)"
    )
    system_prompt: Optional[str] = Field(
        default=None,
        description="Optional system prompt"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        description="Maximum tokens to generate"
    )


class ChatRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., description="List of message dictionaries")
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use"
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Sampling temperature"
    )
    max_tokens: Optional[int] = Field(
        default=None,
        description="Maximum tokens to generate"
    )


class ExtractionRequest(BaseModel):
    content: str = Field(..., description="Content to extract from")
    extraction_type: str = Field(
        default="general",
        description="Type of extraction"
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use"
    )


class TranslationRequest(BaseModel):
    text: str = Field(..., description="Text to translate")
    target_language: str = Field(..., description="Target language code")
    source_language: str = Field(
        default="auto",
        description="Source language code"
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use"
    )


class AnalysisRequest(BaseModel):
    text: str = Field(..., description="Text to analyze")
    analysis_type: str = Field(
        default="comprehensive",
        description="Type of analysis"
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use"
    )


class SynthesisRequest(BaseModel):
    sources: List[Union[str, Dict[str, Any]]] = Field(
        ...,
        description="List of sources to synthesize"
    )
    synthesis_type: str = Field(
        default="summary",
        description="Type of synthesis"
    )
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use"
    )


class ModelOperationRequest(BaseModel):
    model_id: str = Field(..., description="Model identifier")


class BatchProcessRequest(BaseModel):
    items: List[Union[str, Dict[str, Any]]] = Field(
        ...,
        description="List of items to process"
    )
    operation: str = Field(..., description="Operation to perform")
    model_id: Optional[str] = Field(
        default=None,
        description="Model to use"
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional options for the operation"
    )


@router.get("/health")
async def health_check(service: LLMService = Depends(get_llm_service)):
    """Check LLM service health"""
    return {
        "status": "healthy",
        "ollama_installed": service.model_manager.is_ollama_installed(),
        "ollama_running": service.model_manager.is_ollama_running()
    }


@router.get("/models")
async def list_models(service: LLMService = Depends(get_llm_service)):
    """List available models and their status"""
    try:
        return service.get_model_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities")
async def get_capabilities():
    """Get list of supported capabilities"""
    return {
        "capabilities": [
            {
                "name": "text_generation",
                "description": "Generate text based on prompts",
                "endpoint": "/api/llm/generate",
                "methods": ["POST"]
            },
            {
                "name": "chat",
                "description": "Chat completion with memory of conversation",
                "endpoint": "/api/llm/chat",
                "methods": ["POST"]
            },
            {
                "name": "text_extraction",
                "description": "Extract structured information from text",
                "endpoint": "/api/llm/extract",
                "methods": ["POST"],
                "types": ["general", "entities", "keywords", "summary", "metadata", "quotes", "links"]
            },
            {
                "name": "translation",
                "description": "Translate text between languages",
                "endpoint": "/api/llm/translate",
                "methods": ["POST"],
                "supported_languages": [
                    "en", "fr", "es", "de", "it", "pt", "ru", "zh", "ja", "ar", "hi", "auto"
                ]
            },
            {
                "name": "text_analysis",
                "description": "Analyze text for various characteristics",
                "endpoint": "/api/llm/analyze",
                "methods": ["POST"],
                "types": [
                    "sentiment", "tone", "bias", "readability", 
                    "emotion", "comprehensive", "disinformation"
                ]
            },
            {
                "name": "synthesis",
                "description": "Synthesize information from multiple sources",
                "endpoint": "/api/llm/synthesize",
                "methods": ["POST"],
                "types": ["summary", "comparison", "timeline", "report", "faq"]
            },
            {
                "name": "batch_processing",
                "description": "Process multiple items in batch",
                "endpoint": "/api/llm/batch",
                "methods": ["POST"],
                "operations": ["extract", "translate", "analyze", "synthesize"]
            }
        ],
        "models": {
            "default": "llama3:8b",
            "available": list(get_llm_config().default_models.keys())
        }
    }
