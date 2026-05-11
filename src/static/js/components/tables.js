/**
 * Tables Component for Open-Omniscience
 * Handles table sorting, pagination, filtering, row expansion, and action menus
 */

class TableManager {
    /**
     * Create a new table manager
     * @param {HTMLTableElement|string} table - Table element or selector
     * @param {Object} options - Configuration options
     */
    constructor(table, options = {}) {
        this.table = typeof table === 'string' ? document.querySelector(table) : table;
        this.options = {
            sortable: true,
            paginate: true,
            filterable: true,
            pageSize: 20,
            pageSizeOptions: [10, 20, 50, 100],
            currentPage: 1,
            expandableRows: false,
            multiSelect: false,
            rowSelection: false,
            showHeader: true,
            showFooter: false,
            loadingIndicator: true,
            emptyMessage: 'No data available',
            ...options
        };

        this.data = [];
        this.filteredData = [];
        this.sortedData = [];
        this.selectedRows = new Set();
        this.expandedRows = new Set();
        this.sortColumn = null;
        this.sortDirection = 'asc';
        this.filters = {};
        this._initialize();
    }

    /**
     * Initialize the table
     * @private
     */
    _initialize() {
        if (!this.table) {
            console.warn('Table element not found');
            return;
        }

        this._setupStructure();
        this._setupEventListeners();
        this._setupSorting();
        this._setupPagination();
        this._setupFiltering();
        this._setupRowSelection();
        this._setupRowExpansion();
    }

    /**
     * Setup table structure
     * @private
     */
    _setupStructure() {
        this.thead = this.table.querySelector('thead');
        this.tbody = this.table.querySelector('tbody');
        this.tfoot = this.table.querySelector('tfoot');

        // Create wrapper if it doesn't exist
        if (!this.table.parentElement.classList.contains('table-wrapper')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'table-wrapper';
            this.table.parentNode.insertBefore(wrapper, this.table);
            wrapper.appendChild(this.table);
            this.wrapper = wrapper;
        } else {
            this.wrapper = this.table.parentElement;
        }

        // Add table classes
        this.table.classList.add('table', 'table-hover');

        // Create loading indicator
        if (this.options.loadingIndicator) {
            this.loadingIndicator = document.createElement('div');
            this.loadingIndicator.className = 'table-loading-overlay d-none';
            this.loadingIndicator.innerHTML = `
                <div class="d-flex align-items-center justify-content-center h-100">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            `;
            this.wrapper.appendChild(this.loadingIndicator);
        }

        // Create empty state
        this.emptyState = document.createElement('div');
        this.emptyState.className = 'table-empty-state d-none text-center py-5';
        this.emptyState.innerHTML = `
            <div class="text-muted">
                <i class="fas fa-inbox fa-3x mb-3"></i>
                <h5>${this.options.emptyMessage}</h5>
            </div>
        `;
        this.wrapper.appendChild(this.emptyState);

        // Create pagination controls
        if (this.options.paginate) {
            this.pagination = document.createElement('div');
            this.pagination.className = 'table-pagination d-flex justify-content-between align-items-center mt-3';
            this.pagination.innerHTML = `
                <div class="d-flex align-items-center">
                    <span class="text-muted me-2">Show</span>
                    <select class="form-select form-select-sm page-size-select" style="width: 80px;">
                        ${this.options.pageSizeOptions.map(size => 
                            `<option value="${size}" ${size === this.options.pageSize ? 'selected' : ''}>${size}</option>`
                        ).join('')}
                    </select>
                    <span class="text-muted ms-2">entries</span>
                </div>
                <div class="d-flex align-items-center">
                    <span class="page-info text-muted me-3"></span>
                    <nav aria-label="Table pagination">
                        <ul class="pagination pagination-sm mb-0">
                            <li class="page-item disabled">
                                <button class="page-link" data-action="first" aria-label="First">
                                    <i class="fas fa-angle-double-left"></i>
                                </button>
                            </li>
                            <li class="page-item disabled">
                                <button class="page-link" data-action="prev" aria-label="Previous">
                                    <i class="fas fa-angle-left"></i>
                                </button>
                            </li>
                            <li class="page-item active">
                                <button class="page-link" data-action="page" data-page="1">1</button>
                            </li>
                            <li class="page-item">
                                <button class="page-link" data-action="next" aria-label="Next">
                                    <i class="fas fa-angle-right"></i>
                                </button>
                            </li>
                            <li class="page-item">
                                <button class="page-link" data-action="last" aria-label="Last">
                                    <i class="fas fa-angle-double-right"></i>
                                </button>
                            </li>
                        </ul>
                    </nav>
                </div>
            `;
            this.wrapper.appendChild(this.pagination);
        }

        // Create filter controls
        if (this.options.filterable) {
            this.filterControls = document.createElement('div');
            this.filterControls.className = 'table-filters mb-3';
            this.filterControls.innerHTML = `
                <div class="d-flex flex-wrap gap-2">
                    <div class="flex-grow-1">
                        <input type="text" class="form-control form-control-sm" 
                               placeholder="Search..." 
                               data-filter="global">
                    </div>
                    <button class="btn btn-sm btn-outline-secondary" data-action="clear-filters">
                        <i class="fas fa-times me-1"></i> Clear
                    </button>
                </div>
            `;
            this.wrapper.insertBefore(this.filterControls, this.table);
        }
    }

