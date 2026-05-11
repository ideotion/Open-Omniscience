/**
 * Source Manager Page Logic for Open-Omniscience
 * Handles source management functionality
 */

class SourceManager {
    /**
     * Create a new source manager instance
     * @param {Object} options - Configuration options
     */
    constructor(options = {}) {
        this.options = {
            apiClient: null,
            tableSelector: '#sourcesTable',
            groupsTableSelector: '#groupsTable',
            discoverTableSelector: '#discoverResultsTable',
            autoLoad: true,
            ...options
        };

        this.apiClient = this.options.apiClient || getAPIClient();
        this.sourcesTableManager = null;
        this.groupsTableManager = null;
        this.discoverTableManager = null;
        this.sources = [];
        this.groups = [];
        this.statistics = {};
        this.currentTab = 'sources';

        this._initialize();
    }

    /**
     * Initialize the source manager
     * @private
     */
    _initialize() {
        this._setupElements();
        this._setupEventListeners();
        this._setupTables();

        if (this.options.autoLoad) {
            this.loadInitialData();
        }
    }

    /**
     * Setup DOM elements
     * @private
     */
    _setupElements() {
        this.sourcesTableEl = document.querySelector(this.options.tableSelector);
        this.groupsTableEl = document.querySelector(this.options.groupsTableSelector);
        this.discoverTableEl = document.querySelector(this.options.discoverTableSelector);

        // Tab elements
        this.tabButtons = document.querySelectorAll('[data-bs-toggle="tab"]');
        this.tabPanes = document.querySelectorAll('.tab-pane');

        // Loading indicator
        this.loadingIndicator = document.getElementById('loadingOverlay');
    }

    /**
     * Setup event listeners
     * @private
     */
    _setupEventListeners() {
        // Tab change events
        if (this.tabButtons.length > 0) {
            this.tabButtons.forEach(tabBtn => {
                tabBtn.addEventListener('shown.bs.tab', (event) => {
                    this._handleTabChange(event.target);
                });
            });
        }

        // Source actions
        document.addEventListener('click', (e) => {
            // Add source button
            const addSourceBtn = e.target.closest('#addSourceBtn');
            if (addSourceBtn) {
                this._showAddSourceModal();
            }

            // Save source button
            const saveSourceBtn = e.target.closest('#saveSourceBtn');
            if (saveSourceBtn) {
                this._saveSource();
            }

            // Edit source button
            const editBtn = e.target.closest('[data-action="edit-source"]');
            if (editBtn) {
                const sourceId = editBtn.dataset.sourceId;
                this._showEditSourceModal(sourceId);
            }

            // Delete source button
            const deleteBtn = e.target.closest('[data-action="delete-source"]');
            if (deleteBtn) {
                const sourceId = deleteBtn.dataset.sourceId;
                this._confirmDeleteSource(sourceId);
            }

            // Test source button
            const testBtn = e.target.closest('[data-action="test-source"]');
            if (testBtn) {
                const sourceId = testBtn.dataset.sourceId;
                this._testSource(sourceId);
            }

            // Sync source button
            const syncBtn = e.target.closest('[data-action="sync-source"]');
            if (syncBtn) {
                const sourceId = syncBtn.dataset.sourceId;
                this._syncSource(sourceId);
            }

            // Toggle source status
            const toggleBtn = e.target.closest('[data-action="toggle-source"]');
            if (toggleBtn) {
                const sourceId = toggleBtn.dataset.sourceId;
                this._toggleSourceStatus(sourceId);
            }

            // Group actions
            const addGroupBtn = e.target.closest('#addGroupBtn');
            if (addGroupBtn) {
                this._showAddGroupModal();
            }

            const saveGroupBtn = e.target.closest('#saveGroupBtn');
            if (saveGroupBtn) {
                this._saveGroup();
            }

            // Filter actions
            const clearFiltersBtn = e.target.closest('#clearSourceFilters');
            if (clearFiltersBtn) {
                this._clearFilters();
            }

            // Search actions
            const searchForm = e.target.closest('#discoverForm');
            if (searchForm && e.type === 'submit') {
                e.preventDefault();
                this._performDiscoverSearch();
            }

            // Refresh actions
            const refreshBtn = e.target.closest('#refreshButton, #refreshGroupsBtn, #refreshDiscoverBtn, #refreshStatsBtn');
            if (refreshBtn) {
                this._refreshCurrentTab();
            }

            // Back button
            const backBtn = e.target.closest('#backButton');
            if (backBtn) {
                window.location.href = 'index.html';
            }

            // Export button
            const exportBtn = e.target.closest('#exportSourcesBtn');
            if (exportBtn) {
                this._exportSources();
            }

            // Confirm action button
            const confirmBtn = e.target.closest('#confirmActionBtn');
            if (confirmBtn) {
                this._handleConfirmAction();
            }
        });

        // Filter input events
        const filterInputs = document.querySelectorAll('#sourceSearch, #sourceStatusFilter, #sourcePriorityFilter, #sourceGroupFilter');
        filterInputs.forEach(input => {
            input.addEventListener('input', (e) => {
                this._applyFilters();
            });
            input.addEventListener('change', (e) => {
                this._applyFilters();
            });
        });

        // Group type change (show/hide tag pattern)
        const groupTypeSelect = document.getElementById('groupType');
        if (groupTypeSelect) {
            groupTypeSelect.addEventListener('change', (e) => {
                const tagPatternGroup = document.getElementById('tagPatternGroup');
                if (e.target.value === 'dynamic') {
                    tagPatternGroup.style.display = 'block';
                } else {
                    tagPatternGroup.style.display = 'none';
                }
            });
        }

        // Theme toggle
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            themeToggle.addEventListener('click', () => {
                this._toggleTheme();
            });
        }

