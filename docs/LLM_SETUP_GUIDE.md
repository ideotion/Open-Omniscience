# LLM Setup Guide for Open-Omniscience

**Version:** 1.0  
**Last Updated:** $(date)  
**Author:** Ideotion

---

## 📋 Overview

This guide provides step-by-step instructions for setting up Local LLM (Large Language Model) support in Open-Omniscience. The LLM features enable advanced text processing capabilities including text generation, translation, analysis, and synthesis - all while maintaining full data privacy as all processing happens locally on your machine.

---

## 🎯 Prerequisites

### System Requirements

#### Minimum (Core Features Only)
- **Operating System:** Debian-based Linux (Ubuntu, Debian, etc.)
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 10GB free disk space
- **Python:** 3.8+

#### Recommended (With LLM Support)
- **Operating System:** Debian-based Linux (Ubuntu 20.04+ recommended)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB+ free disk space (for 3-4 models)
- **GPU:** NVIDIA GPU with 8GB+ VRAM (recommended for better performance)
- **Python:** 3.8+

#### High-End (Full LLM Capabilities)
- **Operating System:** Debian-based Linux (Ubuntu, Debian, etc.)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ free disk space (for multiple large models)
- **GPU:** NVIDIA GPU with 24GB+ VRAM
- **Python:** 3.8+

### Software Dependencies

- **Git** - Version control
- **Python** - 3.8 or higher
- **pip** - Python package manager
- **Docker** (optional) - For containerized deployment
- **Ollama** - Local LLM runtime (required for LLM features)

---

## 🚀 Installation Methods

Choose one of the following installation methods based on your needs:

### Method 1: Docker Deployment (Recommended for Production)

This is the easiest way to get started with LLM support.

#### Step 1: Clone the Repository
```bash
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
```

#### Step 2: Configure Environment
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your settings (optional)
nano .env

# Recommended settings for LLM:
OLLAMA_HOST=0.0.0.0
OLLAMA_ORIGINS=*
AUTO_DOWNLOAD_MODELS=true
```

#### Step 3: Start with Docker Compose
```bash
# Start both standard and LLM services
docker-compose -f docker-compose.yml -f docker-compose.llm.yml up -d --build

# This will:
# 1. Build the standard Open-Omniscience image
# 2. Build the LLM-enabled image
# 3. Start Ollama server
# 4. Start Open-Omniscience API
# 5. Set up model volume for persistence
```

#### Step 4: Verify Installation
```bash
# Check that containers are running
docker ps

# Check LLM service health
curl http://localhost:8000/api/llm/health

# List available models
curl http://localhost:8000/api/llm/models
```

#### Step 5: Download Models (Optional)
```bash
# Download the default model (gemma4:e2b)
docker exec open-omniscience-llm ollama pull gemma4:e2b

# Or download multiple models
docker exec open-omniscience-llm ollama pull mistral:7b
docker exec open-omniscience-llm ollama pull phi3:3.8b
```

### Method 2: Bare Metal Installation (Recommended for Development)

This method gives you more control over the installation.

#### Step 1: Clone the Repository
```bash
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
```

#### Step 2: Set Up Python Environment
```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate
```

#### Step 3: Install Core Dependencies
```bash
pip install -r requirements.txt
```

#### Step 4: Install LLM Dependencies
```bash
pip install -r requirements-llm.txt
```

#### Step 5: Install Ollama

For Debian-based Linux systems:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

**Manual Installation:**
If the above method doesn't work, download Ollama manually from [https://ollama.com](https://ollama.com)

#### Step 6: Start Ollama Server
```bash
# Start Ollama in the background
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

#### Step 7: Download Models
```bash
# Download the default model
ollama pull gemma4:e2b

# Optional: Download additional models
ollama pull mistral:7b
ollama pull phi3:3.8b
ollama pull qwen2.5:7b
```

#### Step 8: Initialize Database
```bash
mkdir -p data audit logs
python -c "import sys; sys.path.insert(0, 'src'); from database.models import Base, engine; Base.metadata.create_all(engine); print('Database initialized')"
```

#### Step 9: Start Open-Omniscience
```bash
uvicorn api.main:app --reload
```

