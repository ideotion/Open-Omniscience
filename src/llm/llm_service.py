"""
LLM Service for Open-Omniscience
Main interface for LLM operations: text extraction, analysis, translation, synthesis
"""

import json
import time
from typing import Optional, Dict, List, Any, Union
import requests

from .config import get_llm_config, ModelConfig
from .model_manager import ModelManager
from .exceptions import (
    OllamaNotRunningError,
    ModelNotFoundError,
    LLMTimeoutError,
    LLMProcessingError
)


class LLMService:
    """Main LLM service providing text processing capabilities"""
    
    def __init__(self, model_manager: ModelManager = None, config=None):
        self.config = config or get_llm_config()
        self.model_manager = model_manager or ModelManager(self.config)
    
    def _ensure_ollama_running(self):
        """Ensure Ollama server is running"""
        if not self.model_manager.is_ollama_running():
            self.model_manager.start_ollama()
    
    def _ensure_model_available(self, model_id: str):
        """Ensure the requested model is available"""
        if not self.model_manager.is_model_downloaded(model_id):
            if self.config.ollama.auto_download_models:
                self.model_manager.download_model(model_id)
            else:
                raise ModelNotFoundError(model_id)
    
    def _call_ollama_api(
        self,
        endpoint: str,
        payload: Dict,
        model_id: str = None,
        timeout: int = None
    ) -> Dict:
        """Generic method to call Ollama API"""
        self._ensure_ollama_running()
        
        if model_id:
            self._ensure_model_available(model_id)
        
        timeout = timeout or self.config.ollama.timeout
        url = f"{self.config.ollama.base_url}{endpoint}"
        
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=timeout
            )
            
            if response.status_code != 200:
                error_details = response.text
                raise LLMProcessingError(
                    f"API call to {endpoint}",
                    f"Status {response.status_code}: {error_details}"
                )
            
            return response.json()
        except requests.exceptions.Timeout:
            raise LLMTimeoutError(f"API call to {endpoint}", timeout)
        except requests.exceptions.RequestException as e:
            raise LLMProcessingError(f"API call to {endpoint}", str(e))
    
    def generate_text(
        self,
        prompt: str,
        model_id: str = None,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = None,
        **kwargs
    ) -> str:
        """
        Generate text using the LLM
        
        Args:
            prompt: The user prompt
            model_id: Model to use (defaults to default model)
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters for the API
            
        Returns:
            Generated text
        """
        if model_id is None:
            default_model = self.config.get_default_model()
            if default_model:
                model_id = default_model.model_id
            else:
                model_id = "llama3:8b"  # Fallback
        
        payload = {
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens or self.config.max_tokens,
            }
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        # Merge additional kwargs
        payload.update(kwargs)
        
        result = self._call_ollama_api("/api/generate", payload, model_id)
        
        if "response" in result:
            return result["response"]
        else:
            raise LLMProcessingError(
                "text_generation",
                f"Unexpected response format: {json.dumps(result)}"
            )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str = None,
        temperature: float = 0.7,
        max_tokens: int = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Chat completion using the LLM
        
        Args:
            messages: List of message dictionaries (role: 'user' or 'assistant', content: str)
            model_id: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with response and metadata
        """
        if model_id is None:
            default_model = self.config.get_default_model()
            if default_model:
                model_id = default_model.model_id
            else:
                model_id = "llama3:8b"  # Fallback
        
        payload = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens or self.config.max_tokens,
            }
        }
        
        payload.update(kwargs)
        
        result = self._call_ollama_api("/api/chat", payload, model_id)
        
        if "message" in result and "content" in result["message"]:
            return {
                "response": result["message"]["content"],
                "model": result.get("model", model_id),
                "done": result.get("done", True),
                "total_duration": result.get("total_duration"),
                "load_duration": result.get("load_duration"),
                "prompt_eval_count": result.get("prompt_eval_count"),
                "eval_count": result.get("eval_count")
            }
        else:
            raise LLMProcessingError(
                "chat_completion",
                f"Unexpected response format: {json.dumps(result)}"
            )
    
    def extract_text(
        self,
        content: str,
        model_id: str = None,
        extraction_type: str = "general",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Extract structured text from content
        
        Args:
            content: The content to extract from
            model_id: Model to use
            extraction_type: Type of extraction (general, entities, keywords, etc.)
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with extracted information
        """
        if model_id is None:
            # Use a model optimized for extraction
            extraction_models = self.model_manager.get_models_by_capability("analysis")
            if extraction_models:
                model_id = extraction_models[0].model_id
            else:
                model_id = "llama3:8b"
        
        # Define extraction prompts based on type
        extraction_prompts = {
            "general": "Extract the main text content, removing any HTML tags, advertisements, or boilerplate text. Return only the clean text.",
            "entities": "Extract all named entities (people, organizations, locations, dates) from the text. Return as a JSON list of entities with their types.",
            "keywords": "Extract the main keywords and key phrases from the text. Return as a JSON list of keywords with their importance scores (1-10).",
            "summary": "Extract the main points and create a concise summary of the text. Return as a JSON object with 'summary' and 'key_points' fields.",
            "metadata": "Extract metadata from the text including author, date, title, and source. Return as a JSON object.",
            "quotes": "Extract all direct quotes from the text along with their speakers if available. Return as a JSON list of quote objects.",
            "links": "Extract all URLs and links mentioned in the text. Return as a JSON list of URLs."
        }
        
        prompt = extraction_prompts.get(
            extraction_type,
            extraction_prompts["general"]
        )
        
        user_message = f"Content to extract from:\n\n{content}\n\n{prompt}"
        
        messages = [
            {"role": "system", "content": "You are a text extraction assistant. Extract information accurately and return it in the requested format."},
            {"role": "user", "content": user_message}
        ]
        
        result = self.chat(
            messages=messages,
            model_id=model_id,
            temperature=0.3,  # Lower temperature for more deterministic extraction
            **kwargs
        )
        
        # Try to parse JSON if the extraction type expects it
        if extraction_type in ["entities", "keywords", "summary", "metadata", "quotes", "links"]:
            try:
                import json
                # The response might already be JSON or need parsing
                if result["response"].strip().startswith("{") or result["response"].strip().startswith("["):
                    return {
                        "extraction_type": extraction_type,
                        "data": json.loads(result["response"]),
                        "raw_response": result["response"]
                    }
                else:
                    return {
                        "extraction_type": extraction_type,
                        "data": result["response"],
                        "raw_response": result["response"]
                    }
            except json.JSONDecodeError:
                return {
                    "extraction_type": extraction_type,
                    "data": result["response"],
                    "raw_response": result["response"]
                }
        
        return {
            "extraction_type": extraction_type,
            "data": result["response"],
            "raw_response": result["response"]
        }
    
    def translate_text(
        self,
        text: str,
        target_language: str,
        source_language: str = "auto",
        model_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Translate text to target language
        
        Args:
            text: Text to translate
            target_language: Target language code (e.g., 'en', 'fr', 'es')
            source_language: Source language code (default: auto-detect)
            model_id: Model to use
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with translation and metadata
        """
        if model_id is None:
            # Use a model optimized for translation
            translation_models = self.model_manager.get_models_by_capability("translation")
            if translation_models:
                model_id = translation_models[0].model_id
            else:
                model_id = "llama3:8b"
        
        language_names = {
            "en": "English",
            "fr": "French",
            "es": "Spanish",
            "de": "German",
            "it": "Italian",
            "pt": "Portuguese",
            "ru": "Russian",
            "zh": "Chinese",
            "ja": "Japanese",
            "ar": "Arabic",
            "hi": "Hindi",
            "auto": "auto-detect"
        }
        
        source_lang_name = language_names.get(source_language, source_language)
        target_lang_name = language_names.get(target_language, target_language)
        
        prompt = f"""Translate the following text from {source_lang_name} to {target_lang_name}.

Text to translate:
{text}

Return only the translated text, without any additional commentary or formatting."""
        
        messages = [
            {"role": "system", "content": f"You are a professional translator. Translate text from {source_lang_name} to {target_lang_name} accurately and naturally."},
            {"role": "user", "content": prompt}
        ]
        
        result = self.chat(
            messages=messages,
            model_id=model_id,
            temperature=0.2,  # Lower temperature for more accurate translation
            **kwargs
        )
        
        return {
            "source_language": source_language,
            "target_language": target_language,
            "translation": result["response"],
            "model": result.get("model", model_id)
        }
    
    def analyze_text(
        self,
        text: str,
        analysis_type: str = "comprehensive",
        model_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Analyze text for various characteristics
        
        Args:
            text: Text to analyze
            analysis_type: Type of analysis to perform
            model_id: Model to use
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with analysis results
        """
        if model_id is None:
            analysis_models = self.model_manager.get_models_by_capability("analysis")
            if analysis_models:
                model_id = analysis_models[0].model_id
            else:
                model_id = "llama3:8b"
        
        analysis_prompts = {
            "sentiment": """Analyze the sentiment of the following text. Return a JSON object with:
- sentiment: 'positive', 'negative', or 'neutral'
- confidence: score from 0 to 1
- explanation: brief explanation of the analysis""",
            
            "tone": """Analyze the tone of the following text. Return a JSON object with:
- tones: list of detected tones (e.g., 'formal', 'casual', 'urgent', 'sarcastic')
- primary_tone: the most prominent tone
- confidence: score from 0 to 1""",
            
            "bias": """Analyze the text for potential biases. Return a JSON object with:
- biases: list of detected biases (e.g., 'political', 'gender', 'racial')
- bias_level: 'none', 'low', 'medium', or 'high'
- explanation: explanation of findings""",
            
            "readability": """Analyze the readability of the text. Return a JSON object with:
- flesch_reading_ease: score (higher is easier)
- flesch_kincaid_grade: grade level
- sentence_count: number of sentences
- word_count: number of words
- syllable_count: number of syllables
- average_sentence_length: average words per sentence""",
            
            "emotion": """Analyze the emotional content of the text. Return a JSON object with:
- emotions: dictionary of emotion scores (e.g., {'joy': 0.8, 'anger': 0.1})
- primary_emotion: the strongest emotion
- intensity: overall emotional intensity (0-1)""",
            
            "comprehensive": """Perform a comprehensive analysis of the text. Return a JSON object with:
- sentiment: overall sentiment
- tone: primary tone
- readability: readability metrics
- emotions: emotion scores
- keywords: list of important keywords
- entities: list of named entities
- summary: brief summary of the text""",
            
            "disinformation": """Analyze the text for potential disinformation or misleading content. Return a JSON object with:
- disinformation_risk: 'low', 'medium', or 'high'
- confidence: score from 0 to 1
- red_flags: list of potential issues
- recommendations: suggestions for verification"""
        }
        
        prompt = analysis_prompts.get(
            analysis_type,
            analysis_prompts["comprehensive"]
        )
        
        user_message = f"Text to analyze:\n\n{text}\n\n{prompt}"
        
        messages = [
            {"role": "system", "content": "You are a text analysis expert. Provide accurate and objective analysis of the text."},
            {"role": "user", "content": user_message}
        ]
        
        result = self.chat(
            messages=messages,
            model_id=model_id,
            temperature=0.3,
            **kwargs
        )
        
        try:
            import json
            if result["response"].strip().startswith("{"):
                return {
                    "analysis_type": analysis_type,
                    "results": json.loads(result["response"]),
                    "raw_response": result["response"]
                }
            else:
                return {
                    "analysis_type": analysis_type,
                    "results": {"text": result["response"]},
                    "raw_response": result["response"]
                }
        except json.JSONDecodeError:
            return {
                "analysis_type": analysis_type,
                "results": {"text": result["response"]},
                "raw_response": result["response"]
            }
    
    def synthesize_text(
        self,
        sources: List[Union[str, Dict[str, Any]]],
        synthesis_type: str = "summary",
        model_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Synthesize information from multiple sources
        
        Args:
            sources: List of text strings or dictionaries with 'text' and optional 'metadata'
            synthesis_type: Type of synthesis to perform
            model_id: Model to use
            **kwargs: Additional parameters
            
        Returns:
            Dictionary with synthesized results
        """
        if model_id is None:
            synthesis_models = self.model_manager.get_models_by_capability("synthesis")
            if synthesis_models:
                model_id = synthesis_models[0].model_id
            else:
                model_id = "llama3:8b"
        
        synthesis_prompts = {
            "summary": """Synthesize the following information into a concise summary. Identify key themes, main points, and any contradictions or agreements between sources. Return a JSON object with:
- summary: concise summary of all sources
- key_points: list of main points
- themes: list of identified themes
- contradictions: list of contradictions between sources
- agreements: list of points where sources agree""",
            
            "comparison": """Compare the information from the following sources. Return a JSON object with:
- similarities: list of points where sources agree
- differences: list of differences between sources
- unique_points: list of points unique to each source
- overall_assessment: summary of the comparison""",
            
            "timeline": """Create a chronological timeline from the information in the following sources. Return a JSON object with:
- events: list of events with date, description, and source
- timeline: ordered list of events sorted by date""",
            
            "report": """Create a comprehensive report based on the following sources. Return a JSON object with:
- title: appropriate title for the report
- executive_summary: brief summary
- introduction: introduction to the topic
- main_content: organized content from sources
- conclusion: conclusions and recommendations
- sources_used: list of sources referenced""",
            
            "faq": """Generate a list of frequently asked questions and answers based on the information in the following sources. Return a JSON object with:
- faq: list of Q&A pairs
- categories: suggested categories for the FAQs"""
        }
        
        # Format sources for the prompt
        formatted_sources = []
        for i, source in enumerate(sources, 1):
            if isinstance(source, dict):
                text = source.get("text", "")
                metadata = source.get("metadata", {})
                source_str = f"Source {i}:"
                if metadata:
                    source_str += f" ({', '.join(f'{k}: {v}' for k, v in metadata.items())})\n"
                source_str += f"{text}\n\n"
            else:
                source_str = f"Source {i}:\n{source}\n\n"
            formatted_sources.append(source_str)
        
        prompt = synthesis_prompts.get(
            synthesis_type,
            synthesis_prompts["summary"]
        )
        
        user_message = f"Sources to synthesize:\n\n{''.join(formatted_sources)}\n{prompt}"
        
        messages = [
            {"role": "system", "content": "You are an expert information synthesizer. Combine information from multiple sources into coherent, accurate, and well-structured outputs."},
            {"role": "user", "content": user_message}
        ]
        
        result = self.chat(
            messages=messages,
            model_id=model_id,
            temperature=0.4,
            **kwargs
        )
        
        try:
            import json
            if result["response"].strip().startswith("{"):
                return {
                    "synthesis_type": synthesis_type,
                    "results": json.loads(result["response"]),
                    "raw_response": result["response"]
                }
            else:
                return {
                    "synthesis_type": synthesis_type,
                    "results": {"text": result["response"]},
                    "raw_response": result["response"]
                }
        except json.JSONDecodeError:
            return {
                "synthesis_type": synthesis_type,
                "results": {"text": result["response"]},
                "raw_response": result["response"]
            }
    
    def batch_process(
        self,
        items: List[Union[str, Dict[str, Any]]],
        operation: str,
        model_id: str = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Process multiple items in batch
        
        Args:
            items: List of items to process
            operation: Operation to perform (extract, translate, analyze, synthesize)
            model_id: Model to use
            **kwargs: Additional parameters for the operation
            
        Returns:
            List of results for each item
        """
        results = []
        
        operation_methods = {
            "extract": self.extract_text,
            "translate": self.translate_text,
            "analyze": self.analyze_text,
            "synthesize": self.synthesize_text
        }
        
        method = operation_methods.get(operation, self.analyze_text)
        
        for item in items:
            try:
                if operation == "translate":
                    # For translation, we need special handling
                    result = method(
                        text=item.get("text", item) if isinstance(item, dict) else item,
                        target_language=kwargs.get("target_language", "en"),
                        source_language=kwargs.get("source_language", "auto"),
                        model_id=model_id,
                        **{k: v for k, v in kwargs.items() if k not in ["target_language", "source_language"]}
                    )
                elif operation == "synthesize":
                    # For synthesis, the items are the sources
                    result = method(
                        sources=[item] if not isinstance(item, list) else item,
                        synthesis_type=kwargs.get("synthesis_type", "summary"),
                        model_id=model_id,
                        **{k: v for k, v in kwargs.items() if k != "synthesis_type"}
                    )
                else:
                    # For extract and analyze
                    result = method(
                        content=item.get("text", item) if isinstance(item, dict) else item,
                        model_id=model_id,
                        **kwargs
                    )
                
                results.append({"status": "success", "result": result})
            except Exception as e:
                results.append({"status": "error", "error": str(e)})
        
        return results
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about available models and their capabilities"""
        return {
            "ollama_running": self.model_manager.is_ollama_running(),
            "ollama_installed": self.model_manager.is_ollama_installed(),
            "local_models": self.model_manager.list_local_models(),
            "available_models": [
                {
                    "id": model_id,
                    "name": config.name,
                    "description": config.description,
                    "capabilities": config.capabilities,
                    "size_gb": config.size_gb,
                    "downloaded": self.model_manager.is_model_downloaded(config.model_id)
                }
                for model_id, config in self.config.default_models.items()
            ],
            "config": {
                "base_url": self.config.ollama.base_url,
                "auto_download": self.config.ollama.auto_download_models,
                "model_library_path": self.config.model_library_path
            }
        }
