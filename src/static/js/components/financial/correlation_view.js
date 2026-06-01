/**
 * Correlation View Component for Pillar 5 - Financial Intelligence
 * 
 * Displays hybrid correlation results between articles and financial instruments
 * using the correlation engine with mention, keyword, sector, and temporal scoring.
 * 
 * Features:
 * - Fetch correlations from /api/v1/financial/correlations endpoints
 * - Display correlation scores with breakdown by component (mention, keyword, sector, temporal)
 * - Show matched keywords and sectors
 * - Filter by article, instrument, correlation type, or score threshold
 * - Interactive visualization of correlation networks
 */

class CorrelationView {
    /**
     * Create a new Correlation View instance
     * @param {Object} options - Configuration options
     * @param {string|HTMLElement} options.container - Container element or selector
     * @param {Object} options.apiClient - API client instance
     * @param {string} options.articleId - Optional initial article ID
     */
    constructor(options = {}) {
        this.container = typeof options.container === 'string' 
            ? document.querySelector(options.container) 
            : options.container;
        this.apiClient = options.apiClient || new APIClient({ baseUrl: '/api/v1' });
        this.articleId = options.articleId || null;
        
        // State
        this.articles = [];
        this.instruments = [];
        this.correlations = [];
        this.selectedArticle = null;
        this.selectedInstrument = null;
        this.minScoreThreshold = 0.1;
        this.correlationTypes = ['mention', 'keyword', 'sector', 'temporal', 'hybrid'];
        this.selectedTypes = ['hybrid'];
        
        // UI Elements
        this.ui = {};
        
        // Hybrid correlation weights (from specification)
        this.weights = {
            mention: 0.4,
            keyword: 0.3,
            sector: 0.2,
            temporal: 0.1
        };
        
        // Color scheme for correlation scores
        this.scoreColors = {
            getColor: (score) => {
                if (score >= 0.8) return '#10b981'; // Strong positive
                if (score >= 0.6) return '#3b82f6'; // Moderate positive
                if (score >= 0.4) return '#f59e0b'; // Weak positive
                if (score >= 0.2) return '#fbbf24'; // Very weak
                return '#ef4444'; // Negative/none
            }
        };
        
        this._initialize();
    }
    
    /**
     * Initialize the component
     * @private
     */
    _initialize() {
        if (!this.container) {
            console.error('CorrelationView: Container element not found');
            return;
        }
        
        this._createUI();
        this._bindEvents();
        this._loadInitialData();
    }
    
