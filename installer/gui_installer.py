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

# Import FeatureChecker
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
            return psutil.virtual_memory().total / (1024**3)
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
            return psutil.disk_usage(path).free / (1024**3)
        except:
            try:
                result = subprocess.run(['df', '-k', path], capture_output=True, text=True)
                for line in result.stdout.split('\n')[1:]:
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
                                  capture_output=True, text=True, timeout=5)
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
        "                                 .-=+*#%@@@@@@@@@@%#*+-:                                        \n"
        "                            .-+#@@@@@@%%@@@@@@@@@%%%@@@@@@#+:                                  \n"
        "                         -+%@@@#*=:.-*#*#@*-@=+@#*#*-.:-+*%@@@#=:                               \n"
        "                      -*@@%+-.    +%+. *#.  @: .*#..=%+     :=#@@%+:                            \n"
        "                   .+@%*-       :%+##+%*    @:   *%=*#+%-       :=#@%=                          \n"
        "                 :#%+.         -@:   ##+****@#***+#@   .%=          -*%+.                       \n"
        "               :*+.           .@:   :@.     @:     @-   .@:            -**.                     \n"
        "             .=-              *#    *#      @:     *#    *#              .==                    \n"
        "            :-                #%****@%******@#*****%@****%%                =                   \n"
        "             .=:              *#    *#      @:     +#    +#               --                    \n"
        "               -*=.           :@.   -@      @:     %=   .@-            :++.                     \n"
        "                 -##-          +%.   %*=+**#@#**+=*%    #*          .=%*.                       \n"
        "                   :*@#=.       =%=+#*%#.   @:  .*@*#*=%+        :+%%=.                         \n"
        "                      =#@@*=.    .*%- .#*   @:  +%. :%#:     :=#@@*:                            \n"
        "                        .=#@@@#+-: .+#*=*@=.@--%#=*#+. .:=*%@@%*-                               \n"
        "                            :+#@@@@@%**%@@@@@@@@@%**#%@@@@%*=.                                  \n"
        "                                .-+*%@@@@@@@@@@@@@@@%#+=:                                       \n"
        "                                       .::-----::.                                             \n"
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
