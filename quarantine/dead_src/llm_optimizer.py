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
LLM Integration Optimization for Open Omniscience

This module provides optimized LLM integration including:
- Model caching and reuse
- Batch processing for efficiency
- Automatic model selection based on task requirements
- Prompt optimization and compression
- Response caching
- Rate limiting and queue management
- Cost tracking and optimization

Author: Ideotion
"""

import asyncio
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache, wraps
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
import threading

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class LLMConfig:
    """Configuration for LLM integration."""
    # Model selection
    default_model: str = "llama3.2:3b"
    available_models: List[str] = field(default_factory=lambda: [
        "llama3.2:3b",
        "llama3.2:11b",
        "llama3.2:70b",
        "mistral:7b",
        "mistral:latest",
        "phi3:3.8b",
        "phi3:14b",
        "qwen2.5:7b",
        "qwen2.5:14b",
        "qwen2.5:72b",
    ])
    
    # Model capabilities and costs
    model_info: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Caching
    cache_enabled: bool = True
    cache_ttl: int = 3600  # 1 hour
    max_cache_size: int = 10000
    
    # Batch processing
    batch_enabled: bool = True
    max_batch_size: int = 10
    batch_timeout: float = 30.0  # seconds
    
    # Rate limiting
    rate_limit: float = 10.0  # requests per minute
    max_concurrent_requests: int = 5
    
    # Retry logic
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # Timeouts
    timeout: float = 60.0  # seconds
    
    # Cost tracking
    track_costs: bool = True
    cost_per_token: Dict[str, float] = field(default_factory=lambda: {
        "input": 0.000001,
        "output": 0.000002,
    })
    
    # Prompt optimization
    optimize_prompts: bool = True
    max_prompt_length: int = 4096
    
    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Create configuration from environment variables."""
        import os
        
        return cls(
            default_model=os.getenv("LLM_DEFAULT_MODEL", "llama3.2:3b"),
            cache_enabled=os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true",
            cache_ttl=int(os.getenv("LLM_CACHE_TTL", "3600")),
            max_cache_size=int(os.getenv("LLM_MAX_CACHE_SIZE", "10000")),
            batch_enabled=os.getenv("LLM_BATCH_ENABLED", "true").lower() == "true",
            max_batch_size=int(os.getenv("LLM_MAX_BATCH_SIZE", "10")),
            batch_timeout=float(os.getenv("LLM_BATCH_TIMEOUT", "30.0")),
            rate_limit=float(os.getenv("LLM_RATE_LIMIT", "10.0")),
            max_concurrent_requests=int(os.getenv("LLM_MAX_CONCURRENT", "5")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
            retry_delay=float(os.getenv("LLM_RETRY_DELAY", "2.0")),
            timeout=float(os.getenv("LLM_TIMEOUT", "60.0")),
            track_costs=os.getenv("LLM_TRACK_COSTS", "true").lower() == "true",
            optimize_prompts=os.getenv("LLM_OPTIMIZE_PROMPTS", "true").lower() == "true",
        )
    
    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Get information about a model."""
        if model_name not in self.model_info:
            # Default model info
            self.model_info[model_name] = {
                "name": model_name,
                "context_length": 8192,
                "capabilities": ["text-generation", "chat"],
                "cost_per_input_token": 0.000001,
                "cost_per_output_token": 0.000002,
                "speed": "medium",
                "quality": "high",
            }
        
        return self.model_info[model_name]


# Global configuration
config = LLMConfig.from_env()


# =============================================================================
# Enums
# =============================================================================

class TaskType(str, Enum):
    """Types of LLM tasks."""
    TEXT_GENERATION = "text_generation"
    CHAT = "chat"
    SUMMARIZATION = "summarization"
    ANALYSIS = "analysis"
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    TRANSLATION = "translation"
    EMBEDDING = "embedding"


class ModelCapability(str, Enum):
    """Model capabilities."""
    TEXT_GENERATION = "text-generation"
    CHAT = "chat"
    EMBEDDING = "embedding"
    VISION = "vision"
    AUDIO = "audio"
    CODE = "code"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class LLMRequest:
    """Represents an LLM request."""
    task_type: TaskType
    model: str
    prompt: str
    system_prompt: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    
    # Metadata
    request_id: str = field(default_factory=lambda: f"req_{int(time.time() * 1000)}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def get_cache_key(self) -> str:
        """Generate a cache key for this request."""
        content = f"{self.task_type.value}:{self.model}:{self.prompt}"
        if self.system_prompt:
            content += f":{self.system_prompt}"
        if self.messages:
            content += f":{json.dumps(self.messages, sort_keys=True)}"
        content += f":{json.dumps(self.parameters, sort_keys=True)}"
        
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_type": self.task_type.value,
            "model": self.model,
            "prompt": self.prompt,
            "system_prompt": self.system_prompt,
            "messages": self.messages,
            "parameters": self.parameters,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class LLMResponse:
    """Represents an LLM response."""
    request_id: str
    content: str
    model: str
    finish_reason: str
    usage: Dict[str, int] = field(default_factory=dict)
    
    # Metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    execution_time: float = 0.0
    cached: bool = False
    
    # Cost tracking
    cost: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "content": self.content,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "created_at": self.created_at.isoformat(),
            "execution_time": self.execution_time,
            "cached": self.cached,
            "cost": self.cost,
        }


@dataclass
class ModelStats:
    """Statistics for a model."""
    model_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_execution_time: float = 0.0
    last_used: Optional[datetime] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests
    
    def update(self, success: bool, tokens: int, cost: float, execution_time: float) -> None:
        """Update statistics."""
        self.total_requests += 1
        now = datetime.now(timezone.utc)
        
        if success:
            self.successful_requests += 1
            self.total_tokens += tokens
            self.total_cost += cost
            
            # Update average execution time
            if self.avg_execution_time == 0:
                self.avg_execution_time = execution_time
            else:
                self.avg_execution_time = 0.9 * self.avg_execution_time + 0.1 * execution_time
        else:
            self.failed_requests += 1
        
        self.last_used = now


# =============================================================================
# Model Selector
# =============================================================================

class ModelSelector:
    """
    Selects the best model for a given task based on requirements and constraints.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize the model selector.
        
        Args:
            config: LLM configuration.
        """
        self.config = config or config
        self._model_capabilities: Dict[str, List[ModelCapability]] = {}
    
    def select_model(
        self,
        task_type: TaskType,
        requirements: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Select the best model for a task.
        
        Args:
            task_type: Type of task.
            requirements: Task requirements (e.g., context_length, quality).
            constraints: Constraints (e.g., max_cost, latency).
            
        Returns:
            Selected model name.
        """
        requirements = requirements or {}
        constraints = constraints or {}
        
        # Get candidate models
        candidates = self._get_candidate_models(task_type, requirements)
        
        if not candidates:
            return self.config.default_model
        
        # Filter by constraints
        candidates = self._filter_by_constraints(candidates, constraints)
        
        if not candidates:
            return self.config.default_model
        
        # Rank candidates
        ranked = self._rank_candidates(candidates, task_type, requirements, constraints)
        
        return ranked[0]["model"]
    
    def _get_candidate_models(
        self, 
        task_type: TaskType, 
        requirements: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get candidate models for a task."""
        candidates = []
        
        for model_name in self.config.available_models:
            model_info = self.config.get_model_info(model_name)
            
            # Check if model supports the task type
            if not self._model_supports_task(model_info, task_type):
                continue
            
            # Check requirements
            if not self._model_meets_requirements(model_info, requirements):
                continue
            
            candidates.append({
                "model": model_name,
                "info": model_info,
                "score": 0.0,
            })
        
        return candidates
    
    def _model_supports_task(self, model_info: Dict[str, Any], task_type: TaskType) -> bool:
        """Check if a model supports a task type."""
        capabilities = model_info.get("capabilities", [])
        
        # Map task types to capabilities
        task_capability_map = {
            TaskType.TEXT_GENERATION: ModelCapability.TEXT_GENERATION,
            TaskType.CHAT: ModelCapability.CHAT,
            TaskType.SUMMARIZATION: ModelCapability.TEXT_GENERATION,
            TaskType.ANALYSIS: ModelCapability.TEXT_GENERATION,
            TaskType.CLASSIFICATION: ModelCapability.TEXT_GENERATION,
            TaskType.EXTRACTION: ModelCapability.TEXT_GENERATION,
            TaskType.TRANSLATION: ModelCapability.TEXT_GENERATION,
            TaskType.EMBEDDING: ModelCapability.EMBEDDING,
        }
        
        required_capability = task_capability_map.get(task_type)
        return required_capability in capabilities
    
    def _model_meets_requirements(
        self, 
        model_info: Dict[str, Any], 
        requirements: Dict[str, Any]
    ) -> bool:
        """Check if a model meets the requirements."""
        # Check context length
        if "context_length" in requirements:
            if model_info.get("context_length", 0) < requirements["context_length"]:
                return False
        
        # Check quality
        if "quality" in requirements:
            model_quality = model_info.get("quality", "medium")
            quality_order = ["low", "medium", "high", "very_high"]
            if quality_order.index(model_quality) < quality_order.index(requirements["quality"]):
                return False
        
        # Check speed
        if "speed" in requirements:
            model_speed = model_info.get("speed", "medium")
            speed_order = ["slow", "medium", "fast", "very_fast"]
            if speed_order.index(model_speed) < speed_order.index(requirements["speed"]):
                return False
        
        return True
    
    def _filter_by_constraints(
        self, 
        candidates: List[Dict[str, Any]], 
        constraints: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Filter candidates by constraints."""
        filtered = []
        
        for candidate in candidates:
            model_info = candidate["info"]
            
            # Check max cost
            if "max_cost" in constraints:
                # Estimate cost for a typical request
                estimated_cost = self._estimate_cost(model_info, constraints.get("max_tokens", 512))
                if estimated_cost > constraints["max_cost"]:
                    continue
            
            # Check max latency
            if "max_latency" in constraints:
                # Estimate latency based on model speed
                estimated_latency = self._estimate_latency(model_info)
                if estimated_latency > constraints["max_latency"]:
                    continue
            
            filtered.append(candidate)
        
        return filtered
    
    def _rank_candidates(
        self, 
        candidates: List[Dict[str, Any]], 
        task_type: TaskType, 
        requirements: Dict[str, Any], 
        constraints: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Rank candidates by suitability."""
        for candidate in candidates:
            score = self._calculate_score(
                candidate["info"], task_type, requirements, constraints
            )
            candidate["score"] = score
        
        # Sort by score descending
        return sorted(candidates, key=lambda x: x["score"], reverse=True)
    
    def _calculate_score(
        self, 
        model_info: Dict[str, Any], 
        task_type: TaskType, 
        requirements: Dict[str, Any], 
        constraints: Dict[str, Any]
    ) -> float:
        """Calculate a suitability score for a model."""
        score = 0.0
        
        # Base score
        score += 10.0
        
        # Quality bonus
        quality = model_info.get("quality", "medium")
        quality_scores = {"low": 0, "medium": 5, "high": 10, "very_high": 15}
        score += quality_scores.get(quality, 0)
        
        # Speed bonus (higher is better for most tasks)
        speed = model_info.get("speed", "medium")
        speed_scores = {"slow": 0, "medium": 5, "fast": 10, "very_fast": 15}
        score += speed_scores.get(speed, 0) * 0.5
        
        # Context length bonus
        context_length = model_info.get("context_length", 0)
        if context_length >= 32768:
            score += 10
        elif context_length >= 16384:
            score += 5
        elif context_length >= 8192:
            score += 2
        
        # Cost penalty (lower cost is better)
        cost_per_token = model_info.get("cost_per_input_token", 0)
        if cost_per_token > 0:
            score -= cost_per_token * 1000000  # Normalize
        
        # Task-specific bonuses
        if task_type == TaskType.EMBEDDING:
            if ModelCapability.EMBEDDING in model_info.get("capabilities", []):
                score += 20
        
        return score
    
    def _estimate_cost(self, model_info: Dict[str, Any], tokens: int) -> float:
        """Estimate the cost for a request."""
        input_cost = model_info.get("cost_per_input_token", 0.000001)
        output_cost = model_info.get("cost_per_output_token", 0.000002)
        
        # Assume 1:1 input to output ratio
        return (input_cost + output_cost) * tokens
    
    def _estimate_latency(self, model_info: Dict[str, Any]) -> float:
        """Estimate the latency for a request."""
        speed = model_info.get("speed", "medium")
        latency_map = {
            "slow": 10.0,
            "medium": 5.0,
            "fast": 2.0,
            "very_fast": 1.0,
        }
        return latency_map.get(speed, 5.0)


# Global model selector
model_selector = ModelSelector()


# =============================================================================
# Prompt Optimizer
# =============================================================================

class PromptOptimizer:
    """
    Optimizes prompts for better performance and lower cost.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize the prompt optimizer.
        
        Args:
            config: LLM configuration.
        """
        self.config = config or config
    
    def optimize(
        self, 
        prompt: str, 
        task_type: TaskType, 
        model: Optional[str] = None
    ) -> str:
        """
        Optimize a prompt.
        
        Args:
            prompt: The prompt to optimize.
            task_type: Type of task.
            model: Target model.
            
        Returns:
            Optimized prompt.
        """
        optimized = prompt
        
        # Apply task-specific optimizations
        if task_type == TaskType.SUMMARIZATION:
            optimized = self._optimize_summarization(prompt)
        elif task_type == TaskType.ANALYSIS:
            optimized = self._optimize_analysis(prompt)
        elif task_type == TaskType.CLASSIFICATION:
            optimized = self._optimize_classification(prompt)
        elif task_type == TaskType.EXTRACTION:
            optimized = self._optimize_extraction(prompt)
        
        # Apply general optimizations
        optimized = self._apply_general_optimizations(optimized, model)
        
        # Ensure prompt is within length limits
        if model:
            model_info = self.config.get_model_info(model)
            max_length = model_info.get("context_length", self.config.max_prompt_length)
            optimized = self._truncate_prompt(optimized, max_length)
        
        return optimized
    
    def _optimize_summarization(self, prompt: str) -> str:
        """Optimize a summarization prompt."""
        # Add clear instructions
        if "summarize" not in prompt.lower():
            prompt = f"Please summarize the following text:\n\n{prompt}"
        
        # Add output format instructions
        if "format" not in prompt.lower():
            prompt += "\n\nProvide a concise summary in 3-5 bullet points."
        
        return prompt
    
    def _optimize_analysis(self, prompt: str) -> str:
        """Optimize an analysis prompt."""
        # Add clear instructions
        if "analyze" not in prompt.lower():
            prompt = f"Please analyze the following text:\n\n{prompt}"
        
        # Add structure
        if "structure" not in prompt.lower():
            prompt += "\n\nProvide your analysis with clear sections: Key Points, Insights, Recommendations."
        
        return prompt
    
    def _optimize_classification(self, prompt: str) -> str:
        """Optimize a classification prompt."""
        # Add clear instructions
        if "classify" not in prompt.lower():
            prompt = f"Please classify the following text:\n\n{prompt}"
        
        # Add categories if not specified
        if "categories" not in prompt.lower() and "options" not in prompt.lower():
            prompt += "\n\nChoose from: Positive, Negative, Neutral, Mixed"
        
        # Request structured output
        if "format" not in prompt.lower():
            prompt += "\n\nRespond with only the category name."
        
        return prompt
    
    def _optimize_extraction(self, prompt: str) -> str:
        """Optimize an extraction prompt."""
        # Add clear instructions
        if "extract" not in prompt.lower():
            prompt = f"Please extract the following information:\n\n{prompt}"
        
        # Request structured output
        if "format" not in prompt.lower():
            prompt += "\n\nRespond with a JSON object containing the extracted information."
        
        return prompt
    
    def _apply_general_optimizations(self, prompt: str, model: Optional[str]) -> str:
        """Apply general prompt optimizations."""
        optimized = prompt
        
        # Remove redundant whitespace
        optimized = " ".join(optimized.split())
        
        # Add role instructions if missing
        if not optimized.startswith("You are") and not optimized.startswith("Act as"):
            if model and "llama" in model.lower():
                optimized = f"You are a helpful AI assistant. {optimized}"
        
        return optimized
    
    def _truncate_prompt(self, prompt: str, max_length: int) -> str:
        """Truncate a prompt to fit within length limits."""
        if len(prompt) <= max_length:
            return prompt
        
        # Try to find a good truncation point
        # Look for the last sentence boundary before max_length
        truncated = prompt[:max_length]
        
        # Find last period, exclamation, or question mark
        last_punct = max(
            truncated.rfind("."),
            truncated.rfind("!"),
            truncated.rfind("?"),
        )
        
        if last_punct > max_length * 0.8:  # Only truncate if we can save a significant amount
            truncated = truncated[:last_punct + 1]
        
        # Add ellipsis if truncated
        if len(truncated) < len(prompt):
            truncated += "..."
        
        return truncated
    
    def compress_prompt(self, prompt: str, max_tokens: int) -> str:
        """
        Compress a prompt to fit within token limits.
        
        Args:
            prompt: The prompt to compress.
            max_tokens: Maximum number of tokens.
            
        Returns:
            Compressed prompt.
        """
        # Simple implementation - just truncate
        # In practice, this would use token counting and smart compression
        
        # Estimate tokens (rough approximation: 4 characters per token)
        estimated_tokens = len(prompt) // 4
        
        if estimated_tokens <= max_tokens:
            return prompt
        
        # Calculate max characters
        max_chars = max_tokens * 4
        
        return self._truncate_prompt(prompt, max_chars)


# Global prompt optimizer
prompt_optimizer = PromptOptimizer()


# =============================================================================
# Response Cache
# =============================================================================

class ResponseCache:
    """
    Caches LLM responses to avoid redundant requests.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize the response cache.
        
        Args:
            config: LLM configuration.
        """
        self.config = config or config
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._max_size = self.config.max_cache_size
    
    def get(self, key: str) -> Optional[LLMResponse]:
        """
        Get a cached response.
        
        Args:
            key: Cache key.
            
        Returns:
            Cached response or None.
        """
        with self._lock:
            if key not in self._cache:
                return None
            
            # Check TTL
            if time.time() - self._access_times.get(key, 0) > self.config.cache_ttl:
                del self._cache[key]
                del self._access_times[key]
                return None
            
            # Update access time
            self._access_times[key] = time.time()
            
            # Return cached response
            cached_data = self._cache[key]
            response = LLMResponse(
                request_id=cached_data["request_id"],
                content=cached_data["content"],
                model=cached_data["model"],
                finish_reason=cached_data["finish_reason"],
                usage=cached_data.get("usage", {}),
                created_at=datetime.fromisoformat(cached_data["created_at"]),
                execution_time=cached_data.get("execution_time", 0.0),
                cached=True,
                cost=cached_data.get("cost", 0.0),
            )
            
            return response
    
    def set(self, key: str, response: LLMResponse) -> None:
        """
        Cache a response.
        
        Args:
            key: Cache key.
            response: Response to cache.
        """
        with self._lock:
            # Check if we need to evict old entries
            if len(self._cache) >= self._max_size:
                self._evict_oldest()
            
            # Store response
            self._cache[key] = {
                "request_id": response.request_id,
                "content": response.content,
                "model": response.model,
                "finish_reason": response.finish_reason,
                "usage": response.usage,
                "created_at": response.created_at.isoformat(),
                "execution_time": response.execution_time,
                "cost": response.cost,
            }
            self._access_times[key] = time.time()
    
    def _evict_oldest(self) -> None:
        """Evict the oldest cache entry."""
        if not self._access_times:
            return
        
        # Find oldest entry
        oldest_key = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        
        # Remove it
        del self._cache[oldest_key]
        del self._access_times[oldest_key]
    
    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
    
    def size(self) -> int:
        """Get the cache size."""
        with self._lock:
            return len(self._cache)
    
    def cleanup(self) -> int:
        """
        Clean up expired entries.
        
        Returns:
            Number of entries removed.
        """
        with self._lock:
            removed = 0
            now = time.time()
            
            for key in list(self._access_times.keys()):
                if now - self._access_times[key] > self.config.cache_ttl:
                    del self._cache[key]
                    del self._access_times[key]
                    removed += 1
            
            return removed


# Global response cache
response_cache = ResponseCache()


# =============================================================================
# LLM Client
# =============================================================================

class LLMClient:
    """
    Client for interacting with LLM models.
    """
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        Initialize the LLM client.
        
        Args:
            config: LLM configuration.
        """
        self.config = config or config
        self.model_selector = model_selector
        self.prompt_optimizer = prompt_optimizer
        self.cache = response_cache
        self._stats: Dict[str, ModelStats] = {}
        self._lock = threading.Lock()
        self._rate_limiter = RateLimiter()
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent_requests)
    
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        use_cache: bool = True,
        optimize_prompt: bool = True
    ) -> LLMResponse:
        """
        Generate text from a prompt.
        
        Args:
            prompt: The prompt.
            model: Model to use (defaults to configured default).
            system_prompt: Optional system prompt.
            max_tokens: Maximum tokens to generate.
            temperature: Temperature for sampling.
            top_p: Top-p sampling.
            use_cache: Whether to use cached responses.
            optimize_prompt: Whether to optimize the prompt.
            
        Returns:
            LLMResponse with generated text.
        """
        # Select model
        if model is None:
            model = self.model_selector.select_model(
                TaskType.TEXT_GENERATION,
                requirements={"quality": "high"},
                constraints={"max_cost": 0.01}
            )
        
        # Optimize prompt
        if optimize_prompt:
            prompt = self.prompt_optimizer.optimize(
                prompt, TaskType.TEXT_GENERATION, model
            )
        
        # Create request
        request = LLMRequest(
            task_type=TaskType.TEXT_GENERATION,
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        
        # Check cache
        cache_key = request.get_cache_key()
        if use_cache and self.config.cache_enabled:
            cached = self.cache.get(cache_key)
            if cached:
                return cached
        
        # Rate limit check
        if not self._rate_limiter.acquire(model):
            raise Exception(f"Rate limited for model {model}")
        
        # Execute request
        start_time = time.time()
        
        try:
            response = self._execute_request(request)
            execution_time = time.time() - start_time
            
            # Update rate limiter
            self._rate_limiter.release(model)
            
            # Update stats
            self._update_stats(model, True, response.usage.get("total_tokens", 0), execution_time)
            
            # Cache response
            if use_cache and self.config.cache_enabled:
                self.cache.set(cache_key, response)
            
            return response
            
        except Exception as e:
            # Update rate limiter
            self._rate_limiter.release(model, False)
            
            # Update stats
            self._update_stats(model, False, 0, time.time() - start_time)
            
            raise
    
    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        use_cache: bool = True
    ) -> LLMResponse:
        """
        Send a chat message.
        
        Args:
            messages: List of chat messages.
            model: Model to use.
            max_tokens: Maximum tokens to generate.
            temperature: Temperature for sampling.
            top_p: Top-p sampling.
            use_cache: Whether to use cached responses.
            
        Returns:
            LLMResponse with assistant's reply.
        """
        # Select model
        if model is None:
            model = self.model_selector.select_model(
                TaskType.CHAT,
                requirements={"quality": "high"},
            )
        
        # Create request
        request = LLMRequest(
            task_type=TaskType.CHAT,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
        )
        
        # Check cache
        cache_key = request.get_cache_key()
        if use_cache and self.config.cache_enabled:
            cached = self.cache.get(cache_key)
            if cached:
                return cached
        
        # Rate limit check
        if not self._rate_limiter.acquire(model):
            raise Exception(f"Rate limited for model {model}")
        
        # Execute request
        start_time = time.time()
        
        try:
            response = self._execute_request(request)
            execution_time = time.time() - start_time
            
            # Update rate limiter
            self._rate_limiter.release(model)
            
            # Update stats
            self._update_stats(model, True, response.usage.get("total_tokens", 0), execution_time)
            
            # Cache response
            if use_cache and self.config.cache_enabled:
                self.cache.set(cache_key, response)
            
            return response
            
        except Exception as e:
            # Update rate limiter
            self._rate_limiter.release(model, False)
            
            # Update stats
            self._update_stats(model, False, 0, time.time() - start_time)
            
            raise
    
    def _execute_request(self, request: LLMRequest) -> LLMResponse:
        """
        Execute an LLM request.
        
        Args:
            request: The request to execute.
            
        Returns:
            LLMResponse with the result.
        """
        # Import here to avoid circular imports
        try:
            from src.llm.ollama_integration import generate_with_ollama
            
            # Use Ollama integration
            if request.task_type == TaskType.TEXT_GENERATION:
                result = generate_with_ollama(
                    model=request.model,
                    prompt=request.prompt,
                    system=request.system_prompt,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                )
            elif request.task_type == TaskType.CHAT:
                result = generate_with_ollama(
                    model=request.model,
                    prompt=None,
                    system=request.system_prompt,
                    messages=request.messages,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                )
            else:
                result = generate_with_ollama(
                    model=request.model,
                    prompt=request.prompt,
                    system=request.system_prompt,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    top_p=request.top_p,
                )
            
            # Parse result
            content = result.get("response", "")
            finish_reason = result.get("done", False)
            usage = result.get("usage", {})
            
            # Calculate cost
            cost = self._calculate_cost(request.model, usage)
            
            return LLMResponse(
                request_id=request.request_id,
                content=content,
                model=request.model,
                finish_reason="stop" if finish_reason else "unknown",
                usage=usage,
                execution_time=result.get("total_duration", 0) or 0.0,
                cost=cost,
            )
            
        except ImportError:
            # Fallback to mock implementation
            logger.warning("Ollama integration not available, using mock")
            return self._mock_execute(request)
    
    def _mock_execute(self, request: LLMRequest) -> LLMResponse:
        """Mock execution for testing."""
        import random
        
        # Generate mock response
        content = f"This is a mock response from {request.model} for: {request.prompt[:50]}..."
        
        return LLMResponse(
            request_id=request.request_id,
            content=content,
            model=request.model,
            finish_reason="stop",
            usage={
                "prompt_tokens": random.randint(10, 100),
                "completion_tokens": random.randint(10, 100),
                "total_tokens": random.randint(20, 200),
            },
            execution_time=random.uniform(0.5, 2.0),
            cost=0.0,
        )
    
    def _calculate_cost(self, model: str, usage: Dict[str, int]) -> float:
        """Calculate the cost of a request."""
        if not self.config.track_costs:
            return 0.0
        
        model_info = self.config.get_model_info(model)
        input_cost = model_info.get("cost_per_input_token", self.config.cost_per_token["input"])
        output_cost = model_info.get("cost_per_output_token", self.config.cost_per_token["output"])
        
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        
        return (input_tokens * input_cost) + (output_tokens * output_cost)
    
    def _update_stats(
        self, 
        model: str, 
        success: bool, 
        tokens: int, 
        execution_time: float
    ) -> None:
        """Update model statistics."""
        with self._lock:
            if model not in self._stats:
                self._stats[model] = ModelStats(model_name=model)
            
            cost = self._calculate_cost(model, {"prompt_tokens": tokens, "completion_tokens": tokens})
            self._stats[model].update(success, tokens, cost, execution_time)
    
    def get_stats(self, model: Optional[str] = None) -> Union[ModelStats, Dict[str, ModelStats]]:
        """
        Get model statistics.
        
        Args:
            model: Optional model name. If None, returns all stats.
            
        Returns:
            ModelStats or dictionary of all stats.
        """
        with self._lock:
            if model:
                return self._stats.get(model, ModelStats(model_name=model))
            return self._stats.copy()
    
    def list_models(self) -> List[str]:
        """List available models."""
        return self.config.available_models
    
    def get_model_info(self, model: str) -> Dict[str, Any]:
        """Get information about a model."""
        return self.config.get_model_info(model)


class RateLimiter:
    """
    Rate limiter for LLM requests.
    """
    
    def __init__(self):
        """Initialize the rate limiter."""
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}
        self._lock = threading.Lock()
    
    def acquire(self, model: str) -> bool:
        """
        Acquire permission to make a request.
        
        Args:
            model: Model name.
            
        Returns:
            True if permission granted.
        """
        with self._lock:
            now = time.time()
            
            # Get or initialize tokens
            if model not in self._tokens:
                self._tokens[model] = config.rate_limit
                self._last_refill[model] = now
            
            # Refill tokens
            elapsed = now - self._last_refill[model]
            rate = config.rate_limit / 60.0  # Convert to per second
            self._tokens[model] = min(config.rate_limit, self._tokens[model] + elapsed * rate)
            self._last_refill[model] = now
            
            # Try to acquire a token
            if self._tokens[model] >= 1:
                self._tokens[model] -= 1
                return True
            
            return False
    
    def release(self, model: str, success: bool = True) -> None:
        """
        Release after a request.
        
        Args:
            model: Model name.
            success: Whether the request was successful.
        """
        # For now, we don't need to do anything on release
        # The token bucket will refill automatically
        pass


