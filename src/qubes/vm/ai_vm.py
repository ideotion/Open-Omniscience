"""
AI VM module for Open-Omniscience.

This module contains the configuration and logic specific to the AI VM,
which handles AI/LLM integration and analysis in a Qubes OS environment.

The AI VM is designed to:
- Run AI models for content analysis and generation
- Communicate with the API VM via Qubes RPC
- Handle resource-intensive AI operations in an isolated environment
- Support both local and remote AI model access

Security Considerations:
- AI VM has network access (via NetVM) for downloading models
- All AI operations are isolated from the database
- Communication with other VMs is via Qubes RPC only
- No direct filesystem access between VMs
"""

import os
import json
import logging
import time
import traceback
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field, asdict
from enum import Enum

# Import Qubes utilities
try:
    from src.qubes import (
        get_qubes_environment,
        get_current_qube,
        qubes_rpc_call,
        QubeInfo,
        QubesEnvironment,
        RPCCallResult
    )
    from src.qubes.rpc import QubesRPCServer, QubesRPCClient
    QUBES_AVAILABLE = True
except ImportError as e:
    QUBES_AVAILABLE = False
    logging.warning(f"Qubes utilities not available: {e}")

# Configure logging
logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class AIModelConfig:
    """Configuration for an AI model."""
    name: str
    model_type: str = "text-generation"  # text-generation, embedding, classification, etc.
    model_path: str = ""
    model_url: str = ""
    max_memory: str = "4GB"  # Maximum memory for the model
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 50
    device: str = "cpu"  # cpu, cuda, mps
    quantized: bool = False
    quant_method: str = "bitsandbytes"  # bitsandbytes, gptq, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AIModelConfig':
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class AIVMConfig:
    """Configuration for the AI VM."""
    vm_name: str = "open-omniscience-ai"
    label: str = "red"
    memory: int = 4096  # MB
    max_memory: int = 8192  # MB
    vcpus: int = 4
    
    # AI Model configurations
    default_model: str = "mistral-7b"
    available_models: Dict[str, AIModelConfig] = field(default_factory=dict)
    
    # RPC Configuration
    rpc_timeout: int = 300  # 5 minutes
    max_concurrent_requests: int = 4
    
    # API Configuration
    api_host: str = "127.0.0.1"
    api_port: int = 8001
    
    # Model directories
    model_dir: str = "/var/lib/open-omniscience/models"
    cache_dir: str = "/var/cache/open-omniscience/ai"
    
    # Security
    allow_remote_models: bool = True
    allowed_remote_sources: List[str] = field(default_factory=lambda: [
        "huggingface.co",
        "github.com",
    ])
    
    # Performance
    max_batch_size: int = 8
    max_sequence_length: int = 2048
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "available_models": {k: v.to_dict() for k, v in self.available_models.items()}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AIVMConfig':
        config = cls(**{k: v for k, v in data.items() if k not in ['available_models']})
        config.available_models = {
            k: AIModelConfig.from_dict(v) 
            for k, v in data.get('available_models', {}).items()
        }
        return config


# Default configuration
DEFAULT_CONFIG = AIVMConfig()


class AIModelStatus(Enum):
    """Status of an AI model."""
    NOT_LOADED = "not_loaded"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"
    UNLOADING = "unloading"


@dataclass
class AIModelState:
    """State of a loaded AI model."""
    model_name: str
    status: AIModelStatus
    loaded_at: Optional[float] = None
    last_used: Optional[float] = None
    usage_count: int = 0
    error_message: Optional[str] = None
    memory_usage: Optional[int] = None  # MB
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# AI VM Class
# ============================================================================

