/**
 * Financial Dashboard Component for Pillar 5 - Financial Intelligence
 * 
 * Main dashboard that integrates all Pillar 5 GUI components:
 * - Metric Explorer
 * - Correlation View
 * - Instrument Browser
 * 
 * Provides a unified interface for financial data analysis with
 * tab-based navigation and integrated workflows.
 */

class FinancialDashboard {
    /**
     * Create a new Financial Dashboard instance
     * @param {Object} options - Configuration options
     * @param {string|HTMLElement} options.container - Container element or selector
     * @param {Object} options.apiClient - API client instance
     */
    constructor(options = {}) {
        this.container = typeof options.container === 'string' 
            ? document.querySelector(options.container) 
            : options.container;
        this.apiClient = options.apiClient || new APIClient({ baseUrl: '/api/v1' });
        
        // Child components
        this.metricExplorer = null;
        this.correlationView = null;
        this.instrumentBrowser = null;
        
        // State
        this.activeTab = 'instruments';
        this.systemStats = null;
        
        // UI Elements
        this.ui = {};
        
        this._initialize();
    }
    
    /**
     * Initialize the component
     * @private
     */
    _initialize() {
        if (!this.container) {
            console.error('FinancialDashboard: Container element not found');
            return;
        }
        
        this._createUI();
        this._bindEvents();
        this._loadSystemStats();
        this._initializeComponents();
    }
    
    /**
     * Create the UI structure
     * @private
     */
    _createUI() {
        this.container.innerHTML = `
            <div class="financial-dashboard">
                <div class="dashboard-header">
                    <div class="dashboard-logo">
                        <h1>Open-Omniscience Pillar 5</h1>
                        <p>Global Financial Intelligence</p>
                    </div>
                    <div class="dashboard-nav">
                        <ul class="nav-tabs">
                            <li class="nav-tab active" data-tab="instruments">
                                <span class="tab-icon">📊</span>
                                <span class="tab-text">Instruments</span>
                            </li>
                            <li class="nav-tab" data-tab="metrics">
                                <span class="tab-icon">📈</span>
                                <span class="tab-text">Metrics</span>
                            </li>
                            <li class="nav-tab" data-tab="correlations">
                                <span class="tab-icon">🔗</span>
                                <span class="tab-text">Correlations</span>
                            </li>
                            <li class="nav-tab" data-tab="analytics">
                                <span class="tab-icon">📊</span>
                                <span class="tab-text">Analytics</span>
                            </li>
                        </ul>
                    </div>
                    <div class="dashboard-actions">
                        <button class="btn-refresh-all">Refresh All</button>
                        <button class="btn-dashboard-settings">⚙️ Settings</button>
                    </div>
                </div>
                
                <div class="dashboard-system-stats">
                    <div class="stats-grid">
                        <div class="stat-card">
                            <h4>Total Instruments</h4>
                            <p class="stat-value" id="total-instruments">0</p>
                            <p class="stat-label">Across all asset classes</p>
                        </div>
                        <div class="stat-card">
                            <h4>Total Exchanges</h4>
                            <p class="stat-value" id="total-exchanges">0</p>
                            <p class="stat-label">Global coverage</p>
                        </div>
                        <div class="stat-card">
                            <h4>Pre-computed Metrics</h4>
                            <p class="stat-value" id="total-metrics">0</p>
                            <p class="stat-label">80+ metric types</p>
                        </div>
                        <div class="stat-card">
                            <h4>Correlations Calculated</h4>
                            <p class="stat-value" id="total-correlations">0</p>
                            <p class="stat-label">Hybrid scoring engine</p>
                        </div>
                        <div class="stat-card">
                            <h4>Last Updated</h4>
                            <p class="stat-value" id="last-updated">Never</p>
                            <p class="stat-label">Data freshness</p>
                        </div>
                    </div>
                </div>
                
                <div class="dashboard-main-content">
                    <div class="tab-content active" id="tab-instruments">
                        <div data-instrument-browser class="tab-pane"></div>
                    </div>
                    <div class="tab-content" id="tab-metrics">
                        <div data-metric-explorer class="tab-pane"></div>
                    </div>
                    <div class="tab-content" id="tab-correlations">
                        <div data-correlation-view class="tab-pane"></div>
                    </div>
                    <div class="tab-content" id="tab-analytics">
                        <div class="analytics-pane">
                            <h2>Advanced Analytics</h2>
                            <p>Comprehensive financial analysis tools coming soon...</p>
                            <div class="analytics-features">
                                <div class="feature-card">
                                    <h3>Portfolio Analysis</h3>
                                    <p>Analyze portfolio performance and risk metrics</p>
                                </div>
                                <div class="feature-card">
                                    <h3>Sector Comparison</h3>
                                    <p>Compare performance across different sectors</p>
                                </div>
                                <div class="feature-card">
                                    <h3>Trend Analysis</h3>
                                    <p>Identify trends and patterns in financial data</p>
                                </div>
                                <div class="feature-card">
                                    <h3>Custom Reports</h3>
                                    <p>Generate custom reports with selected metrics</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="dashboard-footer">
                    <p>Open-Omniscience Pillar 5 - Global Financial Intelligence System</p>
                    <p>Data provided by open web sources | Respecting robots.txt and rate limits</p>
                </div>
            </div>
        `;
        
        // Cache UI elements
        this.ui.navTabs = this.container.querySelectorAll('.nav-tab');
        this.ui.tabContents = this.container.querySelectorAll('.tab-content');
        this.ui.totalInstruments = this.container.querySelector('#total-instruments');
        this.ui.totalExchanges = this.container.querySelector('#total-exchanges');
        this.ui.totalMetrics = this.container.querySelector('#total-metrics');
        this.ui.totalCorrelations = this.container.querySelector('#total-correlations');
        this.ui.lastUpdated = this.container.querySelector('#last-updated');
        this.ui.refreshAllBtn = this.container.querySelector('.btn-refresh-all');
    }
    
