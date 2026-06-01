/**
 * Instrument Browser Component for Pillar 5 - Financial Intelligence
 * 
 * Provides browsing and filtering of financial instruments across all asset classes
 * (stocks, ETFs, indices, commodities, forex, crypto).
 * 
 * Features:
 * - Fetch instruments from /api/v1/financial/instruments endpoints
 * - Filter by type, exchange, sector, or search query
 * - Display instrument details including fundamentals and metrics
 * - Sort by various fields (symbol, name, price, volume, etc.)
 * - Pagination for large datasets
 */

class InstrumentBrowser {
    /**
     * Create a new Instrument Browser instance
     * @param {Object} options - Configuration options
     * @param {string|HTMLElement} options.container - Container element or selector
     * @param {Object} options.apiClient - API client instance
     */
    constructor(options = {}) {
        this.container = typeof options.container === 'string' 
            ? document.querySelector(options.container) 
            : options.container;
        this.apiClient = options.apiClient || new APIClient({ baseUrl: '/api/v1' });
        
        // State
        this.instruments = [];
        this.exchanges = [];
        this.filteredInstruments = [];
        this.selectedInstrument = null;
        this.selectedTypes = [];
        this.selectedExchange = '';
        this.searchQuery = '';
        this.sortField = 'symbol';
        this.sortDirection = 'asc';
        this.currentPage = 1;
        this.itemsPerPage = 20;
        
        // Asset type colors
        this.typeColors = {
            stock: '#3b82f6',
            etf: '#10b981',
            index: '#8b5cf6',
            commodity: '#f59e0b',
            forex: '#06b6d4',
            crypto: '#ec4899'
        };
        
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
            console.error('InstrumentBrowser: Container element not found');
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
            <div class="instrument-browser">
                <div class="instrument-browser-header">
                    <h2>Financial Instruments Browser</h2>
                    <div class="instrument-browser-controls">
                        <div class="search-box">
                            <input type="text" placeholder="Search instruments..." class="instrument-search">
                            <button class="btn-search">🔍</button>
                        </div>
                        <select class="type-filter" multiple>
                            <option value="stock" selected>Stocks</option>
                            <option value="etf" selected>ETFs</option>
                            <option value="index" selected>Indices</option>
                            <option value="commodity" selected>Commodities</option>
                            <option value="forex" selected>Forex</option>
                            <option value="crypto" selected>Crypto</option>
                        </select>
                        <select class="exchange-filter">
                            <option value="">All Exchanges</option>
                        </select>
                        <select class="sort-field">
                            <option value="symbol">Symbol</option>
                            <option value="name">Name</option>
                            <option value="price">Price</option>
                            <option value="volume">Volume</option>
                            <option value="market_cap">Market Cap</option>
                        </select>
                        <select class="sort-direction">
                            <option value="asc">Ascending</option>
                            <option value="desc">Descending</option>
                        </select>
                    </div>
                </div>
                
                <div class="instrument-browser-layout">
                    <div class="instrument-types-sidebar">
                        <h3>Asset Types</h3>
                        <ul class="type-list">
                            ${Object.entries(this.typeColors).map(([type, color]) => `
                                <li class="type-item" data-type="${type}">
                                    <span class="type-color" style="background-color: ${color}"></span>
                                    <span class="type-name">${type.charAt(0).toUpperCase() + type.slice(1)}</span>
                                    <span class="type-count">(0)</span>
                                </li>
                            `).join('')}
                        </ul>
                        
                        <div class="quick-stats">
                            <h4>Quick Stats</h4>
                            <div class="stat-row">
                                <span>Total:</span>
                                <span class="stat-value total-instruments">0</span>
                            </div>
                            <div class="stat-row">
                                <span>Stocks:</span>
                                <span class="stat-value stock-count">0</span>
                            </div>
                            <div class="stat-row">
                                <span>ETFs:</span>
                                <span class="stat-value etf-count">0</span>
                            </div>
                            <div class="stat-row">
                                <span>Indices:</span>
                                <span class="stat-value index-count">0</span>
                            </div>
                            <div class="stat-row">
                                <span>Commodities:</span>
                                <span class="stat-value commodity-count">0</span>
                            </div>
                            <div class="stat-row">
                                <span>Forex:</span>
                                <span class="stat-value forex-count">0</span>
                            </div>
                            <div class="stat-row">
                                <span>Crypto:</span>
                                <span class="stat-value crypto-count">0</span>
                            </div>
                        </div>
                    </div>
                    
                    <div class="instrument-main-content">
                        <div class="instrument-list-container">
                            <h3>Instruments <span class="instrument-count">(0)</span></h3>
                            <div class="instrument-list">
                                <table class="instrument-table">
                                    <thead>
                                        <tr>
                                            <th data-sort="symbol">Symbol</th>
                                            <th data-sort="name">Name</th>
                                            <th data-sort="type">Type</th>
                                            <th data-sort="exchange">Exchange</th>
                                            <th data-sort="price">Price</th>
                                            <th data-sort="volume">Volume</th>
                                            <th data-sort="market_cap">Market Cap</th>
                                            <th>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody class="instrument-table-body">
                                    </tbody>
                                </table>
                            </div>
                            
                            <div class="pagination-controls">
                                <button class="btn-first-page">⏮</button>
                                <button class="btn-prev-page">◀</button>
                                <span class="page-info">Page <span class="current-page">1</span> of <span class="total-pages">1</span></span>
                                <button class="btn-next-page">▶</button>
                                <button class="btn-last-page">⏭</button>
                                <select class="items-per-page">
                                    <option value="10">10 per page</option>
                                    <option value="20" selected>20 per page</option>
                                    <option value="50">50 per page</option>
                                    <option value="100">100 per page</option>
                                </select>
                            </div>
                        </div>
                        
                        <div class="instrument-details-panel">
                            <h3>Instrument Details</h3>
                            <div class="instrument-details">
                                <p><strong>Symbol:</strong> <span class="detail-symbol">-</span></p>
                                <p><strong>Name:</strong> <span class="detail-name">-</span></p>
                                <p><strong>Type:</strong> <span class="detail-type">-</span></p>
                                <p><strong>Exchange:</strong> <span class="detail-exchange">-</span></p>
                                <p><strong>Sector:</strong> <span class="detail-sector">-</span></p>
                                <p><strong>Industry:</strong> <span class="detail-industry">-</span></p>
                                
                                <div class="detail-section">
                                    <h4>Fundamentals</h4>
                                    <div class="fundamentals-grid">
                                        <div class="fundamental-item">
                                            <span class="fundamental-label">Price:</span>
                                            <span class="fundamental-value detail-price">-</span>
                                        </div>
                                        <div class="fundamental-item">
                                            <span class="fundamental-label">Volume:</span>
                                            <span class="fundamental-value detail-volume">-</span>
                                        </div>
                                        <div class="fundamental-item">
                                            <span class="fundamental-label">Market Cap:</span>
                                            <span class="fundamental-value detail-market-cap">-</span>
                                        </div>
                                        <div class="fundamental-item">
                                            <span class="fundamental-label">P/E Ratio:</span>
                                            <span class="fundamental-value detail-pe-ratio">-</span>
                                        </div>
                                        <div class="fundamental-item">
                                            <span class="fundamental-label">Dividend Yield:</span>
                                            <span class="fundamental-value detail-dividend-yield">-</span>
                                        </div>
                                        <div class="fundamental-item">
                                            <span class="fundamental-label">52 Week High:</span>
                                            <span class="fundamental-value detail-52week-high">-</span>
                                        </div>
                                    </div>
                                </div>
                                
                                <div class="detail-section">
                                    <h4>Description</h4>
                                    <p class="detail-description">No description available</p>
                                </div>
                                
                                <div class="detail-section">
                                    <h4>Keywords</h4>
                                    <div class="detail-keywords"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="instrument-browser-footer">
                    <button class="btn-export-instruments" disabled>Export List</button>
                    <button class="btn-refresh-instruments">Refresh</button>
                </div>
            </div>
        `;
        
        // Cache UI elements
        this.ui.searchInput = this.container.querySelector('.instrument-search');
        this.ui.typeFilter = this.container.querySelector('.type-filter');
        this.ui.exchangeFilter = this.container.querySelector('.exchange-filter');
        this.ui.sortField = this.container.querySelector('.sort-field');
        this.ui.sortDirection = this.container.querySelector('.sort-direction');
        this.ui.typeItems = this.container.querySelectorAll('.type-item');
        this.ui.tableBody = this.container.querySelector('.instrument-table-body');
        this.ui.instrumentCount = this.container.querySelector('.instrument-count');
        this.ui.totalInstruments = this.container.querySelector('.total-instruments');
        this.ui.stockCount = this.container.querySelector('.stock-count');
        this.ui.etfCount = this.container.querySelector('.etf-count');
        this.ui.indexCount = this.container.querySelector('.index-count');
        this.ui.commodityCount = this.container.querySelector('.commodity-count');
        this.ui.forexCount = this.container.querySelector('.forex-count');
        this.ui.cryptoCount = this.container.querySelector('.crypto-count');
        this.ui.currentPage = this.container.querySelector('.current-page');
        this.ui.totalPages = this.container.querySelector('.total-pages');
        this.ui.itemsPerPageSelect = this.container.querySelector('.items-per-page');
        this.ui.exportBtn = this.container.querySelector('.btn-export-instruments');
        this.ui.refreshBtn = this.container.querySelector('.btn-refresh-instruments');
        this.ui.firstPageBtn = this.container.querySelector('.btn-first-page');
        this.ui.prevPageBtn = this.container.querySelector('.btn-prev-page');
        this.ui.nextPageBtn = this.container.querySelector('.btn-next-page');
        this.ui.lastPageBtn = this.container.querySelector('.btn-last-page');
        
        // Detail elements
        this.ui.detailSymbol = this.container.querySelector('.detail-symbol');
        this.ui.detailName = this.container.querySelector('.detail-name');
        this.ui.detailType = this.container.querySelector('.detail-type');
        this.ui.detailExchange = this.container.querySelector('.detail-exchange');
        this.ui.detailSector = this.container.querySelector('.detail-sector');
        this.ui.detailIndustry = this.container.querySelector('.detail-industry');
        this.ui.detailPrice = this.container.querySelector('.detail-price');
        this.ui.detailVolume = this.container.querySelector('.detail-volume');
        this.ui.detailMarketCap = this.container.querySelector('.detail-market-cap');
        this.ui.detailPeRatio = this.container.querySelector('.detail-pe-ratio');
        this.ui.detailDividendYield = this.container.querySelector('.detail-dividend-yield');
        this.ui.detail52WeekHigh = this.container.querySelector('.detail-52week-high');
        this.ui.detailDescription = this.container.querySelector('.detail-description');
        this.ui.detailKeywords = this.container.querySelector('.detail-keywords');
    }
    
    /**
     * Bind event listeners
     * @private
     */
    _bindEvents() {
        // Search
        this.ui.searchInput.addEventListener('input', (e) => {
            this.searchQuery = e.target.value.toLowerCase();
            this.currentPage = 1;
            this._filterAndDisplayInstruments();
        });
        
        // Type filter
        this.ui.typeFilter.addEventListener('change', (e) => {
            const selectedOptions = Array.from(e.target.selectedOptions).map(o => o.value);
            this.selectedTypes = selectedOptions.length > 0 ? selectedOptions : Object.keys(this.typeColors);
            this.currentPage = 1;
            this._filterAndDisplayInstruments();
        });
        
        // Exchange filter
        this.ui.exchangeFilter.addEventListener('change', (e) => {
            this.selectedExchange = e.target.value;
            this.currentPage = 1;
            this._filterAndDisplayInstruments();
        });
        
        // Sort field
        this.ui.sortField.addEventListener('change', (e) => {
            this.sortField = e.target.value;
            this._filterAndDisplayInstruments();
        });
        
        // Sort direction
        this.ui.sortDirection.addEventListener('change', (e) => {
            this.sortDirection = e.target.value;
            this._filterAndDisplayInstruments();
        });
        
        // Items per page
        this.ui.itemsPerPageSelect.addEventListener('change', (e) => {
            this.itemsPerPage = parseInt(e.target.value);
            this.currentPage = 1;
            this._filterAndDisplayInstruments();
        });
        
        // Pagination buttons
        this.ui.firstPageBtn.addEventListener('click', () => {
            this.currentPage = 1;
            this._filterAndDisplayInstruments();
        });
        
        this.ui.prevPageBtn.addEventListener('click', () => {
            if (this.currentPage > 1) {
                this.currentPage--;
                this._filterAndDisplayInstruments();
            }
        });
        
        this.ui.nextPageBtn.addEventListener('click', () => {
            const totalPages = Math.ceil(this.filteredInstruments.length / this.itemsPerPage);
            if (this.currentPage < totalPages) {
                this.currentPage++;
                this._filterAndDisplayInstruments();
            }
        });
        
        this.ui.lastPageBtn.addEventListener('click', () => {
            const totalPages = Math.ceil(this.filteredInstruments.length / this.itemsPerPage);
            this.currentPage = totalPages;
            this._filterAndDisplayInstruments();
        });
        
        // Type sidebar items
        this.ui.typeItems.forEach(item => {
            item.addEventListener('click', () => {
                const type = item.dataset.type;
                const isSelected = this.selectedTypes.includes(type);
                
                if (isSelected) {
                    this.selectedTypes = this.selectedTypes.filter(t => t !== type);
                    item.classList.remove('active');
                } else {
                    this.selectedTypes.push(type);
                    item.classList.add('active');
                }
                
                if (this.selectedTypes.length === 0) {
                    this.selectedTypes = Object.keys(this.typeColors);
                    this.ui.typeItems.forEach(i => i.classList.add('active'));
                }
                
                this.currentPage = 1;
                this._filterAndDisplayInstruments();
            });
        });
        
        // Refresh button
        this.ui.refreshBtn.addEventListener('click', () => {
            this._loadInitialData();
        });
        
        // Export button
        this.ui.exportBtn.addEventListener('click', () => {
            this._exportInstruments();
        });
        
        // Table header sorting
        this.ui.tableBody.parentElement.querySelectorAll('th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const field = th.dataset.sort;
                if (this.sortField === field) {
                    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
                } else {
                    this.sortField = field;
                    this.sortDirection = 'asc';
                }
                this.ui.sortField.value = this.sortField;
                this.ui.sortDirection.value = this.sortDirection;
                this._filterAndDisplayInstruments();
            });
        });
    }
    
    /**
     * Load initial data (instruments and exchanges)
     * @private
     */
    async _loadInitialData() {
        try {
            // Load instruments
            const instrumentsResponse = await this.apiClient.get('/financial/instruments');
            if (instrumentsResponse.success) {
                this.instruments = instrumentsResponse.data || [];
                this._populateExchangeFilter();
                this._updateTypeCounts();
                this._updateQuickStats();
                this._filterAndDisplayInstruments();
                this.ui.exportBtn.disabled = false;
            }
            
            // Load exchanges
            const exchangesResponse = await this.apiClient.get('/financial/exchanges');
            if (exchangesResponse.success) {
                this.exchanges = exchangesResponse.data || [];
                this._populateExchangeFilter();
            }
        } catch (error) {
            console.error('InstrumentBrowser: Failed to load initial data:', error);
            this._showError('Failed to load instruments data. Please try again.');
        }
    }
    
    /**
     * Populate exchange dropdown
     * @private
     */
    _populateExchangeFilter() {
        const select = this.ui.exchangeFilter;
        select.innerHTML = '<option value="">All Exchanges</option>';
        
        // Get unique exchanges from instruments
        const exchangeSet = new Set();
        this.instruments.forEach(instrument => {
            if (instrument.exchange_id || instrument.exchange) {
                exchangeSet.add(instrument.exchange_id || instrument.exchange);
            }
        });
        
        // Also add from exchanges list
        this.exchanges.forEach(exchange => {
            exchangeSet.add(exchange.id || exchange.code);
        });
        
        Array.from(exchangeSet).sort().forEach(exchangeId => {
            const exchange = this.exchanges.find(e => e.id === exchangeId || e.code === exchangeId);
            const option = document.createElement('option');
            option.value = exchangeId;
            option.textContent = exchange ? `${exchange.code} - ${exchange.name}` : exchangeId;
            select.appendChild(option);
        });
    }
    
    /**
     * Update type counts in sidebar
     * @private
     */
    _updateTypeCounts() {
        const typeCounts = {};
        Object.keys(this.typeColors).forEach(type => {
            typeCounts[type] = 0;
        });
        
        this.instruments.forEach(instrument => {
            const type = instrument.type || 'stock';
            if (typeCounts[type] !== undefined) {
                typeCounts[type]++;
            }
        });
        
        Object.entries(typeCounts).forEach(([type, count]) => {
            const item = this.container.querySelector(`.type-item[data-type="${type}"] .type-count`);
            if (item) {
                item.textContent = `(${count})`;
            }
        });
    }
    
    /**
     * Update quick stats
     * @private
     */
    _updateQuickStats() {
        const typeCounts = {};
        Object.keys(this.typeColors).forEach(type => {
            typeCounts[type] = 0;
        });
        
        this.instruments.forEach(instrument => {
            const type = instrument.type || 'stock';
            if (typeCounts[type] !== undefined) {
                typeCounts[type]++;
            }
        });
        
        this.ui.totalInstruments.textContent = this.instruments.length;
        this.ui.stockCount.textContent = typeCounts.stock || 0;
        this.ui.etfCount.textContent = typeCounts.etf || 0;
        this.ui.indexCount.textContent = typeCounts.index || 0;
        this.ui.commodityCount.textContent = typeCounts.commodity || 0;
        this.ui.forexCount.textContent = typeCounts.forex || 0;
        this.ui.cryptoCount.textContent = typeCounts.crypto || 0;
    }
    
    /**
     * Filter and display instruments based on current selections
     * @private
     */
    _filterAndDisplayInstruments() {
        let filtered = this.instruments;
        
        // Filter by type
        if (this.selectedTypes.length > 0) {
            filtered = filtered.filter(i => 
                this.selectedTypes.includes(i.type || 'stock')
            );
        }
        
        // Filter by exchange
        if (this.selectedExchange) {
            filtered = filtered.filter(i => 
                (i.exchange_id === this.selectedExchange) ||
                (i.exchange === this.selectedExchange)
            );
        }
        
        // Filter by search query
        if (this.searchQuery) {
            filtered = filtered.filter(i => 
                (i.symbol && i.symbol.toLowerCase().includes(this.searchQuery)) ||
                (i.name && i.name.toLowerCase().includes(this.searchQuery)) ||
                (i.description && i.description.toLowerCase().includes(this.searchQuery)) ||
                (i.sector && i.sector.toLowerCase().includes(this.searchQuery)) ||
                (i.industry && i.industry.toLowerCase().includes(this.searchQuery))
            );
        }
        
        // Sort
        filtered = this._sortInstruments(filtered);
        
        this.filteredInstruments = filtered;
        this._displayInstruments(filtered);
        this._updatePagination();
        this.ui.instrumentCount.textContent = `(${filtered.length})`;
    }
    
    /**
     * Sort instruments
     * @private
     */
    _sortInstruments(instruments) {
        const field = this.sortField;
        const direction = this.sortDirection;
        
        return [...instruments].sort((a, b) => {
            let aVal = this._getSortValue(a, field);
            let bVal = this._getSortValue(b, field);
            
            // Handle numeric comparison
            if (typeof aVal === 'number' && typeof bVal === 'number') {
                return direction === 'asc' ? aVal - bVal : bVal - aVal;
            }
            
            // Handle string comparison
            aVal = String(aVal || '').toLowerCase();
            bVal = String(bVal || '').toLowerCase();
            
            if (aVal < bVal) return direction === 'asc' ? -1 : 1;
            if (aVal > bVal) return direction === 'asc' ? 1 : -1;
            return 0;
        });
    }
    
    /**
     * Get sort value for a field
     * @private
     */
    _getSortValue(instrument, field) {
        const fieldMap = {
            symbol: () => instrument.symbol,
            name: () => instrument.name,
            type: () => instrument.type,
            exchange: () => instrument.exchange || instrument.exchange_id,
            price: () => instrument.price || instrument.last_price || 0,
            volume: () => instrument.volume || 0,
            market_cap: () => instrument.market_cap || 0
        };
        
        const getter = fieldMap[field] || (() => instrument[field]);
        return getter();
    }
    
    /**
     * Display instruments in table
     * @private
     */
    _displayInstruments(instruments) {
        this.ui.tableBody.innerHTML = '';
        
        if (instruments.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="8" class="no-instruments">No instruments found matching your criteria.</td>';
            this.ui.tableBody.appendChild(row);
            return;
        }
        
        // Pagination
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const paginatedInstruments = instruments.slice(startIndex, endIndex);
        
        paginatedInstruments.forEach(instrument => {
            const row = document.createElement('tr');
            row.dataset.instrumentId = instrument.id || instrument.instrument_id;
            
            const type = instrument.type || 'stock';
            const color = this.typeColors[type] || '#666';
            
            row.innerHTML = `
                <td class="col-symbol">${instrument.symbol || 'N/A'}</td>
                <td class="col-name">${instrument.name || 'N/A'}</td>
                <td class="col-type">
                    <span class="type-badge" style="background-color: ${color}">
                        ${type.toUpperCase()}
                    </span>
                </td>
                <td class="col-exchange">${instrument.exchange || instrument.exchange_id || 'N/A'}</td>
                <td class="col-price">${instrument.price ? instrument.price.toFixed(2) : 'N/A'}</td>
                <td class="col-volume">${instrument.volume ? this._formatNumber(instrument.volume) : 'N/A'}</td>
                <td class="col-market-cap">${instrument.market_cap ? this._formatMarketCap(instrument.market_cap) : 'N/A'}</td>
                <td class="col-actions">
                    <button class="btn-view-details" data-instrument-id="${instrument.id || instrument.instrument_id}">
                        View
                    </button>
                </td>
            `;
            
            this.ui.tableBody.appendChild(row);
        });
        
        // Add event listeners to view buttons
        this.ui.tableBody.querySelectorAll('.btn-view-details').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const instrumentId = e.target.dataset.instrumentId;
                this._loadInstrumentDetails(instrumentId);
            });
        });
        
        // Add click handler to rows
        this.ui.tableBody.querySelectorAll('tr').forEach(row => {
            row.addEventListener('click', (e) => {
                // Don't trigger if clicking on button
                if (e.target.tagName === 'BUTTON') return;
                
                const instrumentId = row.dataset.instrumentId;
                this._loadInstrumentDetails(instrumentId);
            });
        });
    }
    
    /**
     * Update pagination controls
     * @private
     */
    _updatePagination() {
        const totalPages = Math.ceil(this.filteredInstruments.length / this.itemsPerPage);
        
        this.ui.currentPage.textContent = this.currentPage;
        this.ui.totalPages.textContent = totalPages || 1;
        
        this.ui.firstPageBtn.disabled = this.currentPage === 1;
        this.ui.prevPageBtn.disabled = this.currentPage === 1;
        this.ui.nextPageBtn.disabled = this.currentPage >= totalPages;
        this.ui.lastPageBtn.disabled = this.currentPage >= totalPages;
    }
    
    /**
     * Load detailed data for a specific instrument
     * @private
     */
    async _loadInstrumentDetails(instrumentId) {
        try {
            const response = await this.apiClient.get(`/financial/instruments/${instrumentId}`);
            if (response.success) {
                const instrument = response.data;
                this.selectedInstrument = instrument;
                this._displayInstrumentDetails(instrument);
            }
        } catch (error) {
            console.error('InstrumentBrowser: Failed to load instrument details:', error);
            this._showError('Failed to load instrument details.');
        }
    }
    
    /**
     * Display instrument details
     * @private
     */
    _displayInstrumentDetails(instrument) {
        this.ui.detailSymbol.textContent = instrument.symbol || 'N/A';
        this.ui.detailName.textContent = instrument.name || 'N/A';
        
        const type = instrument.type || 'stock';
        const color = this.typeColors[type] || '#666';
        this.ui.detailType.innerHTML = `
            <span class="type-badge" style="background-color: ${color}">
                ${type.toUpperCase()}
            </span>
        `;
        
        this.ui.detailExchange.textContent = instrument.exchange || instrument.exchange_id || 'N/A';
        this.ui.detailSector.textContent = instrument.sector || 'N/A';
        this.ui.detailIndustry.textContent = instrument.industry || 'N/A';
        
        // Fundamentals
        this.ui.detailPrice.textContent = instrument.price ? `$${instrument.price.toFixed(2)}` : 'N/A';
        this.ui.detailVolume.textContent = instrument.volume ? this._formatNumber(instrument.volume) : 'N/A';
        this.ui.detailMarketCap.textContent = instrument.market_cap ? this._formatMarketCap(instrument.market_cap) : 'N/A';
        this.ui.detailPeRatio.textContent = instrument.pe_ratio ? instrument.pe_ratio.toFixed(2) : 'N/A';
        this.ui.detailDividendYield.textContent = instrument.dividend_yield ? `${(instrument.dividend_yield * 100).toFixed(2)}%` : 'N/A';
        this.ui.detail52WeekHigh.textContent = instrument.high_52w ? `$${instrument.high_52w.toFixed(2)}` : 'N/A';
        
        // Description
        this.ui.detailDescription.textContent = instrument.description || 'No description available';
        
        // Keywords
        this.ui.detailKeywords.innerHTML = '';
        if (instrument.keywords && instrument.keywords.length > 0) {
            instrument.keywords.forEach(keyword => {
                const tag = document.createElement('span');
                tag.className = 'keyword-tag';
                tag.textContent = keyword;
                this.ui.detailKeywords.appendChild(tag);
            });
        } else {
            this.ui.detailKeywords.innerHTML = '<p>No keywords available</p>';
        }
    }
    
    /**
     * Format large numbers
     * @private
     */
    _formatNumber(num) {
        if (num >= 1e9) {
            return (num / 1e9).toFixed(2) + 'B';
        }
        if (num >= 1e6) {
            return (num / 1e6).toFixed(2) + 'M';
        }
        if (num >= 1e3) {
            return (num / 1e3).toFixed(2) + 'K';
        }
        return num.toString();
    }
    
    /**
     * Format market cap
     * @private
     */
    _formatMarketCap(num) {
        if (num >= 1e12) {
            return `$${(num / 1e12).toFixed(2)}T`;
        }
        if (num >= 1e9) {
            return `$${(num / 1e9).toFixed(2)}B`;
        }
        if (num >= 1e6) {
            return `$${(num / 1e6).toFixed(2)}M`;
        }
        return `$${num.toFixed(2)}`;
    }
    
    /**
     * Export instruments list
     * @private
     */
    _exportInstruments() {
        if (this.filteredInstruments.length === 0) {
            this._showError('No instruments to export.');
            return;
        }
        
        const data = {
            instruments: this.filteredInstruments,
            filters: {
                types: this.selectedTypes,
                exchange: this.selectedExchange,
                search: this.searchQuery
            },
            sort: {
                field: this.sortField,
                direction: this.sortDirection
            },
            timestamp: new Date().toISOString(),
            source: 'Open-Omniscience Pillar 5'
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `instruments_export_${new Date().toISOString().split('T')[0]}.json`;
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
        const errorElement = this.container.querySelector('.instrument-error');
        if (!errorElement) {
            const errorDiv = document.createElement('div');
            errorDiv.className = 'instrument-error';
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
        this.instruments = [];
        this.exchanges = [];
        this.filteredInstruments = [];
    }
}

// Auto-initialize if data attributes are present
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        const containers = document.querySelectorAll('[data-instrument-browser]');
        containers.forEach(container => {
            new InstrumentBrowser({ container });
        });
    });
}
