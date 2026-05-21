# LLM Setup Guide for Open-Omniscience

**Version:** 1.0  
**Last Updated:** 2025-05-21  
**Author:** Ideotion

---

## 📋 Overview

This guide provides step-by-step instructions for setting up Local LLM (Large Language Model) support in Open-Omniscience. The LLM features enable advanced text processing capabilities including text generation, translation, analysis, and synthesis - all while maintaining full data privacy as all processing happens locally on your machine.

---

## 🎯 Prerequisites

### System Requirements

#### Minimum (Core Features Only)
- **Operating System:** Linux (Debian/Ubuntu recommended), macOS, or Windows (WSL2)
- **CPU:** 2 cores
- **RAM:** 4GB
- **Storage:** 10GB free disk space
- **Python:** 3.8+

#### Recommended (With LLM Support)
- **Operating System:** Linux (Ubuntu 22.04+ or Debian 12+ recommended)
- **CPU:** 8 cores
- **RAM:** 16GB
- **Storage:** 50GB+ free disk space (for 3-4 models)
- **GPU:** NVIDIA GPU with 8GB+ VRAM (recommended for better performance)
- **Python:** 3.8+

#### High-End (Full LLM Capabilities)
- **Operating System:** Linux (Ubuntu, Debian, etc.)
- **CPU:** 16+ cores
- **RAM:** 32GB+
- **Storage:** 100GB+ free disk space (for multiple large models)
- **GPU:** NVIDIA GPU with 24GB+ VRAM
- **Python:** 3.8+

### Software Dependencies

- **Git** - Version control
- **Python** - 3.8 or higher
- **pip** - Python package manager
- **Ollama** - Local LLM runtime (required for LLM features)

---

## 🚀 Installation Methods

### Method 1: Direct Python Installation (Recommended)

This is the simplest way to get started with LLM support.

#### Step 1: Clone the Repository
```bash
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
```

#### Step 2: Set Up Python Environment
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

#### Step 3: Install Core Dependencies
```bash
pip install -r requirements-core.txt
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
ollama serve &

# Verify it's running
ollama --version
```

#### Step 7: Configure Environment
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your settings (optional)
nano .env

# Recommended settings for LLM:
OLLAMA_HOST=http://localhost:11434
AUTO_DOWNLOAD_MODELS=false
```

#### Step 8: Start Open-Omniscience
```bash
# Start the application
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Or for production:
pip install gunicorn
gunicorn -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000 api.main:app
```

#### Step 9: Verify Installation
```bash
# Check LLM service health
curl http://localhost:8000/api/llm/health

# List available models
curl http://localhost:8000/api/llm/models
```

#### Step 10: Download Models (Optional)
```bash
# Download the default model (gemma4:e2b)
ollama pull gemma4:e2b

# Or download multiple models
ollama pull mistral:7b
ollama pull phi3:3.8b
ollama pull llama3:8b
```

---

## 📚 Model Recommendations

### Lightweight Models (Good for testing, lower resource usage)
- **phi3:3.8b** - Fast, efficient, good for basic tasks
- **gemma4:e2b** - Balanced performance and quality
- **mistral:7b** - Good general purpose model

### Medium Models (Better quality, moderate resource usage)
- **llama3:8b** - Improved reasoning capabilities
- **mistral:7b-instruct** - Better at following instructions
- **gemma:7b** - Google's open model

### Large Models (Best quality, higher resource usage)
- **llama3:70b** - Excellent for complex tasks (requires 48GB+ RAM)
- **mistral-large** - High quality responses
- **mixtral-8x7b** - Mixture of experts model

### Specialized Models
- **codellama:13b** - Optimized for code generation and analysis
- **llava:13b** - Multimodal (text + image) model

---

## ⚙️ Configuration

### Ollama Configuration

Edit your Ollama configuration at `~/.ollama/ollama.env`:

```bash
# Allow connections from other hosts (for remote access)
OLLAMA_HOST=0.0.0.0

# Allow all origins (for web interface)
OLLAMA_ORIGINS=*

# Custom model directory
OLLAMA_MODELS=/path/to/models

# GPU settings (if available)
OLLAMA_MAX_LOADED_MODELS=2
OLLAMA_GPU=all
```

### Open-Omniscience LLM Configuration

In your `.env` file:

```bash
# Enable/disable LLM features
LLM_ENABLED=true