#### Step 10: Verify Installation
```bash
# Check LLM service health
curl http://localhost:8000/api/llm/health

# List available models
curl http://localhost:8000/api/llm/models
```

### Method 3: Automated Setup Script

For the quickest setup, use the provided setup script:

```bash
# Run the automated setup
python scripts/setup_llm.py --all

# This will:
# 1. Install Ollama (if not already installed)
# 2. Start Ollama server
# 3. Download the default model (gemma4:e2b)
# 4. Verify the installation
```

You can also use specific options:

```bash
# Install Ollama only
python scripts/setup_llm.py --install-ollama

# Download default models only
python scripts/setup_llm.py --download-models

# Download specific models
python scripts/setup_llm.py --model gemma4:e2b --model mistral:7b

# Show current status
python scripts/setup_llm.py --status
```

---

## 📦 Model Management

### Available Models

Open-Omniscience comes with 9 pre-configured models:

| Model ID | Name | Size | VRAM Required | RAM Required | Best For |
|----------|------|------|---------------|--------------|----------|
| `phi3:3.8b` | Microsoft Phi-3 3.8B | 2.3GB | 3GB | 4GB | Lightweight tasks, fast inference |
| `bart-large` | Facebook BART Large | 1.4GB | 3GB | 4GB | Translation, summarization |
| `mistral:7b` | Mistral AI 7B | 4.1GB | 5GB | 8GB | General purpose, balanced |
| `gemma4:e2b` | Google Gemma 4 E2B | 2.7GB | 3GB | 4GB | **All tasks (DEFAULT)** |
| `gemma:7b` | Google Gemma 7B | 4.8GB | 5GB | 8GB | CPU-optimized |
| `qwen2.5:7b` | Alibaba Qwen 2.5 7B | 4.8GB | 5GB | 8GB | Multilingual support |
| `llava:7b` | LLaVA 7B | 4.5GB | 6GB | 10GB | Multimodal (text + vision) |
| `llama3:70b` | Meta Llama 3 70B | 40GB | 42GB | 80GB | High capability, complex tasks |

### Downloading Models

#### Using Ollama CLI
```bash
# Download a specific model
ollama pull gemma4:e2b

# Download multiple models
ollama pull gemma4:e2b mistral:7b phi3:3.8b

# List downloaded models
ollama list
```

#### Using Open-Omniscience API
```bash
# List available models
curl http://localhost:8000/api/llm/models

# Get model information
curl http://localhost:8000/api/llm/models | jq
```

### Removing Models

To free up disk space, you can remove downloaded models:

```bash
# Remove a specific model
ollama rm gemma4:e2b

# List downloaded models
ollama list
```

### Model Storage

Ollama stores models in:
- **Debian-based Linux:** `~/.ollama/models/`

To check disk usage:
```bash
# Using Open-Omniscience API
du -sh ~/.ollama/models/

# Or use the API endpoint
curl http://localhost:8000/api/llm/models | jq '.disk_usage'
```

---

## 🔧 Configuration

### Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# Database configuration
DATABASE_URL=sqlite:///./data/open_omniscience.db

# CORS configuration
ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000

# Ollama configuration
OLLAMA_HOST=0.0.0.0
OLLAMA_ORIGINS=*

# LLM configuration
DOWNLOAD_DEFAULT_MODELS=false
AUTO_DOWNLOAD_MODELS=true
MAX_CONTEXT_LENGTH=8192
MAX_TOKENS=4096

# Model library path
MODEL_LIBRARY_PATH=./data/llm_models
```

### Configuration Options

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `0.0.0.0` | Host for Ollama server |
| `OLLAMA_ORIGINS` | `*` | CORS origins for Ollama |
| `DOWNLOAD_DEFAULT_MODELS` | `false` | Auto-download default models on startup |
| `AUTO_DOWNLOAD_MODELS` | `true` | Auto-download models when first used |
| `MAX_CONTEXT_LENGTH` | `8192` | Maximum context length for LLM |
| `MAX_TOKENS` | `4096` | Maximum tokens to generate |
| `MODEL_LIBRARY_PATH` | `./data/llm_models` | Path to store downloaded models |

### Configuration File

You can also configure LLM settings in Python code:

```python
from src.llm.config import LLMConfig, ModelConfig