    /**
     * Create the UI structure
     * @private
     */
    _createUI() {
        this.container.innerHTML = `
            <div class="correlation-view">
                <div class="correlation-view-header">
                    <h2>Financial Correlation View</h2>
                    <div class="correlation-view-controls">
                        <div class="article-selector">
                            <select class="article-select">
                                <option value="">Select Article...</option>
                            </select>
                            <button class="btn-load-article">Load Article</button>
                        </div>
                        <div class="score-filter">
                            <label>Min Score:</label>
                            <input type="range" class="score-slider" min="0" max="1" step="0.01" value="0.1">
                            <span class="score-value">0.1</span>
                        </div>
                        <div class="type-filter">
                            <label>Types:</label>
                            <select class="type-select" multiple>
                                <option value="hybrid" selected>Hybrid</option>
                                <option value="mention">Mention</option>
                                <option value="keyword">Keyword</option>
                                <option value="sector">Sector</option>
                                <option value="temporal">Temporal</option>
                            </select>
                        </div>
                    </div>
                </div>
                
                <div class="correlation-view-layout">
                    <div class="correlation-summary">
                        <h3>Correlation Summary</h3>
                        <div class="summary-stats">
                            <div class="stat-card">
                                <h4>Total Correlations</h4>
                                <p class="stat-value">0</p>
                            </div>
                            <div class="stat-card">
                                <h4>Avg Score</h4>
                                <p class="stat-value">0.00</p>
                            </div>
                            <div class="stat-card">
                                <h4>Highest Score</h4>
                                <p class="stat-value">0.00</p>
                            </div>
                            <div class="stat-card">
                                <h4>Strong (>=0.8)</h4>
                                <p class="stat-value">0</p>
                            </div>
                        </div>
                        
                        <div class="weights-display">
                            <h4>Hybrid Scoring Weights</h4>
                            <div class="weight-bars">
                                ${Object.entries(this.weights).map(([type, weight]) => `
                                    <div class="weight-bar">
                                        <span class="weight-label">${type}</span>
                                        <div class="weight-bar-container">
                                            <div class="weight-bar-fill" 
                                                 style="width: ${weight * 100}%; background-color: ${this._getTypeColor(type)}"></div>
                                        </div>
                                        <span class="weight-value">${weight}</span>
                                    </div>
                                `).join('')}
                            </div>
                            <p class="weight-formula">
                                <strong>Formula:</strong> correlation_score = (mention × 0.4) + (keyword × 0.3) + (sector × 0.2) + (temporal × 0.1)
                            </p>
                        </div>
                    </div>
                    
                    <div class="correlation-main-content">
                        <div class="correlation-list-container">
                            <h3>Correlations <span class="correlation-count">(0)</span></h3>
                            <div class="correlation-list">
                                <div class="correlation-cards"></div>
                            </div>
                        </div>
                        
                        <div class="correlation-visualization">
                            <h3>Correlation Network</h3>
                            <div class="network-container">
                                <svg class="correlation-network" width="100%" height="400"></svg>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="correlation-view-footer">
                    <button class="btn-export-correlations" disabled>Export Correlations</button>
                    <button class="btn-refresh-correlations">Refresh</button>
                </div>
            </div>
        `;
        
        // Cache UI elements
        this.ui.articleSelect = this.container.querySelector('.article-select');
        this.ui.loadArticleBtn = this.container.querySelector('.btn-load-article');
        this.ui.scoreSlider = this.container.querySelector('.score-slider');
        this.ui.scoreValue = this.container.querySelector('.score-value');
        this.ui.typeSelect = this.container.querySelector('.type-select');
        this.ui.correlationCards = this.container.querySelector('.correlation-cards');
        this.ui.correlationCount = this.container.querySelector('.correlation-count');
        this.ui.totalCorrelations = this.container.querySelectorAll('.stat-card')[0].querySelector('.stat-value');
        this.ui.avgScore = this.container.querySelectorAll('.stat-card')[1].querySelector('.stat-value');
        this.ui.highestScore = this.container.querySelectorAll('.stat-card')[2].querySelector('.stat-value');
        this.ui.strongCorrelations = this.container.querySelectorAll('.stat-card')[3].querySelector('.stat-value');
        this.ui.exportBtn = this.container.querySelector('.btn-export-correlations');
        this.ui.refreshBtn = this.container.querySelector('.btn-refresh-correlations');
        this.ui.networkSvg = this.container.querySelector('.correlation-network');
    }
    
    /**
     * Get color for correlation type
     * @private
     */
    _getTypeColor(type) {
        const colors = {
            mention: '#3b82f6',
            keyword: '#10b981',
            sector: '#8b5cf6',
            temporal: '#f59e0b',
            hybrid: '#6366f1'
        };
        return colors[type] || '#666';
    }
    
    /**
     * Bind event listeners
     * @private
     */
    _bindEvents() {
        // Article selection
        this.ui.articleSelect.addEventListener('change', (e) => {
            this.articleId = e.target.value || null;
        });
        
        // Load article button
        this.ui.loadArticleBtn.addEventListener('click', () => {
            if (this.articleId) {
                this._loadCorrelations(this.articleId);
            }
        });
        
        // Score threshold slider
        this.ui.scoreSlider.addEventListener('input', (e) => {
            this.minScoreThreshold = parseFloat(e.target.value);
            this.ui.scoreValue.textContent = this.minScoreThreshold.toFixed(2);
            this._filterAndDisplayCorrelations();
        });
        
        // Type selection
        this.ui.typeSelect.addEventListener('change', (e) => {
            const selectedOptions = Array.from(e.target.selectedOptions).map(o => o.value);
            this.selectedTypes = selectedOptions.length > 0 ? selectedOptions : ['hybrid'];
            this._filterAndDisplayCorrelations();
        });
        
        // Refresh button
        this.ui.refreshBtn.addEventListener('click', () => {
            if (this.articleId) {
                this._loadCorrelations(this.articleId);
            }
        });
        
        // Export button
        this.ui.exportBtn.addEventListener('click', () => {
            this._exportCorrelations();
        });
    }
    