# Global LLM client
llm_client = LLMClient()


# =============================================================================
# Batch Processor
# =============================================================================

class BatchProcessor:
    """
    Processes multiple LLM requests in batches for efficiency.
    """
    
    def __init__(self, client: Optional[LLMClient] = None):
        """
        Initialize the batch processor.
        
        Args:
            client: LLM client to use.
        """
        self.client = client or llm_client
        self.config = self.client.config
    
    def process_batch(
        self,
        requests: List[LLMRequest]
    ) -> List[LLMResponse]:
        """
        Process a batch of requests.
        
        Args:
            requests: List of requests to process.
            
        Returns:
            List of responses.
        """
        if not self.config.batch_enabled or len(requests) == 1:
            # Process individually
            return [self.client._execute_request(req) for req in requests]
        
        # Group by model for batching
        by_model: Dict[str, List[LLMRequest]] = {}
        for req in requests:
            if req.model not in by_model:
                by_model[req.model] = []
            by_model[req.model].append(req)
        
        # Process each model's batch
        responses = []
        for model, model_requests in by_model.items():
            # Check batch size limit
            if len(model_requests) > self.config.max_batch_size:
                # Split into smaller batches
                for i in range(0, len(model_requests), self.config.max_batch_size):
                    batch = model_requests[i:i + self.config.max_batch_size]
                    batch_responses = self._process_model_batch(model, batch)
                    responses.extend(batch_responses)
            else:
                batch_responses = self._process_model_batch(model, model_requests)
                responses.extend(batch_responses)
        
        return responses
    
    def _process_model_batch(
        self, 
        model: str, 
        requests: List[LLMRequest]
    ) -> List[LLMResponse]:
        """Process a batch of requests for a single model."""
        # For now, process individually
        # In a full implementation, this would use the model's batch API
        return [self.client._execute_request(req) for req in requests]