# Create custom configuration
config = LLMConfig(
    ollama=OllamaConfig(
        enabled=True,
        base_url="http://localhost:11434",
        timeout=120,
        max_retries=3
    ),
    model_library_path="./data/llm_models",
    auto_download_models=True,
    max_context_length=8192,
    max_tokens=4096
)
```

---

## 🧪 Testing the Installation

### Health Check
```bash
curl http://localhost:8000/api/llm/health
```

Expected response:
```json
{
  "status": "healthy",
  "ollama_installed": true,
  "ollama_running": true
}
```

### List Models
```bash
curl http://localhost:8000/api/llm/models
```

### Test Text Generation
```bash
curl -X POST http://localhost:8000/api/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is Open Omniscience?", "temperature": 0.7}'
```

### Test Translation
```bash
curl -X POST http://localhost:8000/api/llm/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, how are you?", "target_language": "fr", "source_language": "en"}'
```

### Test Text Extraction
```bash
curl -X POST http://localhost:8000/api/llm/extract \
  -H "Content-Type: application/json" \
  -d '{"content": "Apple Inc. was founded by Steve Jobs in 1976.", "extraction_type": "entities"}'
```

---

## 🛠️ Troubleshooting

### Common Issues

#### Issue 1: Ollama Not Installed

**Error:** `OllamaNotInstalledError: Ollama is not installed`

**Solution:**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Verify installation
ollama --version
```

#### Issue 2: Ollama Server Not Running

**Error:** `OllamaNotRunningError: Ollama server is not running`

**Solution:**
```bash
# Start Ollama server
ollama serve

# Verify it's running
curl http://localhost:11434/api/tags
```

#### Issue 3: Model Not Downloaded

**Error:** `ModelNotFoundError: Model 'gemma4:e2b' not found or not downloaded`

**Solution:**
```bash
# Download the model
ollama pull gemma4:e2b

# Verify download
ollama list
```

#### Issue 4: Insufficient Resources

**Error:** `InsufficientResourcesError` or out of memory errors

**Solution:**
- Use a smaller model (e.g., `phi3:3.8b` instead of `llama3:70b`)
- Close other memory-intensive applications
- Add more RAM or use a machine with more resources
- Enable GPU acceleration if available

#### Issue 5: Port Already in Use

**Error:** `Address already in use` or similar

**Solution:**
```bash
# Find and kill the process using port 11434
sudo lsof -i :11434
sudo kill -9 <PID>

# Or use a different port
OLLAMA_HOST=0.0.0.0:11435 ollama serve
```

#### Issue 6: Permission Denied

**Error:** `Permission denied` when installing or running

**Solution:**
```bash
# Use sudo for Debian-based Linux
sudo curl -fsSL https://ollama.com/install.sh | sh

# Or fix permissions
sudo chown -R $USER:$USER ~/.ollama
```

### Debugging Tips

#### Check Ollama Logs
```bash
# View Ollama logs
journalctl -u ollama -f  # Systemd
# OR
tail -f ~/.ollama/logs/server.log
```

#### Check Open-Omniscience Logs
```bash
# View application logs
 tail -f logs/open_omniscience.log
```

#### Enable Verbose Logging
```python
# In your Python code
import logging
logging.basicConfig(level=logging.DEBUG)
```

#### Test Ollama API Directly
```bash
# Test Ollama API directly
curl http://localhost:11434/api/tags

# Test model generation
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model": "gemma4:e2b", "prompt": "Hello"}'
```

---

## 📈 Performance Optimization

### GPU Acceleration

Ollama automatically uses GPU if available:

```bash
# Check if GPU is being used
nvidia-smi  # For NVIDIA GPUs

# Or check Ollama logs for GPU usage
```

### Model Selection

Choose the right model for your needs:

| Use Case | Recommended Model | Reason |
|----------|------------------|--------|
| Quick testing | `phi3:3.8b` | Fast, lightweight |
| General use | `gemma4:e2b` | Balanced performance |
| Multilingual | `qwen2.5:7b` | Best language support |
| Translation | `bart-large` | Optimized for translation |
| High accuracy | `llama3:70b` | Most capable (requires more resources) |

