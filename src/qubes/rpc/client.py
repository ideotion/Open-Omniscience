"""
Qubes RPC Client for Open-Omniscience.

This module provides the client-side of the RPC communication, allowing
components to make requests to other qubes.
"""

import json
import subprocess
import uuid
from typing import Dict, Any, Optional, Union
from dataclasses import dataclass

from src.qubes import get_qubes_environment, RPCCallResult


@dataclass
class RPCClientConfig:
    """Configuration for the RPC client."""
    target_vm: str
    timeout: int = 30
    user: Optional[str] = None
    retry_count: int = 3
    retry_delay: float = 1.0


class QubesRPCClient:
    """
    RPC Client for making requests to other qubes.
    
    This client handles the communication with RPC servers running in other qubes,
    managing timeouts, retries, and error handling.
    """
    
    def __init__(self, config: Optional[RPCClientConfig] = None):
        self.config = config or RPCClientConfig(target_vm='')
        self.qubes_env = get_qubes_environment()
    
    def set_target_vm(self, vm_name: str):
        """Set the target VM for RPC calls."""
        self.config.target_vm = vm_name
    
    def set_timeout(self, timeout: int):
        """Set the timeout for RPC calls."""
        self.config.timeout = timeout
    
    def set_user(self, user: str):
        """Set the user for RPC calls."""
        self.config.user = user
    
    def call(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        retry: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Make an RPC call to the target VM.
        
        Args:
            action: The action to perform
            params: Parameters for the action
            timeout: Override the default timeout
            retry: Override the default retry count
            
        Returns:
            Dictionary containing the response
        """
        if not self.config.target_vm:
            raise ValueError("Target VM not configured")
        
        if not self.qubes_env.is_qubes:
            raise RuntimeError("Not running in Qubes OS")
        
        # Generate request
        request = {
            'action': action,
            'params': params or {},
            'request_id': str(uuid.uuid4())
        }
        
        # Convert to JSON
        request_json = json.dumps(request)
        
        # Make the call with retries
        last_exception = None
        for attempt in range(retry or self.config.retry_count):
            try:
                result = self._make_call(request_json, timeout or self.config.timeout)
                return result
            except Exception as e:
                last_exception = e
                if attempt < (retry or self.config.retry_count) - 1:
                    import time
                    time.sleep(self.config.retry_delay)
        
        # If we get here, all retries failed
        raise last_exception or RuntimeError("RPC call failed")
    
    def _make_call(self, request_json: str, timeout: int) -> Dict[str, Any]:
        """
        Make a single RPC call attempt.
        
        Args:
            request_json: JSON string containing the request
            timeout: Timeout in seconds
            
        Returns:
            Dictionary containing the response
        """
        # Build command
        cmd = ['qvm-run', '-u', self.config.target_vm, '--skip-prepare', '--no-wait']
        
        if self.config.user:
            cmd.extend(['--user', self.config.user])
        
        # We need to pass the request as stdin to the RPC server
        # Use a temporary file or pipe
        import tempfile
        import os
        
        # Create a temporary file with the request
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(request_json)
            temp_file = f.name
        
        try:
            # Run the RPC server script with the request file as stdin
            rpc_server_script = '/opt/open-omniscience/src/qubes/rpc/server.py'
            cmd = [
                'qvm-run', '-u', self.config.target_vm, '--skip-prepare', '--no-wait',
                'python3', rpc_server_script
            ]
            
            result = subprocess.run(
                cmd,
                input=request_json,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Parse response
            if result.returncode != 0:
                raise RuntimeError(f"RPC call failed: {result.stderr}")
            
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                raise RuntimeError(f"Invalid response: {result.stdout}")
        
        finally:
            # Clean up temp file
            try:
                os.unlink(temp_file)
            except OSError as e:
                logger.warning(f"Failed to clean up temp file {temp_file}: {e}")
    
    # Convenience methods for common actions
    
    def ping(self) -> Dict[str, Any]:
        """Ping the target VM."""
        return self.call('ping')
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of the target VM."""
        return self.call('status')
    
    def get_info(self) -> Dict[str, Any]:
        """Get info about the target VM."""
        return self.call('info')
    
    def scrape(self, url: str, depth: int = 1) -> Dict[str, Any]:
        """Request scraping of a URL."""
        return self.call('scrape', {'url': url, 'depth': depth})
    
    def analyze(self, content: str, analysis_type: str) -> Dict[str, Any]:
        """Request analysis of content."""
        return self.call('analyze', {'content': content, 'analysis_type': analysis_type})
    
    def store(self, data: Any, collection: str) -> Dict[str, Any]:
        """Store data in a collection."""
        return self.call('store', {'data': data, 'collection': collection})
    
    def query(self, query: Dict[str, Any], collection: str) -> Dict[str, Any]:
        """Query a collection."""
        return self.call('query', {'query': query, 'collection': collection})
    
    def search(self, query: str, collection: str = 'articles') -> Dict[str, Any]:
        """Search a collection."""
        return self.call('search', {'query': query, 'collection': collection})
    
    def upload_file(self, file_path: str, target_path: Optional[str] = None) -> Dict[str, Any]:
        """Upload a file to the target VM."""
        return self.call('upload', {'file_path': file_path, 'target_path': target_path})
    
    def download_file(self, file_path: str) -> Dict[str, Any]:
        """Download a file from the target VM."""
        return self.call('download', {'file_path': file_path})
    
    def start_job(self, job_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Start a job on the target VM."""
        return self.call('start_job', {'job_type': job_type, 'params': params})
    
    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of a job."""
        return self.call('get_job_status', {'job_id': job_id})
    
    def cancel_job(self, job_id: str) -> Dict[str, Any]:
        """Cancel a job."""
        return self.call('cancel_job', {'job_id': job_id})


class RPCClientPool:
    """
    Pool of RPC clients for different VMs.
    
    Manages multiple RPC clients for different target VMs,
    allowing easy communication between various components.
    """
    
    def __init__(self):
        self.clients: Dict[str, QubesRPCClient] = {}
    
    def get_client(self, vm_name: str) -> QubesRPCClient:
        """Get or create an RPC client for a VM."""
        if vm_name not in self.clients:
            self.clients[vm_name] = QubesRPCClient(
                RPCClientConfig(target_vm=vm_name)
            )
        return self.clients[vm_name]
    
    def __getitem__(self, vm_name: str) -> QubesRPCClient:
        """Get a client by VM name."""
        return self.get_client(vm_name)
    
    def __contains__(self, vm_name: str) -> bool:
        """Check if a client exists for a VM."""
        return vm_name in self.clients


# Global client pool
_client_pool: Optional[RPCClientPool] = None


def get_rpc_client_pool() -> RPCClientPool:
    """Get the global RPC client pool."""
    global _client_pool
    if _client_pool is None:
        _client_pool = RPCClientPool()
    return _client_pool


def get_rpc_client(vm_name: str) -> QubesRPCClient:
    """Get an RPC client for a specific VM."""
    return get_rpc_client_pool()[vm_name]