        // Settings button
        const settingsBtn = document.getElementById('settingsButton');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => {
                this._openSettingsModal();
            });
        }
    }

    /**
     * Setup tables
     * @private
     */
    _setupTables() {
        // Sources table
        if (this.sourcesTableEl) {
            this.sourcesTableManager = new TableManager(this.sourcesTableEl, {
                sortable: true,
                paginate: true,
                filterable: true,
                pageSize: 20,
                pageSizeOptions: [10, 20, 50, 100],
                multiSelect: true,
                rowSelection: true,
                emptyMessage: 'No sources found',
                renderRow: (item) => {
                    const cells = [];

                    // Selection checkbox
                    const selectCell = document.createElement('td');
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.className = 'form-check-input';
                    checkbox.dataset.sourceId = item.id;
                    selectCell.appendChild(checkbox);
                    cells.push(selectCell);

                    // Name
                    const nameCell = document.createElement('td');
                    nameCell.innerHTML = `
                        <strong>${item.name}</strong>
                        ${item.description ? `<br><small class="text-muted">${FormatUtils.truncate(item.description, 50)}</small>` : ''}
                    `;
                    cells.push(nameCell);

                    // Domain
                    const domainCell = document.createElement('td');
                    domainCell.innerHTML = `
                        <a href="${item.homepage || '#'}" target="_blank" class="text-decoration-none">
                            ${item.domain || 'N/A'}
                        </a>
                    `;
                    cells.push(domainCell);

                    // RSS URL
                    const rssCell = document.createElement('td');
                    rssCell.innerHTML = `
                        <small class="text-muted">${FormatUtils.truncate(item.rss_url || 'N/A', 40)}</small>
                    `;
                    cells.push(rssCell);

                    // Status
                    const statusCell = document.createElement('td');
                    const statusClass = item.enabled ? 'bg-success' : (item.error ? 'bg-danger' : 'bg-warning');
                    const statusText = item.enabled ? 'Enabled' : (item.error ? 'Error' : 'Disabled');
                    statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
                    cells.push(statusCell);

                    // Priority
                    const priorityCell = document.createElement('td');
                    const priorityClass = item.priority === 1 ? 'bg-danger' : (item.priority === 2 ? 'bg-warning' : 'bg-info');
                    priorityCell.innerHTML = `<span class="badge ${priorityClass}">${item.priority || 'N/A'}</span>`;
                    cells.push(priorityCell);

                    // Rate Limit
                    const rateLimitCell = document.createElement('td');
                    rateLimitCell.textContent = item.rate_limit ? `${item.rate_limit}s` : 'N/A';
                    cells.push(rateLimitCell);

                    // Tags
                    const tagsCell = document.createElement('td');
                    if (item.tags && item.tags.length > 0) {
                        tagsCell.innerHTML = item.tags.map(tag => 
                            `<span class="badge bg-light text-dark me-1">${FormatUtils.truncate(tag, 15)}</span>`
                        ).join('');
                    } else {
                        tagsCell.innerHTML = '<span class="text-muted">-</span>';
                    }
                    cells.push(tagsCell);

                    // Groups
                    const groupsCell = document.createElement('td');
                    if (item.groups && item.groups.length > 0) {
                        groupsCell.innerHTML = item.groups.map(group => 
                            `<span class="badge bg-secondary me-1">${FormatUtils.truncate(group, 15)}</span>`
                        ).join('');
                    } else {
                        groupsCell.innerHTML = '<span class="text-muted">-</span>';
                    }
                    cells.push(groupsCell);

                    // Article count
                    const articleCountCell = document.createElement('td');
                    articleCountCell.textContent = item.article_count || 0;
                    cells.push(articleCountCell);

                    // Actions
                    const actionsCell = document.createElement('td');
                    actionsCell.innerHTML = `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" data-action="edit-source" data-source-id="${item.id}" title="Edit">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-outline-success" data-action="test-source" data-source-id="${item.id}" title="Test">
                                <i class="fas fa-play"></i>
                            </button>
                            <button class="btn btn-outline-primary" data-action="sync-source" data-source-id="${item.id}" title="Sync">
                                <i class="fas fa-sync"></i>
                            </button>
                            <button class="btn btn-outline-${item.enabled ? 'warning' : 'success'}" 
                                    data-action="toggle-source" 
                                    data-source-id="${item.id}" 
                                    title="${item.enabled ? 'Disable' : 'Enable'}">
                                <i class="fas fa-${item.enabled ? 'pause' : 'play'}"></i>
                            </button>
                            <button class="btn btn-outline-danger" data-action="delete-source" data-source-id="${item.id}" title="Delete">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    `;
                    cells.push(actionsCell);

                    return cells;
                }
            });
        }

        // Groups table
        if (this.groupsTableEl) {
            this.groupsTableManager = new TableManager(this.groupsTableEl, {
                sortable: true,
                paginate: true,
                filterable: false,
                pageSize: 20,
                multiSelect: true,
                rowSelection: true,
                emptyMessage: 'No groups found',
                renderRow: (item) => {
                    const cells = [];

                    // Selection checkbox
                    const selectCell = document.createElement('td');
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.className = 'form-check-input';
                    checkbox.dataset.groupId = item.id;
                    selectCell.appendChild(checkbox);
                    cells.push(selectCell);

                    // Name
                    const nameCell = document.createElement('td');
                    nameCell.innerHTML = `
                        <strong>${item.name}</strong>
                        ${item.description ? `<br><small class="text-muted">${FormatUtils.truncate(item.description, 50)}</small>` : ''}
                    `;
                    cells.push(nameCell);

                    // Type
                    const typeCell = document.createElement('td');
                    const typeClass = item.type === 'dynamic' ? 'bg-info' : 'bg-secondary';
                    typeCell.innerHTML = `<span class="badge ${typeClass}">${item.type || 'static'}</span>`;
                    cells.push(typeCell);

                    // Source count
                    const sourceCountCell = document.createElement('td');
                    sourceCountCell.textContent = item.source_count || 0;
                    cells.push(sourceCountCell);

                    // Priority
                    const priorityCell = document.createElement('td');
                    const priorityClass = item.priority === 1 ? 'bg-danger' : (item.priority === 2 ? 'bg-warning' : 'bg-info');
                    priorityCell.innerHTML = `<span class="badge ${priorityClass}">${item.priority || 'N/A'}</span>`;
                    cells.push(priorityCell);

                    // Rate Limit
                    const rateLimitCell = document.createElement('td');
                    rateLimitCell.textContent = item.rate_limit ? `${item.rate_limit}s` : 'N/A';
                    cells.push(rateLimitCell);

                    // Status
                    const statusCell = document.createElement('td');
                    const statusClass = item.enabled ? 'bg-success' : 'bg-warning';
                    const statusText = item.enabled ? 'Enabled' : 'Disabled';
                    statusCell.innerHTML = `<span class="badge ${statusClass}">${statusText}</span>`;
                    cells.push(statusCell);

                    // Tag Pattern
                    const tagPatternCell = document.createElement('td');
                    tagPatternCell.textContent = item.tag_pattern || 'N/A';
                    cells.push(tagPatternCell);

                    // Actions
                    const actionsCell = document.createElement('td');
                    actionsCell.innerHTML = `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" data-action="edit-group" data-group-id="${item.id}" title="Edit">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button class="btn btn-outline-danger" data-action="delete-group" data-group-id="${item.id}" title="Delete">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    `;
                    cells.push(actionsCell);

                    return cells;
                }
            });
        }

        // Discover results table
        if (this.discoverTableEl) {
            this.discoverTableManager = new TableManager(this.discoverTableEl, {
                sortable: true,
                paginate: true,
                filterable: false,
                pageSize: 10,
                emptyMessage: 'No sources found matching your criteria',
                renderRow: (item) => {
                    const cells = [];

                    // Selection checkbox
                    const selectCell = document.createElement('td');
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    checkbox.className = 'form-check-input';
                    checkbox.dataset.sourceId = item.id;
                    selectCell.appendChild(checkbox);
                    cells.push(selectCell);

                    // Name
                    const nameCell = document.createElement('td');
                    nameCell.innerHTML = `
                        <strong>${item.name}</strong>
                        ${item.description ? `<br><small class="text-muted">${FormatUtils.truncate(item.description, 50)}</small>` : ''}
                    `;
                    cells.push(nameCell);

                    // Domain
                    const domainCell = document.createElement('td');
                    domainCell.innerHTML = `
                        <a href="${item.homepage || '#'}" target="_blank" class="text-decoration-none">
                            ${item.domain || 'N/A'}
                        </a>
                    `;
                    cells.push(domainCell);

                    // Category
                    const categoryCell = document.createElement('td');
                    categoryCell.textContent = item.category || 'N/A';
                    cells.push(categoryCell);

                    // Language
                    const languageCell = document.createElement('td');
                    languageCell.textContent = item.language || 'N/A';
                    cells.push(languageCell);

                    // Actions
                    const actionsCell = document.createElement('td');
                    actionsCell.innerHTML = `
                        <div class="btn-group btn-group-sm">
                            <button class="btn btn-outline-primary" data-action="add-discovered-source" data-source-id="${item.id}" title="Add">
                                <i class="fas fa-plus"></i>
                            </button>
                            <button class="btn btn-outline-info" data-action="preview-discovered-source" data-source-id="${item.id}" title="Preview">
                                <i class="fas fa-eye"></i>
                            </button>
                        </div>
                    `;
                    cells.push(actionsCell);

                    return cells;
                }
            });
        }
    }

    /**
     * Load initial data
     */
    async loadInitialData() {
        this.showLoading();

        try {
            // Load sources
            await this.loadSources();

            // Load groups
            await this.loadGroups();

            // Load statistics
            await this.loadStatistics();

            this.hideLoading();
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to load initial data', error);
        }
    }

    /**
     * Load sources
     */
    async loadSources() {
        try {
            this.sources = await this.apiClient.getSources();
            
            if (this.sourcesTableManager) {
                this.sourcesTableManager.loadData(this.sources);
            }

            // Update group filters
            this._updateGroupFilters();

            // Update statistics
            this._updateSourceStatistics();
        } catch (error) {
            console.error('Failed to load sources:', error);
            this.showError('Failed to load sources', error);
        }
    }

    /**
     * Load groups
     */
    async loadGroups() {
        try {
            this.groups = await this.apiClient.getSourceCategories();
            
            if (this.groupsTableManager) {
                this.groupsTableManager.loadData(this.groups);
            }

            // Update group filters
            this._updateGroupFilters();
        } catch (error) {
            console.error('Failed to load groups:', error);
            this.showError('Failed to load groups', error);
        }
    }

    /**
     * Load statistics
     */
    async loadStatistics() {
        try {
            this.statistics = await this.apiClient.getStatistics();
            this._updateStatistics();
        } catch (error) {
            console.error('Failed to load statistics:', error);
        }
    }

    /**
     * Update source statistics
     * @private
     */
    _updateSourceStatistics() {
        if (!this.sources || !this.sourcesTableManager) return;

        const total = this.sources.length;
        const active = this.sources.filter(s => s.enabled).length;
        const disabled = this.sources.filter(s => !s.enabled).length;
        const error = this.sources.filter(s => s.error).length;

        // Update page info
        const pageInfo = document.getElementById('pageInfoSources');
        if (pageInfo) {
            const start = ((this.sourcesTableManager.options.currentPage - 1) * this.sourcesTableManager.options.pageSize) + 1;
            const end = Math.min(this.sourcesTableManager.options.currentPage * this.sourcesTableManager.options.pageSize, total);
            pageInfo.textContent = `Showing ${start}-${end} of ${total} sources`;
        }
    }

    /**
     * Update statistics display
     * @private
     */
    _updateStatistics() {
        if (!this.statistics) return;

        const totalSourcesEl = document.getElementById('totalSourcesCount');
        const activeSourcesEl = document.getElementById('activeSourcesCount');
        const totalGroupsEl = document.getElementById('totalGroupsCount');
        const totalArticlesEl = document.getElementById('totalArticlesCount');

        if (totalSourcesEl) {
            totalSourcesEl.textContent = FormatUtils.formatNumber(this.statistics.total_sources || 0);
        }
        if (activeSourcesEl) {
            activeSourcesEl.textContent = FormatUtils.formatNumber(this.statistics.active_sources || 0);
        }
        if (totalGroupsEl) {
            totalGroupsEl.textContent = FormatUtils.formatNumber(this.statistics.total_groups || 0);
        }
        if (totalArticlesEl) {
            totalArticlesEl.textContent = FormatUtils.formatNumber(this.statistics.total_articles || 0);
        }

        // Update charts
        this._updateCharts();
    }

    /**
     * Update charts
     * @private
     */
    _updateCharts() {
        if (!window.Recharts) {
            console.warn('Recharts not loaded, cannot render charts');
            return;
        }

        // Sources by status chart
        const sourcesByStatusData = [
            { name: 'Enabled', value: this.sources.filter(s => s.enabled).length },
            { name: 'Disabled', value: this.sources.filter(s => !s.enabled && !s.error).length },
            { name: 'Error', value: this.sources.filter(s => s.error).length }
        ];

        this._renderSourcesByStatusChart(sourcesByStatusData);

        // Articles by source chart
        const articlesBySourceData = this.sources
            .filter(s => s.article_count > 0)
            .sort((a, b) => b.article_count - a.article_count)
            .slice(0, 10)
            .map(s => ({
                name: s.name,
                value: s.article_count || 0
            }));

        this._renderArticlesBySourceChart(articlesBySourceData);
    }

    /**
     * Render sources by status chart
     * @private
     * @param {Array} data - Chart data
     */
    _renderSourcesByStatusChart(data) {
        if (!window.Recharts) return;

        const { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } = Recharts;
        const COLORS = ['#198754', '#ffc107', '#dc3545'];

        const chartData = data.map((item, index) => ({
            ...item,
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
            document.getElementById('sourcesByStatusChart')
        );
    }

    /**
     * Render articles by source chart
     * @private
     * @param {Array} data - Chart data
     */
    _renderArticlesBySourceChart(data) {
        if (!window.Recharts) return;

        const { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } = Recharts;

        ReactDOM.render(
            React.createElement(ResponsiveContainer, { width: '100%', height: '100%' },
                React.createElement(BarChart, { data: data },
                    React.createElement(CartesianGrid, { strokeDasharray: '3 3' }),
                    React.createElement(XAxis, { dataKey: 'name' }),
                    React.createElement(YAxis),
                    React.createElement(Tooltip),
                    React.createElement(Legend),
                    React.createElement(Bar, { dataKey: 'value', fill: '#0d6efd' })
                )
            ),
            document.getElementById('articlesBySourceChart')
        );
    }

    /**
     * Handle tab change
     * @private
     * @param {HTMLElement} tabButton - Tab button element
     */
    _handleTabChange(tabButton) {
        this.currentTab = tabButton.getAttribute('aria-controls');
        
        // Load tab-specific data
        switch (this.currentTab) {
            case 'sources':
                this._refreshSourcesTab();
                break;
            case 'groups':
                this._refreshGroupsTab();
                break;
            case 'discover':
                this._refreshDiscoverTab();
                break;
            case 'statistics':
                this._refreshStatisticsTab();
                break;
        }
    }

    /**
     * Refresh current tab
     * @private
     */
    _refreshCurrentTab() {
        switch (this.currentTab) {
            case 'sources':
                this._refreshSourcesTab();
                break;
            case 'groups':
                this._refreshGroupsTab();
                break;
            case 'discover':
                this._refreshDiscoverTab();
                break;
            case 'statistics':
                this._refreshStatisticsTab();
                break;
        }
    }

    /**
     * Refresh sources tab
     * @private
     */
    _refreshSourcesTab() {
        this.loadSources();
    }

    /**
     * Refresh groups tab
     * @private
     */
    _refreshGroupsTab() {
        this.loadGroups();
    }

    /**
     * Refresh discover tab
     * @private
     */
    _refreshDiscoverTab() {
        // Clear discover results
        if (this.discoverTableManager) {
            this.discoverTableManager.loadData([]);
        }
    }

    /**
     * Refresh statistics tab
     * @private
     */
    _refreshStatisticsTab() {
        this.loadStatistics();
    }

    /**
     * Apply filters to sources table
     * @private
     */
    _applyFilters() {
        if (!this.sourcesTableManager || !this.sources) return;

        const searchQuery = document.getElementById('sourceSearch')?.value.toLowerCase() || '';
        const statusFilter = document.getElementById('sourceStatusFilter')?.value || '';
        const priorityFilter = document.getElementById('sourcePriorityFilter')?.value || '';
        const groupFilter = document.getElementById('sourceGroupFilter')?.value || '';

        const filteredSources = this.sources.filter(source => {
            // Search filter
            if (searchQuery) {
                const searchMatch = source.name.toLowerCase().includes(searchQuery) ||
                                   source.domain.toLowerCase().includes(searchQuery) ||
                                   (source.tags || []).some(tag => tag.toLowerCase().includes(searchQuery));
                if (!searchMatch) return false;
            }

            // Status filter
            if (statusFilter) {
                if (statusFilter === 'enabled' && !source.enabled) return false;
                if (statusFilter === 'disabled' && source.enabled) return false;
                if (statusFilter === 'error' && !source.error) return false;
            }

            // Priority filter
            if (priorityFilter && source.priority != parseInt(priorityFilter)) {
                return false;
            }

            // Group filter
            if (groupFilter && !(source.groups || []).includes(groupFilter)) {
                return false;
            }

            return true;
        });

        this.sourcesTableManager.loadData(filteredSources);
    }

    /**
     * Update group filters
     * @private
     */
    _updateGroupFilters() {
        const groupFilter = document.getElementById('sourceGroupFilter');
        if (!groupFilter) return;

        // Clear existing options (except first)
        while (groupFilter.options.length > 1) {
            groupFilter.remove(1);
        }

        // Add group options
        this.groups.forEach(group => {
            const option = document.createElement('option');
            option.value = group.id || group.name;
            option.textContent = group.name;
            groupFilter.appendChild(option);
        });
    }

    /**
     * Clear filters
     * @private
     */
    _clearFilters() {
        const searchInput = document.getElementById('sourceSearch');
        const statusFilter = document.getElementById('sourceStatusFilter');
        const priorityFilter = document.getElementById('sourcePriorityFilter');
        const groupFilter = document.getElementById('sourceGroupFilter');

        if (searchInput) searchInput.value = '';
        if (statusFilter) statusFilter.value = '';
        if (priorityFilter) priorityFilter.value = '';
        if (groupFilter) groupFilter.value = '';

        this._applyFilters();
    }

    /**
     * Show add source modal
     * @private
     */
    _showAddSourceModal() {
        const modal = new bootstrap.Modal(document.getElementById('addSourceModal'));
        modal.show();

        // Reset form
        const form = document.getElementById('addSourceForm');
        if (form) {
            form.reset();
        }

        // Populate groups dropdown
        this._populateGroupsDropdown('sourceGroups');
    }

    /**
     * Show edit source modal
     * @private
     * @param {string} sourceId - Source ID
     */
    _showEditSourceModal(sourceId) {
        const source = this.sources.find(s => s.id === sourceId);
        if (!source) return;

        const modal = new bootstrap.Modal(document.getElementById('editSourceModal'));
        modal.show();

        // Populate form with source data
        const form = document.getElementById('editSourceForm');
        if (form) {
            form.reset();
            
            // Set hidden ID
            const idInput = document.getElementById('editSourceId');
            if (idInput) idInput.value = source.id;

            // Populate fields
            this._populateFormFromSource(form, source);
        }

        // Populate groups dropdown
        this._populateGroupsDropdown('editSourceGroups');
    }

    /**
     * Populate form from source data
     * @private
     * @param {HTMLFormElement} form - Form element
     * @param {Object} source - Source data
     */
    _populateFormFromSource(form, source) {
        const fields = [
            { name: 'name', value: source.name },
            { name: 'domain', value: source.domain },
            { name: 'rss_url', value: source.rss_url },
            { name: 'homepage', value: source.homepage },
            { name: 'category', value: source.category },
            { name: 'language', value: source.language },
            { name: 'description', value: source.description },
            { name: 'rate_limit', value: source.rate_limit },
            { name: 'timeout', value: source.timeout },
            { name: 'priority', value: source.priority },
            { name: 'enabled', value: source.enabled, type: 'checkbox' },
            { name: 'tags', value: (source.tags || []).join(', ') }
        ];

        fields.forEach(field => {
            const input = form.querySelector(`[name="${field.name}"]`);
            if (input) {
                if (field.type === 'checkbox') {
                    input.checked = field.value;
                } else {
                    input.value = field.value || '';
                }
            }
        });

        // Set groups
        const groupsInput = form.querySelector('[name="groups"]');
        if (groupsInput && source.groups) {
            source.groups.forEach(groupId => {
                const option = groupsInput.querySelector(`option[value="${groupId}"]`);
                if (option) option.selected = true;
            });
        }
    }

    /**
     * Populate groups dropdown
     * @private
     * @param {string} selectId - Select element ID
     */
    _populateGroupsDropdown(selectId) {
        const select = document.getElementById(selectId);
        if (!select) return;

        // Clear existing options (except first)
        while (select.options.length > 1) {
            select.remove(1);
        }

        // Add group options
        this.groups.forEach(group => {
            const option = document.createElement('option');
            option.value = group.id || group.name;
            option.textContent = group.name;
            select.appendChild(option);
        });
    }

    /**
     * Save source
     * @private
     */
    async _saveSource() {
        const form = document.getElementById('addSourceForm');
        if (!form) return;

        // Validate form
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const formData = new FormData(form);
        const sourceData = Object.fromEntries(formData.entries());

        // Process tags
        if (sourceData.tags) {
            sourceData.tags = sourceData.tags.split(',').map(tag => tag.trim()).filter(tag => tag);
        }

        // Process groups
        if (sourceData.groups) {
            sourceData.groups = Array.from(formData.getAll('groups'));
        }

        // Process boolean fields
        sourceData.enabled = formData.get('enabled') === 'on';

        // Process numeric fields
        sourceData.rate_limit = parseInt(sourceData.rate_limit) || 300;
        sourceData.timeout = parseInt(sourceData.timeout) || 30;
        sourceData.priority = parseInt(sourceData.priority) || 2;

        this.showLoading();

        try {
            const newSource = await this.apiClient.createSource(sourceData);
            
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('addSourceModal'));
            modal.hide();

            // Reload sources
            await this.loadSources();

            this.hideLoading();
            this.showSuccess('Source added successfully');
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to add source', error);
        }
    }

    /**
     * Update source
     * @private
     */
    async _updateSource() {
        const form = document.getElementById('editSourceForm');
        if (!form) return;

        const sourceId = document.getElementById('editSourceId')?.value;
        if (!sourceId) return;

        // Validate form
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const formData = new FormData(form);
        const sourceData = Object.fromEntries(formData.entries());

        // Process tags
        if (sourceData.tags) {
            sourceData.tags = sourceData.tags.split(',').map(tag => tag.trim()).filter(tag => tag);
        }

        // Process groups
        if (sourceData.groups) {
            sourceData.groups = Array.from(formData.getAll('groups'));
        }

        // Process boolean fields
        sourceData.enabled = formData.get('enabled') === 'on';

        // Process numeric fields
        sourceData.rate_limit = parseInt(sourceData.rate_limit) || 300;
        sourceData.timeout = parseInt(sourceData.timeout) || 30;
        sourceData.priority = parseInt(sourceData.priority) || 2;

        this.showLoading();

        try {
            const updatedSource = await this.apiClient.updateSource(sourceId, sourceData);
            
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('editSourceModal'));
            modal.hide();

            // Reload sources
            await this.loadSources();

            this.hideLoading();
            this.showSuccess('Source updated successfully');
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to update source', error);
        }
    }

    /**
     * Confirm delete source
     * @private
     * @param {string} sourceId - Source ID
     */
    _confirmDeleteSource(sourceId) {
        const source = this.sources.find(s => s.id === sourceId);
        if (!source) return;

        const confirmMessage = document.getElementById('confirmMessage');
        if (confirmMessage) {
            confirmMessage.innerHTML = `
                Are you sure you want to delete the source <strong>${source.name}</strong>?
                <br><small class="text-muted">This action cannot be undone.</small>
            `;
        }

        // Store source ID in confirm button
        const confirmBtn = document.getElementById('confirmActionBtn');
        if (confirmBtn) {
            confirmBtn.dataset.action = 'delete-source';
            confirmBtn.dataset.sourceId = sourceId;
        }

        // Show confirmation modal
        const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
        modal.show();
    }

    /**
     * Delete source
     * @private
     * @param {string} sourceId - Source ID
     */
    async _deleteSource(sourceId) {
        this.showLoading();

        try {
            await this.apiClient.deleteSource(sourceId);
            
            // Reload sources
            await this.loadSources();

            this.hideLoading();
            this.showSuccess('Source deleted successfully');
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to delete source', error);
        }
    }

    /**
     * Test source
     * @private
     * @param {string} sourceId - Source ID
     */
    async _testSource(sourceId) {
        this.showLoading();

        try {
            const result = await this.apiClient.testSource(sourceId);
            
            this.hideLoading();
            if (result.success) {
                this.showSuccess(`Source test successful: ${result.message || 'Connection established'}`);
            } else {
                this.showError(`Source test failed: ${result.message || 'Unknown error'}`);
            }
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to test source', error);
        }
    }

    /**
     * Sync source
     * @private
     * @param {string} sourceId - Source ID
     */
    async _syncSource(sourceId) {
        this.showLoading();

        try {
            const result = await this.apiClient.syncSource(sourceId);
            
            this.hideLoading();
            if (result.success) {
                this.showSuccess(`Source sync started: ${result.message || 'Syncing...'}`);
                // Refresh sources to update article count
                await this.loadSources();
            } else {
                this.showError(`Source sync failed: ${result.message || 'Unknown error'}`);
            }
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to sync source', error);
        }
    }

    /**
     * Toggle source status
     * @private
     * @param {string} sourceId - Source ID
     */
    async _toggleSourceStatus(sourceId) {
        const source = this.sources.find(s => s.id === sourceId);
        if (!source) return;

        const newStatus = !source.enabled;

        this.showLoading();

        try {
            await this.apiClient.updateSource(sourceId, { enabled: newStatus });
            
            // Update local data
            source.enabled = newStatus;
            
            // Refresh table
            if (this.sourcesTableManager) {
                this.sourcesTableManager.render();
            }

            this.hideLoading();
            this.showSuccess(`Source ${newStatus ? 'enabled' : 'disabled'} successfully`);
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to toggle source status', error);
        }
    }

    /**
     * Show add group modal
     * @private
     */
    _showAddGroupModal() {
        const modal = new bootstrap.Modal(document.getElementById('addGroupModal'));
        modal.show();

        // Reset form
        const form = document.getElementById('addGroupForm');
        if (form) {
            form.reset();
        }
    }

    /**
     * Save group
     * @private
     */
    async _saveGroup() {
        const form = document.getElementById('addGroupForm');
        if (!form) return;

        // Validate form
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const formData = new FormData(form);
        const groupData = Object.fromEntries(formData.entries());

        // Process boolean fields
        groupData.enabled = formData.get('enabled') === 'on';

        // Process numeric fields
        groupData.priority = parseInt(groupData.priority) || 2;
        groupData.rate_limit = parseInt(groupData.rate_limit) || 300;

        this.showLoading();

        try {
            // Note: The API might not have a dedicated groups endpoint
            // For now, we'll use the source categories endpoint
            const newGroup = await this.apiClient.createSource(groupData);
            
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('addGroupModal'));
            modal.hide();

            // Reload groups
            await this.loadGroups();

            this.hideLoading();
            this.showSuccess('Group added successfully');
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to add group', error);
        }
    }

    /**
     * Perform discover search
     * @private
     */
    async _performDiscoverSearch() {
        const form = document.getElementById('discoverForm');
        if (!form) return;

        const formData = new FormData(form);
        const searchData = Object.fromEntries(formData.entries());

        this.showLoading();

        try {
            const results = await this.apiClient.discoverSources({
                query: searchData.discoverQuery,
                category: searchData.discoverCategory,
                language: searchData.discoverLanguage
            });

            if (this.discoverTableManager) {
                this.discoverTableManager.loadData(results || []);
            }

            this.hideLoading();
        } catch (error) {
            this.hideLoading();
            this.showError('Discover search failed', error);
        }
    }

    /**
     * Export sources
     * @private
     */
    async _exportSources() {
        this.showLoading();

        try {
            const response = await this.apiClient.exportArticles({
                format: 'csv',
                type: 'sources'
            });

            if (response) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `sources-export.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            }

            this.hideLoading();
            this.showSuccess('Sources export started. File will download automatically.');
        } catch (error) {
            this.hideLoading();
            this.showError('Export failed', error);
        }
    }

    /**
     * Handle confirm action
     * @private
     */
    _handleConfirmAction() {
        const confirmBtn = document.getElementById('confirmActionBtn');
        if (!confirmBtn) return;

        const action = confirmBtn.dataset.action;
        const sourceId = confirmBtn.dataset.sourceId;
        const groupId = confirmBtn.dataset.groupId;

        // Close confirmation modal
        const confirmModal = bootstrap.Modal.getInstance(document.getElementById('confirmModal'));
        confirmModal.hide();

        switch (action) {
            case 'delete-source':
                this._deleteSource(sourceId);
                break;
            case 'delete-group':
                this._deleteGroup(groupId);
                break;
        }
    }

    /**
     * Delete group
     * @private
     * @param {string} groupId - Group ID
     */
    async _deleteGroup(groupId) {
        this.showLoading();

        try {
            // Note: The API might not have a dedicated groups endpoint
            await this.apiClient.deleteSource(groupId);
            
            // Reload groups
            await this.loadGroups();

            this.hideLoading();
            this.showSuccess('Group deleted successfully');
        } catch (error) {
            this.hideLoading();
            this.showError('Failed to delete group', error);
        }
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

        // Update theme toggle button
        const themeToggle = document.getElementById('themeToggle');
        if (themeToggle) {
            const icon = themeToggle.querySelector('i');
            if (theme === 'dark') {
                icon.className = 'fas fa-sun';
                themeToggle.setAttribute('aria-label', 'Switch to light mode');
            } else {
                icon.className = 'fas fa-moon';
                themeToggle.setAttribute('aria-label', 'Switch to dark mode');
            }
        }

        this.showSuccess(`Theme set to ${theme}`);
    }

    /**
     * Open settings modal
     * @private
     */
    _openSettingsModal() {
        // For now, just show a simple settings modal
        // This can be expanded later
        const modalId = 'settingsModal';
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
                                <form id="settingsForm">
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
                                </form>
                            </div>
                            <div class="modal-footer">
                                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                            </div>
                        </div>
                    </div>
                `
            });
            document.body.appendChild(modal);

            // Setup event listeners
            const themeBtns = modal.querySelectorAll('[data-action="set-theme"]');
            themeBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    this._setTheme(btn.dataset.theme);
                });
            });
        }

        // Show modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
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
     * Destroy the source manager
     */
    destroy() {
        if (this.sourcesTableManager) {
            this.sourcesTableManager.destroy();
        }
        if (this.groupsTableManager) {
            this.groupsTableManager.destroy();
        }
        if (this.discoverTableManager) {
            this.discoverTableManager.destroy();
        }
    }
}

/**
 * Create a new source manager instance
 * @param {Object} options - Configuration options
 * @returns {SourceManager} Source manager instance
 */
function createSourceManager(options = {}) {
    return new SourceManager(options);
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        if (document.querySelector('#sourcesTable') || 
            document.querySelector('#groupsTable') ||
            document.querySelector('.source-manager')) {
            createSourceManager();
        }
    });
} else {
    // DOM already loaded
    if (document.querySelector('#sourcesTable') || 
        document.querySelector('#groupsTable') ||
        document.querySelector('.source-manager')) {
        createSourceManager();
    }
}

// Export for use in modules
export { SourceManager, createSourceManager };