# Global batch processor
batch_processor = BatchProcessor()


# =============================================================================
# Task-Specific Functions
# =============================================================================

def summarize(
    text: str,
    model: Optional[str] = None,
    max_length: int = 200,
    **kwargs
) -> str:
    """
    Summarize text using an LLM.
    
    Args:
        text: Text to summarize.
        model: Model to use.
        max_length: Maximum length of summary.
        **kwargs: Additional arguments.
        
    Returns:
        Summary text.
    """
    prompt = f"Please summarize the following text in {max_length} words or less:\n\n{text}"
    
    response = llm_client.generate(
        prompt=prompt,
        model=model,
        max_tokens=max_length * 2,  # Allow some buffer
        temperature=0.3,  # Lower temperature for more deterministic summaries
        **kwargs
    )
    
    return response.content


def analyze(
    text: str,
    model: Optional[str] = None,
    focus: Optional[str] = None,
    **kwargs
) -> str:
    """
    Analyze text using an LLM.
    
    Args:
        text: Text to analyze.
        model: Model to use.
        focus: Optional focus area for analysis.
        **kwargs: Additional arguments.
        
    Returns:
        Analysis text.
    """
    prompt = f"Please analyze the following text:\n\n{text}"
    
    if focus:
        prompt += f"\n\nFocus on: {focus}"
    
    prompt += "\n\nProvide a detailed analysis with insights and recommendations."
    
    response = llm_client.generate(
        prompt=prompt,
        model=model,
        max_tokens=1024,
        temperature=0.7,
        **kwargs
    )
    
    return response.content


