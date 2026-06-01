/**
 * Metric Explorer Component for Pillar 5 - Financial Intelligence
 * 
 * Provides interactive browsing and visualization of pre-computed financial metrics
 * grouped by theme (Trend, Momentum, Volatility, Volume, Fundamental, Statistical, Pattern, Custom)
 * 
 * Features:
 * - Fetch metrics from /api/v1/financial/metrics endpoints
 * - Group metrics by theme for intuitive exploration
 * - Filter by instrument, timeframe, metric group
 * - Visualization-ready data for charting libraries
 * - Responsive design with sorting, pagination, and search
 */

class MetricExplorer {
    /**
     * Create a new Metric Explorer instance
     * @param {Object} options - Configuration options
     * @param {string|HTMLElement} options.container - Container element or selector
     * @param {Object} options.apiClient - API client instance
     * @param {Object} options.chartLibrary - Optional charting library (Chart.js, D3, etc.)
     */
    constructor(options = {}) {
        this.container = typeof options.container === 'string' 
            ? document.querySelector(options.container) 
            : options.container;
        this.apiClient = options.apiClient || new APIClient({ baseUrl: '/api/v1' });
        this.chartLibrary = options.chartLibrary || null;
        
        // State
        this.metrics = [];
        this.metricGroups = {
            'Trend': [],
            'Momentum': [],
            'Volatility': [],
            'Volume': [],
            'Fundamental': [],
            'Statistical': [],
            'Pattern': [],
            'Custom': []
        };
        this.instruments = [];
        this.selectedInstrument = null;
        this.selectedGroup = 'Trend';
        this.selectedMetric = null;
        this.timeframe = '1d';
        this.searchQuery = '';
        
        // UI Elements
        this.ui = {};
        
        // Visualization settings
        this.visualizationConfig = {
            chartType: 'line',
            colors: {
                Trend: '#3b82f6',
                Momentum: '#10b981',
                Volatility: '#f59e0b',
                Volume: '#8b5cf6',
                Fundamental: '#06b6d4',
                Statistical: '#eab308',
                Pattern: '#ec4899',
                Custom: '#6366f1'
            },
            defaultRange: 30 // days
        };
        
        this._initialize();
    }
    
