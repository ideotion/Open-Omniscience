/**
 * Dashboard Page Logic for Open-Omniscience
 * Handles dashboard-specific functionality including search, charts, and data management
 */

class Dashboard {
    /**
     * Create a new dashboard instance
     * @param {Object} options - Configuration options
     */
    constructor(options = {}) {
        this.options = {
            apiClient: null,
            tableSelector: '#results-table',
            searchFormSelector: '#search-form',
            chartsContainerSelector: '#charts-container',
            statsContainerSelector: '#stats-container',
            savedSearchesSelector: '#saved-searches',
            searchHistorySelector: '#search-history',
            autoLoad: true,
            debounceSearch: 500,
            ...options
        };

        this.apiClient = this.options.apiClient || getAPIClient();
        this.tableManager = null;
        this.searchTimeout = null;
        this.currentSearch = {};
        this.savedSearches = [];
        this.searchHistory = [];
        this.statistics = {};
        this.charts = {};

        this._initialize();
    }

    /**
     * Initialize the dashboard
     * @private
     */
    _initialize() {
        this._setupElements();
        this._setupEventListeners();
        this._setupTable();
        this._setupCharts();

        if (this.options.autoLoad) {
            this.loadInitialData();
        }
    }

    /**
     * Setup DOM elements
     * @private
     */
    _setupElements() {
        this.tableEl = document.querySelector(this.options.tableSelector);
        this.searchFormEl = document.querySelector(this.options.searchFormSelector);
        this.chartsContainerEl = document.querySelector(this.options.chartsContainerSelector);
        this.statsContainerEl = document.querySelector(this.options.statsContainerSelector);
        this.savedSearchesEl = document.querySelector(this.options.savedSearchesSelector);
        this.searchHistoryEl = document.querySelector(this.options.searchHistorySelector);

        // Initialize loading indicators
        this.loadingIndicator = DOMUtils.createElement('div', {
            className: 'loading-overlay d-none',
            innerHTML: `
                <div class="d-flex align-items-center justify-content-center h-100">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            `
        });

        // Add loading indicator to main content
        const mainContent = document.querySelector('.main-content') || document.body;
        mainContent.appendChild(this.loadingIndicator);
    }

