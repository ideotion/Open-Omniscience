"""
Model Manager for Local LLM Support
Handles model downloading, management, and verification
"""

import os
import subprocess
import shutil
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import requests

from .config import get_llm_config, ModelConfig
from .exceptions import (
    OllamaNotInstalledError,
    OllamaNotRunningError,
    ModelNotFoundError,
    ModelDownloadError,
    InvalidModelConfigError
)


class ModelManager:
    """Manages local LLM models via Ollama"""
    
    def __init__(self, config=None):
        self.config = config or get_llm_config()
        self._ensure_model_library_path()
    
    def _ensure_model_library_path(self):
        """Ensure the model library directory exists"""
        Path(self.config.model_library_path).mkdir(parents=True, exist_ok=True)
    
    def is_ollama_installed(self) -> bool:
        """Check if Ollama is installed on the system"""
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
    
    def is_ollama_running(self) -> bool:
        """Check if Ollama server is running"""
        try:
            response = requests.get(
                f"{self.config.ollama.base_url}/api/tags",
                timeout=5
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def start_ollama(self) -> bool:
        """Start Ollama server if not running"""
        if self.is_ollama_running():
            return True
        
        if not self.is_ollama_installed():
            raise OllamaNotInstalledError()
        
        try:
            # Start Ollama in background
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            # Wait for server to start
            max_attempts = 10
            for _ in range(max_attempts):
                if self.is_ollama_running():
                    return True
                time.sleep(2)
            
            raise OllamaNotRunningError(
                "Ollama server failed to start within the expected time."
            )
        except Exception as e:
            raise OllamaNotRunningError(f"Failed to start Ollama: {str(e)}")
    
    def stop_ollama(self) -> bool:
        """Stop Ollama server"""
        try:
            subprocess.run(
                ["pkill", "ollama"],
                capture_output=True
            )
            return True
        except Exception:
            return False
    
    def list_local_models(self) -> List[str]:
        """List all locally available models"""
        if not self.is_ollama_installed():
            return []
            
        if not self.is_ollama_running():
            try:
                self.start_ollama()
            except (OllamaNotInstalledError, OllamaNotRunningError):
                return []
        
        try:
            response = requests.get(
                f"{self.config.ollama.base_url}/api/tags"
            )
            if response.status_code == 200:
                data = response.json()
                return [model["name"] for model in data.get("models", [])]
            return []
        except requests.exceptions.RequestException:
            return []
    
    def list_remote_models(self) -> List[Dict]:
        """List available models from Ollama registry"""
        try:
            response = requests.get(
                "https://registry.ollama.ai/api/v1/models"
            )
            if response.status_code == 200:
                return response.json().get("models", [])
            return []
        except requests.exceptions.RequestException:
            return []
    
    def is_model_downloaded(self, model_id: str) -> bool:
        """Check if a model is already downloaded"""
        local_models = self.list_local_models()
        return model_id in local_models
    
    def get_model_info(self, model_id: str) -> Optional[Dict]:
        """Get detailed information about a model"""
        if not self.is_ollama_running():
            self.start_ollama()
        
        try:
            response = requests.get(
                f"{self.config.ollama.base_url}/api/show",
                params={"name": model_id}
            )
            if response.status_code == 200:
                return response.json()
            return None
        except requests.exceptions.RequestException:
            return None
    
    def download_model(self, model_id: str, show_progress: bool = True) -> bool:
        """Download a model from Ollama registry"""
        if not self.is_ollama_installed():
            raise OllamaNotInstalledError()
        
        if not self.is_ollama_running():
            self.start_ollama()
        
        if self.is_model_downloaded(model_id):
            return True
        
        try:
            # Use ollama pull command
            cmd = ["ollama", "pull", model_id]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Stream output if progress is requested
            if show_progress:
                for line in process.stdout:
                    print(line.strip())
            
            process.wait()
            
            if process.returncode != 0:
                error = process.stderr.read()
                raise ModelDownloadError(model_id, error)
            
            return True
        except subprocess.CalledProcessError as e:
            raise ModelDownloadError(model_id, str(e))
        except Exception as e:
            raise ModelDownloadError(model_id, str(e))
    
    def remove_model(self, model_id: str) -> bool:
        """Remove a downloaded model"""
        try:
            result = subprocess.run(
                ["ollama", "rm", model_id],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def get_model_size(self, model_id: str) -> Optional[float]:
        """Get the size of a model in GB"""
        info = self.get_model_info(model_id)
        if info and "size" in info:
            # Size is in bytes, convert to GB
            return info["size"] / (1024 ** 3)
        return None
    
    def verify_model_integrity(self, model_id: str) -> bool:
        """Verify the integrity of a downloaded model"""
        info = self.get_model_info(model_id)
        if not info:
            return False
        
        # Check if model files exist and are valid
        try:
            response = requests.get(
                f"{self.config.ollama.base_url}/api/show",
                params={"name": model_id}
            )
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def get_models_by_capability(self, capability: str) -> List[ModelConfig]:
        """Get models that support a specific capability"""
        return self.config.get_models_for_capability(capability)
    
    def get_recommended_models(self, task: str = None) -> List[ModelConfig]:
        """Get recommended models for a specific task"""
        if task:
            # Map tasks to capabilities
            task_capabilities = {
                "translation": ["translation"],
                "summarization": ["summarization"],
                "analysis": ["analysis"],
                "text_generation": ["text-generation"],
                "general": ["text-generation", "analysis", "summarization"]
            }
            
            capabilities = task_capabilities.get(task, ["text-generation"])
            models = []
            for cap in capabilities:
                models.extend(self.get_models_by_capability(cap))
            
            # Remove duplicates and sort by size (smallest first for efficiency)
            unique_models = {}
            for model in models:
                if model.name not in unique_models:
                    unique_models[model.name] = model
            
            return sorted(
                unique_models.values(),
                key=lambda x: x.size_gb
            )
        
        # Return all models sorted by size
        return sorted(
            self.config.default_models.values(),
            key=lambda x: x.size_gb
        )
    
    def batch_download_models(self, model_ids: List[str]) -> Dict[str, bool]:
        """Download multiple models in batch"""
        results = {}
        for model_id in model_ids:
            try:
                results[model_id] = self.download_model(model_id)
            except Exception as e:
                results[model_id] = False
                print(f"Failed to download {model_id}: {str(e)}")
        return results
    
    def get_model_directory(self, model_id: str) -> Optional[str]:
        """Get the local directory path for a model"""
        # Ollama stores models in ~/.ollama/models
        home = Path.home()
        model_dir = home / ".ollama" / "models"
        
        # Find the directory for this model
        if model_dir.exists():
            for dir_path in model_dir.iterdir():
                if dir_path.is_dir() and model_id in dir_path.name:
                    return str(dir_path)
        
        return None
    
    def cleanup_unused_models(self, keep_models: List[str] = None) -> int:
        """Remove models that are not in the keep list"""
        if keep_models is None:
            keep_models = []
        
        local_models = self.list_local_models()
        removed_count = 0
        
        for model in local_models:
            if model not in keep_models:
                if self.remove_model(model):
                    removed_count += 1
        
        return removed_count
    
    def get_disk_usage(self) -> Dict[str, float]:
        """Get disk usage for models"""
        usage = {"total_gb": 0.0, "models": {}}
        
        for model_id in self.list_local_models():
            size = self.get_model_size(model_id)
            if size:
                usage["models"][model_id] = size
                usage["total_gb"] += size
        
        return usage
    
    def optimize_storage(self, max_size_gb: float = None) -> Dict:
        """Optimize storage by removing less used models"""
        if max_size_gb is None:
            max_size_gb = 50.0  # Default 50GB limit
        
        usage = self.get_disk_usage()
        current_size = usage["total_gb"]
        
        if current_size <= max_size_gb:
            return {"status": "ok", "message": "Storage is within limits"}
        
        # Sort models by size (largest first) and remove until under limit
        models_by_size = sorted(
            usage["models"].items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        removed = []
        for model_id, size in models_by_size:
            if current_size <= max_size_gb:
                break
            
            if self.remove_model(model_id):
                current_size -= size
                removed.append(model_id)
        
        return {
            "status": "optimized",
            "removed_models": removed,
            "new_size_gb": current_size
        }
