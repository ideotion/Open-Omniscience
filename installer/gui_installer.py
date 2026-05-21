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
- Feature availability check with color coding
- On-demand dependency installation

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
from tkinter import ttk, messagebox, scrolledtext, filedialog
from pathlib import Path
import platform
import socket
import psutil
import json
import webbrowser

# Import modern theme
try:
    from installer.modern_theme import ModernTheme, apply_modern_styles, get_status_color, get_status_icon
except ImportError:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from modern_theme import ModernTheme, apply_modern_styles, get_status_color, get_status_icon

# Import feature checker
try:
    from installer.feature_checker import FeatureChecker
except ImportError:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from feature_checker import FeatureChecker


class SystemChecker:
    """Check system requirements and dependencies."""
    
    @staticmethod
    def check_root():
        return os.geteuid() == 0
    
    @staticmethod
    def check_debian():
        try:
            with open('/etc/os-release', 'r') as f:
                content = f.read()
                return 'debian' in content.lower() or 'ubuntu' in content.lower()
        except FileNotFoundError:
            return False
    
    @staticmethod
    def check_architecture():
        return platform.machine()
    
    @staticmethod
    def check_memory():
        try:
            mem = psutil.virtual_memory()
            return mem.total / (1024**3)
        except:
            try:
                with open('/proc/meminfo', 'r') as f:
                    for line in f:
                        if line.startswith('MemTotal:'):
                            return int(line.split()[1]) / (1024 * 1024)
            except:
                return 0
    
    @staticmethod
    def check_disk_space(path='/'):
        try:
            disk = psutil.disk_usage(path)
            return disk.free / (1024**3)
        except:
            try:
                result = subprocess.run(['df', '-k', path], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if path in line or line.startswith('Filesystem'):
                        continue
                    parts = line.split()
                    if len(parts) >= 4:
                        return int(parts[3]) / (1024 * 1024)
            except:
                return 0
    
    @staticmethod
    def check_command(cmd):
        return shutil.which(cmd) is not None
    
    @staticmethod
    def check_git():
        return SystemChecker.check_command('git')
    
    @staticmethod
    def check_curl():
        return SystemChecker.check_command('curl')
    
    @staticmethod
    def check_python():
        try:
            result = subprocess.run(['python3', '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'],
                                  capture_output=True, text=True)
            major, minor = map(int, result.stdout.strip().split('.'))
            return major >= 3 and minor >= 8
        except:
            return False

    @staticmethod
    def check_ollama():
        return SystemChecker.check_command('ollama')
    
    @staticmethod
    def check_port(port):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('0.0.0.0', port))
                return True
        except:
            return False
    
    @staticmethod
    def get_all_checks():
        return {
            'is_debian': SystemChecker.check_debian(),
            'is_root': SystemChecker.check_root(),
            'architecture': SystemChecker.check_architecture(),
            'memory_gb': SystemChecker.check_memory(),
            'disk_space_gb': SystemChecker.check_disk_space(),
            'has_git': SystemChecker.check_git(),
            'has_curl': SystemChecker.check_curl(),
            'has_python': SystemChecker.check_python(),
            'has_ollama': SystemChecker.check_ollama(),
            'port_8000_available': SystemChecker.check_port(8000),
            'port_11434_available': SystemChecker.check_port(11434),
        }


class InstallerConfig:
    REPO_URL = "https://github.com/ideotion/Open-Omniscience.git"
    REPO_BRANCH = "0.02"
    INSTALL_DIR = os.path.expanduser("~/open-omniscience")
    DEFAULT_DB = "sqlite"
    DEFAULT_MODEL = "gemma4:e2b"
    
    @classmethod
    def get_config(cls):
        return {
            'repo_url': cls.REPO_URL,
            'repo_branch': cls.REPO_BRANCH,
            'install_dir': cls.INSTALL_DIR,
            'default_db': cls.DEFAULT_DB,
            'default_model': cls.DEFAULT_MODEL,
        }


