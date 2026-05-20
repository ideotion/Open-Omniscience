#!/usr/bin/env python3
"""
Open-Omniscience GUI Installer for Debian-based Systems
========================================================

A graphical installer for non-technical users to install Open-Omniscience
on Debian-based Linux systems (Ubuntu, Debian, etc.).

Features:
- Interactive GUI with Tkinter
- System requirements check
- Optional Ollama installation
- Database configuration (SQLite/PostgreSQL)
- Automatic service startup
- Application launcher creation
- Progress tracking

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import os
import sys
import subprocess
import shutil
import stat
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from pathlib import Path
import platform
import socket
import psutil
import json
import webbrowser


class SystemChecker:
    """Check system requirements and dependencies."""
    
    @staticmethod
    def check_root():
        """Check if running as root."""
        return os.geteuid() == 0
    
    @staticmethod
    def check_debian():
        """Check if running on Debian-based system."""
        try:
            with open('/etc/os-release', 'r') as f:
                content = f.read()
                if 'debian' in content.lower() or 'ubuntu' in content.lower():
                    return True
        except FileNotFoundError:
            pass
        return False
    
    @staticmethod
    def check_architecture():
        """Check system architecture."""
        return platform.machine()
    
    @staticmethod
    def check_memory():
        """Check available memory in GB."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return mem.total / (1024**3)
        except:
            # Fallback: try to read from /proc/meminfo
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if line.startswith('MemTotal:'):
                            # MemTotal:       8018840 kB
                            total_kb = int(line.split()[1])
                            return total_kb / (1024 * 1024)  # Convert KB to GB
            except:
                pass
            return 0
    
    @staticmethod
    def check_disk_space(path='/'):
        """Check available disk space in GB."""
        try:
            import psutil
            disk = psutil.disk_usage(path)
            return disk.free / (1024**3)
        except:
            # Fallback: use df command
            try:
                import subprocess
                result = subprocess.run(['df', '-k', path], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if path in line or line.startswith('Filesystem'):
                        continue
                    parts = line.split()
                    if len(parts) >= 4:
                        available_kb = int(parts[3])
                        return available_kb / (1024 * 1024)  # Convert KB to GB
            except:
                pass
            return 0
    
    @staticmethod
    def check_command(cmd):
        """Check if command is available."""
        return shutil.which(cmd) is not None
    
    @staticmethod
    def check_docker():
        """Check Docker installation."""
        return SystemChecker.check_command('docker')
    
    @staticmethod
    def check_docker_compose():
        """Check Docker Compose installation."""
        # Check for docker-compose standalone
        if SystemChecker.check_command('docker-compose'):
            return True
        # Check for docker compose plugin
        if SystemChecker.check_command('docker'):
            try:
                result = subprocess.run(['docker', 'compose', 'version'], 
                                      capture_output=True, text=True, timeout=5)
                return result.returncode == 0
            except:
                pass
        return False
    
    @staticmethod
    def check_git():
        """Check Git installation."""
        return SystemChecker.check_command('git')
    
    @staticmethod
    def check_curl():
        """Check cURL installation."""
        return SystemChecker.check_command('curl')
    
    @staticmethod
    def check_python():
        """Check Python 3.8+ installation."""
        try:
            result = subprocess.run(['python3', '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'],
                                  capture_output=True, text=True)
            version = result.stdout.strip()
            major, minor = map(int, version.split('.'))
            return major >= 3 and minor >= 8
        except:
            return False
    
    @staticmethod
    def check_ollama():
        """Check Ollama installation."""
        return SystemChecker.check_command('ollama')
    
    @staticmethod
    def check_port(port):
        """Check if port is available."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return True
        except:
            return False
    
    @staticmethod
    def get_all_checks():
        """Run all system checks and return results."""
        checks = {
            'is_debian': SystemChecker.check_debian(),
            'is_root': SystemChecker.check_root(),
            'architecture': SystemChecker.check_architecture(),
            'memory_gb': SystemChecker.check_memory(),
            'disk_space_gb': SystemChecker.check_disk_space(),
            'has_docker': SystemChecker.check_docker(),
            'has_docker_compose': SystemChecker.check_docker_compose(),
            'has_git': SystemChecker.check_git(),
            'has_curl': SystemChecker.check_curl(),
            'has_python': SystemChecker.check_python(),
            'has_ollama': SystemChecker.check_ollama(),
            'port_8000_available': SystemChecker.check_port(8000),
            'port_11434_available': SystemChecker.check_port(11434),
        }
        return checks


class InstallerConfig:
    """Configuration for the installer."""
    
    REPO_URL = "https://github.com/ideotion/Open-Omniscience.git"
    REPO_BRANCH = "0.02"
    INSTALL_DIR = os.path.expanduser("~/open-omniscience")
    DEFAULT_DB = "sqlite"
    DEFAULT_MODEL = "gemma4:e2b"
    
    @classmethod
    def get_config(cls):
        """Get current configuration."""
        return {
            'repo_url': cls.REPO_URL,
            'repo_branch': cls.REPO_BRANCH,
            'install_dir': cls.INSTALL_DIR,
            'default_db': cls.DEFAULT_DB,
            'default_model': cls.DEFAULT_MODEL,
        }


class CommandRunner:
    """Run shell commands with output capture."""
    
    # Cache for docker compose command
    _docker_compose_cmd = None
    
    @classmethod
    def get_docker_compose_cmd(cls):
        """Get the correct docker compose command (docker-compose or docker compose)."""
        if cls._docker_compose_cmd is None:
            if SystemChecker.check_command('docker-compose'):
                cls._docker_compose_cmd = 'docker-compose'
            elif SystemChecker.check_command('docker'):
                # Check if docker compose plugin is available
                result = subprocess.run(['docker', 'compose', 'version'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    cls._docker_compose_cmd = 'docker compose'
                else:
                    cls._docker_compose_cmd = 'docker-compose'
            else:
                cls._docker_compose_cmd = 'docker-compose'
        return cls._docker_compose_cmd
    
    @staticmethod
    def run_command(cmd, check=False, capture=True, text=True, sudo=False):
        """Run a command and return result."""
        if sudo and not SystemChecker.check_root():
            cmd = f"sudo {cmd}"
        
        try:
            result = subprocess.run(cmd, shell=True, check=check, 
                                  capture_output=capture, text=text)
            return result
        except subprocess.CalledProcessError as e:
            return e
    
    @staticmethod
    def run_docker_compose(args, check=False, capture=True, text=True, sudo=False):
        """Run docker-compose command, trying both variants."""
        cmd = CommandRunner.get_docker_compose_cmd()
        full_cmd = f"{cmd} {args}"
        return CommandRunner.run_command(full_cmd, check=check, capture=capture, text=text, sudo=sudo)
    
    @staticmethod
    def run_async(cmd, output_callback=None, error_callback=None):
        """Run command asynchronously with callbacks."""
        def run():
            try:
                result = subprocess.run(cmd, shell=True, 
                                      stdout=subprocess.PIPE, 
                                      stderr=subprocess.PIPE,
                                      text=True)
                if output_callback:
                    output_callback(result.stdout)
            except Exception as e:
                if error_callback:
                    error_callback(str(e))
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread


class GUIInstaller:
    """Main GUI installer application."""
    
    # Open-Omniscience ASCII Logo
    LOGO = (
        "                                 .-=+*#%@@@@@@@@@@%#*+-:                                         \n"
        "                            .-+#@@@@@@%%@@@@@@@@@%%%@@@@@@#+:                                   \n"
        "                         -+%@@@#*=:.-*#*#@*-@=+@#*#*-.:-+*%@@@#=:                                \n"
        "                      -*@@%+-.    +%+. *#.  @: .*#..=%+     :=#@@%+:                             \n"
        "                   .+@%*-       :%+##+%*    @:   *%=*#+%-       :=#@%=                           \n"
        "                 :#%+.         -@:   ##+****@#***+#@   .%=          -*%+.                        \n"
        "               :*+.           .@:   :@.     @:     @-   .@:            -**.                      \n"
        "             .=-              *#    *#      @:     *#    *#              .==                     \n"
        "            :-                #%****@%******@#*****%@****%%                 =                    \n"
        "             .=:              *#    *#      @:     +#    +#               --                     \n"
        "               -*=.           :@.   -@      @:     %=   .@-            :++.                      \n"
        "                 -##-          +%.   %*=+**#@#**+=*%    #*          .=%*.                        \n"
        "                   :*@#=.       =%=+#*%#.   @:  .*@*#*=%+        :+%%=.                          \n"
        "                      =#@@*=.    .*%- .#*   @:  +%. :%#:     :=#@@*:                             \n"
        "                        .=#@@@#+-: .+#*=*@=.@--%#=*#+. .:=*%@@%*-                                \n"
        "                            :+#@@@@@%**%@@@@@@@@@%**#%@@@@%*=.                                   \n"
        "                                .-+*%@@@@@@@@@@@@@@@%#+=:                                        \n"
        "                                       .::-----::.                                              \n"
    )
    
    def __init__(self, root):
        self.root = root
        self.root.title("Open-Omniscience Installer")
        self.root.geometry("800x700")
        self.root.resizable(True, True)
        self.root.minsize(800, 700)
        
        # Set window icon (if available)
        try:
            self.root.iconbitmap(default='installer/icon.xbm')
        except:
            pass
        
        # Configuration
        self.config = {
            'install_dir': InstallerConfig.INSTALL_DIR,
            'install_ollama': True,
            'database_type': InstallerConfig.DEFAULT_DB,
            'start_services': True,
            'create_launcher': True,
        }
        
        # System checks
        self.system_checks = SystemChecker.get_all_checks()
        
        # Next page target
        self.next_page_target = None
        
        # Setup UI
        self.setup_styles()
        self.create_widgets()
        self.show_welcome_page()
    
    def setup_styles(self):
        """Setup custom styles."""
        self.style = ttk.Style()
        self.style.configure('TFrame', background='#f0f0f0')
        self.style.configure('TLabel', background='#f0f0f0', font=('Arial', 10))
        self.style.configure('TButton', font=('Arial', 10))
        self.style.configure('TCheckbutton', background='#f0f0f0')
        self.style.configure('TRadiobutton', background='#f0f0f0')
        self.style.configure('Header.TLabel', font=('Arial', 14, 'bold'), background='#f0f0f0')
        self.style.configure('Success.TLabel', font=('Arial', 10), foreground='green', background='#f0f0f0')
        self.style.configure('Warning.TLabel', font=('Arial', 10), foreground='orange', background='#f0f0f0')
        self.style.configure('Error.TLabel', font=('Arial', 10), foreground='red', background='#f0f0f0')
    
    def create_widgets(self):
        """Create all widgets."""
        # Main container
        self.main_frame = ttk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Navigation buttons - pack at the bottom
        self.nav_frame = ttk.Frame(self.root)
        self.nav_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=5)
        
        self.prev_button = ttk.Button(self.nav_frame, text="Back", command=self.prev_page)
        self.prev_button.pack(side=tk.LEFT, padx=5)
        
        self.next_button = ttk.Button(self.nav_frame, text="Next", command=self.next_page)
        self.next_button.pack(side=tk.RIGHT, padx=5)
        
        self.cancel_button = ttk.Button(self.nav_frame, text="Cancel", command=self.cancel_installation)
        self.cancel_button.pack(side=tk.RIGHT, padx=5)
        
        # Page containers
        self.pages = {}
        self.current_page = None
        self.page_history = []
    
    def show_page(self, page_name):
        """Show a specific page."""
        # Hide current page
        if self.current_page:
            self.current_page.pack_forget()
        
        # Show new page
        if page_name not in self.pages:
            self.create_page(page_name)
        
        self.pages[page_name].pack(fill=tk.BOTH, expand=True)
        self.current_page = self.pages[page_name]
        
        # Update navigation
        self.update_navigation(page_name)
        
        # Add to history
        if self.page_history and self.page_history[-1] != page_name:
            self.page_history.append(page_name)
        else:
            self.page_history = [page_name]
    
    def prev_page(self):
        """Go to previous page."""
        if len(self.page_history) > 1:
            self.page_history.pop()
            self.show_page(self.page_history[-1])
    
    def next_page(self):
        """Go to next page."""
        if self.next_page_target:
            if callable(self.next_page_target):
                self.next_page_target()
            else:
                self.show_page(self.next_page_target)
    
    def update_navigation(self, page_name):
        """Update navigation buttons based on current page."""
        can_go_back = len(self.page_history) > 1
        
        # Hide all navigation buttons on installing and complete pages
        # (these pages have their own buttons)
        hide_nav = page_name in ['installing', 'complete']
        
        self.prev_button.config(state=tk.DISABLED if hide_nav else (tk.NORMAL if can_go_back else tk.DISABLED))
        
        # Preserve the command when updating state
        current_command = self.next_button.cget('command')
        self.next_button.config(state=tk.DISABLED if hide_nav else tk.NORMAL, command=current_command)
        self.cancel_button.config(state=tk.DISABLED if hide_nav else tk.NORMAL)
    
    def cancel_installation(self):
        """Cancel installation and exit."""
        if messagebox.askyesno("Cancel Installation", "Are you sure you want to cancel the installation?"):
            self.root.destroy()
    
    def create_page(self, page_name):
        """Create a page based on name."""
        if page_name == 'welcome':
            self.pages['welcome'] = self.create_welcome_page()
        elif page_name == 'requirements':
            self.pages['requirements'] = self.create_requirements_page()
        elif page_name == 'options':
            self.pages['options'] = self.create_options_page()
        elif page_name == 'installing':
            self.pages['installing'] = self.create_installing_page()
        elif page_name == 'complete':
            self.pages['complete'] = self.create_complete_page()
    
    def create_welcome_page(self):
        """Create welcome page."""
        frame = ttk.Frame(self.main_frame)
        
        # Header
        header = ttk.Label(frame, text="Welcome to Open-Omniscience", style='Header.TLabel')
        header.pack(pady=10)
        
        # Logo (compact)
        logo_frame = ttk.Frame(frame)
        logo_frame.pack(fill=tk.X, pady=5)
        
        logo_label = ttk.Label(logo_frame, text=self.LOGO, font=('Courier', 7), background='#f0f0f0', anchor=tk.CENTER)
        logo_label.pack()
        
        # Description
        desc = ttk.Label(frame, text="Open-Omniscience is an ethical, open-source global intelligence platform\nfor investigative journalism with local LLM support.", wraplength=700)
        desc.pack(pady=10)
        
        # Features
        features_label = ttk.Label(frame, text="Key Features:", style='Header.TLabel')
        features_label.pack(anchor=tk.W, padx=20, pady=(5, 2))
        
        features = [
            "• Scrape 1900+ news sources (RSS and HTML)",
            "• Advanced search with Boolean operators",
            "• Local LLM support for text analysis",
            "• Data export in CSV, JSON, or SQLite",
            "• Audit logging for transparency",
            "• Ethical scraping with robots.txt compliance",
        ]
        
        for feature in features:
            ttk.Label(frame, text=feature, background='#f0f0f0').pack(anchor=tk.W, padx=40, pady=1)
        
        # Platform notice
        platform_label = ttk.Label(frame, 
                                   text="⚠️  This installer is designed for Debian-based Linux systems only (Ubuntu, Debian, etc.)",
                                   style='Warning.TLabel', wraplength=700)
        platform_label.pack(pady=10)
        
        # Set next page target
        self.next_page_target = 'requirements'
        
        return frame
    
    def create_requirements_page(self):
        """Create system requirements check page."""
        frame = ttk.Frame(self.main_frame)
        
        # Header
        header = ttk.Label(frame, text="System Requirements Check", style='Header.TLabel')
        header.pack(pady=20)
        
        # Description
        desc = ttk.Label(frame, text="Checking your system for required dependencies...", wraplength=700)
        desc.pack(pady=10)
        
        # Requirements list
        requirements_frame = ttk.Frame(frame)
        requirements_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Scrollable area
        canvas = tk.Canvas(requirements_frame)
        scrollbar = ttk.Scrollbar(requirements_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Check requirements
        self.check_system_requirements(scrollable_frame)
        
        # Set next page target
        self.next_page_target = 'options'
        
        return frame
    
    def check_system_requirements(self, parent_frame):
        """Check and display system requirements."""
        checks = self.system_checks
        
        # Critical checks
        critical_checks = [
            ('Debian-based System', checks.get('is_debian', False), True, 
             "This installer only works on Debian-based Linux"),
            ('Python 3.8+', checks.get('has_python', False), True,
             "Required for running Open-Omniscience"),
            ('Git', checks.get('has_git', False), True,
             "Required for cloning the repository"),
            ('cURL', checks.get('has_curl', False), True,
             "Required for downloading dependencies"),
        ]
        
        # Recommended checks
        recommended_checks = [
            ('Docker', checks.get('has_docker', False), False,
             "Required for containerized deployment"),
            ('Docker Compose', checks.get('has_docker_compose', False), False,
             "Required for multi-container deployment"),
            ('Ollama', checks.get('has_ollama', False), False,
             "Required for LLM features"),
        ]
        
        # System resource checks
        resource_checks = [
            (f"Memory ({checks.get('memory_gb', 0):.1f} GB)", checks.get('memory_gb', 0) >= 4, False,
             "Recommended: 4GB+ for core, 16GB+ for LLM"),
            (f"Disk Space ({checks.get('disk_space_gb', 0):.1f} GB)", checks.get('disk_space_gb', 0) >= 10, False,
             "Recommended: 10GB+ for core, 50GB+ for LLM"),
            ('Port 8000 Available', checks.get('port_8000_available', False), False,
             "Required for web interface"),
            ('Port 11434 Available', checks.get('port_11434_available', False), False,
             "Required for Ollama server"),
        ]
        
        # Display critical checks
        ttk.Label(parent_frame, text="Critical Requirements:", style='Header.TLabel').pack(anchor=tk.W, pady=(0, 5))
        
        all_critical_passed = True
        for name, passed, critical, description in critical_checks:
            status = "✓" if passed else "✗"
            color = 'green' if passed else 'red'
            label = ttk.Label(parent_frame, text=f"{status} {name}: {'OK' if passed else 'MISSING'}", 
                             foreground=color, background='#f0f0f0')
            label.pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent_frame, text=f"   {description}", background='#f0f0f0').pack(anchor=tk.W, padx=40)
            
            if critical and not passed:
                all_critical_passed = False
        
        # Display recommended checks
        ttk.Label(parent_frame, text="\nRecommended:", style='Header.TLabel').pack(anchor=tk.W, pady=(10, 5))
        
        for name, passed, critical, description in recommended_checks:
            status = "✓" if passed else "○"
            color = 'green' if passed else 'gray'
            label = ttk.Label(parent_frame, text=f"{status} {name}: {'Installed' if passed else 'Not installed'}", 
                             foreground=color, background='#f0f0f0')
            label.pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent_frame, text=f"   {description}", background='#f0f0f0').pack(anchor=tk.W, padx=40)
        
        # Display resource checks
        ttk.Label(parent_frame, text="\nSystem Resources:", style='Header.TLabel').pack(anchor=tk.W, pady=(10, 5))
        
        for name, passed, critical, description in resource_checks:
            status = "✓" if passed else "⚠"
            color = 'green' if passed else 'orange'
            label = ttk.Label(parent_frame, text=f"{status} {name}", 
                             foreground=color, background='#f0f0f0')
            label.pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent_frame, text=f"   {description}", background='#f0f0f0').pack(anchor=tk.W, padx=40)
        
        # Warning if critical checks failed
        if not all_critical_passed:
            warning = ttk.Label(parent_frame, 
                               text="⚠️  Some critical requirements are missing. Please install them before continuing.",
                               style='Warning.TLabel', wraplength=700)
            warning.pack(pady=20)
            # Preserve the command when disabling
            current_command = self.next_button.cget('command')
            self.next_button.config(state=tk.DISABLED, command=current_command)
    
    def create_options_page(self):
        """Create installation options page."""
        frame = ttk.Frame(self.main_frame)
        
        # Header
        header = ttk.Label(frame, text="Installation Options", style='Header.TLabel')
        header.pack(pady=20)
        
        # Description
        desc = ttk.Label(frame, text="Please select your installation preferences:", wraplength=700)
        desc.pack(pady=10)
        
        # Options frame
        options_frame = ttk.Frame(frame)
        options_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        
        # Installation directory
        dir_frame = ttk.Frame(options_frame)
        dir_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(dir_frame, text="Installation Directory:", background='#f0f0f0').pack(anchor=tk.W)
        self.dir_entry = ttk.Entry(dir_frame, width=50)
        self.dir_entry.insert(0, self.config['install_dir'])
        self.dir_entry.pack(fill=tk.X, padx=20, pady=5)
        
        ttk.Button(dir_frame, text="Browse...", command=self.browse_directory).pack(anchor=tk.W, padx=20)
        
        # Ollama installation
        ollama_frame = ttk.Frame(options_frame)
        ollama_frame.pack(fill=tk.X, pady=10)
        
        self.ollama_var = tk.BooleanVar(value=self.config['install_ollama'])
        ollama_check = ttk.Checkbutton(ollama_frame, text="Install Ollama for LLM support", 
                                      variable=self.ollama_var, onvalue=True, offvalue=False)
        ollama_check.pack(anchor=tk.W, padx=20)
        
        ttk.Label(ollama_frame, text="Ollama enables local LLM features (text generation, translation, analysis)", 
                 background='#f0f0f0', font=('Arial', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Database type
        db_frame = ttk.Frame(options_frame)
        db_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(db_frame, text="Database Type:", background='#f0f0f0').pack(anchor=tk.W, padx=20)
        
        self.db_var = tk.StringVar(value=self.config['database_type'])
        
        sqlite_radio = ttk.Radiobutton(db_frame, text="SQLite (Recommended for beginners)", 
                                       variable=self.db_var, value='sqlite')
        sqlite_radio.pack(anchor=tk.W, padx=40, pady=5)
        
        postgres_radio = ttk.Radiobutton(db_frame, text="PostgreSQL (Recommended for production)", 
                                         variable=self.db_var, value='postgresql')
        postgres_radio.pack(anchor=tk.W, padx=40, pady=5)
        
        ttk.Label(db_frame, text="SQLite is file-based and requires no setup. PostgreSQL requires separate installation.", 
                 background='#f0f0f0', font=('Arial', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Start services
        services_frame = ttk.Frame(options_frame)
        services_frame.pack(fill=tk.X, pady=10)
        
        self.services_var = tk.BooleanVar(value=self.config['start_services'])
        services_check = ttk.Checkbutton(services_frame, text="Start services automatically after installation", 
                                        variable=self.services_var, onvalue=True, offvalue=False)
        services_check.pack(anchor=tk.W, padx=20)
        
        # Create launcher
        launcher_frame = ttk.Frame(options_frame)
        launcher_frame.pack(fill=tk.X, pady=10)
        
        self.launcher_var = tk.BooleanVar(value=self.config['create_launcher'])
        launcher_check = ttk.Checkbutton(launcher_frame, text="Create application launcher", 
                                         variable=self.launcher_var, onvalue=True, offvalue=False)
        launcher_check.pack(anchor=tk.W, padx=20)
        
        ttk.Label(launcher_frame, text="Creates a .desktop file for easy launching from your application menu", 
                 background='#f0f0f0', font=('Arial', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Set next page target
        self.next_page_target = self.start_installation
        
        return frame
    
    def browse_directory(self):
        """Open directory browser."""
        # Simple implementation - in a real app, use tkinter.filedialog
        dir_path = tk.filedialog.askdirectory(initialdir=self.config['install_dir'])
        if dir_path:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, dir_path)
    
    def start_installation(self):
        """Start the installation process."""
        # Save configuration
        self.config['install_dir'] = self.dir_entry.get()
        self.config['install_ollama'] = self.ollama_var.get()
        self.config['database_type'] = self.db_var.get()
        self.config['start_services'] = self.services_var.get()
        self.config['create_launcher'] = self.launcher_var.get()
        
        # Show installing page
        self.show_page('installing')
        
        # Start installation in background
        self.root.after(100, self.run_installation)
    
    def create_installing_page(self):
        """Create installation progress page."""
        frame = ttk.Frame(self.main_frame)
        
        # Header
        header = ttk.Label(frame, text="Installing Open-Omniscience", style='Header.TLabel')
        header.pack(pady=20)
        
        # Logo
        logo_frame = ttk.Frame(frame)
        logo_frame.pack(fill=tk.X, pady=10)
        logo_label = ttk.Label(logo_frame, text=self.LOGO, font=('Courier', 8), background='#f0f0f0', anchor=tk.CENTER)
        logo_label.pack()
        
        # Progress bar
        self.progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=700, mode='determinate')
        self.progress.pack(pady=20)
        self.progress['value'] = 0
        
        # Status label
        self.status_label = ttk.Label(frame, text="Starting installation...", background='#f0f0f0')
        self.status_label.pack(pady=10)
        
        # Log area
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, width=80, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Add initial log message
        self.log_message("Open-Omniscience Installer v1.0")
        self.log_message(f"Installation directory: {self.config['install_dir']}")
        self.log_message(f"Install Ollama: {self.config['install_ollama']}")
        self.log_message(f"Database type: {self.config['database_type']}")
        
        return frame
    
    def log_message(self, message):
        """Add a message to the log."""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def update_progress(self, value, status):
        """Update progress bar and status."""
        self.progress['value'] = value
        self.status_label.config(text=status)
        self.root.update_idletasks()
    
    def run_installation(self):
        """Run the installation steps."""
        try:
            # Step 1: Install dependencies
            self.update_progress(0, "Installing system dependencies...")
            self.log_message("Installing system dependencies...")
            self.install_dependencies()
            self.update_progress(10, "Dependencies installed")
            
            # Step 2: Clone repository
            self.update_progress(20, "Cloning repository...")
            self.log_message("Cloning Open-Omniscience repository...")
            self.clone_repository()
            self.update_progress(30, "Repository cloned")
            
            # Step 3: Install Ollama (if requested)
            if self.config['install_ollama']:
                self.update_progress(40, "Installing Ollama...")
                self.log_message("Installing Ollama for LLM support...")
                self.install_ollama()
                self.update_progress(50, "Ollama installed")
            else:
                self.update_progress(50, "Skipping Ollama installation")
                self.log_message("Skipping Ollama installation (user choice)")
            
            # Step 4: Install Python dependencies
            self.update_progress(60, "Installing Python dependencies...")
            self.log_message("Installing Python dependencies...")
            self.install_python_deps()
            self.update_progress(70, "Python dependencies installed")
            
            # Step 5: Configure environment
            self.update_progress(80, "Configuring environment...")
            self.log_message("Configuring environment...")
            self.configure_environment()
            self.update_progress(90, "Environment configured")
            
            # Step 6: Create launcher (if requested)
            if self.config['create_launcher']:
                self.update_progress(95, "Creating application launcher...")
                self.log_message("Creating application launcher...")
                self.create_launcher()
            
            # Step 7: Start services (if requested)
            if self.config['start_services']:
                self.update_progress(98, "Starting services...")
                self.log_message("Starting Open-Omniscience services...")
                self.start_services(open_browser=True)
            
            self.update_progress(100, "Installation complete!")
            self.log_message("Installation completed successfully!")
            
            # Show completion page
            self.root.after(1000, lambda: self.show_page('complete'))
            
        except Exception as e:
            self.log_message(f"Error: {str(e)}")
            self.update_progress(0, "Installation failed")
            messagebox.showerror("Installation Error", f"An error occurred: {str(e)}")
    
    def install_dependencies(self):
        """Install system dependencies."""
        commands = [
            "sudo apt-get update -qq",
            "sudo apt-get install -y -qq git curl wget ca-certificates gnupg lsb-release",
        ]
        
        for cmd in commands:
            self.log_message(f"Running: {cmd}")
            result = CommandRunner.run_command(cmd, check=False, capture=True, text=True)
            if result.returncode != 0:
                self.log_message(f"Warning: {result.stderr}")
    
    def clone_repository(self):
        """Clone the Open-Omniscience repository."""
        install_dir = self.config['install_dir']
        
        # Check if repository already exists
        git_dir = os.path.join(install_dir, '.git')
        if os.path.exists(git_dir):
            self.log_message("Repository already exists at: " + install_dir)
            # Ask for permission to remove and replace
            response = messagebox.askyesno(
                "Repository Exists",
                f"A repository already exists at:\n{install_dir}\n\n"
                "Would you like to remove the existing repository and download a fresh copy?"
            )
            if response:
                self.log_message("Removing existing repository...")
                # Remove the entire directory
                try:
                    import shutil
                    shutil.rmtree(install_dir)
                    self.log_message("Existing repository removed successfully.")
                except Exception as e:
                    self.log_message(f"Failed to remove existing repository: {str(e)}")
                    raise
            else:
                self.log_message("Using existing repository.")
                os.chdir(install_dir)
                CommandRunner.run_command("git fetch origin")
                CommandRunner.run_command(f"git checkout {InstallerConfig.REPO_BRANCH}")
                CommandRunner.run_command("git pull origin")
                return
        
        # Create directory if it doesn't exist
        os.makedirs(install_dir, exist_ok=True)
        
        # Clone fresh repository
        self.log_message("Cloning repository...")
        CommandRunner.run_command(f"git clone --branch {InstallerConfig.REPO_BRANCH} --depth 1 {InstallerConfig.REPO_URL} {install_dir}")
        
        os.chdir(install_dir)
    
    def install_ollama(self):
        """Install Ollama."""
        if SystemChecker.check_ollama():
            self.log_message("Ollama is already installed")
            return
        
        self.log_message("Downloading and installing Ollama...")
        result = CommandRunner.run_command("curl -fsSL https://ollama.com/install.sh | sh", 
                                          check=False, capture=True, text=True)
        if result.returncode != 0:
            self.log_message(f"Warning: Ollama installation may have failed: {result.stderr}")
        else:
            self.log_message("Ollama installed successfully")
    
    def install_python_deps(self):
        """Install Python dependencies."""
        os.chdir(self.config['install_dir'])
        
        # Create virtual environment
        if not os.path.exists('venv'):
            self.log_message("Creating virtual environment...")
            CommandRunner.run_command("python3 -m venv venv")
        
        # Install dependencies
        self.log_message("Installing core dependencies...")
        CommandRunner.run_command("source venv/bin/activate && pip install --upgrade pip setuptools wheel")
        CommandRunner.run_command("source venv/bin/activate && pip install -r requirements.txt")
        
        if self.config['install_ollama']:
            self.log_message("Installing LLM dependencies...")
            CommandRunner.run_command("source venv/bin/activate && pip install -r requirements-llm.txt")
    
    def configure_environment(self):
        """Configure the environment."""
        os.chdir(self.config['install_dir'])
        
        # Copy example environment file
        if not os.path.exists('.env'):
            if os.path.exists('.env.example'):
                shutil.copy('.env.example', '.env')
                self.log_message("Created .env from .env.example")
        
        # Create data directories
        for dir_name in ['data', 'audit', 'logs']:
            os.makedirs(dir_name, exist_ok=True)
            self.log_message(f"Created directory: {dir_name}")
        
        # Configure database based on selection
        if self.config['database_type'] == 'sqlite':
            self.log_message("Using SQLite database (default)")
        else:
            self.log_message("PostgreSQL selected - you will need to configure it manually")
    
    def create_launcher(self):
        """Create application launcher."""
        install_dir = self.config['install_dir']
        
        # Create .desktop file
        desktop_file = os.path.expanduser("~/.local/share/applications/open-omniscience.desktop")
        os.makedirs(os.path.dirname(desktop_file), exist_ok=True)
        
        dc_cmd = CommandRunner.get_docker_compose_cmd()
        desktop_content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=Open-Omniscience
GenericName=Investigative Journalism Platform
Comment=Ethical Global Intelligence Platform for Investigative Journalism
Exec=bash -c "cd {install_dir} && {dc_cmd} up -d --build && echo 'Waiting for services...' && while ! curl -s http://localhost:8000 > /dev/null 2>&1; do sleep 1; done && xdg-open http://localhost:8000"
Terminal=true
Categories=Development;Journalism;Research;Utility;
StartupWMClass=Open-Omniscience
"""
        
        with open(desktop_file, 'w') as f:
            f.write(desktop_content)
        
        # Make executable
        os.chmod(desktop_file, os.stat(desktop_file).st_mode | stat.S_IEXEC)
        
        # Update desktop database
        if SystemChecker.check_command('update-desktop-database'):
            CommandRunner.run_command("update-desktop-database ~/.local/share/applications")
        
        self.log_message(f"Created desktop launcher at {desktop_file}")
        self.log_message("You can now find 'Open-Omniscience' in your application menu")
    
    def start_services(self, open_browser=True):
        """Start Open-Omniscience services and optionally open browser."""
        os.chdir(self.config['install_dir'])
        
        # Start with Docker Compose
        self.log_message("Starting services with Docker Compose...")
        result = CommandRunner.run_docker_compose("up -d --build", 
                                                  check=False, capture=True, text=True)
        if result.returncode != 0:
            self.log_message(f"Warning: Failed to start services: {result.stderr}")
            # Try to see what containers are running
            result2 = CommandRunner.run_docker_compose("ps", check=False, capture=True, text=True)
            self.log_message(f"Container status:\n{result2.stdout}")
            return False
        
        # Wait a bit for containers to initialize
        self.log_message("Waiting for containers to initialize...")
        self.root.after(10000, lambda: self.check_service_ready(open_browser, attempt=0))
        return True
    
    def check_service_ready(self, open_browser, attempt):
        """Check if service is ready, with non-blocking retry."""
        max_attempts = 24  # 120 seconds / 5 seconds per attempt
        
        # First check if containers are actually running
        result_ps = CommandRunner.run_docker_compose("ps", check=False, capture=True, text=True)
        if result_ps.returncode == 0:
            containers_running = "Up" in result_ps.stdout or "running" in result_ps.stdout.lower()
        else:
            containers_running = False
        
        if not containers_running:
            self.log_message(f"Containers not running. Status:\n{result_ps.stdout}")
            # Try to see logs
            result_logs = CommandRunner.run_docker_compose("logs web", check=False, capture=True, text=True)
            self.log_message(f"Web container logs:\n{result_logs.stdout}")
        
        # Check if the web service is responding
        service_ready = False
        try:
            import requests
            try:
                response = requests.get("http://localhost:8000", timeout=5)
                if response.status_code in [200, 301, 302, 307, 308]:
                    service_ready = True
            except requests.exceptions.RequestException as e:
                self.log_message(f"Connection error: {str(e)}")
        except ImportError:
            # requests not available, use curl
            result = CommandRunner.run_command("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000",
                                              check=False, capture=True, text=True)
            if result.returncode == 0 and '200' in result.stdout:
                service_ready = True
        
        if service_ready:
            self.log_message("Application is ready!")
            if open_browser:
                import webbrowser
                webbrowser.open_new("http://localhost:8000")
            return
        
        # Not ready yet, schedule next check
        if attempt < max_attempts - 1:
            self.log_message(f"Waiting... (attempt {attempt + 1}/{max_attempts})")
            self.root.after(5000, lambda: self.check_service_ready(open_browser, attempt + 1))
        else:
            self.log_message("Warning: Application did not become ready within the timeout period")
            self.log_message("You can manually check if it's running and open http://localhost:8000")
            # Show container logs for debugging
            result_logs = CommandRunner.run_docker_compose("logs web", check=False, capture=True, text=True)
            self.log_message(f"Web container logs:\n{result_logs.stdout}")
    
    def create_complete_page(self):
        """Create installation complete page."""
        frame = ttk.Frame(self.main_frame)
        
        # Header
        header = ttk.Label(frame, text="Installation Complete!", style='Header.TLabel')
        header.pack(pady=10)
        
        # Logo
        logo_frame = ttk.Frame(frame)
        logo_frame.pack(fill=tk.X, pady=5)
        logo_label = ttk.Label(logo_frame, text=self.LOGO, font=('Courier', 7), background='#f0f0f0', anchor=tk.CENTER)
        logo_label.pack()
        
        # Success message
        success = ttk.Label(frame, text="✓ Open-Omniscience has been successfully installed!", 
                           style='Success.TLabel', font=('Arial', 11))
        success.pack(pady=10)
        
        # Status label for launch feedback
        self.launch_status_label = ttk.Label(frame, text="", background='#f0f0f0', foreground='blue')
        self.launch_status_label.pack(pady=5)
        
        # Summary
        summary_frame = ttk.Frame(frame)
        summary_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(summary_frame, text="Installation Summary:", style='Header.TLabel').pack(anchor=tk.W, pady=(0, 5))
        
        summary_items = [
            ("Installation Directory", self.config['install_dir']),
            ("Ollama Installed", "Yes" if self.config['install_ollama'] else "No"),
            ("Database Type", self.config['database_type']),
            ("Services Started", "Yes" if self.config['start_services'] else "No"),
            ("Launcher Created", "Yes" if self.config['create_launcher'] else "No"),
        ]
        
        for label, value in summary_items:
            ttk.Label(summary_frame, text=f"  {label}: {value}", background='#f0f0f0').pack(anchor=tk.W, padx=20, pady=1)
        
        # Next steps
        next_steps_frame = ttk.Frame(frame)
        next_steps_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(next_steps_frame, text="Next Steps:", style='Header.TLabel').pack(anchor=tk.W, pady=(0, 5))
        
        steps = [
            "1. Access the application at: http://localhost:8000",
            "2. If you installed Ollama, download models with: ollama pull gemma4:e2b",
            "3. For LLM support, start with: docker compose -f docker-compose.yml -f docker-compose.llm.yml up -d --build",
            "4. Check the documentation at: https://github.com/ideotion/Open-Omniscience",
        ]
        
        for step in steps:
            ttk.Label(next_steps_frame, text=f"  {step}", background='#f0f0f0').pack(anchor=tk.W, padx=20, pady=1)
        
        # Buttons
        button_frame = ttk.Frame(frame)
        button_frame.pack(pady=15)
        
        ttk.Button(button_frame, text="Open Documentation", 
                  command=lambda: webbrowser.open_new("https://github.com/ideotion/Open-Omniscience")).pack(side=tk.LEFT, padx=10)
        
        ttk.Button(button_frame, text="Launch Application", 
                  command=self.launch_application).pack(side=tk.LEFT, padx=10)
        
        ttk.Button(button_frame, text="Exit", command=self.root.destroy).pack(side=tk.LEFT, padx=10)
        
        return frame
    
    def launch_application(self):
        """Launch the application and open browser when ready."""
        os.chdir(self.config['install_dir'])
        self.launch_status_label.config(text="Starting services...")
        self.root.update_idletasks()
        
        # Start services with docker-compose
        result = CommandRunner.run_docker_compose("up -d --build", 
                                                  check=False, capture=True, text=True)
        if result.returncode != 0:
            self.launch_status_label.config(text=f"Failed to start services: {result.stderr}")
            return
        
        self.launch_status_label.config(text="Services started. Waiting for application to be ready...")
        self.root.update_idletasks()
        
        # Check if service is ready with non-blocking retry
        self.check_service_ready_from_complete(open_browser=True, attempt=0)
    
    def check_service_ready_from_complete(self, open_browser, attempt):
        """Check if service is ready from complete page, updates status label."""
        max_attempts = 24  # 120 seconds / 5 seconds per attempt
        
        try:
            # Check if the web service is responding
            import requests
            try:
                response = requests.get("http://localhost:8000", timeout=5)
                if response.status_code in [200, 301, 302, 307, 308]:
                    self.launch_status_label.config(text="Application is ready!")
                    if open_browser:
                        import webbrowser
                        webbrowser.open_new("http://localhost:8000")
                    return
            except requests.exceptions.RequestException:
                pass
        except ImportError:
            # requests not available, use curl
            result = CommandRunner.run_command("curl -s -o /dev/null -w '%{http_code}' http://localhost:8000",
                                              check=False, capture=True, text=True)
            if result.returncode == 0 and '200' in result.stdout:
                self.launch_status_label.config(text="Application is ready!")
                if open_browser:
                    import webbrowser
                    webbrowser.open_new("http://localhost:8000")
                return
        
        # Not ready yet, schedule next check
        if attempt < max_attempts - 1:
            self.launch_status_label.config(text=f"Waiting... (attempt {attempt + 1}/{max_attempts})")
            self.root.update_idletasks()
            self.root.after(5000, lambda: self.check_service_ready_from_complete(open_browser, attempt + 1))
        else:
            self.launch_status_label.config(text="Warning: Application did not become ready. Check if services are running at http://localhost:8000")
    
    def show_welcome_page(self):
        """Show the welcome page initially."""
        self.show_page('welcome')


class AppLauncher:
    """Create application launcher."""
    
    @staticmethod
    def create_launcher(install_dir, name="Open-Omniscience"):
        """Create a .desktop file for the application."""
        desktop_file = os.path.expanduser(f"~/.local/share/applications/{name.lower()}.desktop")
        os.makedirs(os.path.dirname(desktop_file), exist_ok=True)
        
        dc_cmd = CommandRunner.get_docker_compose_cmd()
        content = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={name}
GenericName=Investigative Journalism Platform
Comment=Ethical Global Intelligence Platform for Investigative Journalism
Exec=bash -c "cd {install_dir} && {dc_cmd} up -d --build && echo 'Waiting for services...' && while ! curl -s http://localhost:8000 > /dev/null 2>&1; do sleep 1; done && xdg-open http://localhost:8000"
Terminal=true
Categories=Development;Journalism;Research;Utility;
StartupWMClass={name}
"""
        
        with open(desktop_file, 'w') as f:
            f.write(content)
        
        os.chmod(desktop_file, 0o755)
        
        # Update desktop database
        if SystemChecker.check_command('update-desktop-database'):
            subprocess.run(['update-desktop-database', os.path.dirname(desktop_file)], 
                          capture_output=True)
        
        return desktop_file


def main():
    """Main entry point."""
    # Check if running on Debian-based system
    if not SystemChecker.check_debian():
        print("Error: This installer is designed for Debian-based Linux systems only.")
        print("Detected system:", platform.system(), platform.release())
        sys.exit(1)
    
    # Check for required packages
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox, scrolledtext
    except ImportError:
        print("Error: Tkinter is required. Please install it with:")
        print("  sudo apt-get install python3-tk")
        sys.exit(1)
    
    # Check for psutil
    try:
        import psutil
    except ImportError:
        print("Warning: psutil not available. Some system checks will be limited.")
        print("Install it with: pip install psutil")
        # Continue anyway - psutil is optional
    
    # Create and run GUI
    root = tk.Tk()
    app = GUIInstaller(root)
    root.mainloop()


if __name__ == "__main__":
    main()