def classify(
    text: str,
    categories: List[str],
    model: Optional[str] = None,
    **kwargs
) -> str:
    """
    Classify text into one of the provided categories.
    
    Args:
        text: Text to classify.
        categories: List of categories to choose from.
        model: Model to use.
        **kwargs: Additional arguments.
        
    Returns:
        Selected category.
    """
    categories_str = ", ".join(categories)
    prompt = f"Please classify the following text into one of these categories: {categories_str}\n\n{text}"
    prompt += "\n\nRespond with only the category name, nothing else."
    
    response = llm_client.generate(
        prompt=prompt,
        model=model,
        max_tokens=50,
        temperature=0.1,  # Very low temperature for classification
        **kwargs
    )
    
    # Clean up response
    category = response.content.strip()
    
    # Find the closest match
    for cat in categories:
        if cat.lower() in category.lower():
            return cat
    
    return category


def extract(
    text: str,
    schema: Dict[str, Any],
    model: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Extract structured data from text.
    
    Args:
        text: Text to extract from.
        schema: Schema defining what to extract.
        model: Model to use.
        **kwargs: Additional arguments.
        
    Returns:
        Extracted data as dictionary.
    """
    schema_str = json.dumps(schema, indent=2)
    prompt = f"Please extract data from the following text according to this schema:\n\n{schema_str}\n\nText:\n{text}"
    prompt += "\n\nRespond with a JSON object containing only the extracted data."
    
    response = llm_client.generate(
        prompt=prompt,
        model=model,
        max_tokens=1024,
        temperature=0.2,  # Low temperature for extraction
        **kwargs
    )
    
    # Parse JSON response
    try:
        # Clean up response
        content = response.content.strip()
        
        # Try to extract JSON from response
        if content.startswith("```json"):
            content = content[7:].strip()
        if content.startswith("```"):
            content = content[3:].strip()
        
        return json.loads(content)
    except json.JSONDecodeError:
        # Return raw response if not valid JSON
        return {"raw_response": response.content}


def chat(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    **kwargs
) -> str:
    """
    Send a chat message.
    
    Args:
        messages: List of chat messages.
        model: Model to use.
        **kwargs: Additional arguments.
        
    Returns:
        Assistant's reply.
    """
    response = llm_client.chat(
        messages=messages,
        model=model,
        **kwargs
    )
    
    return response.content


# =============================================================================
# Async LLM Client
# =============================================================================

class AsyncLLMClient:
    """
    Async version of the LLM client.
    """
    
    def __init__(self, client: Optional[LLMClient] = None):
        """
        Initialize the async LLM client.
        
        Args:
            client: Optional synchronous client to wrap.
        """
        self.client = client or llm_client
        self._executor = ThreadPoolExecutor(max_workers=self.client.config.max_concurrent_requests)
    
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Async generate text."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self.client.generate,
            prompt,
            model,
            **kwargs
        )
    
    async def chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """Async chat."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            self.client.chat,
            messages,
            model,
            **kwargs
        )
    
    async def process_batch(
        self,
        requests: List[LLMRequest]
    ) -> List[LLMResponse]:
        """Async batch processing."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            batch_processor.process_batch,
            requests
        )


# Global async LLM client
async_llm_client = AsyncLLMClient()


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Configuration
    "LLMConfig",
    "config",
    # Enums
    "TaskType",
    "ModelCapability",
    # Data models
    "LLMRequest",
    "LLMResponse",
    "ModelStats",
    # Services
    "ModelSelector",
    "model_selector",
    "PromptOptimizer",
    "prompt_optimizer",
    "ResponseCache",
    "response_cache",
    "LLMClient",
    "llm_client",
    "RateLimiter",
    "BatchProcessor",
    "batch_processor",
    "AsyncLLMClient",
    "async_llm_client",
    # Task-specific functions
    "summarize",
    "analyze",
    "classify",
    "extract",
    "chat",
]