    /**
     * Load initial data (articles and instruments)
     * @private
     */
    async _loadInitialData() {
        try {
            // Load articles (assuming there's an articles endpoint)
            // For now, we'll use a placeholder
            this.articles = [];
            this._populateArticleSelect();
            
            // Load instruments
            const instrumentsResponse = await this.apiClient.get('/financial/instruments');
            if (instrumentsResponse.success) {
                this.instruments = instrumentsResponse.data || [];
            }
        } catch (error) {
            console.error('CorrelationView: Failed to load initial data:', error);
            this._showError('Failed to load data. Please try again.');
        }
    }
    
    /**
     * Populate article dropdown
     * @private
     */
    _populateArticleSelect() {
        // This would be populated from the articles API
        // For now, we'll add a placeholder
        const select = this.ui.articleSelect;
        select.innerHTML = '<option value="">Select Article...</option>';
        
        // In a real implementation, this would fetch from /api/v1/articles
        // For demo purposes, we'll add some sample options
        const sampleArticles = [
            { id: 'sample-1', title: 'Tech Stocks Surge on AI Announcements' },
            { id: 'sample-2', title: 'Commodity Prices Drop Amid Economic Concerns' },
            { id: 'sample-3', title: 'Federal Reserve Signals Interest Rate Hike' }
        ];
        
        sampleArticles.forEach(article => {
            const option = document.createElement('option');
            option.value = article.id;
            option.textContent = article.title;
            select.appendChild(option);
        });
    }
    
    /**
     * Load correlations for a specific article
     * @private
     */
    async _loadCorrelations(articleId) {
        try {
            this._showLoading(true);
            
            const response = await this.apiClient.get(`/financial/correlations/article/${articleId}`);
            if (response.success) {
                this.correlations = response.data || [];
                this._filterAndDisplayCorrelations();
                this._updateSummaryStats();
                this._renderNetwork();
                this.ui.exportBtn.disabled = false;
            } else {
                this._showError('No correlations found for this article.');
                this.correlations = [];
                this._filterAndDisplayCorrelations();
            }
        } catch (error) {
            console.error('CorrelationView: Failed to load correlations:', error);
            this._showError('Failed to load correlations. Please try again.');
            this.correlations = [];
            this._filterAndDisplayCorrelations();
        } finally {
            this._showLoading(false);
        }
    }
    
    /**
     * Filter and display correlations based on current selections
     * @private
     */
    _filterAndDisplayCorrelations() {
        let filteredCorrelations = this.correlations;
        
        // Filter by minimum score
        filteredCorrelations = filteredCorrelations.filter(c => 
            c.correlation_score >= this.minScoreThreshold
        );
        
        // Filter by type
        filteredCorrelations = filteredCorrelations.filter(c => {
            const correlationType = c.type || 'hybrid';
            return this.selectedTypes.includes(correlationType) || 
                   this.selectedTypes.includes('hybrid');
        });
        
        this._displayCorrelations(filteredCorrelations);
        this.ui.correlationCount.textContent = `(${filteredCorrelations.length})`;
    }
    
