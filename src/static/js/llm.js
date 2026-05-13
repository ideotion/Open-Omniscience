/**
 * Open-Omniscience - Local LLM Frontend JavaScript
 * Complete implementation with all LLM features
 */

// ============================================
// Configuration & State
// ============================================

const LLMConfig = {
    apiBaseUrl: localStorage.getItem('llmApiBaseUrl') || 'http://localhost:8000',
    defaultModel: localStorage.getItem('llmDefaultModel') || 'gemma4:e2b',
    autoDownloadModels: localStorage.getItem('llmAutoDownload') !== 'false',
    timeout: parseInt(localStorage.getItem('llmTimeout')) || 120000,
    theme: localStorage.getItem('llmTheme') || 'dark'
};

const LLMState = {
    ollamaInstalled: null,
    ollamaRunning: null,
    localModels: [],
    availableModels: [],
    chatHistory: [],
    activityLog: []
};

// ============================================
// Utility Functions
// ============================================

function formatDate(time) {
    return new Date(time).toLocaleString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function truncateText(text, length = 100) {
    if (text.length <= length) return text;
    return text.substring(0, length) + '...';
}

// ============================================
// Model Management
// ============================================

/**
 * Populate all model dropdown selects with available models
 */
async function populateModelDropdowns() {
    try {
        const response = await llmApi.getCapabilities();
        const availableModels = response.models.available || [];
        const defaultModel = response.models.default || LLMConfig.defaultModel;
        
        // Get all select elements that should have model options
        const modelSelects = document.querySelectorAll('select[id*="Model"][id*="model"], select[id*="Model"]');
        
        modelSelects.forEach(select => {
            const currentValue = select.value;
            select.innerHTML = '';
            
            // Add models sorted by name
            const sortedModels = [...availableModels].sort();
            
            sortedModels.forEach(modelId => {
                const option = document.createElement('option');
                option.value = modelId;
                
                // Try to get a display name from the model ID
                let displayName = modelId.replace(':', ' ').replace(/-/g, ' ').replace(/\w/g, l => l.toUpperCase());
                
                // Clean up display name
                displayName = displayName.replace('Llama', 'Llama').replace('Phi', 'Phi').replace('Gemma', 'Gemma');
                
                // Add default indicator
                if (modelId === defaultModel) {
                    displayName += ' (Default)';
                    option.selected = true;
                }
                
                option.textContent = displayName;
                select.appendChild(option);
            });
            
            // Restore previous selection if it exists in the new list
            if (currentValue && sortedModels.includes(currentValue)) {
                select.value = currentValue;
            }
        });
        
        console.log(`Populated ${modelSelects.length} model dropdowns with ${sortedModels.length} models`);
    } catch (error) {
        console.error('Error populating model dropdowns:', error);
        // Fallback: keep existing options if any
    }
}

// ============================================
// API Client
// ============================================

class LLMApiClient {
    constructor(baseUrl = LLMConfig.apiBaseUrl, timeout = LLMConfig.timeout) {
        this.baseUrl = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
        this.timeout = timeout;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                const error = await response.text();
                throw new Error(error || `HTTP ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('Request timed out');
            }
            throw error;
        }
    }

    // Health & Status
    async checkHealth() {
        return this.request('/api/llm/health');
    }

    async getModels() {
        return this.request('/api/llm/models');
    }

    async listLocalModels() {
        return this.request('/api/llm/models/local');
    }

    async listRemoteModels() {
        return this.request('/api/llm/models/remote');
    }

    // Model Management
    async downloadModel(modelId) {
        return this.request(`/api/llm/models/${encodeURIComponent(modelId)}/download`, {
            method: 'POST'
        });
    }

    async removeModel(modelId) {
        return this.request(`/api/llm/models/${encodeURIComponent(modelId)}/remove`, {
            method: 'POST'
        });
    }

    async startOllama() {
        return this.request('/api/llm/start', { method: 'POST' });
    }

    async stopOllama() {
        return this.request('/api/llm/stop', { method: 'POST' });
    }

    // Text Processing
    async generateText(data) {
        return this.request('/api/llm/generate', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async chat(data) {
        return this.request('/api/llm/chat', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async extractText(data) {
        return this.request('/api/llm/extract', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async translateText(data) {
        return this.request('/api/llm/translate', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async analyzeText(data) {
        return this.request('/api/llm/analyze', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async synthesizeText(data) {
        return this.request('/api/llm/synthesize', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
}

// Initialize API client
const apiClient = new LLMApiClient();

// ============================================
// UI Functions
// ============================================

function showLoading(show = true) {
    const overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.classList.toggle('hidden', !show);
}

function showToast(message, type = 'info', duration = 5000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
        <span class="toast-message">${escapeHtml(message)}</span>
    `;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'slideIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function addActivity(message, type = 'info') {
    const container = document.getElementById('activityLog');
    if (!container) return;
    
    const item = document.createElement('div');
    item.className = 'activity-item';
    item.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check' : type === 'error' ? 'exclamation' : 'info'}-circle"></i>
        <span>${formatDate(new Date())}: ${escapeHtml(message)}</span>
    `;
    container.insertBefore(item, container.firstChild);
    
    if (container.children.length > 20) {
        container.removeChild(container.lastChild);
    }
}

function setStatusElement(elementId, value, isGood = null) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    if (isGood === true) {
        element.innerHTML = `<span class="badge online"></span><span>${value}</span>`;
    } else if (isGood === false) {
        element.innerHTML = `<span class="badge offline"></span><span>${value}</span>`;
    } else {
        element.textContent = value;
    }
}

// ============================================
// Navigation
// ============================================

function initNavigation() {
    const navButtons = document.querySelectorAll('.nav-btn');
    const sections = document.querySelectorAll('.section');

    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            navButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            const sectionId = btn.dataset.section;
            sections.forEach(s => s.classList.remove('active'));
            const section = document.getElementById(sectionId);
            if (section) section.classList.add('active');
            
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    });
}

// ============================================
// Theme Toggle
// ============================================

function initThemeToggle() {
    const toggleBtn = document.getElementById('toggleTheme');
    const html = document.documentElement;

    html.setAttribute('data-theme', LLMConfig.theme);

    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            const currentTheme = html.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            html.setAttribute('data-theme', newTheme);
            LLMConfig.theme = newTheme;
            localStorage.setItem('llmTheme', newTheme);
            toggleBtn.innerHTML = newTheme === 'dark' ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';
        });

        toggleBtn.innerHTML = LLMConfig.theme === 'dark' ? '<i class="fas fa-moon"></i>' : '<i class="fas fa-sun"></i>';
    }
}

// ============================================
// Dashboard
// ============================================

async function refreshDashboard() {
    try {
        showLoading(true);
        
        const health = await apiClient.checkHealth();
        setStatusElement('ollamaStatus', 
            health.ollama_installed ? (health.ollama_running ? 'Running' : 'Installed') : 'Not Installed',
            health.ollama_running
        );
        LLMState.ollamaInstalled = health.ollama_installed;
        LLMState.ollamaRunning = health.ollama_running;

        const modelsInfo = await apiClient.getModels();
        LLMState.localModels = modelsInfo.local_models || [];
        LLMState.availableModels = modelsInfo.available_models || [];
        
        document.getElementById('downloadedModelsCount').textContent = LLMState.localModels.length;
        
        const storage = await apiClient.getStorageInfo();
        document.getElementById('storageUsage').textContent = `${storage.total_gb || 0} GB`;

        setStatusElement('ollamaInstalledStatus', health.ollama_installed ? 'Yes' : 'No', health.ollama_installed);
        setStatusElement('ollamaRunningStatus', health.ollama_running ? 'Yes' : 'No', health.ollama_running);
        document.getElementById('localModelsCount').textContent = LLMState.localModels.length;
        document.getElementById('availableModelsCount').textContent = LLMState.availableModels.length;

        refreshModelsList();
        showLoading(false);
    } catch (error) {
        showLoading(false);
        showToast(`Error loading dashboard: ${error.message}`, 'error');
        addActivity(`Dashboard refresh failed: ${error.message}`, 'error');
    }
}

function initDashboard() {
    document.getElementById('startOllama')?.addEventListener('click', async () => {
        try {
            showLoading(true);
            await apiClient.startOllama();
            showToast('Ollama started successfully!', 'success');
            addActivity('Ollama server started');
            await refreshDashboard();
        } catch (error) {
            showToast(`Failed to start Ollama: ${error.message}`, 'error');
            addActivity(`Failed to start Ollama: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    document.getElementById('downloadDefaultModel')?.addEventListener('click', async () => {
        try {
            showLoading(true);
            await apiClient.downloadModel(LLMConfig.defaultModel);
            showToast(`Model ${LLMConfig.defaultModel} downloaded!`, 'success');
            addActivity(`Downloaded model: ${LLMConfig.defaultModel}`);
            await refreshDashboard();
        } catch (error) {
            showToast(`Failed to download model: ${error.message}`, 'error');
            addActivity(`Failed to download model: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    document.getElementById('testGeneration')?.addEventListener('click', () => {
        document.querySelector('[data-section="text-generation"]')?.click();
        document.getElementById('genPrompt').value = 'Hello, how are you today?';
        document.getElementById('generateTextBtn').click();
    });

    document.getElementById('viewAllModels')?.addEventListener('click', () => {
        document.querySelector('[data-section="models"]')?.click();
    });

    document.getElementById('refreshStatus')?.addEventListener('click', refreshDashboard);
    refreshDashboard();
}

// ============================================
// Text Generation
// ============================================

function initTextGeneration() {
    const genBtn = document.getElementById('generateTextBtn');
    const promptInput = document.getElementById('genPrompt');
    const outputEl = document.getElementById('genOutput');
    const modelSelect = document.getElementById('genModel');
    const tempSlider = document.getElementById('genTemperature');
    const tempValue = document.getElementById('genTemperatureValue');
    const maxTokensInput = document.getElementById('genMaxTokens');
    const systemPromptInput = document.getElementById('genSystemPrompt');
    const copyBtn = document.getElementById('copyGenOutput');
    const clearBtn = document.getElementById('clearGenOutput');

    if (!genBtn || !promptInput || !outputEl) return;

    // Temperature slider
    tempSlider?.addEventListener('input', () => {
        tempValue.textContent = tempSlider.value;
    });

    // Generate text
    genBtn.addEventListener('click', async () => {
        const prompt = promptInput.value.trim();
        if (!prompt) {
            showToast('Please enter a prompt', 'error');
            return;
        }

        try {
            showLoading(true);
            const startTime = Date.now();
            
            const response = await apiClient.generateText({
                prompt: prompt,
                model_id: modelSelect?.value || LLMConfig.defaultModel,
                temperature: parseFloat(tempSlider?.value || 0.7),
                max_tokens: parseInt(maxTokensInput?.value || 512),
                system_prompt: systemPromptInput?.value || null
            });

            const endTime = Date.now();
            const duration = endTime - startTime;

            outputEl.innerHTML = `<p>${escapeHtml(response.generated_text)}</p>`;
            document.getElementById('genTime').textContent = duration;
            document.getElementById('genTokens').textContent = response.generated_text ? response.generated_text.split(' ').length : 0;

            addActivity(`Generated text: ${prompt.substring(0, 50)}...`);
        } catch (error) {
            showToast(`Generation failed: ${error.message}`, 'error');
            addActivity(`Generation failed: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    // Copy output
    copyBtn?.addEventListener('click', () => {
        navigator.clipboard.writeText(outputEl.textContent);
        showToast('Copied to clipboard!', 'success');
    });

    // Clear output
    clearBtn?.addEventListener('click', () => {
        outputEl.innerHTML = '<p class="placeholder-text">Generated text will appear here...</p>';
    });

    // Example buttons
    document.querySelectorAll('#text-generation .example-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            promptInput.value = btn.dataset.prompt || '';
        });
    });
}

// ============================================
// Chat
// ============================================

function initChat() {
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendChatBtn');
    const messagesContainer = document.getElementById('chatMessages');
    const modelSelect = document.getElementById('chatModel');
    const clearBtn = document.getElementById('clearChat');
    const exportBtn = document.getElementById('exportChat');

    if (!chatInput || !sendBtn || !messagesContainer) return;

    let chatHistory = [];

    function addMessage(role, content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${role}`;
        messageDiv.innerHTML = `
            <div class="chat-avatar">
                <i class="fas fa-${role === 'user' ? 'user' : 'robot'}"></i>
            </div>
            <div class="chat-content">${escapeHtml(content)}</div>
        `;
        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    function clearChat() {
        chatHistory = [];
        messagesContainer.innerHTML = `
            <div class="chat-welcome">
                <i class="fas fa-comment-dots"></i>
                <p>Start a new conversation</p>
            </div>
        `;
    }

    function exportChat() {
        const data = chatHistory.map(msg => `${msg.role}: ${msg.content}`).join('\n\n');
        const blob = new Blob([data], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `chat-export-${new Date().toISOString().slice(0, 10)}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    }

    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        // Add user message
        addMessage('user', text);
        chatHistory.push({ role: 'user', content: text });
        chatInput.value = '';

        try {
            showLoading(true);
            
            const response = await apiClient.chat({
                messages: chatHistory.map(msg => ({ role: msg.role, content: msg.content })),
                model_id: modelSelect?.value || LLMConfig.defaultModel
            });

            // Add assistant message
            const assistantText = response.response || 'No response';
            addMessage('assistant', assistantText);
            chatHistory.push({ role: 'assistant', content: assistantText });

            addActivity(`Chat: ${text.substring(0, 50)}...`);
        } catch (error) {
            showToast(`Chat failed: ${error.message}`, 'error');
            addActivity(`Chat failed: ${error.message}`, 'error');
            addMessage('assistant', `Error: ${error.message}`);
        } finally {
            showLoading(false);
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    clearBtn?.addEventListener('click', clearChat);
    exportBtn?.addEventListener('click', exportChat);

    // Initial welcome message
    clearChat();
}

// ============================================
// Text Extraction
// ============================================

function initTextExtraction() {
    const extractBtn = document.getElementById('extractTextBtn');
    const contentInput = document.getElementById('extContent');
    const outputEl = document.getElementById('extOutput');
    const modelSelect = document.getElementById('extModel');
    const typeSelect = document.getElementById('extType');
    const copyBtn = document.getElementById('copyExtOutput');
    const clearBtn = document.getElementById('clearExtOutput');

    if (!extractBtn || !contentInput || !outputEl) return;

    extractBtn.addEventListener('click', async () => {
        const content = contentInput.value.trim();
        if (!content) {
            showToast('Please enter content to extract from', 'error');
            return;
        }

        try {
            showLoading(true);
            
            const response = await apiClient.extractText({
                content: content,
                model_id: modelSelect?.value || LLMConfig.defaultModel,
                extraction_type: typeSelect?.value || 'general'
            });

            if (response.data && typeof response.data === 'object') {
                outputEl.innerHTML = `<pre>${JSON.stringify(response.data, null, 2)}</pre>`;
            } else {
                outputEl.innerHTML = `<p>${escapeHtml(response.data || response.raw_response || 'No data extracted')}</p>`;
            }

            addActivity(`Extracted ${response.extraction_type} from text`);
        } catch (error) {
            showToast(`Extraction failed: ${error.message}`, 'error');
            addActivity(`Extraction failed: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    copyBtn?.addEventListener('click', () => {
        navigator.clipboard.writeText(outputEl.textContent);
        showToast('Copied to clipboard!', 'success');
    });

    clearBtn?.addEventListener('click', () => {
        outputEl.innerHTML = '<p class="placeholder-text">Extracted data will appear here...</p>';
    });

    document.querySelectorAll('#extraction .example-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            contentInput.value = btn.dataset.content || '';
        });
    });
}

// ============================================
// Translation
// ============================================

function initTranslation() {
    const translateBtn = document.getElementById('translateBtn');
    const textInput = document.getElementById('transText');
    const outputEl = document.getElementById('transOutput');
    const sourceLangSelect = document.getElementById('transSourceLang');
    const targetLangSelect = document.getElementById('transTargetLang');
    const modelSelect = document.getElementById('transModel');
    const copyBtn = document.getElementById('copyTransOutput');
    const clearBtn = document.getElementById('clearTransOutput');

    if (!translateBtn || !textInput || !outputEl) return;

    translateBtn.addEventListener('click', async () => {
        const text = textInput.value.trim();
        if (!text) {
            showToast('Please enter text to translate', 'error');
            return;
        }

        try {
            showLoading(true);
            
            const response = await apiClient.translateText({
                text: text,
                target_language: targetLangSelect?.value || 'en',
                source_language: sourceLangSelect?.value || 'auto',
                model_id: modelSelect?.value || LLMConfig.defaultModel
            });

            outputEl.innerHTML = `<p>${escapeHtml(response.translation)}</p>`;
            document.getElementById('transFromLang').textContent = response.source_language;
            document.getElementById('transToLang').textContent = response.target_language;

            addActivity(`Translated from ${response.source_language} to ${response.target_language}`);
        } catch (error) {
            showToast(`Translation failed: ${error.message}`, 'error');
            addActivity(`Translation failed: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    copyBtn?.addEventListener('click', () => {
        navigator.clipboard.writeText(outputEl.textContent);
        showToast('Copied to clipboard!', 'success');
    });

    clearBtn?.addEventListener('click', () => {
        outputEl.innerHTML = '<p class="placeholder-text">Translation will appear here...</p>';
    });

    document.querySelectorAll('#translation .example-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            textInput.value = btn.dataset.text || '';
            if (btn.dataset.from) sourceLangSelect.value = btn.dataset.from;
            if (btn.dataset.to) targetLangSelect.value = btn.dataset.to;
        });
    });
}

// ============================================
// Text Analysis
// ============================================

function initTextAnalysis() {
    const analyzeBtn = document.getElementById('analyzeTextBtn');
    const textInput = document.getElementById('analysisText');
    const outputEl = document.getElementById('analysisOutput');
    const modelSelect = document.getElementById('analysisModel');
    const typeSelect = document.getElementById('analysisType');
    const copyBtn = document.getElementById('copyAnalysisOutput');
    const clearBtn = document.getElementById('clearAnalysisOutput');

    if (!analyzeBtn || !textInput || !outputEl) return;

    analyzeBtn.addEventListener('click', async () => {
        const text = textInput.value.trim();
        if (!text) {
            showToast('Please enter text to analyze', 'error');
            return;
        }

        try {
            showLoading(true);
            
            const response = await apiClient.analyzeText({
                text: text,
                model_id: modelSelect?.value || LLMConfig.defaultModel,
                analysis_type: typeSelect?.value || 'sentiment'
            });

            if (response.results && typeof response.results === 'object') {
                outputEl.innerHTML = `<pre>${JSON.stringify(response.results, null, 2)}</pre>`;
            } else {
                outputEl.innerHTML = `<p>${escapeHtml(response.results?.text || response.raw_response || 'No analysis results')}</p>`;
            }

            addActivity(`Analyzed text with ${response.analysis_type}`);
        } catch (error) {
            showToast(`Analysis failed: ${error.message}`, 'error');
            addActivity(`Analysis failed: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    copyBtn?.addEventListener('click', () => {
        navigator.clipboard.writeText(outputEl.textContent);
        showToast('Copied to clipboard!', 'success');
    });

    clearBtn?.addEventListener('click', () => {
        outputEl.innerHTML = '<p class="placeholder-text">Analysis results will appear here...</p>';
    });

    document.querySelectorAll('#analysis .example-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            textInput.value = btn.dataset.text || '';
        });
    });
}

// ============================================
// Synthesis
// ============================================

function initSynthesis() {
    const synthesizeBtn = document.getElementById('synthesizeBtn');
    const outputEl = document.getElementById('synthesisOutput');
    const modelSelect = document.getElementById('synthesisModel');
    const typeSelect = document.getElementById('synthesisType');
    const sourcesList = document.getElementById('sourcesList');
    const addSourceBtn = document.getElementById('addSourceBtn');
    const copyBtn = document.getElementById('copySynthesisOutput');
    const clearBtn = document.getElementById('clearSynthesisOutput');

    if (!synthesizeBtn || !outputEl || !sourcesList) return;

    function addSource(text = '') {
        const sourceItem = document.createElement('div');
        sourceItem.className = 'source-item';
        sourceItem.innerHTML = `
            <textarea class="form-textarea source-text" placeholder="Enter source text..." rows="3">${escapeHtml(text)}</textarea>
            <button class="btn-icon remove-source" title="Remove">
                <i class="fas fa-times"></i>
            </button>
        `;
        
        sourceItem.querySelector('.remove-source').addEventListener('click', () => {
            if (sourcesList.children.length > 1) {
                sourceItem.remove();
            } else {
                showToast('At least one source is required', 'error');
            }
        });
        
        sourcesList.appendChild(sourceItem);
    }

    addSourceBtn?.addEventListener('click', () => addSource());
    addSource(); // Add first source

    synthesizeBtn.addEventListener('click', async () => {
        const sources = Array.from(sourcesList.children).map(item => {
            return item.querySelector('.source-text').value;
        }).filter(text => text.trim());

        if (sources.length === 0) {
            showToast('Please add at least one source', 'error');
            return;
        }

        try {
            showLoading(true);
            
            const response = await apiClient.synthesizeText({
                sources: sources,
                model_id: modelSelect?.value || LLMConfig.defaultModel,
                synthesis_type: typeSelect?.value || 'summary'
            });

            if (response.results && typeof response.results === 'object') {
                outputEl.innerHTML = `<pre>${JSON.stringify(response.results, null, 2)}</pre>`;
            } else {
                outputEl.innerHTML = `<p>${escapeHtml(response.results?.text || response.raw_response || 'No synthesis results')}</p>`;
            }

            addActivity(`Synthesized ${sources.length} sources with ${response.synthesis_type}`);
        } catch (error) {
            showToast(`Synthesis failed: ${error.message}`, 'error');
            addActivity(`Synthesis failed: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });

    copyBtn?.addEventListener('click', () => {
        navigator.clipboard.writeText(outputEl.textContent);
        showToast('Copied to clipboard!', 'success');
    });

    clearBtn?.addEventListener('click', () => {
        outputEl.innerHTML = '<p class="placeholder-text">Synthesis result will appear here...</p>';
    });
}

// ============================================
// Model Management
// ============================================

function refreshModelsList() {
    const localList = document.getElementById('localModelsList');
    const availableList = document.getElementById('availableModelsList');

    if (!localList || !availableList) return;

    // Update local models list
    if (LLMState.localModels.length === 0) {
        localList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-inbox"></i>
                <p>No models downloaded yet</p>
                <button id="downloadFirstModel" class="btn btn-primary">
                    <i class="fas fa-download"></i> Download Default Model
                </button>
            </div>
        `;
        document.getElementById('downloadFirstModel')?.addEventListener('click', async () => {
            try {
                showLoading(true);
                await apiClient.downloadModel(LLMConfig.defaultModel);
                showToast(`Model ${LLMConfig.defaultModel} downloaded!`, 'success');
                addActivity(`Downloaded model: ${LLMConfig.defaultModel}`);
                await refreshDashboard();
            } catch (error) {
                showToast(`Failed to download model: ${error.message}`, 'error');
            } finally {
                showLoading(false);
            }
        });
    } else {
        localList.innerHTML = LLMState.localModels.map(modelId => {
            const model = LLMState.availableModels.find(m => m.id === modelId);
            return `
                <div class="model-item">
                    <div class="model-icon">
                        <i class="fas fa-cube"></i>
                    </div>
                    <div class="model-info">
                        <div class="model-name">${model ? escapeHtml(model.name) : modelId}</div>
                        <div class="model-id">${escapeHtml(modelId)}</div>
                    </div>
                    <div class="model-actions">
                        <button class="btn btn-secondary model-remove-btn" data-model="${modelId}" title="Remove">
                            <i class="fas fa-trash"></i> Remove
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        // Add event listeners for remove buttons
        localList.querySelectorAll('.model-remove-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const modelId = btn.dataset.model;
                if (confirm(`Are you sure you want to remove ${modelId}?`)) {
                    try {
                        showLoading(true);
                        await apiClient.removeModel(modelId);
                        showToast(`Model ${modelId} removed!`, 'success');
                        addActivity(`Removed model: ${modelId}`);
                        await refreshDashboard();
                    } catch (error) {
                        showToast(`Failed to remove model: ${error.message}`, 'error');
                    } finally {
                        showLoading(false);
                    }
                }
            });
        });
    }

    // Update available models list
    availableList.innerHTML = LLMState.availableModels.map(model => {
        const isDownloaded = LLMState.localModels.includes(model.id);
        return `
            <div class="model-item">
                <div class="model-icon">
                    <i class="fas fa-${isDownloaded ? 'check-circle' : 'download'}"></i>
                </div>
                <div class="model-info">
                    <div class="model-name">${escapeHtml(model.name)}</div>
                    <div class="model-id">${escapeHtml(model.id)}</div>
                    <div class="model-size">${model.size_gb} GB</div>
                </div>
                <div class="model-actions">
                    ${isDownloaded ? '' : `
                        <button class="btn btn-primary model-download-btn" data-model="${model.id}" title="Download">
                            <i class="fas fa-download"></i> Download
                        </button>
                    `}
                </div>
            </div>
        `;
    }).join('');

    // Add event listeners for download buttons
    availableList.querySelectorAll('.model-download-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const modelId = btn.dataset.model;
            try {
                showLoading(true);
                await apiClient.downloadModel(modelId);
                showToast(`Model ${modelId} downloaded!`, 'success');
                addActivity(`Downloaded model: ${modelId}`);
                await refreshDashboard();
            } catch (error) {
                showToast(`Failed to download model: ${error.message}`, 'error');
            } finally {
                showLoading(false);
            }
        });
    });
}

function initModelManagement() {
    document.getElementById('refreshModels')?.addEventListener('click', refreshDashboard);
    document.getElementById('checkStorage')?.addEventListener('click', async () => {
        try {
            showLoading(true);
            const storage = await apiClient.getStorageInfo();
            showToast(`Storage usage: ${storage.total_gb || 0} GB`, 'info');
        } catch (error) {
            showToast(`Failed to check storage: ${error.message}`, 'error');
        } finally {
            showLoading(false);
        }
    });
}

// ============================================
// Settings
// ============================================

function initSettings() {
    const toggleBtn = document.getElementById('toggleSettings');
    const settingsContent = document.getElementById('settingsContent');
    const saveBtn = document.getElementById('saveSettings');
    const apiUrlInput = document.getElementById('apiBaseUrl');
    const defaultModelSelect = document.getElementById('defaultModel');
    const autoDownloadCheckbox = document.getElementById('autoDownloadModels');
    const timeoutInput = document.getElementById('timeout');

    if (!toggleBtn || !settingsContent) return;

    // Load saved settings
    if (apiUrlInput) apiUrlInput.value = LLMConfig.apiBaseUrl;
    if (defaultModelSelect) defaultModelSelect.value = LLMConfig.defaultModel;
    if (autoDownloadCheckbox) autoDownloadCheckbox.checked = LLMConfig.autoDownloadModels;
    if (timeoutInput) timeoutInput.value = LLMConfig.timeout / 1000;

    toggleBtn.addEventListener('click', () => {
        settingsContent.classList.toggle('active');
    });

    saveBtn?.addEventListener('click', () => {
        if (apiUrlInput) {
            LLMConfig.apiBaseUrl = apiUrlInput.value;
            localStorage.setItem('llmApiBaseUrl', LLMConfig.apiBaseUrl);
        }
        if (defaultModelSelect) {
            LLMConfig.defaultModel = defaultModelSelect.value;
            localStorage.setItem('llmDefaultModel', LLMConfig.defaultModel);
        }
        if (autoDownloadCheckbox) {
            LLMConfig.autoDownloadModels = autoDownloadCheckbox.checked;
            localStorage.setItem('llmAutoDownload', LLMConfig.autoDownloadModels);
        }
        if (timeoutInput) {
            LLMConfig.timeout = parseInt(timeoutInput.value) * 1000;
            localStorage.setItem('llmTimeout', LLMConfig.timeout);
        }
        
        showToast('Settings saved!', 'success');
        settingsContent.classList.remove('active');
    });
}

// ============================================
// Initialization
// ============================================

document.addEventListener('DOMContentLoaded', async () => {
    initNavigation();
    initThemeToggle();
    initDashboard();
    
    // Load models dynamically before initializing feature-specific functions
    await populateModelDropdowns();
    
    initTextGeneration();
    initChat();
    initTextExtraction();
    initTranslation();
    initTextAnalysis();
    initSynthesis();
    initModelManagement();
    initSettings();
});