### Resource Management

#### Limit Concurrent Requests

```python
# In your application code
from src.llm.llm_service import LLMService

# Create service with custom configuration
service = LLMService(config=custom_config)
```

#### Monitor Resource Usage

```bash
# Monitor CPU and memory
htop

# Monitor GPU usage (NVIDIA)
nvidia-smi

# Check disk usage
du -sh ~/.ollama/
```

#### Clean Up Unused Models

```bash
# List downloaded models
ollama list

# Remove unused models
ollama rm model_name
```

---

## 🔄 Updating Models

### Check for Model Updates

```bash
# List available models from Ollama registry
curl https://registry.ollama.ai/api/v1/models | jq
```

### Update a Model

```bash
# Pull the latest version of a model
ollama pull gemma4:e2b

# This will download the latest version if available
```

### Switch Models

```bash
# Use a different model in your requests
curl -X POST http://localhost:8000/api/llm/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello", "model_id": "mistral:7b"}'
```

---

## 🛡️ Security Considerations

### Data Privacy

✅ **All processing happens locally** - No data is sent to external services
✅ **Models are downloaded and run on your machine** - Full control over your data
✅ **No telemetry** - Ollama and Open-Omniscience don't collect usage data

### Network Security

- **Firewall**: Ensure ports 11434 (Ollama) and 8000 (Open-Omniscience) are protected
- **CORS**: Configure `ALLOWED_ORIGINS` to restrict access
- **HTTPS**: Use HTTPS in production for encrypted communication

### Model Security

- **Verify model sources**: Only download models from trusted sources
- **Check model hashes**: Verify model integrity after download
- **Sandboxing**: Consider running Ollama in a container for isolation

---

## 📚 Additional Resources

### Documentation

- [Main README](../README.md) - Project overview
- [User Guide](USER_GUIDE.md) - Complete user guide with LLM features
- [Developer Guide](DEVELOPER_GUIDE.md) - Development guide with LLM development
- [Contributing Guide](../CONTRIBUTING.md) - Contribution guidelines

### Community

- [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) - Report bugs
- [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions) - Ask questions
- [Ollama Documentation](https://github.com/jmorganca/ollama) - Ollama runtime docs

### Useful Links

- [Ollama Model Library](https://ollama.com/library) - Browse available models
- [Ollama GitHub](https://github.com/jmorganca/ollama) - Ollama source code
- [FastAPI Documentation](https://fastapi.tiangolo.com/) - API framework docs

---

## 📝 Quick Reference Commands

### Ollama Commands

| Command | Description |
|---------|-------------|
| `ollama --version` | Check Ollama version |
| `ollama serve` | Start Ollama server |
| `ollama pull model` | Download a model |
| `ollama list` | List downloaded models |
| `ollama rm model` | Remove a model |
| `ollama ps` | List running processes |
| `ollama kill` | Stop Ollama server |

### Open-Omniscience Commands

| Command | Description |
|---------|-------------|
| `uvicorn api.main:app --reload` | Start development server |
| `python scripts/setup_llm.py --all` | Automated LLM setup |
| `python scripts/setup_llm.py --status` | Check LLM status |
| `pytest tests/test_llm.py` | Run LLM tests |

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/llm/health` | Health check |
| GET | `/api/llm/models` | List models |
| GET | `/api/llm/capabilities` | List capabilities |
| POST | `/api/llm/generate` | Generate text |
| POST | `/api/llm/chat` | Chat completion |
| POST | `/api/llm/extract` | Extract information |
| POST | `/api/llm/translate` | Translate text |
| POST | `/api/llm/analyze` | Analyze text |
| POST | `/api/llm/synthesize` | Synthesize information |
| POST | `/api/llm/batch` | Batch processing |

---

## 🎉 Next Steps

Now that you have LLM support set up, you can:

1. **Explore the API**: Try out all the LLM endpoints
2. **Integrate with your workflow**: Use LLM features in your applications
3. **Download more models**: Experiment with different models
4. **Contribute**: Help improve the LLM features
5. **Provide feedback**: Share your experience and suggestions

---

**© 2024 Ideotion. All rights reserved.**

*For questions or issues, please open a GitHub issue or check the documentation.*