    /**
     * Display correlations as cards
     * @private
     */
    _displayCorrelations(correlations) {
        this.ui.correlationCards.innerHTML = '';
        
        if (correlations.length === 0) {
            this.ui.correlationCards.innerHTML = '<p class="no-correlations">No correlations found matching your criteria.</p>';
            return;
        }
        
        correlations.forEach(correlation => {
            const card = document.createElement('div');
            card.className = 'correlation-card';
            card.dataset.correlationId = correlation.id || correlation.correlation_id;
            
            const score = correlation.correlation_score || correlation.score || 0;
            const color = this.scoreColors.getColor(score);
            const instrument = this._getInstrumentById(correlation.instrument_id);
            
            card.innerHTML = `
                <div class="correlation-card-header">
                    <div class="correlation-score-display" style="background-color: ${color}">
                        <span class="score-value">${(score * 100).toFixed(1)}%</span>
                    </div>
                    <h4>${instrument ? `${instrument.symbol} - ${instrument.name}` : 'Unknown Instrument'}</h4>
                </div>
                <div class="correlation-card-body">
                    <p><strong>Type:</strong> ${correlation.type || 'hybrid'}</p>
                    <p><strong>Article ID:</strong> ${correlation.article_id || 'N/A'}</p>
                    <p><strong>Instrument ID:</strong> ${correlation.instrument_id || 'N/A'}</p>
                    
                    <div class="correlation-components">
                        <h5>Score Breakdown:</h5>
                        <div class="component-bars">
                            ${Object.entries(this.weights).map(([type, weight]) => {
                                const componentScore = correlation[`${type}_score`] || 0;
                                const componentWeighted = componentScore * weight;
                                return `
                                    <div class="component-bar">
                                        <span class="component-label">${type}</span>
                                        <div class="component-bar-container">
                                            <div class="component-bar-fill" 
                                                 style="width: ${componentScore * 100}%; background-color: ${this._getTypeColor(type)}"></div>
                                        </div>
                                        <span class="component-value">${componentScore.toFixed(3)} × ${weight} = ${componentWeighted.toFixed(3)}</span>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                        <p class="total-score">
                            <strong>Total:</strong> ${score.toFixed(4)} 
                            (${(score * 100).toFixed(1)}%)
                        </p>
                    </div>
                    
                    ${correlation.matched_keywords && correlation.matched_keywords.length > 0 ? `
                        <div class="matched-keywords">
                            <h5>Matched Keywords:</h5>
                            <div class="keyword-tags">
                                ${correlation.matched_keywords.map(kw => 
                                    `<span class="keyword-tag">${kw}</span>`
                                ).join('')}
                            </div>
                        </div>
                    ` : ''}
                    
                    ${correlation.matched_sectors && correlation.matched_sectors.length > 0 ? `
                        <div class="matched-sectors">
                            <h5>Matched Sectors:</h5>
                            <div class="sector-tags">
                                ${correlation.matched_sectors.map(sector => 
                                    `<span class="sector-tag">${sector}</span>`
                                ).join('')}
                            </div>
                        </div>
                    ` : ''}
                </div>
            `;
            
            this.ui.correlationCards.appendChild(card);
        });
    }
    
    /**
     * Get instrument by ID
     * @private
     */
    _getInstrumentById(instrumentId) {
        return this.instruments.find(i => 
            i.id === instrumentId || i.instrument_id === instrumentId
        );
    }
    
    /**
     * Update summary statistics
     * @private
     */
    _updateSummaryStats() {
        const scores = this.correlations.map(c => c.correlation_score || c.score || 0);
        
        this.ui.totalCorrelations.textContent = this.correlations.length;
        this.ui.avgScore.textContent = scores.length > 0 
            ? (scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(3)
            : '0.00';
        this.ui.highestScore.textContent = scores.length > 0 
            ? Math.max(...scores).toFixed(3)
            : '0.00';
        this.ui.strongCorrelations.textContent = scores.filter(s => s >= 0.8).length;
    }
    
    /**
     * Render correlation network visualization
     * @private
     */
    _renderNetwork() {
        const svg = this.ui.networkSvg;
        svg.innerHTML = '';
        
        if (this.correlations.length === 0) {
            svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle">No correlations to visualize</text>';
            return;
        }
        
        // Simple network visualization
        const width = svg.clientWidth || 800;
        const height = svg.clientHeight || 400;
        const centerX = width / 2;
        const centerY = height / 2;
        const radius = Math.min(width, height) * 0.3;
        
        // Create article node at center
        const articleNode = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        articleNode.setAttribute('cx', centerX);
        articleNode.setAttribute('cy', centerY);
        articleNode.setAttribute('r', 20);
        articleNode.setAttribute('fill', '#ef4444');
        svg.appendChild(articleNode);
        
        const articleLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        articleLabel.setAttribute('x', centerX);
        articleLabel.setAttribute('y', centerY - 30);
        articleLabel.setAttribute('text-anchor', 'middle');
        articleLabel.setAttribute('fill', '#333');
        articleLabel.textContent = 'Article';
        svg.appendChild(articleLabel);
        
        // Create instrument nodes around the article
        const angleStep = (2 * Math.PI) / this.correlations.length;
        
        this.correlations.forEach((correlation, index) => {
            const angle = index * angleStep;
            const x = centerX + radius * Math.cos(angle);
            const y = centerY + radius * Math.sin(angle);
            
            const score = correlation.correlation_score || correlation.score || 0;
            const color = this.scoreColors.getColor(score);
            const size = 10 + (score * 20); // Size based on score
            
            // Create node
            const node = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            node.setAttribute('cx', x);
            node.setAttribute('cy', y);
            node.setAttribute('r', size);
            node.setAttribute('fill', color);
            node.setAttribute('stroke', '#333');
            node.setAttribute('stroke-width', '1');
            svg.appendChild(node);
            
            // Create label
            const instrument = this._getInstrumentById(correlation.instrument_id);
            const label = instrument ? instrument.symbol : '?';
            
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', x);
            text.setAttribute('y', y - size - 10);
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('fill', '#333');
            text.setAttribute('font-size', '12');
            text.textContent = label;
            svg.appendChild(text);
            
            // Create edge
            const edge = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            edge.setAttribute('x1', centerX);
            edge.setAttribute('y1', centerY);
            edge.setAttribute('x2', x);
            edge.setAttribute('y2', y);
            edge.setAttribute('stroke', color);
            edge.setAttribute('stroke-width', score * 3);
            edge.setAttribute('stroke-opacity', '0.5');
            svg.appendChild(edge);
            
            // Add score label on edge
            const scoreLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            const midX = (centerX + x) / 2;
            const midY = (centerY + y) / 2;
            scoreLabel.setAttribute('x', midX);
            scoreLabel.setAttribute('y', midY);
            scoreLabel.setAttribute('text-anchor', 'middle');
            scoreLabel.setAttribute('fill', color);
            scoreLabel.setAttribute('font-size', '10');
            scoreLabel.textContent = `${(score * 100).toFixed(0)}%`;
            svg.appendChild(scoreLabel);
        });
    }
    
    /**
     * Export correlations data
     * @private
     */
    _exportCorrelations() {
        if (this.correlations.length === 0) {
            this._showError('No correlations to export.');
            return;
        }
        
        const data = {
            article_id: this.articleId,
            correlations: this.correlations,
            summary: {
                total: this.correlations.length,
                average_score: parseFloat(this.ui.avgScore.textContent),
                highest_score: parseFloat(this.ui.highestScore.textContent),
                strong_correlations: parseInt(this.ui.strongCorrelations.textContent)
            },
            timestamp: new Date().toISOString(),
            source: 'Open-Omniscience Pillar 5'
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `correlations_article_${this.articleId || 'export'}_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
    
    /**
     * Show loading state
     * @private
     */
    _showLoading(loading) {
        const overlay = this.container.querySelector('.loading-overlay');
        if (loading && !overlay) {
            const div = document.createElement('div');
            div.className = 'loading-overlay';
            div.style.cssText = 'position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.8); display: flex; align-items: center; justify-content: center; z-index: 1000;';
            div.innerHTML = '<div style="font-size: 24px;">Loading...</div>';
            this.container.style.position = 'relative';
            this.container.appendChild(div);
        } else if (!loading && overlay) {
            overlay.remove();
        }
    }
    
    /**
     * Show error message
     * @private
     */
    _showError(message) {
        const errorElement = this.container.querySelector('.correlation-error');
        if (!errorElement) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'correlation-error';
            errorDiv.style.cssText = 'color: #ef4444; padding: 10px; background: #fef2f2; border-radius: 4px; margin: 10px 0;';
            errorDiv.textContent = message;
            this.container.prepend(errorDiv);
            
            // Remove after 5 seconds
            setTimeout(() => {
                errorDiv.remove();
            }, 5000);
        } else {
            errorElement.textContent = message;
        }
    }
    
    /**
     * Clean up the component
     */
    destroy() {
        if (this.container) {
            this.container.innerHTML = '';
        }
        this.correlations = [];
        this.articles = [];
        this.instruments = [];
    }
}

// Auto-initialize if data attributes are present
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        const containers = document.querySelectorAll('[data-correlation-view]');
        containers.forEach(container => {
            new CorrelationView({ container });
        });
    });
}
