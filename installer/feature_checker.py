"""
Feature Checker for Open-Omniscience GUI
========================================

This module provides functionality to check which features have their
dependencies installed and to prompt users to install missing dependencies.

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import os
import subprocess
import shutil
from installer.modern_theme import ModernTheme


class FeatureChecker:
    """Check which features have their dependencies installed."""
    
    # Map features to their required packages/commands
    FEATURE_DEPENDENCIES = {
        'Web Scraping': {
            'description': 'Scrape 1900+ news sources (RSS and HTML)',
            'icon': '🌐',
            'packages': ['requests', 'beautifulsoup4', 'feedparser'],
            'command': None,
            'install_command': 'pip install requests beautifulsoup4 feedparser',
        },
        'Database (SQLite)': {
            'description': 'Local SQLite database for storing scraped content',
            'icon': '🗃️',
            'packages': ['sqlalchemy', 'alembic'],
            'command': None,
            'install_command': 'pip install sqlalchemy alembic',
        },
        'Database (PostgreSQL)': {
            'description': 'PostgreSQL database for production use',
            'icon': '🗃️',
            'packages': ['sqlalchemy', 'alembic', 'psycopg2'],
            'command': 'psql',
            'install_command': 'sudo apt install postgresql postgresql-contrib && pip install sqlalchemy alembic psycopg2',
        },
        'LLM (Ollama)': {
            'description': 'Local LLM support for text analysis, translation, and synthesis',
            'icon': '🤖',
            'packages': [],
            'command': 'ollama',
            'install_command': 'curl -fsSL https://ollama.com/install.sh | sh',
        },
        'Text Analysis': {
            'description': 'NLP and text processing capabilities',
            'icon': '📝',
            'packages': ['nltk', 'spacy', 'textblob'],
            'command': None,
            'install_command': 'pip install nltk spacy textblob && python -m spacy download en_core_web_sm',
        },
        'Audio Processing': {
            'description': 'Audio analysis and transcription',
            'icon': '🎵',
            'packages': ['pyAudioAnalysis', 'librosa', 'pydub'],
            'command': None,
            'install_command': 'pip install pyAudioAnalysis librosa pydub',
        },
        'Image Processing': {
            'description': 'Image analysis and OCR',
            'icon': '🖼️',
            'packages': ['opencv-python', 'pytesseract', 'Pillow'],
            'command': None,
            'install_command': 'pip install opencv-python pytesseract Pillow',
        },
        'Machine Learning': {
            'description': 'Online machine learning with River',
            'icon': '🤖',
            'packages': ['river'],
            'command': None,
            'install_command': 'pip install river',
        },
        'Network Analysis': {
            'description': 'Network graph analysis and visualization',
            'icon': '🔗',
            'packages': ['networkx', 'python-louvain', 'python-igraph', 'leidenalg'],
            'command': None,
            'install_command': 'pip install networkx python-louvain python-igraph leidenalg',
        },
        'Advanced AI': {
            'description': 'Transformers, ONNX, and PyTorch for advanced AI features',
            'icon': '🤖',
            'packages': ['torch', 'transformers', 'onnx', 'onnxruntime'],
            'command': None,
            'install_command': 'pip install torch transformers onnx onnxruntime',
        },
    }
    
    @classmethod
    def check_feature_availability(cls, feature_name, venv_path=None):
        """Check if all dependencies for a feature are available."""
        if feature_name not in cls.FEATURE_DEPENDENCIES:
            return False
        
        feature = cls.FEATURE_DEPENDENCIES[feature_name]
        
        # Check command dependencies
        if feature.get('command'):
            if not shutil.which(feature['command']):
                return False
        
        # Check Python package dependencies
        if feature.get('packages'):
            for package in feature['packages']:
                if not cls.check_package_installed(package, venv_path):
                    return False
        
        return True
    
    @classmethod
    def check_package_installed(cls, package_name, venv_path=None):
        """Check if a Python package is installed."""
        python_cmd = 'python3'
        if venv_path and os.path.exists(os.path.join(venv_path, 'bin', 'python3')):
            python_cmd = os.path.join(venv_path, 'bin', 'python3')
        
        try:
            # Extract base package name (remove version specifiers)
            base_package = package_name.split('[')[0].split('==')[0].split('>=')[0].split('<=')[0]
            result = subprocess.run(
                [python_cmd, '-c', f'import {base_package}'],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    @classmethod
    def get_install_command(cls, feature_name):
        """Get the install command for a feature."""
        if feature_name in cls.FEATURE_DEPENDENCIES:
            return cls.FEATURE_DEPENDENCIES[feature_name].get('install_command', '')
        return ''
    
    @classmethod
    def get_feature_info(cls, feature_name):
        """Get all information about a feature."""
        return cls.FEATURE_DEPENDENCIES.get(feature_name, {})
    
    @classmethod
    def get_all_features(cls):
        """Get list of all feature names."""
        return list(cls.FEATURE_DEPENDENCIES.keys())
    
    @classmethod
    def get_feature_color(cls, feature_name, venv_path=None):
        """Get the color for a feature based on its availability."""
        if cls.check_feature_availability(feature_name, venv_path):
            return ModernTheme.SUCCESS  # Green for available
        else:
            return ModernTheme.WARNING  # Orange for needs download
