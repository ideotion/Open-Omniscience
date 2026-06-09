"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""

#!/usr/bin/env python3
"""
LLM Setup Script for Open-Omniscience
Automates the installation and configuration of local LLM support

Usage:
    python scripts/setup_llm.py [--install-ollama] [--download-models] [--model MODEL_ID] [--all]

Options:
    --install-ollama    Install Ollama if not already installed
    --download-models   Download default models
    --model MODEL_ID    Download specific model (can be used multiple times)
    --all              Install Ollama and download all default models
    --help             Show this help message
"""

import argparse
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.llm.config import get_llm_config
from src.llm.model_manager import ModelManager


class OllamaInstaller:
    """Handles Ollama installation across different platforms"""

    @staticmethod
    def is_installed() -> bool:
        """Check if Ollama is already installed"""
        try:
            result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def get_install_command() -> list[str] | None:
        """Get the appropriate install command for the current platform"""
        system = platform.system().lower()

        if system == "linux":
            return ["curl", "-fsSL", "https://ollama.com/install.sh", "|", "sh"]
        elif system == "darwin":  # macOS
            return ["brew", "install", "ollama"]
        elif system == "windows":
            # For Windows, we need to use PowerShell
            return ["powershell", "-Command", "irm https://ollama.com/install.ps1 | iex"]
        else:
            return None

    @staticmethod
    def install() -> bool:
        """Install Ollama on the current system"""
        if OllamaInstaller.is_installed():
            print("Ollama is already installed.")
            return True

        command = OllamaInstaller.get_install_command()
        if not command:
            print(f"Unsupported platform: {platform.system()}")
            print("Please install Ollama manually from https://ollama.com")
            return False

        print(f"Installing Ollama using: {' '.join(command)}")

        try:
            # For curl command, we need to handle the pipe
            if "|" in command:
                # Split into parts before and after the pipe
                idx = command.index("|")
                cmd1 = command[:idx]
                cmd2 = command[idx + 1 :]

                # Execute first command and pipe to second
                p1 = subprocess.Popen(cmd1, stdout=subprocess.PIPE)
                p2 = subprocess.Popen(
                    cmd2, stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                p1.stdout.close()  # Allow p1 to receive a SIGPIPE if p2 exits
                output, error = p2.communicate()

                if p2.returncode == 0:
                    print("Ollama installed successfully!")
                    return True
                else:
                    print(f"Failed to install Ollama: {error.decode()}")
                    return False
            else:
                result = subprocess.run(command, capture_output=True, text=True)

                if result.returncode == 0:
                    print("Ollama installed successfully!")
                    return True
                else:
                    print(f"Failed to install Ollama: {result.stderr}")
                    return False
        except Exception as e:
            print(f"Error installing Ollama: {str(e)}")
            return False


class LLMSetup:
    """Main setup class for LLM configuration"""

    def __init__(self):
        self.config = get_llm_config()
        self.model_manager = ModelManager(self.config)

    def install_ollama(self) -> bool:
        """Install Ollama"""
        return OllamaInstaller.install()

    def start_ollama(self) -> bool:
        """Start Ollama server"""
        print("Starting Ollama server...")
        try:
            result = self.model_manager.start_ollama()
            print("Ollama server started successfully!")
            return result
        except Exception as e:
            print(f"Failed to start Ollama: {str(e)}")
            return False

    def download_default_models(self) -> dict[str, bool]:
        """Download all default models"""
        print("Downloading default models...")
        results = {}

        for model_id, model_config in self.config.default_models.items():
            if model_config.default:
                print(f"Downloading {model_config.name} ({model_id})...")
                try:
                    result = self.model_manager.download_model(model_id)
                    results[model_id] = result
                    print(f"  ✓ Successfully downloaded {model_config.name}")
                except Exception as e:
                    results[model_id] = False
                    print(f"  ✗ Failed to download {model_config.name}: {str(e)}")

        return results

    def download_specific_models(self, model_ids: list[str]) -> dict[str, bool]:
        """Download specific models"""
        results = {}

        for model_id in model_ids:
            print(f"Downloading {model_id}...")
            try:
                result = self.model_manager.download_model(model_id)
                results[model_id] = result
                print(f"  ✓ Successfully downloaded {model_id}")
            except Exception as e:
                results[model_id] = False
                print(f"  ✗ Failed to download {model_id}: {str(e)}")

        return results

    def verify_installation(self) -> dict[str, Any]:
        """Verify that everything is properly installed and configured"""
        print("Verifying LLM installation...")

        results = {
            "ollama_installed": self.model_manager.is_ollama_installed(),
            "ollama_running": self.model_manager.is_ollama_running(),
            "local_models": self.model_manager.list_local_models(),
            "default_models": list(self.config.default_models.keys()),
        }

        # Check which default models are downloaded
        downloaded_defaults = []
        for model_id, config in self.config.default_models.items():
            if self.model_manager.is_model_downloaded(model_id):
                downloaded_defaults.append(model_id)
        results["downloaded_default_models"] = downloaded_defaults

        return results

    def print_status(self):
        """Print current LLM status"""
        verification = self.verify_installation()

        print("\n" + "=" * 50)
        print("LLM Installation Status")
        print("=" * 50)

        print(f"\nOllama Installed: {'✓ Yes' if verification['ollama_installed'] else '✗ No'}")
        print(f"Ollama Running: {'✓ Yes' if verification['ollama_running'] else '✗ No'}")

        print(f"\nDownloaded Models ({len(verification['local_models'])}):")
        for model in verification["local_models"]:
            print(f"  - {model}")

        print(f"\nDefault Models Available ({len(verification['default_models'])}):")
        for model_id in verification["default_models"]:
            status = "✓" if model_id in verification["downloaded_default_models"] else "✗"
            config = self.config.default_models[model_id]
            print(f"  {status} {config.name} ({model_id}) - {config.size_gb}GB")

        print("\n" + "=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Setup local LLM support for Open-Omniscience",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/setup_llm.py --all                    # Install Ollama and download all default models
  python scripts/setup_llm.py --install-ollama         # Install Ollama only
  python scripts/setup_llm.py --download-models       # Download default models only
  python scripts/setup_llm.py --model llama3:8b        # Download specific model
  python scripts/setup_llm.py --model llama3:8b --model mistral:7b  # Download multiple models
        """,
    )

    parser.add_argument(
        "--install-ollama", action="store_true", help="Install Ollama if not already installed"
    )
    parser.add_argument("--download-models", action="store_true", help="Download default models")
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="Download specific model (can be used multiple times)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Install Ollama and download all default models"
    )
    parser.add_argument(
        "--start", action="store_true", help="Start Ollama server after installation"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show current LLM installation status"
    )

    args = parser.parse_args()

    setup = LLMSetup()

    # Show status first if requested or if no other action specified
    if args.status or (
        not any([args.install_ollama, args.download_models, args.model, args.all, args.start])
    ):
        setup.print_status()

    # Handle --all option
    if args.all:
        args.install_ollama = True
        args.download_models = True
        args.start = True

    # Install Ollama if requested
    if args.install_ollama:
        if not setup.install_ollama():
            print("\nOllama installation failed. Some features may not work.")
            if not args.download_models and not args.model and not args.start:
                return

    # Download models if requested
    if args.download_models:
        results = setup.download_default_models()
        print(f"\nDownloaded {sum(results.values())} out of {len(results)} default models.")

    # Download specific models
    if args.model:
        results = setup.download_specific_models(args.model)
        print(f"\nDownloaded {sum(results.values())} out of {len(results)} requested models.")

    # Start Ollama if requested
    if args.start:
        setup.start_ollama()

    # Show final status if any action was taken
    if any([args.install_ollama, args.download_models, args.model, args.start]):
        print("\n")
        setup.print_status()


if __name__ == "__main__":
    main()
