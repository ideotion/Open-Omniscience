"""
Qubes RPC Server for Open-Omniscience.

This module implements the server-side of the RPC communication, handling requests
from other qubes and executing the appropriate actions.
"""

import json
import sys
import time
import traceback
from typing import Dict, Any, Callable, Optional, Union
from dataclasses import dataclass, asdict

from src.qubes import get_qubes_environment, QubeInfo


@dataclass
class RPCRequest:
    """Represents an RPC request."""
    action: str
    params: Dict[str, Any] = None
    request_id: Optional[str] = None
    
    def __post_init__(self):
        if self.params is None:
            self.params = {}


@dataclass
class RPCResponse:
    """Represents an RPC response."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    request_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert response to JSON string."""
        return json.dumps(self.to_dict())


class QubesRPCServer:
    """
    RPC Server for handling requests from other qubes.
    
    This server receives JSON-RPC style requests, validates them,
    and dispatches to the appropriate handler methods.
    """
    
    def __init__(self):
        self.handlers: Dict[str, Callable] = {
            # System handlers
            'ping': self.handle_ping,
            'status': self.handle_status,
            'info': self.handle_info,
            
            # Data handlers
            'scrape': self.handle_scrape,
            'analyze': self.handle_analyze,
            'store': self.handle_store,
            'query': self.handle_query,
            'search': self.handle_search,
            
            # File handlers
            'upload': self.handle_upload,
            'download': self.handle_download,
            
            # Management handlers
            'start_job': self.handle_start_job,
            'get_job_status': self.handle_get_job_status,
            'cancel_job': self.handle_cancel_job,
        }
        
        self.qubes_env = get_qubes_environment()
        self.current_qube: Optional[QubeInfo] = None
    
    def initialize(self):
        """Initialize the server."""
        if self.qubes_env.is_qubes:
            self.current_qube = self.qubes_env.current_qube
    
    def handle_request(self, request_data: Union[str, Dict[str, Any]]) -> RPCResponse:
        """
        Handle an incoming RPC request.
        
        Args:
            request_data: JSON string or dictionary containing the request
            
        Returns:
            RPCResponse with the result or error
        """
        try:
            # Parse request
            if isinstance(request_data, str):
                request = self._parse_request(request_data)
            else:
                request = RPCRequest(
                    action=request_data.get('action', ''),
                    params=request_data.get('params', {}),
                    request_id=request_data.get('request_id')
                )
            
            # Validate request
            if not request.action:
                return RPCResponse(
                    success=False,
                    error="Missing 'action' in request",
                    request_id=request.request_id
                )
            
            # Dispatch to handler
            if request.action not in self.handlers:
                return RPCResponse(
                    success=False,
                    error=f"Unknown action: {request.action}",
                    request_id=request.request_id
                )
            
            # Call handler
            try:
                result = self.handlers[request.action](**request.params)
                return RPCResponse(
                    success=True,
                    result=result,
                    request_id=request.request_id
                )
            except Exception as e:
                return RPCResponse(
                    success=False,
                    error=f"Handler error: {str(e)}",
                    request_id=request.request_id
                )
        
        except json.JSONDecodeError as e:
            return RPCResponse(
                success=False,
                error=f"Invalid JSON: {str(e)}"
            )
        except Exception as e:
            return RPCResponse(
                success=False,
                error=f"Internal error: {str(e)}"
            )
    
    def _parse_request(self, request_json: str) -> RPCRequest:
        """Parse a JSON request string."""
        data = json.loads(request_json)
        return RPCRequest(
            action=data.get('action', ''),
            params=data.get('params', {}),
            request_id=data.get('request_id')
        )
    
    # System handlers
    
    def handle_ping(self, **kwargs) -> Dict[str, Any]:
        """Handle ping request."""
        return {
            'message': 'pong',
            'qube': self.current_qube.name if self.current_qube else 'unknown'
        }
    
    def handle_status(self, **kwargs) -> Dict[str, Any]:
        """Handle status request."""
        return {
            'status': 'running',
            'version': '1.0.0',
            'qube': self.current_qube.name if self.current_qube else 'unknown',
            'qube_type': self.current_qube.qube_type if self.current_qube else 'unknown'
        }
    
    def handle_info(self, **kwargs) -> Dict[str, Any]:
        """Handle info request."""
        info = {
            'name': 'Open-Omniscience Qubes RPC Server',
            'version': '1.0.0',
            'qube': self.current_qube.name if self.current_qube else 'unknown',
            'qube_type': self.current_qube.qube_type if self.current_qube else 'unknown',
            'actions': list(self.handlers.keys())
        }
        
        # Add Qubes-specific info
        if self.qubes_env.is_qubes:
            info['all_vms'] = self.qubes_env.list_vms()
        
        return info
    
    # Data handlers
    
    def handle_scrape(self, url: str, depth: int = 1, **kwargs) -> Dict[str, Any]:
        """Handle scrape request."""
        try:
            # Lazy import to avoid circular dependencies
            from src.scraper import scrape_website
            result = scrape_website(url, depth=depth)
            return {'success': True, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_analyze(self, content: str, analysis_type: str, **kwargs) -> Dict[str, Any]:
        """Handle analysis request."""
        try:
            # Lazy import - analysis functions are in pillar3
            # For now, return a placeholder as the actual analysis
            # would need to be implemented based on the specific analysis_type
            result = {
                'content': content[:100] + '...' if len(content) > 100 else content,
                'analysis_type': analysis_type,
                'status': 'placeholder',
                'message': 'Analysis function needs to be implemented based on analysis_type'
            }
            return {'success': True, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_store(self, data: Any, collection: str, **kwargs) -> Dict[str, Any]:
        """Handle store request."""
        try:
            # Lazy import
            from src.database import store_data
            result = store_data(data, collection)
            return {'success': True, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_query(self, query: Dict[str, Any], collection: str, **kwargs) -> Dict[str, Any]:
        """Handle query request."""
        try:
            # Lazy import
            from src.database import query_data
            result = query_data(query, collection)
            return {'success': True, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_search(self, query: str, collection: str = 'articles', **kwargs) -> Dict[str, Any]:
        """Handle search request."""
        try:
            # Lazy import - search is in database module
            from src.database.search import search_collection
            result = search_collection(query, collection)
            return {'success': True, 'result': result}
        except ImportError:
            # Fallback if database.search doesn't exist
            try:
                from src.database import search_collection
                result = search_collection(query, collection)
                return {'success': True, 'result': result}
            except (ImportError, AttributeError):
                # Return placeholder if search not implemented
                return {'success': True, 'result': {'query': query, 'collection': collection, 'message': 'Search function placeholder'}}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    # File handlers
    
    def handle_upload(self, file_path: str, target_path: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Handle file upload request."""
        try:
            import os
            from pathlib import Path
            
            # Validate file exists
            if not os.path.exists(file_path):
                return {'success': False, 'error': f'File not found: {file_path}'}
            
            # Get target path
            if target_path is None:
                target_path = os.path.join('/tmp', os.path.basename(file_path))
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # Copy file
            with open(file_path, 'rb') as src, open(target_path, 'wb') as dst:
                dst.write(src.read())
            
            return {
                'success': True,
                'source': file_path,
                'target': target_path,
                'size': os.path.getsize(target_path)
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_download(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """Handle file download request."""
        try:
            import os
            
            # Validate file exists
            if not os.path.exists(file_path):
                return {'success': False, 'error': f'File not found: {file_path}'}
            
            # Read file
            with open(file_path, 'rb') as f:
                content = f.read()
            
            return {
                'success': True,
                'file': file_path,
                'size': len(content),
                'content': content.hex()  # Return as hex to avoid encoding issues
            }
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    # Management handlers
    
    def handle_start_job(self, job_type: str, params: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Handle job start request."""
        try:
            # Lazy import - use BatchProcessor from pipeline
            from src.pipeline.batch import BatchProcessor
            processor = BatchProcessor()
            # For now, return a placeholder job ID
            # Actual implementation would start a real job
            job_id = f"job_{job_type}_{int(time.time())}"
            result = {'job_id': job_id, 'status': 'queued', 'type': job_type, 'params': params}
            return {'success': True, 'job_id': job_id, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_get_job_status(self, job_id: str, **kwargs) -> Dict[str, Any]:
        """Handle job status request."""
        try:
            # Lazy import - use BatchProcessor
            from src.pipeline.batch import BatchProcessor
            processor = BatchProcessor()
            # For now, return placeholder status
            # Actual implementation would check real job status
            result = {'job_id': job_id, 'status': 'running', 'progress': 0}
            return {'success': True, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}
    
    def handle_cancel_job(self, job_id: str, **kwargs) -> Dict[str, Any]:
        """Handle job cancel request."""
        try:
            # Lazy import - use BatchProcessor
            from src.pipeline.batch import BatchProcessor
            processor = BatchProcessor()
            # For now, return placeholder
            # Actual implementation would cancel the job
            result = {'job_id': job_id, 'status': 'cancelled', 'cancelled_at': int(time.time())}
            return {'success': True, 'result': result}
        except Exception as e:
            return {'success': False, 'error': str(e), 'traceback': traceback.format_exc()}


def main():
    """Main entry point for the RPC server."""
    server = QubesRPCServer()
    server.initialize()
    
    # Read request from stdin
    try:
        request_data = sys.stdin.read()
        
        # Process request
        response = server.handle_request(request_data)
        
        # Output response
        print(response.to_json())
        
    except Exception as e:
        # Output error response
        error_response = RPCResponse(
            success=False,
            error=f"Server error: {str(e)}"
        )
        print(error_response.to_json())
        sys.exit(1)


if __name__ == '__main__':
    main()
