"""
LLM API Routes for Open-Omniscience
Exposes LLM capabilities through REST API endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, Field

from src.llm.llm_service import LLMService
from src.llm.model_manager import ModelManager
from src.llm.config import get_llm_config
from src.llm.exceptions import (
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


# POST endpoints for LLM operations
@router.post("/generate")
async def generate_text(
    request: TextGenerationRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Generate text based on a prompt"""
    try:
        result = service.generate_text(
            prompt=request.prompt,
            model_id=request.model_id,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=getattr(request, 'top_p', 0.9)
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat_completion(
    request: ChatRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Chat completion with conversation memory"""
    try:
        result = service.chat(
            messages=request.messages,
            model_id=request.model_id,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract")
async def extract_text(
    request: ExtractionRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Extract structured information from text"""
    try:
        result = service.extract_text(
            text=request.content,
            extraction_type=request.extraction_type,
            model_id=request.model_id
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/translate")
async def translate_text(
    request: TranslationRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Translate text between languages"""
    try:
        result = service.translate_text(
            text=request.text,
            target_language=request.target_language,
            source_language=request.source_language,
            model_id=request.model_id
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_text(
    request: AnalysisRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Analyze text for various characteristics"""
    try:
        result = service.analyze_text(
            text=request.text,
            analysis_type=request.analysis_type,
            model_id=request.model_id
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/synthesize")
async def synthesize_text(
    request: SynthesisRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Synthesize information from multiple sources"""
    try:
        result = service.synthesize_text(
            sources=request.sources,
            synthesis_type=request.synthesis_type,
            model_id=request.model_id
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch")
async def batch_process(
    request: BatchProcessRequest,
    service: LLMService = Depends(get_llm_service)
):
    """Process multiple items in batch"""
    try:
        result = service.batch_process(
            items=request.items,
            operation=request.operation,
            model_id=request.model_id
        )
        return {"result": result, "model": request.model_id or service.config.get_default_model().model_id}
    except LLMProcessingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