    /**
     * Bind event listeners
     * @private
     */
    _bindEvents() {
        // Tab navigation
        this.ui.navTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const tabId = tab.dataset.tab;
                this._switchTab(tabId);
            });
        });
        
        // Refresh all button
        this.ui.refreshAllBtn.addEventListener('click', () => {
            this._refreshAll();
        });
    }
    
    /**
     * Initialize child components
     * @private
     */
    _initializeComponents() {
        // Initialize Instrument Browser
        const instrumentContainer = this.container.querySelector('[data-instrument-browser]');
        if (instrumentContainer) {
            this.instrumentBrowser = new InstrumentBrowser({
                container: instrumentContainer,
                apiClient: this.apiClient
            });
        }
        
        // Initialize Metric Explorer
        const metricContainer = this.container.querySelector('[data-metric-explorer]');
        if (metricContainer) {
            this.metricExplorer = new MetricExplorer({
                container: metricContainer,
                apiClient: this.apiClient
            });
        }
        
        // Initialize Correlation View
        const correlationContainer = this.container.querySelector('[data-correlation-view]');
        if (correlationContainer) {
            this.correlationView = new CorrelationView({
                container: correlationContainer,
                apiClient: this.apiClient
            });
        }
    }
    
    /**
     * Switch to a different tab
     * @private
     */
    _switchTab(tabId) {
        this.activeTab = tabId;
        
        // Update tab buttons
        this.ui.navTabs.forEach(tab => {
            tab.classList.toggle('active', tab.dataset.tab === tabId);
        });
        
        // Update tab content
        this.ui.tabContents.forEach(content => {
            content.classList.toggle('active', content.id === `tab-${tabId}`);
        });
    }
    
    /**
     * Load system statistics
     * @private
     */
    async _loadSystemStats() {
        try {
            // Load stats from API
            const statsResponse = await this.apiClient.get('/financial/stats');
            if (statsResponse.success) {
                this.systemStats = statsResponse.data;
                this._updateStatsDisplay();
            } else {
                // Fallback to individual API calls
                this._loadStatsIndividually();
            }
        } catch (error) {
            console.error('FinancialDashboard: Failed to load system stats:', error);
            this._loadStatsIndividually();
        }
    }
    
    /**
     * Load stats individually from different endpoints
     * @private
     */
    async _loadStatsIndividually() {
        try {
            // Load instruments count
            const instrumentsResponse = await this.apiClient.get('/financial/instruments');
            if (instrumentsResponse.success) {
                this.ui.totalInstruments.textContent = instrumentsResponse.data.length;
            }
            
            // Load exchanges count
            const exchangesResponse = await this.apiClient.get('/financial/exchanges');
            if (exchangesResponse.success) {
                this.ui.totalExchanges.textContent = exchangesResponse.data.length;
            }
            
            // Load metrics count
            const metricsResponse = await this.apiClient.get('/financial/metrics');
            if (metricsResponse.success) {
                this.ui.totalMetrics.textContent = metricsResponse.data.length;
            }
            
            // Correlations count would come from a separate endpoint
            // For now, we'll use a placeholder
            this.ui.totalCorrelations.textContent = '0';
            
            // Update last updated timestamp
            this.ui.lastUpdated.textContent = new Date().toLocaleString();
            
        } catch (error) {
            console.error('FinancialDashboard: Failed to load individual stats:', error);
        }
    }
    
    /**
     * Update stats display
     * @private
     */
    _updateStatsDisplay() {
        if (!this.systemStats) return;
        
        this.ui.totalInstruments.textContent = this.systemStats.total_instruments || 0;
        this.ui.totalExchanges.textContent = this.systemStats.total_exchanges || 0;
        this.ui.totalMetrics.textContent = this.systemStats.total_metrics || 0;
        this.ui.totalCorrelations.textContent = this.systemStats.total_correlations || 0;
        this.ui.lastUpdated.textContent = this.systemStats.last_updated 
            ? new Date(this.systemStats.last_updated).toLocaleString()
            : 'Never';
    }
    
    /**
     * Refresh all data
     * @private
     */
    async _refreshAll() {
        try {
            // Show loading state
            this._showLoading(true);
            
            // Refresh system stats
            await this._loadSystemStats();
            
            // Refresh child components
            if (this.instrumentBrowser) {
                this.instrumentBrowser._loadInitialData();
            }
            if (this.metricExplorer) {
                this.metricExplorer._loadInitialData();
            }
            if (this.correlationView) {
                this.correlationView._loadInitialData();
            }
            
            // Update last updated timestamp
            this.ui.lastUpdated.textContent = new Date().toLocaleString();
            
        } catch (error) {
            console.error('FinancialDashboard: Failed to refresh all:', error);
            this._showError('Failed to refresh all data. Please try again.');
        } finally {
            this._showLoading(false);
        }
    }
    
    /**
     * Show loading state
     * @private
     */
    _showLoading(loading) {
        const overlay = this.container.querySelector('.dashboard-loading-overlay');
        if (loading && !overlay) {
            const div = document.createElement('div');
            div.className = 'dashboard-loading-overlay';
            div.style.cssText = 'position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(255,255,255,0.8); display: flex; align-items: center; justify-content: center; z-index: 9999;';
            div.innerHTML = '<div style="font-size: 24px; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.2);">Refreshing Data...</div>';
            document.body.appendChild(div);
        } else if (!loading && overlay) {
            overlay.remove();
        }
    }
    
    /**
     * Show error message
     * @private
     */
    _showError(message) {
        const errorElement = this.container.querySelector('.dashboard-error');
        if (!errorElement) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'dashboard-error';
            errorDiv.style.cssText = 'color: #ef4444; padding: 15px; background: #fef2f2; border-radius: 8px; margin: 15px 0; font-size: 16px;';
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
        
        // Clean up child components
        if (this.metricExplorer) {
            this.metricExplorer.destroy();
            this.metricExplorer = null;
        }
        if (this.correlationView) {
            this.correlationView.destroy();
            this.correlationView = null;
        }
        if (this.instrumentBrowser) {
            this.instrumentBrowser.destroy();
            this.instrumentBrowser = null;
        }
    }
}

// Auto-initialize if data attributes are present
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        const containers = document.querySelectorAll('[data-financial-dashboard]');
        containers.forEach(container => {
            new FinancialDashboard({ container });
        });
    });
}
