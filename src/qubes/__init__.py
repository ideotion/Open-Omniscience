"""
Qubes-OS specific utilities and detection for Open-Omniscience.

This module provides utilities for detecting and interacting with Qubes OS environments,
including VM detection, RPC communication, and file transfer between qubes.
"""

import os
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass


@dataclass
class QubeInfo:
    """Information about a Qubes OS qube."""
    name: str
    qube_type: str  # AppVM, TemplateVM, ProxyVM, etc.
    template: Optional[str] = None
    label: Optional[str] = None
    netvm: Optional[str] = None
    provides_network: bool = False
    memory: Optional[int] = None
    maxmem: Optional[int] = None
    vcpus: Optional[int] = None


@dataclass
class RPCCallResult:
    """Result of a Qubes RPC call."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error: Optional[str] = None


class QubesEnvironment:
    """
    Main class for interacting with Qubes OS environment.
    
    Provides methods for:
    - Detecting if running in Qubes OS
    - Getting information about the current qube
    - Making RPC calls to other qubes
    - Copying files between qubes
    - Managing qube lifecycle
    """
    
    def __init__(self):
        self._cached_qube_info: Optional[QubeInfo] = None
        self._is_qubes: Optional[bool] = None
    
    @property
    def is_qubes(self) -> bool:
        """Check if running in Qubes OS."""
        if self._is_qubes is None:
            self._is_qubes = (
                os.path.exists('/usr/bin/qvm-run') or
                os.path.exists('/usr/bin/qvm-ls') or
                os.path.exists('/usr/bin/qvm-prefs')
            )
        return self._is_qubes
    
    @property
    def current_qube(self) -> Optional[QubeInfo]:
        """Get information about the current qube."""
        if self._cached_qube_info is None and self.is_qubes:
            self._cached_qube_info = self._get_current_qube_info()
        return self._cached_qube_info
    
    def _get_current_qube_info(self) -> Optional[QubeInfo]:
        """Get detailed information about the current qube."""
        try:
            # Get current qube name
            qube_name = self.get_qube_name()
            if not qube_name:
                return None
            
            # Get all qubes info
            result = self.run_command(['qvm-ls', '--raw-data', '--no-headers'])
            if not result.success:
                return QubeInfo(name=qube_name, qube_type="Unknown")
            
            # Parse output to find current qube
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) >= 2 and parts[0].strip() == qube_name:
                    qube_type = parts[1].strip()
                    template = parts[2].strip() if len(parts) > 2 else None
                    label = parts[3].strip() if len(parts) > 3 else None
                    netvm = parts[4].strip() if len(parts) > 4 else None
                    
                    return QubeInfo(
                        name=qube_name,
                        qube_type=qube_type,
                        template=template if template and template != '-' else None,
                        label=label if label and label != '-' else None,
                        netvm=netvm if netvm and netvm != '-' else None,
                        provides_network=qube_type in ['ProxyVM', 'SysVM']
                    )
            
            return QubeInfo(name=qube_name, qube_type="Unknown")
            
        except Exception:
            return None
    
    def get_qube_name(self) -> Optional[str]:
        """Get the name of the current qube."""
        try:
            # Try using qvm-run with hostname
            result = self.run_command(['qvm-run', '--quiet', 'hostname'], timeout=5)
            if result.success and result.stdout.strip():
                return result.stdout.strip()
            
            # Fallback: parse /proc/1/cmdline
            if os.path.exists('/proc/1/cmdline'):
                with open('/proc/1/cmdline', 'r') as f:
                    cmdline = f.read()
                # Look for qube name in cmdline
                # This is a heuristic and may not work in all cases
                return None
            
            return None
            
        except Exception:
            return None
    
    def is_app_vm(self) -> bool:
        """Check if current qube is an AppVM."""
        info = self.current_qube
        return info is not None and info.qube_type == 'AppVM'
    
    def is_template_vm(self) -> bool:
        """Check if current qube is a TemplateVM."""
        info = self.current_qube
        return info is not None and info.qube_type == 'TemplateVM'
    
    def is_proxy_vm(self) -> bool:
        """Check if current qube is a ProxyVM."""
        info = self.current_qube
        return info is not None and info.qube_type in ['ProxyVM', 'SysVM']
    
    def is_disp_vm(self) -> bool:
        """Check if current qube is a DispVM (Disposable VM)."""
        info = self.current_qube
        return info is not None and 'Disp' in info.qube_type
    
    def run_command(self, command: list, timeout: int = 30) -> RPCCallResult:
        """Run a command in the current qube."""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return RPCCallResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode
            )
        except subprocess.TimeoutExpired:
            return RPCCallResult(
                success=False,
                error=f"Command timed out after {timeout} seconds"
            )
        except Exception as e:
            return RPCCallResult(
                success=False,
                error=str(e)
            )
    
    def qubes_rpc_call(
        self,
        target_vm: str,
        command: Union[str, list],
        timeout: int = 30,
        user: Optional[str] = None
    ) -> RPCCallResult:
        """
        Make a Qubes RPC call to another VM.
        
        Args:
            target_vm: Name of the target VM
            command: Command to run (string or list)
            timeout: Timeout in seconds
            user: User to run the command as
            
        Returns:
            RPCCallResult with the command output
        """
        if not self.is_qubes:
            return RPCCallResult(
                success=False,
                error="Not running in Qubes OS"
            )
        
        try:
            # Build command
            if isinstance(command, str):
                cmd = ['qvm-run', '-u', target_vm, '--skip-prepare', '--no-wait']
                if user:
                    cmd.extend(['--user', user])
                cmd.append(command)
            else:
                cmd = ['qvm-run', '-u', target_vm, '--skip-prepare', '--no-wait']
                if user:
                    cmd.extend(['--user', user])
                cmd.extend(command)
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return RPCCallResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                returncode=result.returncode
            )
            
        except subprocess.TimeoutExpired:
            return RPCCallResult(
                success=False,
                error=f"RPC call timed out after {timeout} seconds"
            )
        except Exception as e:
            return RPCCallResult(
                success=False,
                error=str(e)
            )
    
    def copy_to_vm(
        self,
        target_vm: str,
        source_path: Union[str, Path],
        dest_path: Optional[Union[str, Path]] = None,
        timeout: int = 30
    ) -> bool:
        """
        Copy a file to another VM using qvm-move-to-vm.
        
        Args:
            target_vm: Name of the target VM
            source_path: Path to the source file
            dest_path: Destination path in the target VM (optional)
            timeout: Timeout in seconds
            
        Returns:
            True if copy was successful, False otherwise
        """
        if not self.is_qubes:
            return False
        
        try:
            if dest_path is None:
                dest_path = Path(source_path).name
            
            cmd = ['qvm-move-to-vm', target_vm, str(source_path), str(dest_path)]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return result.returncode == 0
            
        except Exception:
            return False
    
    def copy_from_vm(
        self,
        source_vm: str,
        source_path: Union[str, Path],
        dest_path: Optional[Union[str, Path]] = None,
        timeout: int = 30
    ) -> bool:
        """
        Copy a file from another VM using qvm-move-to-vm.
        
        Note: This requires the source VM to initiate the copy.
        
        Args:
            source_vm: Name of the source VM
            source_path: Path to the source file in the source VM
            dest_path: Destination path in the current VM (optional)
            timeout: Timeout in seconds
            
        Returns:
            True if copy was successful, False otherwise
        """
        if not self.is_qubes:
            return False
        
        try:
            if dest_path is None:
                dest_path = Path(source_path).name
            
            # Use qvm-run to execute qvm-move-to-vm in the source VM
            cmd = [
                'qvm-run', '-u', source_vm, '--skip-prepare', '--no-wait',
                'qvm-move-to-vm', self.get_qube_name() or '',
                str(source_path), str(dest_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return result.returncode == 0
            
        except Exception:
            return False
    
    def list_vms(self, vm_type: Optional[str] = None) -> list:
        """
        List all VMs, optionally filtered by type.
        
        Args:
            vm_type: Optional VM type filter (AppVM, TemplateVM, etc.)
            
        Returns:
            List of VM names
        """
        if not self.is_qubes:
            return []
        
        try:
            result = self.run_command(['qvm-ls', '--raw-data', '--no-headers'])
            if not result.success:
                return []
            
            vms = []
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) >= 2:
                    vm_name = parts[0].strip()
                    qube_type = parts[1].strip()
                    
                    if vm_type is None or qube_type == vm_type:
                        vms.append(vm_name)
            
            return vms
            
        except Exception:
            return []
    
    def get_vm_info(self, vm_name: str) -> Optional[QubeInfo]:
        """
        Get information about a specific VM.
        
        Args:
            vm_name: Name of the VM
            
        Returns:
            QubeInfo object or None if VM not found
        """
        if not self.is_qubes:
            return None
        
        try:
            result = self.run_command(['qvm-ls', '--raw-data', '--no-headers'])
            if not result.success:
                return None
            
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split('|')
                if len(parts) >= 2 and parts[0].strip() == vm_name:
                    qube_type = parts[1].strip()
                    template = parts[2].strip() if len(parts) > 2 else None
                    label = parts[3].strip() if len(parts) > 3 else None
                    netvm = parts[4].strip() if len(parts) > 4 else None
                    
                    return QubeInfo(
                        name=vm_name,
                        qube_type=qube_type,
                        template=template if template and template != '-' else None,
                        label=label if label and label != '-' else None,
                        netvm=netvm if netvm and netvm != '-' else None,
                        provides_network=qube_type in ['ProxyVM', 'SysVM']
                    )
            
            return None
            
        except Exception:
            return None
    
    def vm_exists(self, vm_name: str) -> bool:
        """Check if a VM exists."""
        return vm_name in self.list_vms()
    
    def start_vm(self, vm_name: str, timeout: int = 60) -> bool:
        """Start a VM."""
        if not self.is_qubes:
            return False
        
        try:
            result = self.run_command(['qvm-start', vm_name], timeout=timeout)
            return result.success
        except Exception:
            return False
    
    def stop_vm(self, vm_name: str, timeout: int = 60, force: bool = False) -> bool:
        """Stop a VM."""
        if not self.is_qubes:
            return False
        
        try:
            cmd = ['qvm-shutdown', vm_name]
            if force:
                cmd.append('--force')
            result = self.run_command(cmd, timeout=timeout)
            return result.success
        except Exception:
            return False
    
    def run_in_vm(
        self,
        vm_name: str,
        command: Union[str, list],
        timeout: int = 30,
        user: Optional[str] = None
    ) -> RPCCallResult:
        """
        Run a command in a specific VM.
        
        Args:
            vm_name: Name of the VM
            command: Command to run
            timeout: Timeout in seconds
            user: User to run the command as
            
        Returns:
            RPCCallResult with the command output
        """
        return self.qubes_rpc_call(vm_name, command, timeout, user)


# Global instance
_qubes_env: Optional[QubesEnvironment] = None


def get_qubes_environment() -> QubesEnvironment:
    """Get the global QubesEnvironment instance."""
    global _qubes_env
    if _qubes_env is None:
        _qubes_env = QubesEnvironment()
    return _qubes_env


def is_qubes_os() -> bool:
    """Check if running in Qubes OS."""
    return get_qubes_environment().is_qubes


def get_current_qube() -> Optional[QubeInfo]:
    """Get information about the current qube."""
    return get_qubes_environment().current_qube


def qubes_rpc_call(
    target_vm: str,
    command: Union[str, list],
    timeout: int = 30,
    user: Optional[str] = None
) -> RPCCallResult:
    """Make a Qubes RPC call to another VM."""
    return get_qubes_environment().qubes_rpc_call(target_vm, command, timeout, user)


def copy_to_vm(
    target_vm: str,
    source_path: Union[str, Path],
    dest_path: Optional[Union[str, Path]] = None,
    timeout: int = 30
) -> bool:
    """Copy a file to another VM."""
    return get_qubes_environment().copy_to_vm(target_vm, source_path, dest_path, timeout)


def copy_from_vm(
    source_vm: str,
    source_path: Union[str, Path],
    dest_path: Optional[Union[str, Path]] = None,
    timeout: int = 30
) -> bool:
    """Copy a file from another VM."""
    return get_qubes_environment().copy_from_vm(source_vm, source_path, dest_path, timeout)