    /**
     * Initialize the component
     * @private
     */
    _initialize() {
        if (!this.container) {
            console.error('MetricExplorer: Container element not found');
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
            <div class="metric-explorer">
                <div class="metric-explorer-header">
                    <h2>Financial Metrics Explorer</h2>
                    <div class="metric-explorer-controls">
                        <div class="search-box">
                            <input type="text" placeholder="Search metrics..." class="metric-search">
                            <button class="btn-search">🔍</button>
                        </div>
                        <select class="instrument-select">
                            <option value="">All Instruments</option>
                        </select>
                        <select class="timeframe-select">
                            <option value="1d">1 Day</option>
                            <option value="1w">1 Week</option>
                            <option value="1m" selected>1 Month</option>
                            <option value="3m">3 Months</option>
                            <option value="1y">1 Year</option>
                        </select>
                    </div>
                </div>
                
                <div class="metric-explorer-layout">
                    <div class="metric-groups-sidebar">
                        <h3>Metric Groups</h3>
                        <ul class="metric-groups-list">
                            ${Object.keys(this.metricGroups).map(group => 
                                `<li class="metric-group-item" data-group="${group}">
                                    <span class="group-color" style="background-color: ${this.visualizationConfig.colors[group]}"></span>
                                    ${group} (0)
                                </li>`
                            ).join('')}
                        </ul>
                    </div>
                    
                    <div class="metric-main-content">
                        <div class="metric-list-container">
                            <h3>Metrics <span class="metric-count">(0)</span></h3>
                            <div class="metric-list">
                                <div class="metric-cards"></div>
                            </div>
                        </div>
                        
                        <div class="metric-visualization">
                            <h3>Visualization</h3>
                            <div class="chart-container">
                                <canvas class="metric-chart"></canvas>
                            </div>
                            <div class="metric-details">
                                <h4>Selected Metric: <span class="selected-metric-name">None</span></h4>
                                <div class="metric-info">
                                    <p><strong>Group:</strong> <span class="metric-group-badge"></span></p>
                                    <p><strong>Description:</strong> <span class="metric-description"></span></p>
                                    <p><strong>Formula:</strong> <span class="metric-formula"></span></p>
                                    <p><strong>Use Case:</strong> <span class="metric-use-case"></span></p>
                                    <p><strong>Current Value:</strong> <span class="metric-current-value">-</span></p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="metric-explorer-footer">
                    <button class="btn-export" disabled>Export Data</button>
                    <button class="btn-refresh">Refresh Metrics</button>
                </div>
            </div>
        `;
        
        // Cache UI elements
        this.ui.searchInput = this.container.querySelector('.metric-search');
        this.ui.instrumentSelect = this.container.querySelector('.instrument-select');
        this.ui.timeframeSelect = this.container.querySelector('.timeframe-select');
        this.ui.groupItems = this.container.querySelectorAll('.metric-group-item');
        this.ui.metricCards = this.container.querySelector('.metric-cards');
        this.ui.metricCount = this.container.querySelector('.metric-count');
        this.ui.selectedMetricName = this.container.querySelector('.selected-metric-name');
        this.ui.metricGroupBadge = this.container.querySelector('.metric-group-badge');
        this.ui.metricDescription = this.container.querySelector('.metric-description');
        this.ui.metricFormula = this.container.querySelector('.metric-formula');
        this.ui.metricUseCase = this.container.querySelector('.metric-use-case');
        this.ui.metricCurrentValue = this.container.querySelector('.metric-current-value');
        this.ui.exportBtn = this.container.querySelector('.btn-export');
        this.ui.refreshBtn = this.container.querySelector('.btn-refresh');
        this.ui.chartContainer = this.container.querySelector('.chart-container');
    }
    
    /**
     * Bind event listeners
     * @private
     */
    _bindEvents() {
        // Search
        this.ui.searchInput.addEventListener('input', (e) => {
            this.searchQuery = e.target.value.toLowerCase();
            this._filterAndDisplayMetrics();
        });
        
        // Instrument selection
        this.ui.instrumentSelect.addEventListener('change', (e) => {
            this.selectedInstrument = e.target.value || null;
            this._filterAndDisplayMetrics();
        });
        
        // Timeframe selection
        this.ui.timeframeSelect.addEventListener('change', (e) => {
            this.timeframe = e.target.value;
            if (this.selectedMetric) {
                this._loadMetricData(this.selectedMetric);
            }
        });
        
        // Group selection
        this.ui.groupItems.forEach(item => {
            item.addEventListener('click', () => {
                this.ui.groupItems.forEach(i => i.classList.remove('active'));
                item.classList.add('active');
                this.selectedGroup = item.dataset.group;
                this._filterAndDisplayMetrics();
            });
        });
        
        // Refresh button
        this.ui.refreshBtn.addEventListener('click', () => {
            this._loadInitialData();
        });
        
        // Export button
        this.ui.exportBtn.addEventListener('click', () => {
            this._exportData();
        });
    }
    
    /**
     * Load initial data (instruments and metrics)
     * @private
     */
    async _loadInitialData() {
        try {
            // Load instruments
            const instrumentsResponse = await this.apiClient.get('/financial/instruments');
            if (instrumentsResponse.success) {
                this.instruments = instrumentsResponse.data || [];
                this._populateInstrumentSelect();
            }
            
            // Load all metrics
            const metricsResponse = await this.apiClient.get('/financial/metrics');
            if (metricsResponse.success) {
                this.metrics = metricsResponse.data || [];
                this._groupMetrics();
                this._updateGroupCounts();
                this._filterAndDisplayMetrics();
            }
        } catch (error) {
            console.error('MetricExplorer: Failed to load initial data:', error);
            this._showError('Failed to load metrics data. Please try again.');
        }
    }
    
    /**
     * Populate instrument dropdown
     * @private
     */
    _populateInstrumentSelect() {
        const select = this.ui.instrumentSelect;
        select.innerHTML = '<option value="">All Instruments</option>';
        
        this.instruments.forEach(instrument => {
            const option = document.createElement('option');
            option.value = instrument.id || instrument.instrument_id;
            option.textContent = `${instrument.symbol} - ${instrument.name} (${instrument.type})`;
            select.appendChild(option);
        });
    }
    
    /**
     * Group metrics by their theme
     * @private
     */
    _groupMetrics() {
        Object.keys(this.metricGroups).forEach(group => {
            this.metricGroups[group] = [];
        });
        
        this.metrics.forEach(metric => {
            const group = metric.group || metric.metric_group || 'Custom';
            if (this.metricGroups[group]) {
                this.metricGroups[group].push(metric);
            } else {
                this.metricGroups['Custom'].push(metric);
            }
        });
    }
    
    /**
     * Update group counts in sidebar
     * @private
     */
    _updateGroupCounts() {
        Object.keys(this.metricGroups).forEach(group => {
            const count = this.metricGroups[group].length;
            const item = this.container.querySelector(`.metric-group-item[data-group="${group}"]`);
            if (item) {
                const text = item.textContent;
                item.textContent = text.replace(/\s*\(\d+\)$/, '') + ` (${count})`;
            }
        });
    }
    
    /**
     * Filter and display metrics based on current selections
     * @private
     */
    _filterAndDisplayMetrics() {
        let filteredMetrics = this.metrics;
        
        // Filter by group
        if (this.selectedGroup) {
            filteredMetrics = filteredMetrics.filter(m => 
                (m.group || m.metric_group || 'Custom') === this.selectedGroup
            );
        }
        
        // Filter by instrument
        if (this.selectedInstrument) {
            filteredMetrics = filteredMetrics.filter(m => 
                m.instrument_id === this.selectedInstrument
            );
        }
        
        // Filter by search query
        if (this.searchQuery) {
            filteredMetrics = filteredMetrics.filter(m => 
                (m.name && m.name.toLowerCase().includes(this.searchQuery)) ||
                (m.description && m.description.toLowerCase().includes(this.searchQuery)) ||
                (m.formula && m.formula.toLowerCase().includes(this.searchQuery))
            );
        }
        
        this._displayMetrics(filteredMetrics);
        this.ui.metricCount.textContent = `(${filteredMetrics.length})`;
    }
    
    /**
     * Display metrics as cards
     * @private
     */
    _displayMetrics(metrics) {
        this.ui.metricCards.innerHTML = '';
        
        if (metrics.length === 0) {
            this.ui.metricCards.innerHTML = '<p class="no-metrics">No metrics found matching your criteria.</p>';
            return;
        }
        
        metrics.forEach(metric => {
            const card = document.createElement('div');
            card.className = 'metric-card';
            card.dataset.metricId = metric.id || metric.metric_id;
            
            const group = metric.group || metric.metric_group || 'Custom';
            const color = this.visualizationConfig.colors[group] || '#666';
            
            card.innerHTML = `
                <div class="metric-card-header">
                    <span class="metric-group-indicator" style="background-color: ${color}"></span>
                    <h4>${metric.name || 'Unnamed Metric'}</h4>
                </div>
                <div class="metric-card-body">
                    <p class="metric-description">${metric.description || 'No description'}</p>
                    <p class="metric-formula">Formula: ${metric.formula || 'N/A'}</p>
                    <p class="metric-value">Value: ${metric.value !== undefined ? metric.value.toFixed(4) : 'N/A'}</p>
                </div>
                <div class="metric-card-footer">
                    <span class="metric-use-case">${metric.use_case || 'General'}</span>
                    <button class="btn-view-details" data-metric-id="${metric.id || metric.metric_id}">View Details</button>
                </div>
            `;
            
            this.ui.metricCards.appendChild(card);
        });
        
        // Add event listeners to view details buttons
        this.ui.metricCards.querySelectorAll('.btn-view-details').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const metricId = e.target.dataset.metricId;
                this._loadMetricDetails(metricId);
            });
        });
    }
    
    /**
     * Load detailed data for a specific metric
     * @private
     */
    async _loadMetricDetails(metricId) {
        try {
            const response = await this.apiClient.get(`/financial/metrics/${metricId}`);
            if (response.success) {
                const metric = response.data;
                this.selectedMetric = metric;
                this._displayMetricDetails(metric);
                this._loadMetricData(metric);
            }
        } catch (error) {
            console.error('MetricExplorer: Failed to load metric details:', error);
            this._showError('Failed to load metric details.');
        }
    }
    
    /**
     * Display metric details
     * @private
     */
    _displayMetricDetails(metric) {
        this.ui.selectedMetricName.textContent = metric.name || 'Unknown';
        
        const group = metric.group || metric.metric_group || 'Custom';
        this.ui.metricGroupBadge.innerHTML = `
            <span style="background-color: ${this.visualizationConfig.colors[group]}; 
                         color: white; padding: 2px 8px; border-radius: 4px;">
                ${group}
            </span>
        `;
        
        this.ui.metricDescription.textContent = metric.description || 'No description available';
        this.ui.metricFormula.textContent = metric.formula || 'N/A';
        this.ui.metricUseCase.textContent = metric.use_case || 'General analysis';
        this.ui.metricCurrentValue.textContent = metric.value !== undefined ? metric.value.toFixed(4) : 'N/A';
        
        // Enable export button
        this.ui.exportBtn.disabled = false;
    }
    
    /**
     * Load historical data for visualization
     * @private
     */
    async _loadMetricData(metric) {
        try {
            // For now, we'll use the metric's value directly
            // In a full implementation, we'd fetch historical data
            if (this.chartLibrary && this.chartLibrary.Chart) {
                this._renderChart(metric);
            } else {
                this._renderSimpleChart(metric);
            }
        } catch (error) {
            console.error('MetricExplorer: Failed to load metric data:', error);
        }
    }
    
    /**
     * Render chart using Chart.js (if available)
     * @private
     */
    _renderChart(metric) {
        // Simple implementation - would be enhanced with actual historical data
        const ctx = this.ui.chartContainer.querySelector('canvas');
        
        if (window.Chart) {
            // Destroy existing chart if it exists
            if (ctx.chart) {
                ctx.chart.destroy();
            }
            
            // Sample data for demonstration
            const labels = Array.from({length: 30}, (_, i) => `Day ${i + 1}`);
            const data = Array.from({length: 30}, (_, i) => 
                (metric.value || 50) + Math.sin(i / 3) * 10 + Math.random() * 5
            );
            
            const group = metric.group || metric.metric_group || 'Custom';
            const color = this.visualizationConfig.colors[group];
            
            ctx.chart = new Chart(ctx, {
                type: this.visualizationConfig.chartType,
                data: {
                    labels: labels,
                    datasets: [{
                        label: metric.name,
                        data: data,
                        borderColor: color,
                        backgroundColor: color + '33',
                        tension: 0.1,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    return `${metric.name}: ${context.parsed.y.toFixed(4)}`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: false
                        }
                    }
                }
            });
        } else {
            this._renderSimpleChart(metric);
        }
    }
    
    /**
     * Render simple SVG chart as fallback
     * @private
     */
    _renderSimpleChart(metric) {
        const container = this.ui.chartContainer;
        container.innerHTML = `
            <div class="simple-chart">
                <h4>Chart Visualization</h4>
                <p>Install Chart.js for interactive charts.</p>
                <p><strong>Current Value:</strong> ${metric.value !== undefined ? metric.value.toFixed(4) : 'N/A'}</p>
            </div>
        `;
    }
    
    /**
     * Export current metric data
     * @private
     */
    _exportData() {
        if (!this.selectedMetric) {
            this._showError('No metric selected to export.');
            return;
        }
        
        const data = {
            metric: this.selectedMetric,
            timestamp: new Date().toISOString(),
            source: 'Open-Omniscience Pillar 5'
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `metric_${this.selectedMetric.name || 'export'}_${new Date().toISOString().split('T')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
    
    /**
     * Show error message
     * @private
     */
    _showError(message) {
        const errorElement = this.container.querySelector('.metric-error');
        if (!errorElement) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'metric-error';
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
        this.metrics = [];
        this.instruments = [];
    }
}

// Auto-initialize if data attributes are present
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        const containers = document.querySelectorAll('[data-metric-explorer]');
        containers.forEach(container => {
            new MetricExplorer({ container });
        });
    });
}