class AIVM:
    """
    AI VM management class.
    
    This class handles all AI-related operations in the Qubes OS environment,
    including model loading, text generation, embeddings, and classification.
    """
    
    def __init__(self, config: Optional[AIVMConfig] = None):
        """
        Initialize the AI VM.
        
        Args:
            config: Configuration for the AI VM. Uses defaults if not provided.
        """
        self.config = config or DEFAULT_CONFIG
        self.models: Dict[str, AIModelState] = {}
        self.rpc_server: Optional[QubesRPCServer] = None
        self.rpc_client: Optional[QubesRPCClient] = None
        self._initialized = False
        
        # Setup logging
        self._setup_logging()
        
        # Initialize Qubes environment if available
        if QUBES_AVAILABLE:
            self.qubes_env = get_qubes_environment()
            self.current_qube = get_current_qube()
        else:
            self.qubes_env = None
            self.current_qube = None
        
        logger.info(f"AI VM initialized with config: {self.config.vm_name}")
    
    def _setup_logging(self) -> None:
        """Setup logging configuration."""
        log_level = os.environ.get('AI_VM_LOG_LEVEL', 'INFO').upper()
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def initialize(self) -> bool:
        """
        Initialize the AI VM.
        
        This method sets up the AI VM environment, including:
        - Creating necessary directories
        - Initializing RPC server
        - Loading default models
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            logger.warning("AI VM already initialized")
            return True
        
        try:
            logger.info("Initializing AI VM...")
            
            # Create directories
            self._create_directories()
            
            # Initialize RPC server
            if not self._initialize_rpc_server():
                logger.error("Failed to initialize RPC server")
                return False
            
            # Load default model
            if not self.load_model(self.config.default_model):
                logger.warning(f"Failed to load default model: {self.config.default_model}")
            
            self._initialized = True
            logger.info("AI VM initialization complete")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize AI VM: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def _create_directories(self) -> None:
        """Create necessary directories."""
        directories = [
            self.config.model_dir,
            self.config.cache_dir,
            os.path.join(self.config.cache_dir, 'downloads'),
            os.path.join(self.config.cache_dir, 'tmp'),
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)
            logger.debug(f"Created directory: {directory}")
    
    def _initialize_rpc_server(self) -> bool:
        """
        Initialize the Qubes RPC server.
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        if not QUBES_AVAILABLE:
            logger.warning("Qubes RPC not available, running in standalone mode")
            return True
        
        try:
            # Create RPC server
            self.rpc_server = QubesRPCServer(
                vm_name=self.config.vm_name,
                timeout=self.config.rpc_timeout
            )
            
            # Register RPC handlers
            self._register_rpc_handlers()
            
            # Start RPC server
            if not self.rpc_server.start():
                logger.error("Failed to start RPC server")
                return False
            
            logger.info("Qubes RPC server initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize RPC server: {e}")
            return False
    
    def _register_rpc_handlers(self) -> None:
        """Register RPC handlers for the AI VM."""
        if self.rpc_server is None:
            return
        
        # Register AI-specific RPC handlers
        handlers = {
            'ai.analyze': self.handle_analyze,
            'ai.generate': self.handle_generate,
            'ai.embed': self.handle_embed,
            'ai.classify': self.handle_classify,
            'ai.list_models': self.handle_list_models,
            'ai.load_model': self.handle_load_model,
            'ai.unload_model': self.handle_unload_model,
            'ai.get_status': self.handle_get_status,
        }
        
        for method_name, handler in handlers.items():
            self.rpc_server.register_handler(
                f"open-omniscience.{method_name}",
                handler
            )
            logger.debug(f"Registered RPC handler: open-omniscience.{method_name}")
    
    # ============================================================================
    # Model Management
    # ============================================================================
    
    def load_model(self, model_name: str) -> bool:
        """
        Load an AI model.
        
        Args:
            model_name: Name of the model to load.
        
        Returns:
            True if model loaded successfully, False otherwise.
        """
        if model_name in self.models:
            if self.models[model_name].status == AIModelStatus.READY:
                logger.info(f"Model {model_name} already loaded")
                return True
            elif self.models[model_name].status == AIModelStatus.LOADING:
                logger.info(f"Model {model_name} is already loading")
                return True
        
        # Check if model is configured
        if model_name not in self.config.available_models:
            logger.error(f"Model {model_name} not configured")
            return False
        
        model_config = self.config.available_models[model_name]
        
        try:
            # Update model state
            self.models[model_name] = AIModelState(
                model_name=model_name,
                status=AIModelStatus.LOADING,
                loaded_at=time.time()
            )
            
            logger.info(f"Loading model: {model_name}")
            logger.info(f"  Type: {model_config.model_type}")
            logger.info(f"  Device: {model_config.device}")
            logger.info(f"  Max Tokens: {model_config.max_tokens}")
            
            # Placeholder for actual model loading
            # In production, this would load the actual AI model
            # For example:
            # if model_config.model_type == "text-generation":
            #     from transformers import AutoModelForCausalLM, AutoTokenizer
            #     self._models[model_name] = {
            #         'model': AutoModelForCausalLM.from_pretrained(...),
            #         'tokenizer': AutoTokenizer.from_pretrained(...)
            #     }
            
            # Simulate loading time
            time.sleep(2)
            
            # Update model state
            self.models[model_name].status = AIModelStatus.READY
            self.models[model_name].last_used = time.time()
            
            logger.info(f"Model {model_name} loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model {model_name}: {e}")
            logger.error(traceback.format_exc())
            
            # Update model state with error
            if model_name in self.models:
                self.models[model_name].status = AIModelStatus.ERROR
                self.models[model_name].error_message = str(e)
            
            return False
    
    def unload_model(self, model_name: str) -> bool:
        """
        Unload an AI model.
        
        Args:
            model_name: Name of the model to unload.
        
        Returns:
            True if model unloaded successfully, False otherwise.
        """
        if model_name not in self.models:
            logger.error(f"Model {model_name} not loaded")
            return False
        
        model_state = self.models[model_name]
        
        if model_state.status not in [AIModelStatus.READY, AIModelStatus.ERROR]:
            logger.error(f"Model {model_name} cannot be unloaded in current state: {model_state.status}")
            return False
        
        try:
            logger.info(f"Unloading model: {model_name}")
            
            # Update model state
            model_state.status = AIModelStatus.UNLOADING
            
            # Placeholder for actual model unloading
            # In production, this would unload the model from memory
            # For example:
            # if model_name in self._models:
            #     del self._models[model_name]
            #     import torch
            #     torch.cuda.empty_cache()
            
            # Simulate unloading time
            time.sleep(1)
            
            # Remove model from state
            del self.models[model_name]
            
            logger.info(f"Model {model_name} unloaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unload model {model_name}: {e}")
            logger.error(traceback.format_exc())
            
            # Update model state
            model_state.status = AIModelStatus.ERROR
            model_state.error_message = str(e)
            
            return False
    
    def get_model_status(self, model_name: str) -> Optional[AIModelState]:
        """
        Get the status of a model.
        
        Args:
            model_name: Name of the model.
        
        Returns:
            AIModelState if model exists, None otherwise.
        """
        return self.models.get(model_name)
    
    def list_models(self) -> Dict[str, Dict[str, Any]]:
        """
        List all available and loaded models.
        
        Returns:
            Dictionary of model information.
        """
        result = {}
        
        # Add configured models
        for name, config in self.config.available_models.items():
            result[name] = {
                'configured': True,
                'loaded': name in self.models,
                'type': config.model_type,
                'default': name == self.config.default_model
            }
            
            if name in self.models:
                result[name]['status'] = self.models[name].status.value
        
        return result
    
    # ============================================================================
    # AI Operations
    # ============================================================================
    
    def analyze_content(self, content: str, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Analyze content using AI.
        
        Args:
            content: Content to analyze.
            model_name: Name of the model to use. Uses default if not specified.
        
        Returns:
            Analysis results.
        """
        model_name = model_name or self.config.default_model
        
        # Ensure model is loaded
        if not self._ensure_model_loaded(model_name):
            return {
                'success': False,
                'error': f'Failed to load model: {model_name}',
                'model': model_name
            }
        
        try:
            logger.info(f"Analyzing content with model: {model_name}")
            
            # Placeholder for actual analysis
            # In production, this would use the loaded model to analyze content
            # For example:
            # model = self._models[model_name]['model']
            # tokenizer = self._models[model_name]['tokenizer']
            # inputs = tokenizer(content, return_tensors="pt")
            # outputs = model(**inputs)
            # result = tokenizer.decode(outputs[0].argmax(-1))
            
            # Simulate analysis
            time.sleep(1)
            
            # Generate placeholder analysis
            result = {
                'success': True,
                'model': model_name,
                'content_length': len(content),
                'analysis': {
                    'sentiment': 'neutral',
                    'topics': ['technology', 'ai', 'open-source'],
                    'entities': [],
                    'summary': content[:100] + '...' if len(content) > 100 else content
                },
                'processing_time': 1.0
            }
            
            # Update model usage
            if model_name in self.models:
                self.models[model_name].last_used = time.time()
                self.models[model_name].usage_count += 1
            
            logger.info(f"Content analysis complete: {model_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to analyze content: {e}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'model': model_name
            }
    
    def generate_text(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Generate text using AI.
        
        Args:
            prompt: Prompt for text generation.
            model_name: Name of the model to use. Uses default if not specified.
            max_tokens: Maximum number of tokens to generate.
            temperature: Temperature for sampling.
            top_p: Top-p sampling parameter.
        
        Returns:
            Generated text and metadata.
        """
        model_name = model_name or self.config.default_model
        max_tokens = max_tokens or self.config.available_models.get(
            model_name, AIModelConfig()
        ).max_tokens
        temperature = temperature or self.config.available_models.get(
            model_name, AIModelConfig()
        ).temperature
        top_p = top_p or self.config.available_models.get(
            model_name, AIModelConfig()
        ).top_p
        
        # Ensure model is loaded
        if not self._ensure_model_loaded(model_name):
            return {
                'success': False,
                'error': f'Failed to load model: {model_name}',
                'model': model_name
            }
        
        try:
            logger.info(f"Generating text with model: {model_name}")
            logger.debug(f"  Prompt: {prompt[:100]}...")
            logger.debug(f"  Max Tokens: {max_tokens}")
            logger.debug(f"  Temperature: {temperature}")
            logger.debug(f"  Top-p: {top_p}")
            
            # Placeholder for actual text generation
            # In production, this would use the loaded model to generate text
            # For example:
            # model = self._models[model_name]['model']
            # tokenizer = self._models[model_name]['tokenizer']
            # inputs = tokenizer(prompt, return_tensors="pt")
            # outputs = model.generate(
            #     **inputs,
            #     max_new_tokens=max_tokens,
            #     temperature=temperature,
            #     top_p=top_p
            # )
            # generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            # Simulate generation
            time.sleep(2)
            
            # Generate placeholder response
            generated_text = f"This is a generated response to: {prompt[:50]}..."
            
            result = {
                'success': True,
                'model': model_name,
                'prompt': prompt,
                'generated_text': generated_text,
                'tokens_generated': len(generated_text.split()),
                'max_tokens': max_tokens,
                'temperature': temperature,
                'top_p': top_p,
                'processing_time': 2.0
            }
            
            # Update model usage
            if model_name in self.models:
                self.models[model_name].last_used = time.time()
                self.models[model_name].usage_count += 1
            
            logger.info(f"Text generation complete: {model_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate text: {e}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'model': model_name
            }
    
    def generate_embeddings(
        self,
        text: str,
        model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate embeddings for text.
        
        Args:
            text: Text to generate embeddings for.
            model_name: Name of the embedding model to use.
        
        Returns:
            Embedding vector and metadata.
        """
        # For embeddings, we might use a different default model
        if model_name is None:
            # Find first embedding model in configuration
            for name, config in self.config.available_models.items():
                if config.model_type == "embedding":
                    model_name = name
                    break
            else:
                model_name = self.config.default_model
        
        # Ensure model is loaded
        if not self._ensure_model_loaded(model_name):
            return {
                'success': False,
                'error': f'Failed to load model: {model_name}',
                'model': model_name
            }
        
        try:
            logger.info(f"Generating embeddings with model: {model_name}")
            
            # Placeholder for actual embedding generation
            # In production, this would use an embedding model
            # For example:
            # from sentence_transformers import SentenceTransformer
            # model = self._models[model_name]['model']
            # embeddings = model.encode(text)
            
            # Simulate embedding generation
            time.sleep(1)
            
            # Generate placeholder embeddings (384-dimensional vector)
            embedding_dim = 384
            embeddings = [0.1 * (i % 10) for i in range(embedding_dim)]
            
            result = {
                'success': True,
                'model': model_name,
                'text': text,
                'embedding': embeddings,
                'dimension': embedding_dim,
                'processing_time': 1.0
            }
            
            # Update model usage
            if model_name in self.models:
                self.models[model_name].last_used = time.time()
                self.models[model_name].usage_count += 1
            
            logger.info(f"Embedding generation complete: {model_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to generate embeddings: {e}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'model': model_name
            }
    
    def classify_text(
        self,
        text: str,
        categories: Optional[List[str]] = None,
        model_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Classify text into categories.
        
        Args:
            text: Text to classify.
            categories: List of categories to classify into.
            model_name: Name of the classification model to use.
        
        Returns:
            Classification results.
        """
        # For classification, we might use a different default model
        if model_name is None:
            # Find first classification model in configuration
            for name, config in self.config.available_models.items():
                if config.model_type == "classification":
                    model_name = name
                    break
            else:
                model_name = self.config.default_model
        
        # Ensure model is loaded
        if not self._ensure_model_loaded(model_name):
            return {
                'success': False,
                'error': f'Failed to load model: {model_name}',
                'model': model_name
            }
        
        # Default categories
        if categories is None:
            categories = ['technology', 'science', 'politics', 'sports', 'entertainment', 'business']
        
        try:
            logger.info(f"Classifying text with model: {model_name}")
            
            # Placeholder for actual classification
            # In production, this would use a classification model
            # For example:
            # from transformers import pipeline
            # classifier = self._models[model_name]['model']
            # results = classifier(text, candidate_labels=categories)
            
            # Simulate classification
            time.sleep(1)
            
            # Generate placeholder classification results
            import random
            scores = [random.uniform(0, 1) for _ in categories]
            total = sum(scores)
            normalized_scores = [s / total for s in scores]
            
            # Create results sorted by score
            results = sorted(
                zip(categories, normalized_scores),
                key=lambda x: x[1],
                reverse=True
            )
            
            result = {
                'success': True,
                'model': model_name,
                'text': text,
                'categories': categories,
                'results': [
                    {'label': label, 'score': float(score)} 
                    for label, score in results
                ],
                'top_category': results[0][0] if results else None,
                'top_score': float(results[0][1]) if results else 0.0,
                'processing_time': 1.0
            }
            
            # Update model usage
            if model_name in self.models:
                self.models[model_name].last_used = time.time()
                self.models[model_name].usage_count += 1
            
            logger.info(f"Classification complete: {model_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to classify text: {e}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'model': model_name
            }
    
    def _ensure_model_loaded(self, model_name: str) -> bool:
        """
        Ensure a model is loaded.
        
        Args:
            model_name: Name of the model.
        
        Returns:
            True if model is loaded or was successfully loaded, False otherwise.
        """
        if model_name in self.models:
            if self.models[model_name].status == AIModelStatus.READY:
                return True
            elif self.models[model_name].status == AIModelStatus.LOADING:
                # Wait for loading to complete
                timeout = 300  # 5 minutes
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    if self.models[model_name].status == AIModelStatus.READY:
                        return True
                    elif self.models[model_name].status == AIModelStatus.ERROR:
                        return False
                    time.sleep(1)
                
                logger.error(f"Timeout waiting for model {model_name} to load")
                return False
        
        # Model not loaded, try to load it
        return self.load_model(model_name)
    
    # ============================================================================
    # RPC Handlers
    # ============================================================================
    
    def handle_analyze(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for content analysis.
        
        Args:
            request: RPC request containing content and options.
        
        Returns:
            Analysis results.
        """
        try:
            content = request.get('content', '')
            model_name = request.get('model')
            
            result = self.analyze_content(content, model_name)
            return {'success': True, 'result': result}
            
        except Exception as e:
            logger.error(f"RPC analyze handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_generate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for text generation.
        
        Args:
            request: RPC request containing prompt and options.
        
        Returns:
            Generation results.
        """
        try:
            prompt = request.get('prompt', '')
            model_name = request.get('model')
            max_tokens = request.get('max_tokens')
            temperature = request.get('temperature')
            top_p = request.get('top_p')
            
            result = self.generate_text(
                prompt, model_name, max_tokens, temperature, top_p
            )
            return {'success': True, 'result': result}
            
        except Exception as e:
            logger.error(f"RPC generate handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_embed(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for embedding generation.
        
        Args:
            request: RPC request containing text and options.
        
        Returns:
            Embedding results.
        """
        try:
            text = request.get('text', '')
            model_name = request.get('model')
            
            result = self.generate_embeddings(text, model_name)
            return {'success': True, 'result': result}
            
        except Exception as e:
            logger.error(f"RPC embed handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_classify(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for text classification.
        
        Args:
            request: RPC request containing text, categories, and options.
        
        Returns:
            Classification results.
        """
        try:
            text = request.get('text', '')
            categories = request.get('categories')
            model_name = request.get('model')
            
            result = self.classify_text(text, categories, model_name)
            return {'success': True, 'result': result}
            
        except Exception as e:
            logger.error(f"RPC classify handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_list_models(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for listing models.
        
        Args:
            request: RPC request (unused).
        
        Returns:
            List of available models.
        """
        try:
            models = self.list_models()
            return {'success': True, 'models': models}
            
        except Exception as e:
            logger.error(f"RPC list_models handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_load_model(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for loading a model.
        
        Args:
            request: RPC request containing model name.
        
        Returns:
            Load result.
        """
        try:
            model_name = request.get('model_name', '')
            
            if not model_name:
                return {'success': False, 'error': 'model_name is required'}
            
            result = self.load_model(model_name)
            return {'success': result, 'model_name': model_name}
            
        except Exception as e:
            logger.error(f"RPC load_model handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_unload_model(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for unloading a model.
        
        Args:
            request: RPC request containing model name.
        
        Returns:
            Unload result.
        """
        try:
            model_name = request.get('model_name', '')
            
            if not model_name:
                return {'success': False, 'error': 'model_name is required'}
            
            result = self.unload_model(model_name)
            return {'success': result, 'model_name': model_name}
            
        except Exception as e:
            logger.error(f"RPC unload_model handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def handle_get_status(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        RPC handler for getting AI VM status.
        
        Args:
            request: RPC request (unused).
        
        Returns:
            AI VM status.
        """
        try:
            status = {
                'vm_name': self.config.vm_name,
                'initialized': self._initialized,
                'loaded_models': {
                    name: state.to_dict() 
                    for name, state in self.models.items()
                },
                'config': self.config.to_dict()
            }
            return {'success': True, 'status': status}
            
        except Exception as e:
            logger.error(f"RPC get_status handler failed: {e}")
            return {'success': False, 'error': str(e)}
    
    # ============================================================================
    # Utility Methods
    # ============================================================================
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get the health status of the AI VM.
        
        Returns:
            Health status information.
        """
        return {
            'status': 'healthy' if self._initialized else 'initializing',
            'vm_name': self.config.vm_name,
            'loaded_models': list(self.models.keys()),
            'default_model': self.config.default_model,
            'qubes_environment': self.qubes_env is not None
        }
    
    def shutdown(self) -> None:
        """Shutdown the AI VM and cleanup resources."""
        logger.info("Shutting down AI VM...")
        
        # Unload all models
        for model_name in list(self.models.keys()):
            self.unload_model(model_name)
        
        # Stop RPC server
        if self.rpc_server:
            self.rpc_server.stop()
            self.rpc_server = None
        
        self._initialized = False
        logger.info("AI VM shutdown complete")


# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Main entry point for AI VM."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Open-Omniscience AI VM Service'
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to configuration file'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        '--standalone',
        action='store_true',
        help='Run in standalone mode (without Qubes)'
    )
    
    args = parser.parse_args()
    
    # Set up logging level
    if args.debug:
        os.environ['AI_VM_LOG_LEVEL'] = 'DEBUG'
    
    # Create AI VM instance
    ai_vm = AIVM()
    
    # Initialize
    if not ai_vm.initialize():
        logger.error("Failed to initialize AI VM")
        return 1
    
    # If running in Qubes, start the RPC server
    if not args.standalone and QUBES_AVAILABLE:
        logger.info("Running in Qubes mode with RPC server")
        
        # Keep the server running
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            ai_vm.shutdown()
    else:
        # Standalone mode - just keep running
        logger.info("Running in standalone mode")
        logger.info("AI VM is ready for local use")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            ai_vm.shutdown()
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