class CommandRunner:
    @staticmethod
    def run_command(cmd, check=False, capture=True, text=True, sudo=False):
        if sudo and not SystemChecker.check_root():
            cmd = f"sudo {cmd}"
        try:
            return subprocess.run(cmd, shell=True, check=check, capture_output=capture, text=text)
        except subprocess.CalledProcessError as e:
            return e
    
    @staticmethod
    def run_async(cmd, output_callback=None, error_callback=None):
        def run():
            try:
                result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if output_callback:
                    output_callback(result.stdout)
            except Exception as e:
                if error_callback:
                    error_callback(str(e))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread


class GUIInstaller:
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
        
        try:
            self.root.iconbitmap(default='installer/icon.xbm')
        except:
            pass
        
        self.config = {
            'install_dir': InstallerConfig.INSTALL_DIR,
            'install_ollama': False,
            'database_type': InstallerConfig.DEFAULT_DB,
            'start_services': True,
            'create_launcher': True,
        }
        
        self.system_checks = SystemChecker.get_all_checks()
        self.next_page_target = None
        self.feature_availability = {}
        
        self.setup_styles()
        self.create_widgets()
        self.show_welcome_page()
    
    def setup_styles(self):
        self.style = ttk.Style()
        apply_modern_styles(self.style)
        self.root.configure(background=ModernTheme.BG_PRIMARY)
        
        # Custom styles for feature buttons
        self.style.configure('Available.TButton', 
                            foreground=ModernTheme.TEXT_LIGHT,
                            background=ModernTheme.SUCCESS,
                            font=('Segoe UI', 10, 'bold'))
        self.style.configure('Missing.TButton', 
                            foreground=ModernTheme.TEXT_DARK,
                            background=ModernTheme.WARNING,
                            font=('Segoe UI', 10, 'bold'))
    
    def create_widgets(self):
        self.main_frame = ttk.Frame(self.root, style='TFrame')
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        self.nav_frame = ttk.Frame(self.root, style='TFrame')
        self.nav_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=20, pady=10)
        
        self.prev_button = ttk.Button(self.nav_frame, text="Back", command=self.prev_page, style='TButton')
        self.prev_button.pack(side=tk.LEFT, padx=5)
        
        self.next_button = ttk.Button(self.nav_frame, text="Next", command=self.next_page, style='TButton')
        self.next_button.pack(side=tk.RIGHT, padx=5)
        
        self.cancel_button = ttk.Button(self.nav_frame, text="Cancel", command=self.cancel_installation, style='TButton')
        self.cancel_button.pack(side=tk.RIGHT, padx=5)
        
        self.pages = {}
        self.current_page = None
        self.page_history = []
    
    def show_page(self, page_name):
        if self.current_page:
            self.current_page.pack_forget()
        
        if page_name not in self.pages:
            self.create_page(page_name)
        
        self.pages[page_name].pack(fill=tk.BOTH, expand=True)
        self.current_page = self.pages[page_name]
        self.update_navigation(page_name)
        
        if self.page_history and self.page_history[-1] != page_name:
            self.page_history.append(page_name)
        else:
            self.page_history = [page_name]
    
    def prev_page(self):
        if len(self.page_history) > 1:
            self.page_history.pop()
            self.show_page(self.page_history[-1])
    
    def next_page(self):
        if self.next_page_target:
            if callable(self.next_page_target):
                self.next_page_target()
            else:
                self.show_page(self.next_page_target)
    
    def update_navigation(self, page_name):
        can_go_back = len(self.page_history) > 1
        hide_nav = page_name in ['installing', 'complete', 'features']
        
        self.prev_button.config(state=tk.DISABLED if hide_nav else (tk.NORMAL if can_go_back else tk.DISABLED))
        current_command = self.next_button.cget('command')
        self.next_button.config(state=tk.DISABLED if hide_nav else tk.NORMAL, command=current_command)
        self.cancel_button.config(state=tk.DISABLED if hide_nav else tk.NORMAL)
    
    def cancel_installation(self):
        if messagebox.askyesno("Cancel Installation", "Are you sure you want to cancel the installation?"):
            self.root.destroy()
    
    def create_page(self, page_name):
        if page_name == 'welcome':
            self.pages['welcome'] = self.create_welcome_page()
        elif page_name == 'requirements':
            self.pages['requirements'] = self.create_requirements_page()
        elif page_name == 'options':
            self.pages['options'] = self.create_options_page()
        elif page_name == 'features':
            self.pages['features'] = self.create_features_page()
        elif page_name == 'installing':
            self.pages['installing'] = self.create_installing_page()
        elif page_name == 'complete':
            self.pages['complete'] = self.create_complete_page()
    
    def create_welcome_page(self):
        frame = ttk.Frame(self.main_frame)
        
        header = ttk.Label(frame, text="🌍 Open-Omniscience", style='Header.TLabel')
        header.pack(pady=20)
        
        subtitle = ttk.Label(frame, text="Ethical Global Intelligence Platform", 
                           style='Subheader.TLabel', font=('Segoe UI', 14))
        subtitle.pack(pady=5)
        
        desc = ttk.Label(frame, 
                        text="A modern, open-source platform for investigative journalism with local LLM support.", 
                        style='TLabel', wraplength=700, justify=tk.CENTER)
        desc.pack(pady=20)
        
        features_label = ttk.Label(frame, text="✨ Key Features:", style='Subheader.TLabel')
        features_label.pack(anchor=tk.W, padx=20, pady=(10, 5))
        
        features = [
            ("🌐", "Scrape 1900+ news sources (RSS and HTML)"),
            ("🔍", "Advanced search with Boolean operators"),
            ("🤖", "Local LLM support for text analysis"),
            ("💾", "Data export in CSV, JSON, or SQLite"),
            ("📊", "Audit logging for transparency"),
            ("⚖️", "Ethical scraping with robots.txt compliance"),
        ]
        
        for icon, feature in features:
            feature_frame = ttk.Frame(frame)
            feature_frame.pack(anchor=tk.W, padx=40, pady=2)
            icon_label = ttk.Label(feature_frame, text=icon, font=('Segoe UI', 12))
            icon_label.pack(side=tk.LEFT, padx=(0, 10))
            text_label = ttk.Label(feature_frame, text=feature)
            text_label.pack(side=tk.LEFT)
        
        platform_label = ttk.Label(frame, 
                                   text="📱 This installer is designed for Debian-based Linux systems only (Ubuntu, Debian, etc.)",
                                   style='Warning.TLabel', wraplength=700, justify=tk.CENTER)
        platform_label.pack(pady=20)
        
        self.next_page_target = 'requirements'
        return frame
    
    def create_requirements_page(self):
        frame = ttk.Frame(self.main_frame)
        
        header = ttk.Label(frame, text="🔧 System Requirements Check", style='Header.TLabel')
        header.pack(pady=20)
        
        desc = ttk.Label(frame, text="Checking your system for required dependencies...", wraplength=700)
        desc.pack(pady=10)
        
        requirements_frame = ttk.Frame(frame)
        requirements_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        canvas = tk.Canvas(requirements_frame)
        scrollbar = ttk.Scrollbar(requirements_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.check_system_requirements(scrollable_frame)
        self.next_page_target = 'options'
        return frame
    
    def check_system_requirements(self, parent_frame):
        checks = self.system_checks
        
        critical_checks = [
            ('Debian-based System', checks.get('is_debian', False), True, "This installer only works on Debian-based Linux"),
            ('Python 3.8+', checks.get('has_python', False), True, "Required for running Open-Omniscience"),
            ('Git', checks.get('has_git', False), True, "Required for cloning the repository"),
            ('cURL', checks.get('has_curl', False), True, "Required for downloading dependencies"),
        ]
        
        recommended_checks = [
            ('Ollama', checks.get('has_ollama', False), False, "Required for LLM features"),
        ]
        
        resource_checks = [
            (f"Memory ({checks.get('memory_gb', 0):.1f} GB)", checks.get('memory_gb', 0) >= 4, False, "Recommended: 4GB+ for core, 16GB+ for LLM"),
            (f"Disk Space ({checks.get('disk_space_gb', 0):.1f} GB)", checks.get('disk_space_gb', 0) >= 10, False, "Recommended: 10GB+ for core, 50GB+ for LLM"),
            ('Port 8000 Available', checks.get('port_8000_available', False), False, "Required for web interface"),
            ('Port 11434 Available', checks.get('port_11434_available', False), False, "Required for Ollama server"),
        ]
        
        ttk.Label(parent_frame, text="🔴 Critical Requirements:", style='Subheader.TLabel').pack(anchor=tk.W, pady=(0, 10))
        all_critical_passed = True
        for name, passed, critical, description in critical_checks:
            status = get_status_icon('success' if passed else 'error')
            color = get_status_color('success' if passed else 'error')
            label = ttk.Label(parent_frame, text=f"{status} {name}: {'OK' if passed else 'MISSING'}", foreground=color, background=ModernTheme.BG_PRIMARY)
            label.pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent_frame, text=f"   {description}", background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=40)
            if critical and not passed:
                all_critical_passed = False
        
        ttk.Label(parent_frame, text="🟡 Recommended:", style='Subheader.TLabel').pack(anchor=tk.W, pady=(10, 10))
        for name, passed, critical, description in recommended_checks:
            status = get_status_icon('success' if passed else 'pending')
            color = get_status_color('success' if passed else 'pending')
            label = ttk.Label(parent_frame, text=f"{status} {name}: {'Installed' if passed else 'Not installed'}", foreground=color, background=ModernTheme.BG_PRIMARY)
            label.pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent_frame, text=f"   {description}", background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=40)
        
        ttk.Label(parent_frame, text="💾 System Resources:", style='Subheader.TLabel').pack(anchor=tk.W, pady=(10, 10))
        for name, passed, critical, description in resource_checks:
            status = get_status_icon('success' if passed else 'warning')
            color = get_status_color('success' if passed else 'warning')
            label = ttk.Label(parent_frame, text=f"{status} {name}", foreground=color, background=ModernTheme.BG_PRIMARY)
            label.pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent_frame, text=f"   {description}", background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=40)
        
        if not all_critical_passed:
            warning = ttk.Label(parent_frame, text="⚠️  Some critical requirements are missing. Please install them before continuing.", style='Warning.TLabel', wraplength=700)
            warning.pack(pady=20)
            current_command = self.next_button.cget('command')
            self.next_button.config(state=tk.DISABLED, command=current_command)
    
    def create_options_page(self):
        frame = ttk.Frame(self.main_frame)
        
        header = ttk.Label(frame, text="⚙️ Installation Options", style='Header.TLabel')
        header.pack(pady=20)
        
        desc = ttk.Label(frame, text="Please select your installation preferences:", wraplength=700)
        desc.pack(pady=10)
        
        options_frame = ttk.Frame(frame)
        options_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        
        # Installation directory
        dir_frame = ttk.Frame(options_frame, style='TFrame')
        dir_frame.pack(fill=tk.X, pady=15)
        ttk.Label(dir_frame, text="📁 Installation Directory:", style='Subheader.TLabel').pack(anchor=tk.W)
        self.dir_entry = ttk.Entry(dir_frame, width=50)
        self.dir_entry.insert(0, self.config['install_dir'])
        self.dir_entry.pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(dir_frame, text="Browse...", command=self.browse_directory).pack(anchor=tk.W, padx=20)
        
        # Ollama installation
        ollama_frame = ttk.Frame(options_frame, style='TFrame')
        ollama_frame.pack(fill=tk.X, pady=15)
        self.ollama_var = tk.BooleanVar(value=self.config['install_ollama'])
        ollama_check = ttk.Checkbutton(ollama_frame, text="🤖 Install Ollama for LLM support", variable=self.ollama_var, onvalue=True, offvalue=False, style='TCheckbutton')
        ollama_check.pack(anchor=tk.W, padx=20)
        ttk.Label(ollama_frame, text="   Ollama enables local LLM features (text generation, translation, analysis)", style='TLabel', foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Database type
        db_frame = ttk.Frame(options_frame, style='TFrame')
        db_frame.pack(fill=tk.X, pady=15)
        ttk.Label(db_frame, text="🗃️ Database Type:", style='Subheader.TLabel').pack(anchor=tk.W, padx=20)
        self.db_var = tk.StringVar(value=self.config['database_type'])
        sqlite_radio = ttk.Radiobutton(db_frame, text="SQLite (Recommended for beginners)", variable=self.db_var, value='sqlite', style='TRadiobutton')
        sqlite_radio.pack(anchor=tk.W, padx=40, pady=5)
        postgres_radio = ttk.Radiobutton(db_frame, text="PostgreSQL (Recommended for production)", variable=self.db_var, value='postgresql', style='TRadiobutton')
        postgres_radio.pack(anchor=tk.W, padx=40, pady=5)
        ttk.Label(db_frame, text="   SQLite is file-based and requires no setup. PostgreSQL requires separate installation.", style='TLabel', foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Start services
        services_frame = ttk.Frame(options_frame, style='TFrame')
        services_frame.pack(fill=tk.X, pady=15)
        self.services_var = tk.BooleanVar(value=self.config['start_services'])
        services_check = ttk.Checkbutton(services_frame, text="▶️ Start services automatically after installation", variable=self.services_var, onvalue=True, offvalue=False, style='TCheckbutton')
        services_check.pack(anchor=tk.W, padx=20)
        
        # Create launcher
        launcher_frame = ttk.Frame(options_frame, style='TFrame')
        launcher_frame.pack(fill=tk.X, pady=15)
        self.launcher_var = tk.BooleanVar(value=self.config['create_launcher'])
        launcher_check = ttk.Checkbutton(launcher_frame, text="🎯 Create application launcher", variable=self.launcher_var, onvalue=True, offvalue=False, style='TCheckbutton')
        launcher_check.pack(anchor=tk.W, padx=20)
        ttk.Label(launcher_frame, text="   Creates a .desktop file for easy launching from your application menu", style='TLabel', foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Features button
        features_button_frame = ttk.Frame(options_frame, style='TFrame')
        features_button_frame.pack(fill=tk.X, pady=15)
        ttk.Button(features_button_frame, text="🎨 Manage Optional Features", command=lambda: self.show_page('features')).pack(pady=10)
        ttk.Label(features_button_frame, text="   Review and install additional features (LLM, Text Analysis, Audio Processing, etc.)", style='TLabel', foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=700).pack(anchor=tk.W, padx=20)
        
        self.next_page_target = self.start_installation
        return frame
    
    def create_features_page(self):
        """Create features selection page with color coding."""
        frame = ttk.Frame(self.main_frame)
        
        header = ttk.Label(frame, text="🎨 Optional Features", style='Header.TLabel')
        header.pack(pady=20)
        
        desc = ttk.Label(frame, text="Click on features below to manage their dependencies. Green = Ready, Orange = Needs Download", wraplength=700, justify=tk.CENTER)
        desc.pack(pady=10)
        
        features_frame = ttk.Frame(frame)
        features_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        canvas = tk.Canvas(features_frame)
        scrollbar = ttk.Scrollbar(features_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        self.create_feature_buttons(scrollable_frame)
        
        back_frame = ttk.Frame(frame)
        back_frame.pack(fill=tk.X, pady=20)
        ttk.Button(back_frame, text="← Back to Options", command=lambda: self.show_page('options')).pack()
        
        return frame
    
    def create_feature_buttons(self, parent_frame):
        """Create buttons for each feature with color coding."""
        venv_path = os.path.join(self.config.get('install_dir', ''), 'venv')
        
        for feature_name, feature_info in FeatureChecker.FEATURE_DEPENDENCIES.items():
            is_available = FeatureChecker.check_feature_availability(feature_name, venv_path)
            button_style = 'Available.TButton' if is_available else 'Missing.TButton'
            
            button_frame = ttk.Frame(parent_frame)
            button_frame.pack(fill=tk.X, padx=20, pady=10)
            
            button = ttk.Button(
                button_frame,
                text=f"{feature_info.get('icon', '•')} {feature_name}",
                style=button_style,
                command=lambda fn=feature_name: self.handle_feature_click(fn),
                wraplength=600,
                anchor=tk.W
            )
            button.pack(fill=tk.X, pady=5)
            
            desc_label = ttk.Label(
                button_frame,
                text=f"   {feature_info['description']}",
                background=ModernTheme.BG_PRIMARY,
                foreground=ModernTheme.TEXT_SECONDARY,
                font=('Segoe UI', 8),
                wraplength=600,
                anchor=tk.W
            )
            desc_label.pack(fill=tk.X, padx=25)
            
            self.feature_availability[feature_name] = is_available
    
    def handle_feature_click(self, feature_name):
        """Handle click on a feature button."""
        venv_path = os.path.join(self.config.get('install_dir', ''), 'venv')
        is_available = FeatureChecker.check_feature_availability(feature_name, venv_path)
        
        if is_available:
            messagebox.showinfo("Feature Available", f"✅ {feature_name} is ready to use!\n\nAll required dependencies are installed.")
        else:
            install_cmd = FeatureChecker.get_install_command(feature_name)
            if install_cmd:
                response = messagebox.askyesno("Install Dependencies", f"⚠️ {feature_name} requires additional dependencies.\n\nInstall command:\n{install_cmd}\n\nWould you like to install them now?")
                if response:
                    self.install_feature_dependencies(feature_name, install_cmd)
            else:
                messagebox.showwarning("Cannot Install", f"⚠️ No installation command available for {feature_name}.")
    
    def install_feature_dependencies(self, feature_name, install_command):
        """Install dependencies for a feature."""
        self.show_page('installing')
        self.log_message(f"Installing dependencies for {feature_name}...")
        self.log_message(f"Command: {install_command}")
        self.update_progress(0, f"Installing {feature_name} dependencies...")
        
        def run_install():
            try:
                result = CommandRunner.run_command(install_command, check=True, capture=True, text=True)
                if result.returncode == 0:
                    self.log_message(f"✅ Successfully installed {feature_name} dependencies")
                    venv_path = os.path.join(self.config.get('install_dir', ''), 'venv')
                    if FeatureChecker.check_feature_availability(feature_name, venv_path):
                        self.log_message(f"✅ {feature_name} is now ready to use!")
                        messagebox.showinfo("Success", f"✅ {feature_name} dependencies installed successfully!")
                    else:
                        self.log_message(f"⚠️ Some dependencies may have failed to install")
                        messagebox.showwarning("Partial Installation", f"⚠️ Some dependencies for {feature_name} may not have installed correctly.")
                else:
                    self.log_message(f"❌ Failed to install {feature_name} dependencies")
                    self.log_message(result.stderr)
                    messagebox.showerror("Installation Failed", f"❌ Failed to install dependencies for {feature_name}:\n\n{result.stderr}")
            except Exception as e:
                self.log_message(f"❌ Error installing {feature_name} dependencies: {str(e)}")
                messagebox.showerror("Error", f"❌ Error installing dependencies: {str(e)}")
            self.show_page('features')
        
        threading.Thread(target=run_install, daemon=True).start()
    
    def browse_directory(self):
        dir_path = tk.filedialog.askdirectory(initialdir=self.config['install_dir'])
        if dir_path:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, dir_path)
    
    def start_installation(self):
        self.config['install_dir'] = self.dir_entry.get()
        self.config['install_ollama'] = self.ollama_var.get()
        self.config['database_type'] = self.db_var.get()
        self.config['start_services'] = self.services_var.get()
        self.config['create_launcher'] = self.launcher_var.get()
        self.show_page('installing')
        self.root.after(100, self.run_installation)
    
    def create_installing_page(self):
        frame = ttk.Frame(self.main_frame)
        header = ttk.Label(frame, text="🚀 Installing Open-Omniscience", style='Header.TLabel')
        header.pack(pady=20)
        logo_frame = ttk.Frame(frame)
        logo_frame.pack(fill=tk.X, pady=10)
        logo_label = ttk.Label(logo_frame, text=self.LOGO, font=('Courier', 8), background='#f0f0f0', anchor=tk.CENTER)
        logo_label.pack()
        self.progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=700, mode='determinate')
        self.progress.pack(pady=20)
        self.progress['value'] = 0
        self.status_label = ttk.Label(frame, text="Starting installation...", background='#f0f0f0')
        self.status_label.pack(pady=10)
        log_frame = ttk.Frame(frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, width=80, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_message("Open-Omniscience Installer v1.0")
        self.log_message(f"Installation directory: {self.config['install_dir']}")
        self.log_message(f"Install Ollama: {self.config['install_ollama']}")
        self.log_message(f"Database type: {self.config['database_type']}")
        return frame
    
    def log_message(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def update_progress(self, value, status):
        self.progress['value'] = value
        self.status_label.config(text=status)
        self.root.update_idletasks()
    
    def run_installation(self):
