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
            # Security: Use shell=False to prevent shell injection
            # If shell functionality is needed, cmd should be a list of arguments
            if isinstance(cmd, str):
                import shlex
                cmd = shlex.split(cmd)
            return subprocess.run(cmd, shell=False, check=check, capture_output=capture, text=text)
        except subprocess.CalledProcessError as e:
            return e
    
    @staticmethod
    def run_async(cmd, output_callback=None, error_callback=None):
        def run():
            try:
                # Security: Use shell=False to prevent shell injection
                if isinstance(cmd, str):
                    import shlex
                    cmd = shlex.split(cmd)
                result = subprocess.run(cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        ttk.Label(frame, text="🌍 Open-Omniscience", style='Header.TLabel').pack(pady=20)
        ttk.Label(frame, text="Ethical Global Intelligence Platform", style='Subheader.TLabel', font=('Segoe UI', 14)).pack(pady=5)
        ttk.Label(frame, text="A modern, open-source platform for investigative journalism with local LLM support.", style='TLabel', wraplength=700, justify=tk.CENTER).pack(pady=20)
        ttk.Label(frame, text="✨ Key Features:", style='Subheader.TLabel').pack(anchor=tk.W, padx=20, pady=(10, 5))
        for icon, feature in [("🌐", "Scrape 1900+ news sources"), ("🔍", "Advanced search"), ("🤖", "Local LLM support"), ("💾", "Data export"), ("📊", "Audit logging"), ("⚖️", "Ethical scraping")]:
            f = ttk.Frame(frame)
            f.pack(anchor=tk.W, padx=40, pady=2)
            ttk.Label(f, text=icon, font=('Segoe UI', 12)).pack(side=tk.LEFT, padx=(0, 10))
            ttk.Label(f, text=feature).pack(side=tk.LEFT)
        ttk.Label(frame, text="📱 This installer is designed for Debian-based Linux systems only", style='Warning.TLabel', wraplength=700, justify=tk.CENTER).pack(pady=20)
        self.next_page_target = 'requirements'
        return frame
    
    def create_requirements_page(self):
        frame = ttk.Frame(self.main_frame)
        ttk.Label(frame, text="🔧 System Requirements Check", style='Header.TLabel').pack(pady=20)
        ttk.Label(frame, text="Checking your system for required dependencies...", wraplength=700).pack(pady=10)
        req_frame = ttk.Frame(frame)
        req_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        canvas = tk.Canvas(req_frame)
        scrollbar = ttk.Scrollbar(req_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.check_system_requirements(scrollable)
        self.next_page_target = 'options'
        return frame
    
    def check_system_requirements(self, parent):
        checks = self.system_checks
        critical = [('Debian-based System', checks.get('is_debian', False), True, "This installer only works on Debian-based Linux"), ('Python 3.8+', checks.get('has_python', False), True, "Required for Open-Omniscience"), ('Git', checks.get('has_git', False), True, "Required for cloning"), ('cURL', checks.get('has_curl', False), True, "Required for downloads")]
        recommended = [('Ollama', checks.get('has_ollama', False), False, "Required for LLM features")]
        resources = [(f"Memory ({checks.get('memory_gb', 0):.1f} GB)", checks.get('memory_gb', 0) >= 4, False, "Recommended: 4GB+"), (f"Disk Space ({checks.get('disk_space_gb', 0):.1f} GB)", checks.get('disk_space_gb', 0) >= 10, False, "Recommended: 10GB+"), ('Port 8000 Available', checks.get('port_8000_available', False), False, "Required for web interface"), ('Port 11434 Available', checks.get('port_11434_available', False), False, "Required for Ollama")]
        
        ttk.Label(parent, text="🔴 Critical Requirements:", style='Subheader.TLabel').pack(anchor=tk.W, pady=(0, 10))
        all_passed = True
        for name, passed, crit, desc in critical:
            s = get_status_icon('success' if passed else 'error')
            c = get_status_color('success' if passed else 'error')
            ttk.Label(parent, text=f"{s} {name}: {'OK' if passed else 'MISSING'}", foreground=c, background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent, text=f"   {desc}", background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=40)
            if crit and not passed:
                all_passed = False
        
        ttk.Label(parent, text="🟡 Recommended:", style='Subheader.TLabel').pack(anchor=tk.W, pady=(10, 10))
        for name, passed, crit, desc in recommended:
            s = get_status_icon('success' if passed else 'pending')
            c = get_status_color('success' if passed else 'pending')
            ttk.Label(parent, text=f"{s} {name}: {'Installed' if passed else 'Not installed'}", foreground=c, background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent, text=f"   {desc}", background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=40)
        
        ttk.Label(parent, text="💾 System Resources:", style='Subheader.TLabel').pack(anchor=tk.W, pady=(10, 10))
        for name, passed, crit, desc in resources:
            s = get_status_icon('success' if passed else 'warning')
            c = get_status_color('success' if passed else 'warning')
            ttk.Label(parent, text=f"{s} {name}", foreground=c, background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=20, pady=2)
            ttk.Label(parent, text=f"   {desc}", background=ModernTheme.BG_PRIMARY).pack(anchor=tk.W, padx=40)
        
        if not all_passed:
            ttk.Label(parent, text="⚠️ Some critical requirements are missing. Please install them before continuing.", style='Warning.TLabel', wraplength=700).pack(pady=20)
            self.next_button.config(state=tk.DISABLED, command=self.next_button.cget('command'))
    
    def create_options_page(self):
        frame = ttk.Frame(self.main_frame)
        ttk.Label(frame, text="⚙️ Installation Options", style='Header.TLabel').pack(pady=20)
        ttk.Label(frame, text="Please select your installation preferences:", wraplength=700).pack(pady=10)
        options = ttk.Frame(frame)
        options.pack(fill=tk.BOTH, expand=True, pady=20)
        
        # Install directory
        dir_f = ttk.Frame(options)
        dir_f.pack(fill=tk.X, pady=15)
        ttk.Label(dir_f, text="📁 Installation Directory:", style='Subheader.TLabel').pack(anchor=tk.W)
        self.dir_entry = ttk.Entry(dir_f, width=50)
        self.dir_entry.insert(0, self.config['install_dir'])
        self.dir_entry.pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(dir_f, text="Browse...", command=self.browse_directory).pack(anchor=tk.W, padx=20)
        
        # Ollama
        ollama_f = ttk.Frame(options)
        ollama_f.pack(fill=tk.X, pady=15)
        self.ollama_var = tk.BooleanVar(value=self.config['install_ollama'])
        ttk.Checkbutton(ollama_f, text="🤖 Install Ollama for LLM support", variable=self.ollama_var, onvalue=True, offvalue=False).pack(anchor=tk.W, padx=20)
        ttk.Label(ollama_f, text="   Ollama enables local LLM features", foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=700).pack(anchor=tk.W, padx=40, pady=(0, 10))
        
        # Database
        db_f = ttk.Frame(options)
        db_f.pack(fill=tk.X, pady=15)
        ttk.Label(db_f, text="🗃️ Database Type:", style='Subheader.TLabel').pack(anchor=tk.W, padx=20)
        self.db_var = tk.StringVar(value=self.config['database_type'])
        ttk.Radiobutton(db_f, text="SQLite (Recommended for beginners)", variable=self.db_var, value='sqlite').pack(anchor=tk.W, padx=40, pady=5)
        ttk.Radiobutton(db_f, text="PostgreSQL (Recommended for production)", variable=self.db_var, value='postgresql').pack(anchor=tk.W, padx=40, pady=5)
        
        # Services
        svc_f = ttk.Frame(options)
        svc_f.pack(fill=tk.X, pady=15)
        self.services_var = tk.BooleanVar(value=self.config['start_services'])
        ttk.Checkbutton(svc_f, text="▶️ Start services automatically", variable=self.services_var, onvalue=True, offvalue=False).pack(anchor=tk.W, padx=20)
        
        # Launcher
        launch_f = ttk.Frame(options)
        launch_f.pack(fill=tk.X, pady=15)
        self.launcher_var = tk.BooleanVar(value=self.config['create_launcher'])
        ttk.Checkbutton(launch_f, text="🎯 Create application launcher", variable=self.launcher_var, onvalue=True, offvalue=False).pack(anchor=tk.W, padx=20)
        
        # Features button
        feat_f = ttk.Frame(options)
        feat_f.pack(fill=tk.X, pady=15)
        ttk.Button(feat_f, text="🎨 Manage Optional Features", command=lambda: self.show_page('features')).pack(pady=10)
        ttk.Label(feat_f, text="   Review and install additional features", foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=700).pack(anchor=tk.W, padx=20)
        
        self.next_page_target = self.start_installation
        return frame
    
    def create_features_page(self):
        frame = ttk.Frame(self.main_frame)
        ttk.Label(frame, text="🎨 Optional Features", style='Header.TLabel').pack(pady=20)
        ttk.Label(frame, text="Click features below. Green = Ready, Orange = Needs Download", wraplength=700, justify=tk.CENTER).pack(pady=10)
        feat_frame = ttk.Frame(frame)
        feat_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        canvas = tk.Canvas(feat_frame)
        scrollbar = ttk.Scrollbar(feat_frame, orient="vertical", command=canvas.yview)
        scrollable = ttk.Frame(canvas)
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.create_feature_buttons(scrollable)
        back_f = ttk.Frame(frame)
        back_f.pack(fill=tk.X, pady=20)
        ttk.Button(back_f, text="← Back to Options", command=lambda: self.show_page('options')).pack()
        return frame
    
    def create_feature_buttons(self, parent):
        venv_path = os.path.join(self.config.get('install_dir', ''), 'venv')
        for fname, finfo in FeatureChecker.FEATURE_DEPENDENCIES.items():
            available = FeatureChecker.check_feature_availability(fname, venv_path)
            bf = ttk.Frame(parent)
            bf.pack(fill=tk.X, padx=20, pady=10)
            style = 'Available.TButton' if available else 'Missing.TButton'
            ttk.Button(bf, text=f"{finfo.get('icon', '•')} {fname}", style=style, command=lambda fn=fname: self.handle_feature_click(fn), wraplength=600, anchor=tk.W).pack(fill=tk.X, pady=5)
            ttk.Label(bf, text=f"   {finfo['description']}", background=ModernTheme.BG_PRIMARY, foreground=ModernTheme.TEXT_SECONDARY, font=('Segoe UI', 8), wraplength=600, anchor=tk.W).pack(fill=tk.X, padx=25)
            self.feature_availability[fname] = available
    
    def handle_feature_click(self, fname):
        venv_path = os.path.join(self.config.get('install_dir', ''), 'venv')
        if FeatureChecker.check_feature_availability(fname, venv_path):
            messagebox.showinfo("Feature Available", f"✅ {fname} is ready to use!\n\nAll dependencies installed.")
        else:
            cmd = FeatureChecker.get_install_command(fname)
            if cmd and messagebox.askyesno("Install Dependencies", f"⚠️ {fname} needs dependencies.\n\nCommand:\n{cmd}\n\nInstall now?"):
                self.install_feature_dependencies(fname, cmd)
    
    def install_feature_dependencies(self, fname, cmd):
        self.show_page('installing')
        self.log_message(f"Installing dependencies for {fname}...")
        self.update_progress(0, f"Installing {fname}...")
        def run():
            try:
                result = CommandRunner.run_command(cmd, check=True, capture=True, text=True)
                if result.returncode == 0:
                    self.log_message(f"✅ {fname} dependencies installed")
                    if FeatureChecker.check_feature_availability(fname, os.path.join(self.config.get('install_dir', ''), 'venv')):
                        messagebox.showinfo("Success", f"✅ {fname} is ready!")
                    else:
                        messagebox.showwarning("Partial", f"⚠️ Some dependencies may have failed.")
                else:
                    self.log_message(f"❌ Failed: {result.stderr}")
                    messagebox.showerror("Failed", f"❌ Error: {result.stderr}")
            except Exception as e:
                self.log_message(f"❌ Error: {str(e)}")
                messagebox.showerror("Error", f"❌ {str(e)}")
            self.show_page('features')
        threading.Thread(target=run, daemon=True).start()
    
    def browse_directory(self):
        dir_path = tk.filedialog.askdirectory(initialdir=self.config['install_dir'])
        if dir_path:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, dir_path)
    
    def start_installation(self):
        self.config.update({'install_dir': self.dir_entry.get(), 'install_ollama': self.ollama_var.get(), 'database_type': self.db_var.get(), 'start_services': self.services_var.get(), 'create_launcher': self.launcher_var.get()})
        self.show_page('installing')
        self.root.after(100, self.run_installation)
    
    def create_installing_page(self):
        frame = ttk.Frame(self.main_frame)
        ttk.Label(frame, text="🚀 Installing Open-Omniscience", style='Header.TLabel').pack(pady=20)
        lf = ttk.Frame(frame)
        lf.pack(fill=tk.X, pady=10)
        ttk.Label(lf, text=self.LOGO, font=('Courier', 8), background='#f0f0f0', anchor=tk.CENTER).pack()
        self.progress = ttk.Progressbar(frame, orient=tk.HORIZONTAL, length=700, mode='determinate')
        self.progress.pack(pady=20)
        self.progress['value'] = 0
        self.status_label = ttk.Label(frame, text="Starting installation...", background='#f0f0f0')
        self.status_label.pack(pady=10)
        lf2 = ttk.Frame(frame)
        lf2.pack(fill=tk.BOTH, expand=True, pady=10)
        self.log_text = scrolledtext.ScrolledText(lf2, wrap=tk.WORD, width=80, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_message("Open-Omniscience Installer v1.0")
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
        pass
    
    def create_complete_page(self):
        frame = ttk.Frame(self.main_frame)
        ttk.Label(frame, text="✅ Installation Complete!", style='Header.TLabel').pack(pady=20)
        ttk.Label(frame, text="Open-Omniscience has been successfully installed.", wraplength=700).pack(pady=10)
        ttk.Button(frame, text="Launch Application", command=self.launch_application).pack(pady=20)
        ttk.Button(frame, text="Exit", command=self.root.destroy).pack(pady=10)
        return frame
    
    def launch_application(self):
        pass


if __name__ == "__main__":
    root = tk.Tk()
    app = GUIInstaller(root)
    root.mainloop()