    /**
     * Setup event listeners
     * @private
     */
    _setupEventListeners() {
        // Pagination events
        if (this.options.paginate && this.pagination) {
            this.pagination.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]');
                if (!action) return;

                const actionType = action.dataset.action;
                switch (actionType) {
                    case 'first':
                        this.goToPage(1);
                        break;
                    case 'prev':
                        this.previousPage();
                        break;
                    case 'next':
                        this.nextPage();
                        break;
                    case 'last':
                        this.goToPage(this.totalPages);
                        break;
                    case 'page':
                        this.goToPage(parseInt(action.dataset.page));
                        break;
                }
            });

            // Page size change
            const pageSizeSelect = this.pagination.querySelector('.page-size-select');
            if (pageSizeSelect) {
                pageSizeSelect.addEventListener('change', (e) => {
                    this.options.pageSize = parseInt(e.target.value);
                    this.options.currentPage = 1;
                    this.render();
                });
            }
        }

        // Filter events
        if (this.options.filterable && this.filterControls) {
            const globalFilter = this.filterControls.querySelector('[data-filter="global"]');
            if (globalFilter) {
                globalFilter.addEventListener('input', (e) => {
                    this.filters.global = e.target.value;
                    this.options.currentPage = 1;
                    this.render();
                });
            }

            const clearFiltersBtn = this.filterControls.querySelector('[data-action="clear-filters"]');
            if (clearFiltersBtn) {
                clearFiltersBtn.addEventListener('click', () => {
                    this.filters = {};
                    this.filterControls.querySelectorAll('input').forEach(input => {
                        input.value = '';
                    });
                    this.render();
                });
            }
        }
    }

    /**
     * Setup sorting
     * @private
     */
    _setupSorting() {
        if (!this.options.sortable || !this.thead) return;

        const headers = this.thead.querySelectorAll('th[data-sortable]');
        headers.forEach(header => {
            header.addEventListener('click', (e) => {
                const column = header.dataset.sortable || header.dataset.column;
                if (!column) return;

                // If clicking the same column, reverse direction
                if (this.sortColumn === column) {
                    this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
                } else {
                    this.sortColumn = column;
                    this.sortDirection = 'asc';
                }

                // Update sort indicators
                headers.forEach(h => {
                    h.classList.remove('sorted-asc', 'sorted-desc');
                    const indicator = h.querySelector('.sort-indicator');
                    if (indicator) {
                        indicator.innerHTML = '';
                    }
                });

                header.classList.add(`sorted-${this.sortDirection}`);
                const indicator = header.querySelector('.sort-indicator') || 
                                  document.createElement('span');
                indicator.className = 'sort-indicator ms-1';
                indicator.innerHTML = this.sortDirection === 'asc' ? 
                    '<i class="fas fa-sort-up"></i>' : '<i class="fas fa-sort-down"></i>';
                if (!header.querySelector('.sort-indicator')) {
                    header.appendChild(indicator);
                }

                this.render();
            });

            // Add sort indicator placeholder
            if (!header.querySelector('.sort-indicator')) {
                const indicator = document.createElement('span');
                indicator.className = 'sort-indicator ms-1 text-muted';
                indicator.innerHTML = '<i class="fas fa-sort"></i>';
                header.appendChild(indicator);
            }
        });
    }

    /**
     * Setup pagination
     * @private
     */
    _setupPagination() {
        if (!this.options.paginate) return;
        this.updatePagination();
    }

    /**
     * Setup filtering
     * @private
     */
    _setupFiltering() {
        if (!this.options.filterable) return;

        // Add column filters if headers have filterable attribute
        if (this.thead) {
            const headers = this.thead.querySelectorAll('th[data-filterable]');
            headers.forEach(header => {
                const column = header.dataset.filterable || header.dataset.column;
                if (!column) return;

                const filterInput = document.createElement('input');
                filterInput.type = 'text';
                filterInput.className = 'form-control form-control-sm column-filter';
                filterInput.placeholder = 'Filter...';
                filterInput.dataset.column = column;
                filterInput.style.width = '120px';

                filterInput.addEventListener('input', (e) => {
                    this.filters[column] = e.target.value;
                    this.options.currentPage = 1;
                    this.render();
                });

                header.appendChild(filterInput);
            });
        }
    }

    /**
     * Setup row selection
     * @private
     */
    _setupRowSelection() {
        if (!this.options.rowSelection || !this.tbody) return;

        // Add checkbox to header if multi-select
        if (this.options.multiSelect && this.thead) {
            const selectAllHeader = this.thead.querySelector('th[data-selectable]');
            if (!selectAllHeader) {
                const header = document.createElement('th');
                header.style.width = '40px';
                header.innerHTML = '<input type="checkbox" class="form-check-input select-all">';
                this.thead.querySelector('tr').prepend(header);
            }

            const selectAllCheckbox = this.thead.querySelector('.select-all');
            if (selectAllCheckbox) {
                selectAllCheckbox.addEventListener('change', (e) => {
                    const isChecked = e.target.checked;
                    this.tbody.querySelectorAll('.row-checkbox').forEach(checkbox => {
                        checkbox.checked = isChecked;
                    });

                    if (isChecked) {
                        this.tbody.querySelectorAll('tr').forEach((row, index) => {
                            this.selectedRows.add(index);
                        });
                    } else {
                        this.selectedRows.clear();
                    }

                    this._triggerSelectionChange();
                });
            }
        }
    }

    /**
     * Setup row expansion
     * @private
     */
    _setupRowExpansion() {
        if (!this.options.expandableRows || !this.tbody) return;

        // Add expand/collapse column to header
        if (this.thead) {
            const expandHeader = this.thead.querySelector('th[data-expandable]');
            if (!expandHeader) {
                const header = document.createElement('th');
                header.style.width = '40px';
                this.thead.querySelector('tr').prepend(header);
            }
        }
    }

    /**
     * Load data into the table
     * @param {Array} data - Array of data objects
     */
    loadData(data = []) {
        this.data = [...data];
        this.filteredData = [...data];
        this.sortedData = [...data];
        this.options.currentPage = 1;
        this.render();
    }

    /**
     * Render the table
     */
    render() {
        if (!this.table) return;

        // Apply filtering
        this._applyFilters();

        // Apply sorting
        this._applySorting();

        // Update pagination
        this.updatePagination();

        // Render table body
        this._renderBody();

        // Update empty state
        this._updateEmptyState();

        // Trigger render event
        this.table.dispatchEvent(new CustomEvent('rendered', {
            detail: {
                data: this.data,
                filteredData: this.filteredData,
                sortedData: this.sortedData,
                page: this.options.currentPage,
                pageSize: this.options.pageSize,
                total: this.filteredData.length
            },
            bubbles: true
        }));
    }

    /**
     * Apply filters to data
     * @private
     */
    _applyFilters() {
        if (Object.keys(this.filters).length === 0) {
            this.filteredData = [...this.data];
            return;
        }

        this.filteredData = this.data.filter(item => {
            // Apply global filter
            if (this.filters.global) {
                const searchTerm = this.filters.global.toLowerCase();
                if (!this._itemMatchesSearch(item, searchTerm)) {
                    return false;
                }
            }

            // Apply column filters
            for (const [column, value] of Object.entries(this.filters)) {
                if (column === 'global') continue;

                if (value && value.trim() !== '') {
                    const itemValue = this._getItemValue(item, column);
                    if (!String(itemValue).toLowerCase().includes(value.toLowerCase())) {
                        return false;
                    }
                }
            }

            return true;
        });
    }

    /**
     * Check if item matches search term
     * @private
     * @param {Object} item - Data item
     * @param {string} searchTerm - Search term
     * @returns {boolean} Whether item matches
     */
    _itemMatchesSearch(item, searchTerm) {
        for (const [key, value] of Object.entries(item)) {
            if (String(value).toLowerCase().includes(searchTerm)) {
                return true;
            }
        }
        return false;
    }

    /**
     * Get value from item by column
     * @private
     * @param {Object} item - Data item
     * @param {string} column - Column name
     * @returns {*} Value
     */
    _getItemValue(item, column) {
        if (column.includes('.')) {
            const parts = column.split('.');
            let value = item;
            for (const part of parts) {
                if (value && value[part] !== undefined) {
                    value = value[part];
                } else {
                    return '';
                }
            }
            return value;
        }
        return item[column] !== undefined ? item[column] : '';
    }

    /**
     * Apply sorting to filtered data
     * @private
     */
    _applySorting() {
        if (!this.sortColumn) {
            this.sortedData = [...this.filteredData];
            return;
        }

        this.sortedData = [...this.filteredData].sort((a, b) => {
            const aValue = this._getItemValue(a, this.sortColumn);
            const bValue = this._getItemValue(b, this.sortColumn);

            // Handle numeric sorting
            if (!isNaN(aValue) && !isNaN(bValue)) {
                return this.sortDirection === 'asc' ? aValue - bValue : bValue - aValue;
            }

            // Handle date sorting
            if (this._isDateString(aValue) && this._isDateString(bValue)) {
                const aDate = new Date(aValue);
                const bDate = new Date(bValue);
                return this.sortDirection === 'asc' ? aDate - bDate : bDate - aDate;
            }

            // Default string sorting
            const aStr = String(aValue).toLowerCase();
            const bStr = String(bValue).toLowerCase();
            return this.sortDirection === 'asc' ? 
                aStr.localeCompare(bStr) : bStr.localeCompare(aStr);
        });
    }

    /**
     * Check if value is a date string
     * @private
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is a date string
     */
    _isDateString(value) {
        if (typeof value !== 'string') return false;
        return !isNaN(Date.parse(value));
    }

    /**
     * Render table body
     * @private
     */
    _renderBody() {
        if (!this.tbody) return;

        // Clear existing rows
        this.tbody.innerHTML = '';

        // Get data for current page
        const startIndex = (this.options.currentPage - 1) * this.options.pageSize;
        const endIndex = startIndex + this.options.pageSize;
        const pageData = this.sortedData.slice(startIndex, endIndex);

        // Render rows
        pageData.forEach((item, index) => {
            const row = this._createRow(item, startIndex + index);
            this.tbody.appendChild(row);
        });

        // Update select all checkbox
        if (this.options.multiSelect) {
            const selectAllCheckbox = this.thead.querySelector('.select-all');
            if (selectAllCheckbox) {
                const allSelected = pageData.length > 0 && 
                                   this.selectedRows.size === pageData.length &&
                                   pageData.every((_, index) => 
                                       this.selectedRows.has(startIndex + index));
                selectAllCheckbox.checked = allSelected;
                selectAllCheckbox.indeterminate = 
                    !allSelected && this.selectedRows.size > 0;
            }
        }
    }

    /**
     * Create a table row
     * @private
     * @param {Object} item - Data item
     * @param {number} index - Row index
     * @returns {HTMLElement} Table row element
     */
    _createRow(item, index) {
        const row = document.createElement('tr');
        row.dataset.index = index;

        // Add selection checkbox if enabled
        if (this.options.rowSelection) {
            const cell = document.createElement('td');
            cell.style.width = '40px';
            
            if (this.options.multiSelect) {
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'form-check-input row-checkbox';
                checkbox.dataset.index = index;
                checkbox.checked = this.selectedRows.has(index);

                checkbox.addEventListener('change', (e) => {
                    if (e.target.checked) {
                        this.selectedRows.add(index);
                    } else {
                        this.selectedRows.delete(index);
                    }
                    this._triggerSelectionChange();
                });

                cell.appendChild(checkbox);
            } else {
                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.className = 'form-check-input';
                radio.name = `${this.table.id || 'table'}-selection`;
                radio.dataset.index = index;
                radio.checked = this.selectedRows.has(index);

                radio.addEventListener('change', (e) => {
                    if (e.target.checked) {
                        this.selectedRows.clear();
                        this.selectedRows.add(index);
                        this._triggerSelectionChange();
                    }
                });

                cell.appendChild(radio);
            }

            row.appendChild(cell);
        }

        // Add expand/collapse button if enabled
        if (this.options.expandableRows) {
            const cell = document.createElement('td');
            cell.style.width = '40px';

            const button = document.createElement('button');
            button.className = 'btn btn-sm btn-link p-0';
            button.dataset.action = 'toggle-expand';
            button.dataset.index = index;
            button.setAttribute('aria-expanded', 'false');
            button.setAttribute('aria-label', 'Expand row');
            button.innerHTML = this.expandedRows.has(index) ? 
                '<i class="fas fa-minus"></i>' : '<i class="fas fa-plus"></i>';

            button.addEventListener('click', (e) => {
                e.preventDefault();
                this.toggleRowExpansion(index);
            });

            cell.appendChild(button);
            row.appendChild(cell);
        }

        // Add data cells
        const headers = this.thead ? this.thead.querySelectorAll('th') : [];
        const dataColumns = Array.from(headers).filter(th => 
            !th.dataset.sortable && 
            !th.dataset.filterable && 
            !th.dataset.selectable && 
            !th.dataset.expandable
        );

        // If we have a custom render function, use it
        if (this.options.renderRow) {
            const customRow = this.options.renderRow(item, index);
            if (customRow) {
                // Append custom cells to row
                if (Array.isArray(customRow)) {
                    customRow.forEach(cell => row.appendChild(cell));
                } else if (customRow instanceof HTMLElement) {
                    row.appendChild(customRow);
                }
            }
        } else {
            // Default rendering
            for (const header of headers) {
                const column = header.dataset.column || header.textContent.trim();
                if (column && !header.dataset.sortable && !header.dataset.filterable && 
                    !header.dataset.selectable && !header.dataset.expandable) {
                    
                    const cell = document.createElement('td');
                    const value = this._getItemValue(item, column);
                    cell.textContent = value !== undefined ? value : '';
                    row.appendChild(cell);
                }
            }
        }

        // Add expandable content if enabled
        if (this.options.expandableRows && this.expandedRows.has(index)) {
            const expandRow = document.createElement('tr');
            expandRow.className = 'table-expand-row';
            expandRow.dataset.parentIndex = index;

            const expandCell = document.createElement('td');
            expandCell.colSpan = headers.length + 
                (this.options.rowSelection ? 1 : 0) + 
                (this.options.expandableRows ? 1 : 0);
            expandCell.className = 'p-4';

            // Use custom expand content renderer if available
            if (this.options.renderExpandContent) {
                expandCell.appendChild(this.options.renderExpandContent(item, index));
            } else {
                expandCell.innerHTML = `<div class="bg-light p-3 rounded">
                    <h6>Details</h6>
                    <pre class="mb-0">${JSON.stringify(item, null, 2)}</pre>
                </div>`;
            }

            expandRow.appendChild(expandCell);
            row.insertAdjacentElement('afterend', expandRow);
        }

        return row;
    }

    /**
     * Update empty state visibility
     * @private
     */
    _updateEmptyState() {
        if (!this.emptyState) return;

        const isEmpty = this.filteredData.length === 0;
        this.emptyState.classList.toggle('d-none', !isEmpty);
        this.table.classList.toggle('d-none', isEmpty);

        if (this.options.paginate && this.pagination) {
            this.pagination.classList.toggle('d-none', isEmpty);
        }
    }

    /**
     * Update pagination controls
     */
    updatePagination() {
        if (!this.options.paginate || !this.pagination) return;

        const totalItems = this.filteredData.length;
        this.totalPages = Math.ceil(totalItems / this.options.pageSize);

        // Update page info
        const pageInfo = this.pagination.querySelector('.page-info');
        if (pageInfo) {
            const start = ((this.options.currentPage - 1) * this.options.pageSize) + 1;
            const end = Math.min(this.options.currentPage * this.options.pageSize, totalItems);
            pageInfo.textContent = `Showing ${start} to ${end} of ${totalItems} entries`;
        }

        // Update page buttons
        const pageItems = this.pagination.querySelectorAll('.page-item');
        pageItems.forEach(item => {
            const action = item.querySelector('[data-action]');
            if (!action) return;

            const actionType = action.dataset.action;
            const pageNum = parseInt(action.dataset.page);

            switch (actionType) {
                case 'first':
                case 'prev':
                    item.classList.toggle('disabled', this.options.currentPage <= 1);
                    break;
                case 'next':
                case 'last':
                    item.classList.toggle('disabled', this.options.currentPage >= this.totalPages);
                    break;
                case 'page':
                    item.classList.toggle('active', pageNum === this.options.currentPage);
                    break;
            }
        });

        // Update page numbers
        this._updatePageNumbers();
    }

    /**
     * Update page number buttons
     * @private
     */
    _updatePageNumbers() {
        if (!this.options.paginate || !this.pagination) return;

        const pageNav = this.pagination.querySelector('.pagination');
        if (!pageNav) return;

        // Remove existing page number buttons (keep first, prev, next, last)
        const existingPageItems = pageNav.querySelectorAll('.page-item');
        existingPageItems.forEach(item => {
            const action = item.querySelector('[data-action]');
            if (action && action.dataset.action === 'page') {
                item.remove();
            }
        });

        // Add page number buttons
        const maxVisiblePages = 5;
        let startPage = Math.max(1, this.options.currentPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(this.totalPages, startPage + maxVisiblePages - 1);

        if (endPage - startPage + 1 < maxVisiblePages) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }

        // Add first page and ellipsis if needed
        if (startPage > 1) {
            const firstItem = document.createElement('li');
            firstItem.className = 'page-item';
            firstItem.innerHTML = '<button class="page-link" data-action="page" data-page="1">1</button>';
            pageNav.insertBefore(firstItem, pageNav.querySelector('.page-item:last-child'));

            if (startPage > 2) {
                const ellipsisItem = document.createElement('li');
                ellipsisItem.className = 'page-item disabled';
                ellipsisItem.innerHTML = '<span class="page-link">...</span>';
                pageNav.insertBefore(ellipsisItem, pageNav.querySelector('.page-item:last-child'));
            }
        }

        // Add page numbers
        for (let i = startPage; i <= endPage; i++) {
            const pageItem = document.createElement('li');
            pageItem.className = `page-item ${i === this.options.currentPage ? 'active' : ''}`;
            pageItem.innerHTML = `<button class="page-link" data-action="page" data-page="${i}">${i}</button>`;
            pageNav.insertBefore(pageItem, pageNav.querySelector('.page-item:last-child'));
        }

        // Add last page and ellipsis if needed
        if (endPage < this.totalPages) {
            if (endPage < this.totalPages - 1) {
                const ellipsisItem = document.createElement('li');
                ellipsisItem.className = 'page-item disabled';
                ellipsisItem.innerHTML = '<span class="page-link">...</span>';
                pageNav.insertBefore(ellipsisItem, pageNav.querySelector('.page-item:last-child'));
            }

            const lastItem = document.createElement('li');
            lastItem.className = 'page-item';
            lastItem.innerHTML = `<button class="page-link" data-action="page" data-page="${this.totalPages}">${this.totalPages}</button>`;
            pageNav.insertBefore(lastItem, pageNav.querySelector('.page-item:last-child'));
        }
    }

    /**
     * Go to a specific page
     * @param {number} page - Page number
     */
    goToPage(page) {
        if (page < 1 || page > this.totalPages) return;
        this.options.currentPage = page;
        this.render();
    }

    /**
     * Go to the next page
     */
    nextPage() {
        if (this.options.currentPage < this.totalPages) {
            this.options.currentPage++;
            this.render();
        }
    }

    /**
     * Go to the previous page
     */
    previousPage() {
        if (this.options.currentPage > 1) {
            this.options.currentPage--;
            this.render();
        }
    }

    /**
     * Go to the first page
     */
    firstPage() {
        this.goToPage(1);
    }

    /**
     * Go to the last page
     */
    lastPage() {
        this.goToPage(this.totalPages);
    }

    /**
     * Sort by a specific column
     * @param {string} column - Column name
     * @param {string} direction - Sort direction (asc/desc)
     */
    sortBy(column, direction = 'asc') {
        this.sortColumn = column;
        this.sortDirection = direction;
        this.render();
    }

    /**
     * Filter by a specific column
     * @param {string} column - Column name
     * @param {string} value - Filter value
     */
    filterBy(column, value) {
        this.filters[column] = value;
        this.options.currentPage = 1;
        this.render();
    }

    /**
     * Clear all filters
     */
    clearFilters() {
        this.filters = {};
        if (this.filterControls) {
            this.filterControls.querySelectorAll('input').forEach(input => {
                input.value = '';
            });
        }
        this.render();
    }

    /**
     * Toggle row expansion
     * @param {number} index - Row index
     */
    toggleRowExpansion(index) {
        if (this.expandedRows.has(index)) {
            this.collapseRow(index);
        } else {
            this.expandRow(index);
        }
    }

    /**
     * Expand a row
     * @param {number} index - Row index
     */
    expandRow(index) {
        this.expandedRows.add(index);
        this.render();
    }

    /**
     * Collapse a row
     * @param {number} index - Row index
     */
    collapseRow(index) {
        this.expandedRows.delete(index);
        this.render();
    }

    /**
     * Collapse all expanded rows
     */
    collapseAllRows() {
        this.expandedRows.clear();
        this.render();
    }

    /**
     * Expand all rows
     */
    expandAllRows() {
        const startIndex = (this.options.currentPage - 1) * this.options.pageSize;
        const endIndex = startIndex + this.options.pageSize;
        const pageData = this.sortedData.slice(startIndex, endIndex);

        pageData.forEach((_, index) => {
            this.expandedRows.add(startIndex + index);
        });
        this.render();
    }

    /**
     * Select a row
     * @param {number} index - Row index
     */
    selectRow(index) {
        if (this.options.multiSelect) {
            this.selectedRows.add(index);
        } else {
            this.selectedRows.clear();
            this.selectedRows.add(index);
        }
        this._triggerSelectionChange();
        this.render();
    }

    /**
     * Deselect a row
     * @param {number} index - Row index
     */
    deselectRow(index) {
        this.selectedRows.delete(index);
        this._triggerSelectionChange();
        this.render();
    }

    /**
     * Select all rows on current page
     */
    selectAllRows() {
        const startIndex = (this.options.currentPage - 1) * this.options.pageSize;
        const endIndex = startIndex + this.options.pageSize;
        const pageData = this.sortedData.slice(startIndex, endIndex);

        pageData.forEach((_, index) => {
            this.selectedRows.add(startIndex + index);
        });
        this._triggerSelectionChange();
        this.render();
    }

    /**
     * Deselect all rows
     */
    deselectAllRows() {
        this.selectedRows.clear();
        this._triggerSelectionChange();
        this.render();
    }

    /**
     * Get selected row indices
     * @returns {Array} Array of selected row indices
     */
    getSelectedRows() {
        return Array.from(this.selectedRows);
    }

    /**
     * Get selected row data
     * @returns {Array} Array of selected row data
     */
    getSelectedRowData() {
        return this.getSelectedRows().map(index => this.sortedData[index]);
    }

    /**
     * Get expanded row indices
     * @returns {Array} Array of expanded row indices
     */
    getExpandedRows() {
        return Array.from(this.expandedRows);
    }

    /**
     * Get data for a specific row
     * @param {number} index - Row index
     * @returns {Object} Row data
     */
    getRowData(index) {
        return this.sortedData[index];
    }

    /**
     * Get all data
     * @returns {Array} All data
     */
    getData() {
        return [...this.data];
    }

    /**
     * Get filtered data
     * @returns {Array} Filtered data
     */
    getFilteredData() {
        return [...this.filteredData];
    }

    /**
     * Get sorted data
     * @returns {Array} Sorted data
     */
    getSortedData() {
        return [...this.sortedData];
    }

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
     * Trigger selection change event
     * @private
     */
    _triggerSelectionChange() {
        this.table.dispatchEvent(new CustomEvent('selectionChange', {
            detail: {
                selectedIndices: this.getSelectedRows(),
                selectedData: this.getSelectedRowData()
            },
            bubbles: true
        }));
    }

    /**
     * Refresh the table
     */
    refresh() {
        this.render();
    }

    /**
     * Destroy the table manager
     */
    destroy() {
        // Remove event listeners
        if (this.options.paginate && this.pagination) {
            this.pagination.removeEventListener('click', this._handlePaginationClick);
        }

        // Remove created elements
        if (this.loadingIndicator) {
            this.loadingIndicator.remove();
        }
        if (this.emptyState) {
            this.emptyState.remove();
        }
        if (this.pagination) {
            this.pagination.remove();
        }
        if (this.filterControls) {
            this.filterControls.remove();
        }

        // Clear data
        this.data = [];
        this.filteredData = [];
        this.sortedData = [];
        this.selectedRows.clear();
        this.expandedRows.clear();
    }
}

/**
 * Create a table manager for a table
 * @param {HTMLTableElement|string} table - Table element or selector
 * @param {Object} options - Configuration options
 * @returns {TableManager} Table manager instance
 */
function createTableManager(table, options = {}) {
    return new TableManager(table, options);
}

// Export for use in modules
export { TableManager, createTableManager };