# Ollama server URL
OLLAMA_HOST=http://localhost:11434

# Default model to use
DEFAULT_MODEL=gemma4:e2b

# Auto-download models on first use
auto_download_models=false

# Maximum context length
MAX_CONTEXT_LENGTH=4096

# Temperature (creativity)
LLM_TEMPERATURE=0.7

# Top-p sampling
LLM_TOP_P=0.9

# Maximum tokens per response
MAX_TOKENS=2048
```

---

## 🎯 Using LLM Features

### Basic Text Generation

```python
from api.llm import generate_text

prompt = "Explain the concept of open-source software"
response = generate_text(prompt, model="gemma4:e2b")
print(response)
```

### Text Analysis

```python
from api.llm import analyze_text

text = "Your long document text here..."
analysis = analyze_text(text, model="mistral:7b")
print(analysis)
```

### Translation

```python
from api.llm import translate_text

text = "Hello, how are you?"
translation = translate_text(text, target_language="fr", model="gemma4:e2b")
print(translation)  # "Bonjour, comment allez-vous ?"
```

### Summarization

```python
from api.llm import summarize_text

long_text = "Your long article or document..."
summary = summarize_text(long_text, model="llama3:8b")
print(summary)
```

---

## 🔧 Model Management

### List Available Models
```bash
ollama list
```

### Pull a New Model
```bash
ollama pull model-name
```

### Remove a Model
```bash
ollama rm model-name
```

### Check Model Information
```bash
ollama show model-name
```

### Create Custom Model
```bash
# Create a modelfile
nano Modelfile

# Example modelfile
FROM llama3:8b
SYSTEM You are a helpful assistant that always responds in JSON format.

# Create the model
ollama create my-custom-model -f Modelfile
```

---

## 📊 Performance Optimization

### GPU Acceleration

If you have an NVIDIA GPU, Ollama will automatically use it. To verify:

```bash
# Check GPU detection
ollama run llama3:8b "What GPU am I using?"

# Force CPU only (for testing)
OLLAMA_NO_GPU=true ollama run llama3:8b
```

### Memory Management

```bash
# Limit RAM usage (in bytes)
OLLAMA_MAX_RAM=16GB

# Limit VRAM usage
OLLAMA_MAX_VRAM=8GB

# Limit the number of loaded models
OLLAMA_MAX_LOADED_MODELS=1
```

### Model Quantization

Use smaller quantized versions of models to save memory:

```bash
# 4-bit quantization (smallest, fastest)
ollama pull llama3:8b-instruct-q4_0

# 8-bit quantization (balanced)
ollama pull llama3:8b-instruct-q8_0
```

---

## 🛠️ Troubleshooting

### Common Issues

#### Ollama fails to start
- Check that your system meets the minimum requirements
- Verify you have enough disk space
- Check for port conflicts: `ss -tulnp | grep 11434`

#### Model download fails
- Check your internet connection
- Verify you have enough disk space
- Try a smaller model first

#### Out of memory errors
- Try a smaller model
- Use quantized versions (q4_0, q8_0)
- Close other memory-intensive applications
- Add swap space: `sudo fallocate -l 8G /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`

#### GPU not detected
- Install NVIDIA drivers
- Install CUDA toolkit
- Verify with: `nvidia-smi`

#### Slow performance
- Use a smaller model
- Enable GPU acceleration
- Reduce the context length

### Debug Mode

Run Ollama with debug logging:
```bash
OLLAMA_DEBUG=1 ollama serve
```

---

## 📚 Additional Resources

- [Ollama Documentation](https://github.com/jmorganca/ollama)
- [Ollama Model Library](https://ollama.ai/library)
- [Open-Omniscience API Documentation](API_DOCUMENTATION.md)
- [Deployment Guide](DEPLOYMENT_GUIDE.md)

---

## 🎉 Next Steps

1. **Test the LLM features** - Try different models and prompts
2. **Integrate with your workflow** - Use the API in your applications
3. **Explore custom models** - Create models tailored to your needs
4. **Monitor performance** - Optimize based on your hardware
5. **Contribute** - Share your custom models and configurations

---

*Last updated: 2025-05-21*