    /**
     * Setup event listeners
     * @private
     */
    _setupEventListeners() {
        // Search form submission
        if (this.searchFormEl) {
            this.searchFormEl.addEventListener('submit', (e) => {
                e.preventDefault();
                this._handleSearch();
            });

            // Debounced search on input change
            const searchInputs = this.searchFormEl.querySelectorAll('input, select');
            searchInputs.forEach(input => {
                input.addEventListener('input', (e) => {
                    this._debouncedSearch();
                });
            });
        }

        // Saved search actions
        if (this.savedSearchesEl) {
            this.savedSearchesEl.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]');
                if (!action) return;

                const searchId = action.dataset.searchId;
                const search = this.savedSearches.find(s => s.id === searchId);

                switch (action.dataset.action) {
                    case 'load-saved-search':
                        this._loadSavedSearch(search);
                        break;
                    case 'delete-saved-search':
                        this._deleteSavedSearch(searchId);
                        break;
                }
            });
        }

        // Search history actions
        if (this.searchHistoryEl) {
            this.searchHistoryEl.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]');
                if (!action) return;

                const historyId = action.dataset.historyId;
                const historyItem = this.searchHistory.find(h => h.id === historyId);

                switch (action.dataset.action) {
                    case 'load-history-item':
                        this._loadHistoryItem(historyItem);
                        break;
                    case 'delete-history-item':
                        this._deleteHistoryItem(historyId);
                        break;
                    case 'clear-history':
                        this._clearSearchHistory();
                        break;
                }
            });
        }

        // Export actions
        document.addEventListener('click', (e) => {
            const exportBtn = e.target.closest('[data-export]');
            if (!exportBtn) return;

            const format = exportBtn.dataset.export;
            this._exportResults(format);
        });

        // Settings actions
        document.addEventListener('click', (e) => {
            const settingsBtn = e.target.closest('[data-action="open-settings"]');
            if (settingsBtn) {
                this._openSettingsModal();
            }
        });

        // Theme toggle
        document.addEventListener('click', (e) => {
            const themeToggle = e.target.closest('[data-action="toggle-theme"]');
            if (themeToggle) {
                this._toggleTheme();
            }
        });

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + F to focus search
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
                e.preventDefault();
                const searchInput = this.searchFormEl?.querySelector('[name="q"]');
                if (searchInput) {
                    searchInput.focus();
                }
            }

            // Escape to clear search
            if (e.key === 'Escape') {
                const searchInput = this.searchFormEl?.querySelector('[name="q"]');
                if (searchInput && searchInput.value) {
                    searchInput.value = '';
                    this._handleSearch();
                }
            }
        });
    }

    /**
     * Setup table manager
     * @private
     */
    _setupTable() {
        if (!this.tableEl) return;

        this.tableManager = new TableManager(this.tableEl, {
            sortable: true,
            paginate: true,
            filterable: true,
            pageSize: 20,
            pageSizeOptions: [10, 20, 50, 100],
            expandableRows: true,
            multiSelect: true,
            rowSelection: true,
            emptyMessage: 'No articles found matching your criteria',
            renderRow: (item, index) => {
                const cells = [];

                // Title cell
                const titleCell = DOMUtils.createElement('td', {
                    className: 'article-title',
                    innerHTML: `
                        <a href="#" data-action="preview-article" data-article-id="${item.id}">
                            ${FormatUtils.truncate(item.title || 'Untitled', 80)}
                        </a>
                    `
                });
                cells.push(titleCell);

                // Source cell
                const sourceCell = DOMUtils.createElement('td', {
                    className: 'article-source',
                    innerHTML: `
                        <span class="badge bg-secondary">${FormatUtils.truncate(item.source_name || 'Unknown', 20)}</span>
                    `
                });
                cells.push(sourceCell);

                // Date cell
                const dateCell = DOMUtils.createElement('td', {
                    className: 'article-date',
                    textContent: FormatUtils.formatDateForTable(item.published_at)
                });
                cells.push(dateCell);

                // Tags cell
                const tagsCell = DOMUtils.createElement('td', {
                    className: 'article-tags',
                    innerHTML: (item.tags || []).map(tag => 
                        `<span class="badge bg-light text-dark me-1">${FormatUtils.truncate(tag, 15)}</span>`
                    ).join('')
                });
                cells.push(tagsCell);

                // Actions cell
                const actionsCell = DOMUtils.createElement('td', {
                    className: 'article-actions text-end',
                    innerHTML: `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" 
                                    data-action="preview-article" 
                                    data-article-id="${item.id}" 
                                    title="Preview">
                                <i class="fas fa-eye"></i>
                            </button>
                            <button class="btn btn-outline-secondary" 
                                    data-action="open-article" 
                                    data-article-id="${item.id}" 
                                    title="Open">
                                <i class="fas fa-external-link-alt"></i>
                            </button>
                        </div>
                    `
                });
                cells.push(actionsCell);

                return cells;
            },
            renderExpandContent: (item) => {
                const container = DOMUtils.createElement('div', {
                    className: 'article-expand-content p-3 bg-light rounded'
                });

                const content = `
                    <div class="row">
                        <div class="col-md-8">
                            <h5>${item.title || 'Untitled'}</h5>
                            <div class="text-muted mb-2">
                                <small>
                                    <i class="fas fa-newspaper me-1"></i> ${item.source_name || 'Unknown'} |
                                    <i class="fas fa-calendar me-1 ms-2"></i> ${FormatUtils.formatDate(item.published_at)} |
                                    <i class="fas fa-user me-1 ms-2"></i> ${item.author || 'Unknown'}
                                </small>
                            </div>
                            <div class="article-summary mb-3">
                                ${item.summary || FormatUtils.truncate(item.content || '', 500)}
                            </div>
                            ${item.tags && item.tags.length > 0 ? `
                                <div class="article-tags mb-3">
                                    <strong>Tags:</strong>
                                    ${item.tags.map(tag => `<span class="badge bg-primary me-1">${tag}</span>`).join('')}
                                </div>
                            ` : ''}
                            <div class="d-flex gap-2">
                                <button class="btn btn-sm btn-primary" data-action="preview-article" data-article-id="${item.id}">
                                    <i class="fas fa-eye me-1"></i> Preview
                                </button>
                                <button class="btn btn-sm btn-outline-secondary" data-action="open-article" data-article-id="${item.id}">
                                    <i class="fas fa-external-link-alt me-1"></i> Open
                                </button>
                                ${item.url ? `
                                    <a href="${item.url}" target="_blank" class="btn btn-sm btn-outline-info">
                                        <i class="fas fa-link me-1"></i> Source
                                    </a>
                                ` : ''}
                            </div>
                        </div>
                        <div class="col-md-4">
                            <div class="card">
                                <div class="card-header">
                                    <strong>Article Info</strong>
                                </div>
                                <div class="card-body">
                                    <div class="d-flex justify-content-between mb-2">
                                        <span class="text-muted">ID:</span>
                                        <span>${item.id}</span>
                                    </div>
                                    <div class="d-flex justify-content-between mb-2">
                                        <span class="text-muted">Published:</span>
                                        <span>${FormatUtils.formatDate(item.published_at)}</span>
                                    </div>
                                    <div class="d-flex justify-content-between mb-2">
                                        <span class="text-muted">Retrieved:</span>
                                        <span>${FormatUtils.formatDate(item.retrieved_at)}</span>
                                    </div>
                                    <div class="d-flex justify-content-between mb-2">
                                        <span class="text-muted">Language:</span>
                                        <span>${item.language || 'Unknown'}</span>
                                    </div>
                                    <div class="d-flex justify-content-between">
                                        <span class="text-muted">Word Count:</span>
                                        <span>${item.word_count || 'N/A'}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;

                container.innerHTML = content;
                return container;
            }
        });

        // Add event listeners for table actions
        this.tableEl.addEventListener('click', (e) => {
            const previewBtn = e.target.closest('[data-action="preview-article"]');
            if (previewBtn) {
                const articleId = previewBtn.dataset.articleId;
                this._previewArticle(articleId);
            }

            const openBtn = e.target.closest('[data-action="open-article"]');
            if (openBtn) {
                const articleId = openBtn.dataset.articleId;
                this._openArticle(articleId);
            }
        });
    }

    /**
     * Setup charts
     * @private
     */
    _setupCharts() {
        if (!this.chartsContainerEl) return;

        // Initialize chart containers
        this.charts.articlesByDate = this._createArticlesByDateChart();
        this.charts.articlesBySource = this._createArticlesBySourceChart();
        this.charts.articlesByTag = this._createArticlesByTagChart();
    }

    /**
     * Create articles by date chart
     * @private
     * @returns {Object} Chart configuration
     */
    _createArticlesByDateChart() {
        const container = DOMUtils.createElement('div', {
            className: 'chart-container mb-4',
            innerHTML: `
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Articles by Date</h5>
                        <div class="chart-controls">
                            <button class="btn btn-sm btn-outline-secondary" data-action="chart-refresh">
                                <i class="fas fa-sync"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body">
                        <div id="articles-by-date-chart" style="height: 300px;"></div>
                    </div>
                </div>
            `
        });

        this.chartsContainerEl.appendChild(container);

        return {
            container,
            chart: null,
            data: [],
            render: (data) => this._renderArticlesByDateChart(data)
        };
    }

    /**
     * Create articles by source chart
     * @private
     * @returns {Object} Chart configuration
     */
    _createArticlesBySourceChart() {
        const container = DOMUtils.createElement('div', {
            className: 'chart-container mb-4',
            innerHTML: `
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Articles by Source</h5>
                        <div class="chart-controls">
                            <button class="btn btn-sm btn-outline-secondary" data-action="chart-refresh">
                                <i class="fas fa-sync"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body">
                        <div id="articles-by-source-chart" style="height: 300px;"></div>
                    </div>
                </div>
            `
        });

        this.chartsContainerEl.appendChild(container);

        return {
            container,
            chart: null,
            data: [],
            render: (data) => this._renderArticlesBySourceChart(data)
        };
    }

    /**
     * Create articles by tag chart
     * @private
     * @returns {Object} Chart configuration
     */
    _createArticlesByTagChart() {
        const container = DOMUtils.createElement('div', {
            className: 'chart-container mb-4',
            innerHTML: `
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Top Tags</h5>
                        <div class="chart-controls">
                            <button class="btn btn-sm btn-outline-secondary" data-action="chart-refresh">
                                <i class="fas fa-sync"></i>
                            </button>
                        </div>
                    </div>
                    <div class="card-body">
                        <div id="articles-by-tag-chart" style="height: 300px;"></div>
                    </div>
                </div>
            `
        });

        this.chartsContainerEl.appendChild(container);

        return {
            container,
            chart: null,
            data: [],
            render: (data) => this._renderArticlesByTagChart(data)
        };
    }

    /**
     * Render articles by date chart
     * @private
     * @param {Array} data - Chart data
     */
    _renderArticlesByDateChart(data) {
        if (!window.Recharts) {
            console.warn('Recharts not loaded, cannot render chart');
            return;
        }

        const { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } = Recharts;

        const chartData = data.map(item => ({
            date: FormatUtils.formatDate(item.date),
            count: item.count
        }));

        ReactDOM.render(
            React.createElement(ResponsiveContainer, { width: '100%', height: '100%' },
                React.createElement(BarChart, { data: chartData },
                    React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
                    React.createElement(XAxis, { dataKey: 'date' }),
                    React.createElement(YAxis),
                    React.createElement(Tooltip),
                    React.createElement(Legend),
                    React.createElement(Bar, { dataKey: 'count', fill: '#0d6efd' })
                )
            ),
            document.getElementById('articles-by-date-chart')
        );
    }

    /**
     * Render articles by source chart
     * @private
     * @param {Array} data - Chart data
     */
    _renderArticlesBySourceChart(data) {
        if (!window.Recharts) {
            console.warn('Recharts not loaded, cannot render chart');
            return;
        }

        const { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } = Recharts;

        const COLORS = ['#0d6efd', '#6610f2', '#6f42c1', '#d63384', '#dc3545', '#fd7e14', '#ffc107', '#198754', '#20c997', '#0dcaf0'];

        const chartData = data.map((item, index) => ({
            name: item.source_name,
            value: item.count,
            fill: COLORS[index % COLORS.length]
        }));

        ReactDOM.render(
            React.createElement(ResponsiveContainer, { width: '100%', height: '100%' },
                React.createElement(PieChart, { data: chartData },
                    React.createElement(Pie, { 
                        data: chartData, 
                        cx: '50%', 
                        cy: '50%', 
                        labelLine: false,
                        outerRadius: 80,
                        fill: '#8884d8',
                        dataKey: 'value',
                        nameKey: 'name',
                        label: true
                    },
                        chartData.map((entry, index) => (
                            React.createElement(Cell, { key: `cell-${index}`, fill: entry.fill })
                        ))
                    ),
                    React.createElement(Tooltip),
                    React.createElement(Legend)
                )
            ),
            document.getElementById('articles-by-source-chart')
        );
    }

    /**
     * Render articles by tag chart
     * @private
     * @param {Array} data - Chart data
     */
    _renderArticlesByTagChart(data) {
        if (!window.Recharts) {
            console.warn('Recharts not loaded, cannot render chart');
            return;
        }

        const { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } = Recharts;

        const chartData = data.map(item => ({
            tag: item.tag,
            count: item.count
        }));

        ReactDOM.render(
            React.createElement(ResponsiveContainer, { width: '100%', height: '100%' },
                React.createElement(BarChart, { data: chartData, layout: 'vertical' },
                    React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
                    React.createElement(XAxis, { type: 'number' }),
                    React.createElement(YAxis, { dataKey: 'tag', type: 'category' }),
                    React.createElement(Tooltip),
                    React.createElement(Legend),
                    React.createElement(Bar, { dataKey: 'count', fill: '#198754' })
                )
            ),
            document.getElementById('articles-by-tag-chart')
        );
    }

    /**
     * Load initial data
     */
    async loadInitialData() {
        this.showLoading();

        try {
            // Load statistics
            await this.loadStatistics();

            // Load saved searches
            await this.loadSavedSearches();

            // Load search history
            await this.loadSearchHistory();

            // Perform initial search
            await this._handleSearch();

            // Load chart data
            await this.loadChartData();

            this.hideLoading();
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to load initial data', error);
        }
    }

    /**
     * Load statistics
     */
    async loadStatistics() {
        try {
            this.statistics = await this.apiClient.getStatistics();
            this._renderStatistics();
        } catch (error) {
            console.error('Failed to load statistics:', error);
        }
    }

    /**
     * Render statistics
     * @private
     */
    _renderStatistics() {
        if (!this.statsContainerEl || !this.statistics) return;

        this.statsContainerEl.innerHTML = `
            <div class="row">
                <div class="col-md-3 col-6 mb-3">
                    <div class="card stat-card h-100">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <div class="stat-icon bg-primary bg-opacity-10 text-primary p-3 me-3">
                                    <i class="fas fa-newspaper fa-2x"></i>
                                </div>
                                <div class="flex-grow-1">
                                    <h6 class="text-muted mb-1">Total Articles</h6>
                                    <h3 class="mb-0">${FormatUtils.formatNumber(this.statistics.total_articles || 0)}</h3>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 col-6 mb-3">
                    <div class="card stat-card h-100">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <div class="stat-icon bg-success bg-opacity-10 text-success p-3 me-3">
                                    <i class="fas fa-rss fa-2x"></i>
                                </div>
                                <div class="flex-grow-1">
                                    <h6 class="text-muted mb-1">Active Sources</h6>
                                    <h3 class="mb-0">${FormatUtils.formatNumber(this.statistics.active_sources || 0)}</h3>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 col-6 mb-3">
                    <div class="card stat-card h-100">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <div class="stat-icon bg-warning bg-opacity-10 text-warning p-3 me-3">
                                    <i class="fas fa-tags fa-2x"></i>
                                </div>
                                <div class="flex-grow-1">
                                    <h6 class="text-muted mb-1">Unique Tags</h6>
                                    <h3 class="mb-0">${FormatUtils.formatNumber(this.statistics.unique_tags || 0)}</h3>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 col-6 mb-3">
                    <div class="card stat-card h-100">
                        <div class="card-body">
                            <div class="d-flex align-items-center">
                                <div class="stat-icon bg-info bg-opacity-10 text-info p-3 me-3">
                                    <i class="fas fa-database fa-2x"></i>
                                </div>
                                <div class="flex-grow-1">
                                    <h6 class="text-muted mb-1">Storage Used</h6>
                                    <h3 class="mb-0">${FormatUtils.formatFileSize(this.statistics.storage_used || 0)}</h3>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Load saved searches
     */
    async loadSavedSearches() {
        try {
            this.savedSearches = await this.apiClient.getSavedSearches();
            this._renderSavedSearches();
        } catch (error) {
            console.error('Failed to load saved searches:', error);
        }
    }

    /**
     * Render saved searches
     * @private
     */
    _renderSavedSearches() {
        if (!this.savedSearchesEl) return;

        if (this.savedSearches.length === 0) {
            this.savedSearchesEl.innerHTML = `
                <div class="text-muted text-center py-3">
                    <i class="fas fa-bookmark fa-2x mb-2"></i>
                    <p>No saved searches</p>
                </div>
            `;
            return;
        }

        this.savedSearchesEl.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5>Saved Searches</h5>
                <button class="btn btn-sm btn-outline-primary" data-action="save-current-search">
                    <i class="fas fa-save me-1"></i> Save Current
                </button>
            </div>
            <div class="list-group">
                ${this.savedSearches.map(search => `
                    <div class="list-group-item">
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="flex-grow-1">
                                <h6 class="mb-0">${search.name || search.query}</h6>
                                <small class="text-muted">
                                    ${search.query ? `Query: ${FormatUtils.truncate(search.query, 40)}` : ''}
                                    ${search.sources && search.sources.length > 0 ? ` | Sources: ${search.sources.length}` : ''}
                                    ${search.tags && search.tags.length > 0 ? ` | Tags: ${search.tags.length}` : ''}
                                </small>
                            </div>
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-outline-primary" 
                                        data-action="load-saved-search" 
                                        data-search-id="${search.id}" 
                                        title="Load">
                                    <i class="fas fa-play"></i>
                                </button>
                                <button class="btn btn-outline-danger" 
                                        data-action="delete-saved-search" 
                                        data-search-id="${search.id}" 
                                        title="Delete">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        // Add event listener for save current search
        const saveBtn = this.savedSearchesEl.querySelector('[data-action="save-current-search"]');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => this._saveCurrentSearch());
        }
    }

    /**
     * Load search history
     */
    async loadSearchHistory() {
        try {
            this.searchHistory = await this.apiClient.getSearchHistory();
            this._renderSearchHistory();
        } catch (error) {
            console.error('Failed to load search history:', error);
        }
    }

    /**
     * Render search history
     * @private
     */
    _renderSearchHistory() {
        if (!this.searchHistoryEl) return;

        if (this.searchHistory.length === 0) {
            this.searchHistoryEl.innerHTML = `
                <div class="text-muted text-center py-3">
                    <i class="fas fa-history fa-2x mb-2"></i>
                    <p>No search history</p>
                </div>
            `;
            return;
        }

        this.searchHistoryEl.innerHTML = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5>Search History</h5>
                <button class="btn btn-sm btn-outline-danger" data-action="clear-history">
                    <i class="fas fa-trash me-1"></i> Clear
                </button>
            </div>
            <div class="list-group">
                ${this.searchHistory.map(history => `
                    <div class="list-group-item">
                        <div class="d-flex justify-content-between align-items-center">
                            <div class="flex-grow-1">
                                <h6 class="mb-0">${history.query || 'Empty search'}</h6>
                                <small class="text-muted">
                                    ${FormatUtils.formatRelativeTime(history.timestamp)} |
                                    ${history.results || 0} results
                                </small>
                            </div>
                            <div class="btn-group btn-group-sm">
                                <button class="btn btn-outline-primary" 
                                        data-action="load-history-item" 
                                        data-history-id="${history.id}" 
                                        title="Load">
                                    <i class="fas fa-play"></i>
                                </button>
                                <button class="btn btn-outline-danger" 
                                        data-action="delete-history-item" 
                                        data-history-id="${history.id}" 
                                        title="Delete">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;
    }

    /**
     * Load chart data
     */
    async loadChartData() {
        try {
            // Load articles by date
            const articlesByDate = await this.apiClient.getArticleCountByDate({
                days: 30
            });
            this.charts.articlesByDate.data = articlesByDate;
            this.charts.articlesByDate.render(articlesByDate);

            // Load top sources
            const topSources = await this.apiClient.getTopSources({
                limit: 10
            });
            this.charts.articlesBySource.data = topSources;
            this.charts.articlesBySource.render(topSources);

            // Load top tags
            const tags = await this.apiClient.getTags();
            const topTags = tags.sort((a, b) => b.article_count - a.article_count).slice(0, 10);
            this.charts.articlesByTag.data = topTags;
            this.charts.articlesByTag.render(topTags);

        } catch (error) {
            console.error('Failed to load chart data:', error);
        }
    }

    /**
     * Handle search form submission
     * @private
     */
    _handleSearch() {
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        this._performSearch();
    }

    /**
     * Debounced search
     * @private
     */
    _debouncedSearch() {
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        this.searchTimeout = setTimeout(() => {
            this._performSearch();
        }, this.options.debounceSearch);
    }

    /**
     * Perform the actual search
     * @private
     */
    async _performSearch() {
        if (!this.searchFormEl) return;

        this.showLoading();

        try {
            // Get form data
            const formData = this._getSearchFormData();
            this.currentSearch = { ...formData };

            // Add to search history
            await this._addToSearchHistory(formData);

            // Perform search
            const results = await this.apiClient.searchArticles({
                query: formData.query,
                sources: formData.sources,
                tags: formData.tags,
                dateFrom: formData.dateFrom,
                dateTo: formData.dateTo,
                page: 1,
                pageSize: this.tableManager ? this.tableManager.options.pageSize : 20,
                sortBy: formData.sortBy || 'published_at',
                sortOrder: formData.sortOrder || 'desc'
            });

            // Update table
            if (this.tableManager) {
                this.tableManager.loadData(results.items || results.articles || []);
            }

            // Update statistics
            if (results.total) {
                this._updateSearchStats(results.total);
            }

            this.hideLoading();
        } catch (error) {
            this.hideLoading();
            this.showError('Search failed', error);
        }
    }

    /**
     * Get search form data
     * @private
     * @returns {Object} Form data
     */
    _getSearchFormData() {
        const formData = {};

        if (this.searchFormEl) {
            const inputs = this.searchFormEl.querySelectorAll('input, select');
            inputs.forEach(input => {
                const { name, value, type } = input;

                if (!name) return;

                if (type === 'checkbox') {
                    formData[name] = input.checked;
                } else if (type === 'radio') {
                    if (input.checked) {
                        formData[name] = value;
                    }
                } else if (input.multiple) {
                    const options = Array.from(input.selectedOptions);
                    formData[name] = options.map(opt => opt.value);
                } else {
                    formData[name] = value;
                }
            });
        }

        return formData;
    }

    /**
     * Add to search history
     * @private
     * @param {Object} searchData - Search data
     */
    async _addToSearchHistory(searchData) {
        try {
            // Don't add empty searches
            if (!searchData.query && 
                (!searchData.sources || searchData.sources.length === 0) &&
                (!searchData.tags || searchData.tags.length === 0)) {
                return;
            }

            await this.apiClient.createSavedSearch({
                query: searchData.query,
                sources: searchData.sources,
                tags: searchData.tags,
                date_from: searchData.dateFrom,
                date_to: searchData.dateTo
            });

            // Reload history
            await this.loadSearchHistory();
        } catch (error) {
            console.error('Failed to add to search history:', error);
        }
    }

    /**
     * Update search statistics
     * @private
     * @param {number} total - Total results
     */
    _updateSearchStats(total) {
        const statsEl = document.querySelector('.search-stats');
        if (statsEl) {
            statsEl.textContent = `${FormatUtils.formatNumber(total)} articles found`;
        }
    }

    /**
     * Load a saved search
     * @private
     * @param {Object} search - Saved search
     */
    _loadSavedSearch(search) {
        if (!this.searchFormEl) return;

        // Populate form with saved search data
        const inputs = this.searchFormEl.querySelectorAll('input, select');
        inputs.forEach(input => {
            const { name, type } = input;

            if (search[name] !== undefined) {
                if (type === 'checkbox') {
                    input.checked = search[name];
                } else if (type === 'radio') {
                    if (input.value == search[name]) {
                        input.checked = true;
                    }
                } else if (input.multiple) {
                    if (Array.isArray(search[name])) {
                        search[name].forEach(value => {
                            const option = input.querySelector(`option[value="${value}"]`);
                            if (option) {
                                option.selected = true;
                            }
                        });
                    }
                } else {
                    input.value = search[name];
                }
            }
        });

        // Trigger search
        this._performSearch();
    }

    /**
     * Delete a saved search
     * @private
     * @param {string} searchId - Search ID
     */
    async _deleteSavedSearch(searchId) {
        try {
            await this.apiClient.deleteSavedSearch(searchId);
            await this.loadSavedSearches();
            this.showSuccess('Saved search deleted');
        } catch (error) {
            this.showError('Failed to delete saved search', error);
        }
    }

    /**
     * Save current search
     * @private
     */
    async _saveCurrentSearch() {
        if (!this.searchFormEl) return;

        const formData = this._getSearchFormData();

        // Don't save empty searches
        if (!formData.query && 
            (!formData.sources || formData.sources.length === 0) &&
            (!formData.tags || formData.tags.length === 0)) {
            this.showWarning('Cannot save empty search');
            return;
        }

        try {
            const name = prompt('Enter a name for this search:', formData.query || 'My Search');
            if (!name) return;

            await this.apiClient.createSavedSearch({
                name,
                query: formData.query,
                sources: formData.sources,
                tags: formData.tags,
                date_from: formData.dateFrom,
                date_to: formData.dateTo
            });

            await this.loadSavedSearches();
            this.showSuccess('Search saved successfully');
        } catch (error) {
            this.showError('Failed to save search', error);
        }
    }

    /**
     * Load a history item
     * @private
     * @param {Object} historyItem - History item
     */
    _loadHistoryItem(historyItem) {
        if (!this.searchFormEl) return;

        // Populate form with history data
        const queryInput = this.searchFormEl.querySelector('[name="q"]');
        if (queryInput && historyItem.query) {
            queryInput.value = historyItem.query;
        }

        // Trigger search
        this._performSearch();
    }

    /**
     * Delete a history item
     * @private
     * @param {string} historyId - History ID
     */
    async _deleteHistoryItem(historyId) {
        try {
            // Note: The API might not support deleting individual history items
            // For now, we'll just reload the history
            await this.loadSearchHistory();
        } catch (error) {
            this.showError('Failed to delete history item', error);
        }
    }

    /**
     * Clear search history
     * @private
     */
    async _clearSearchHistory() {
        try {
            if (confirm('Are you sure you want to clear all search history?')) {
                await this.apiClient.clearSearchHistory();
                await this.loadSearchHistory();
                this.showSuccess('Search history cleared');
            }
        } catch (error) {
            this.showError('Failed to clear search history', error);
        }
    }

    /**
     * Preview an article
     * @private
     * @param {string} articleId - Article ID
     */
    async _previewArticle(articleId) {
        try {
            this.showLoading();

            // Get article details
            const article = await this.apiClient.getArticle(articleId);

            // Show in modal
            this._showArticlePreviewModal(article);

            this.hideLoading();
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to load article', error);
        }
    }

    /**
     * Open an article
     * @private
     * @param {string} articleId - Article ID
     */
    async _openArticle(articleId) {
        try {
            // Open in new tab or window
            window.open(`/article/${articleId}`, '_blank');
        } catch (error) {
            this.showError('Failed to open article', error);
        }
    }

    /**
     * Show article preview modal
     * @private
     * @param {Object} article - Article data
     */
    _showArticlePreviewModal(article) {
        const modalId = 'article-preview-modal';
        let modal = document.getElementById(modalId);

        if (!modal) {
            modal = DOMUtils.createElement('div', {
                id: modalId,
                className: 'modal fade',
                innerHTML: `
                    <div class="modal-dialog modal-xl">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Article Preview</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                            </div>
                            <div class="modal-body">
                                <div class="article-preview-content"></div>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                                <button type="button" class="btn btn-primary" data-action="open-article-full">
                                    <i class="fas fa-external-link-alt me-1"></i> Open Full Article
                                </button>
                            </div>
                        </div>
                    </div>
                `
            });
            document.body.appendChild(modal);
        }

        const contentEl = modal.querySelector('.article-preview-content');
        const openFullBtn = modal.querySelector('[data-action="open-article-full"]');

        // Render article content
        contentEl.innerHTML = `
            <div class="row">
                <div class="col-md-8">
                    <h2>${article.title || 'Untitled'}</h2>
                    <div class="article-meta text-muted mb-3">
                        <span class="me-3">
                            <i class="fas fa-newspaper me-1"></i> ${article.source_name || 'Unknown'}
                        </span>
                        <span class="me-3">
                            <i class="fas fa-calendar me-1"></i> ${FormatUtils.formatDate(article.published_at)}
                        </span>
                        <span class="me-3">
                            <i class="fas fa-user me-1"></i> ${article.author || 'Unknown'}
                        </span>
                        <span class="me-3">
                            <i class="fas fa-globe me-1"></i> ${article.language || 'Unknown'}
                        </span>
                        ${article.word_count ? `
                            <span>
                                <i class="fas fa-font me-1"></i> ${FormatUtils.formatNumber(article.word_count)} words
                            </span>
                        ` : ''}
                    </div>
                    
                    ${article.summary ? `
                        <div class="card mb-3">
                            <div class="card-header">
                                <strong>Summary</strong>
                            </div>
                            <div class="card-body">
                                <p>${article.summary}</p>
                            </div>
                        </div>
                    ` : ''}
                    
                    <div class="article-content">
                        ${article.content ? `
                            <div class="article-text">
                                ${article.content.substring(0, 5000)}
                                ${article.content.length > 5000 ? 
                                    `<div class="text-muted mt-3">
                                        <em>Content truncated. Showing first 5000 characters.</em>
                                    </div>` : ''}
                            </div>
                        ` : '<div class="text-muted">No content available</div>'}
                    </div>
                    
                    ${article.tags && article.tags.length > 0 ? `
                        <div class="article-tags mt-3">
                            <strong>Tags:</strong>
                            ${article.tags.map(tag => 
                                `<span class="badge bg-primary me-1">${tag}</span>`
                            ).join('')}
                        </div>
                    ` : ''}
                </div>
                <div class="col-md-4">
                    <div class="card mb-3">
                        <div class="card-header">
                            <strong>Article Information</strong>
                        </div>
                        <div class="card-body">
                            <div class="d-flex justify-content-between mb-2">
                                <span class="text-muted">ID:</span>
                                <span>${article.id}</span>
                            </div>
                            <div class="d-flex justify-content-between mb-2">
                                <span class="text-muted">Published:</span>
                                <span>${FormatUtils.formatDate(article.published_at)}</span>
                            </div>
                            <div class="d-flex justify-content-between mb-2">
                                <span class="text-muted">Retrieved:</span>
                                <span>${FormatUtils.formatDate(article.retrieved_at)}</span>
                            </div>
                            <div class="d-flex justify-content-between mb-2">
                                <span class="text-muted">Source:</span>
                                <span>${article.source_name || 'Unknown'}</span>
                            </div>
                            <div class="d-flex justify-content-between mb-2">
                                <span class="text-muted">Author:</span>
                                <span>${article.author || 'Unknown'}</span>
                            </div>
                            <div class="d-flex justify-content-between mb-2">
                                <span class="text-muted">Language:</span>
                                <span>${article.language || 'Unknown'}</span>
                            </div>
                            <div class="d-flex justify-content-between">
                                <span class="text-muted">Word Count:</span>
                                <span>${article.word_count || 'N/A'}</span>
                            </div>
                        </div>
                    </div>
                    
                    ${article.url ? `
                        <div class="card">
                            <div class="card-header">
                                <strong>Source</strong>
                            </div>
                            <div class="card-body">
                                <a href="${article.url}" target="_blank" class="btn btn-outline-primary w-100">
                                    <i class="fas fa-link me-1"></i> View Original
                                </a>
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;

        // Setup open full button
        if (openFullBtn) {
            openFullBtn.onclick = () => {
                this._openArticle(article.id);
            };
        }

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById(modalId));
        modal.show();
    }

    /**
     * Export results
     * @private
     * @param {string} format - Export format
     */
    async _exportResults(format) {
        try {
            this.showLoading();

            const formData = this._getSearchFormData();

            const response = await this.apiClient.exportArticles({
                format,
                ...formData
            });

            // Handle file download
            if (response) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `articles-export.${format}`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            }

            this.hideLoading();
            this.showSuccess(`Export started. File will download automatically.`);
        } catch (error) {
            this.hideLoading();
            this.showError('Export failed', error);
        }
    }

    /**
     * Open settings modal
     * @private
     */
    _openSettingsModal() {
        const modalId = 'settings-modal';
        let modal = document.getElementById(modalId);

        if (!modal) {
            modal = DOMUtils.createElement('div', {
                id: modalId,
                className: 'modal fade',
                innerHTML: `
                    <div class="modal-dialog">
                        <div class="modal-content">
                            <div class="modal-header">
                                <h5 class="modal-title">Settings</h5>
                                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                            </div>
                            <div class="modal-body">
                                <form id="settings-form">
                                    <div class="mb-3">
                                        <label class="form-label">Theme</label>
                                        <div class="d-flex gap-2">
                                            <button type="button" class="btn btn-outline-secondary flex-grow-1" 
                                                    data-action="set-theme" data-theme="light">
                                                <i class="fas fa-sun me-1"></i> Light
                                            </button>
                                            <button type="button" class="btn btn-outline-secondary flex-grow-1" 
                                                    data-action="set-theme" data-theme="dark">
                                                <i class="fas fa-moon me-1"></i> Dark
                                            </button>
                                            <button type="button" class="btn btn-outline-secondary flex-grow-1" 
                                                    data-action="set-theme" data-theme="system">
                                                <i class="fas fa-desktop me-1"></i> System
                                            </button>
                                        </div>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">Results per page</label>
                                        <select class="form-select" name="pageSize">
                                            <option value="10">10</option>
                                            <option value="20" selected>20</option>
                                            <option value="50">50</option>
                                            <option value="100">100</option>
                                        </select>
                                    </div>
                                    <div class="mb-3">
                                        <label class="form-label">Date format</label>
                                        <select class="form-select" name="dateFormat">
                                            <option value="relative">Relative (e.g., "2 hours ago")</option>
                                            <option value="absolute">Absolute (e.g., "Jan 1, 2024")</option>
                                            <option value="iso">ISO (e.g., "2024-01-01")</option>
                                        </select>
                                    </div>
                                </form>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                                <button type="button" class="btn btn-primary" data-action="save-settings">
                                    <i class="fas fa-save me-1"></i> Save
                                </button>
                            </div>
                        </div>
                    </div>
                `
            });
            document.body.appendChild(modal);
        }

        // Setup event listeners
        const themeBtns = modal.querySelectorAll('[data-action="set-theme"]');
        themeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                this._setTheme(btn.dataset.theme);
            });
        });

        const saveBtn = modal.querySelector('[data-action="save-settings"]');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                this._saveSettings();
            });
        }

        // Show modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    /**
     * Set theme
     * @private
     * @param {string} theme - Theme name
     */
    _setTheme(theme) {
        // Update theme in localStorage
        localStorage.setItem('theme', theme);

        // Update document class
        document.documentElement.classList.remove('theme-light', 'theme-dark');
        if (theme === 'light') {
            document.documentElement.classList.add('theme-light');
        } else if (theme === 'dark') {
            document.documentElement.classList.add('theme-dark');
        }

        // Update theme toggle buttons
        const themeToggles = document.querySelectorAll('[data-action="toggle-theme"]');
        themeToggles.forEach(toggle => {
            const icon = toggle.querySelector('i');
            if (theme === 'dark') {
                icon.className = 'fas fa-sun';
                toggle.setAttribute('aria-label', 'Switch to light mode');
            } else {
                icon.className = 'fas fa-moon';
                toggle.setAttribute('aria-label', 'Switch to dark mode');
            }
        });

        this.showSuccess(`Theme set to ${theme}`);
    }

    /**
     * Toggle theme
     * @private
     */
    _toggleTheme() {
        const currentTheme = localStorage.getItem('theme') || 'system';
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        this._setTheme(newTheme);
    }

    /**
     * Save settings
     * @private
     */
    async _saveSettings() {
        const modal = document.getElementById('settings-modal');
        if (!modal) return;

        const form = modal.querySelector('#settings-form');
        if (!form) return;

        const formData = new FormData(form);
        const settings = Object.fromEntries(formData.entries());

        try {
            await this.apiClient.updateSettings(settings);
            
            // Update table page size if changed
            if (settings.pageSize && this.tableManager) {
                this.tableManager.options.pageSize = parseInt(settings.pageSize);
                this.tableManager.render();
            }

            this.showSuccess('Settings saved successfully');

            // Close modal
            const bsModal = bootstrap.Modal.getInstance(modal);
            bsModal.hide();
        } catch (error) {
            this.showError('Failed to save settings', error);
        }
    }

    // Notification helpers

    /**
     * Show success notification
     * @param {string} message - Message
     */
    showSuccess(message) {
        getNotificationManager().success(message);
    }

    /**
     * Show error notification
     * @param {string} message - Message
     * @param {Error} error - Error object
     */
    showError(message, error = null) {
        const errorMessage = error ? `${message}: ${error.message}` : message;
        getNotificationManager().error(errorMessage);
    }

    /**
     * Show warning notification
     * @param {string} message - Message
     */
    showWarning(message) {
        getNotificationManager().warning(message);
    }

    /**
     * Show info notification
     * @param {string} message - Message
     */
    showInfo(message) {
        getNotificationManager().info(message);
    }

    // Loading helpers

    /**
     * Show loading indicator
     */
    showLoading() {
        if (this.loadingIndicator) {
            this.loadingIndicator.classList.remove('d-none');
        }
    }

    /**
     * Hide loading indicator
     */
    hideLoading() {
        if (this.loadingIndicator) {
            this.loadingIndicator.classList.add('d-none');
        }
    }

    /**
     * Refresh all data
     */
    async refresh() {
        await this.loadInitialData();
    }

    /**
     * Destroy the dashboard
     */
    destroy() {
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        if (this.tableManager) {
            this.tableManager.destroy();
        }

        // Remove created elements
        if (this.loadingIndicator) {
            this.loadingIndicator.remove();
        }
    }
}

/**
 * Create a new dashboard instance
 * @param {Object} options - Configuration options
 * @returns {Dashboard} Dashboard instance
 */
function createDashboard(options = {}) {
    return new Dashboard(options);
}

// Export for use in modules
export { Dashboard, createDashboard };
