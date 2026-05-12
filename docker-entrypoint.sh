#!/bin/bash
# Docker entrypoint script for Open-Omniscience with LLM support
# This script starts Ollama in the background and then launches the main application

set -e

echo "Starting Open-Omniscience with LLM support..."

# Function to check if a port is in use (without nc)
port_in_use() {
    python3 -c "import socket; s = socket.socket(); s.settimeout(1); result = s.connect_ex(('localhost', $1)); s.close(); print('yes' if result == 0 else 'no')"
}

# Start Ollama server in the background
echo "Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to start (up to 30 seconds)
for i in {1..30}; do
    if [ "$(port_in_use 11434)" = "yes" ]; then
        echo "Ollama server is running on port 11434"
        break
    fi
    echo "Waiting for Ollama to start... ($i/30)"
    sleep 1
done

if [ "$(port_in_use 11434)" = "no" ]; then
    echo "Warning: Ollama failed to start within 30 seconds"
    echo "Some LLM features may not be available"
fi

# Check if we should download default models
if [ "${DOWNLOAD_DEFAULT_MODELS:-false}" = "true" ]; then
    echo "Downloading default LLM models..."
    python /app/scripts/setup_llm.py --download-models
fi

# Start the main application
echo "Starting Open-Omniscience API..."
exec "$@"
