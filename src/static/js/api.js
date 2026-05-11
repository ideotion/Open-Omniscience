/**
 * API Client for Open-Omniscience
 * Handles all communication with the FastAPI backend
 * Uses Fetch API with error handling and response normalization
 */

class APIClient {
    /**
     * Create a new API client
     * @param {Object} options - Configuration options
     * @param {string} options.baseUrl - Base API URL
     * @param {string} options.csrfToken - CSRF token for POST requests
     * @param {Object} options.headers - Default headers
     */
    constructor(options = {}) {
        this.baseUrl = options.baseUrl || '';
        this.csrfToken = options.csrfToken || this._getCsrfTokenFromMeta();
        this.defaultHeaders = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            ...options.headers
        };
        this._requestInterceptors = [];
        this._responseInterceptors = [];
    }

    /**
     * Get CSRF token from meta tag
     * @private
     */
    _getCsrfTokenFromMeta() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : null;
    }

    /**
     * Add request interceptor
     * @param {Function} interceptor - Interceptor function (request) => request
     */
    addRequestInterceptor(interceptor) {
        this._requestInterceptors.push(interceptor);
    }

    /**
     * Add response interceptor
     * @param {Function} interceptor - Interceptor function (response) => response
     */
    addResponseInterceptor(interceptor) {
        this._responseInterceptors.push(interceptor);
    }

    /**
     * Build full URL from endpoint
     * @private
     * @param {string} endpoint - API endpoint
     * @param {Object} params - Query parameters
     */
    _buildUrl(endpoint, params = {}) {
        let url = `${this.baseUrl}${endpoint}`;
        
        const queryParams = new URLSearchParams();
        for (const [key, value] of Object.entries(params)) {
            if (value !== undefined && value !== null) {
                if (Array.isArray(value)) {
                    value.forEach(v => queryParams.append(key, v));
                } else {
                    queryParams.append(key, value);
                }
            }
        }
        
        const queryString = queryParams.toString();
        if (queryString) {
            url += `?${queryString}`;
        }
        
        return url;
    }

    /**
     * Apply interceptors to request
     * @private
     * @param {Request} request - Request object
     */
    async _applyRequestInterceptors(request) {
        let result = request;
        for (const interceptor of this._requestInterceptors) {
            result = await interceptor(result);
        }
        return result;
    }

    /**
     * Apply interceptors to response
     * @private
     * @param {Response} response - Response object
     */
    async _applyResponseInterceptors(response) {
        let result = response;
        for (const interceptor of this._responseInterceptors) {
            result = await interceptor(result);
        }
        return result;
    }

    /**
     * Make an HTTP request
     * @param {string} method - HTTP method
     * @param {string} endpoint - API endpoint
     * @param {Object} data - Request body data
     * @param {Object} params - Query parameters
     * @param {Object} options - Additional options
     */
    async request(method, endpoint, data = null, params = {}, options = {}) {
        const url = this._buildUrl(endpoint, params);
        
        const headers = {
            ...this.defaultHeaders,
            ...options.headers
        };

        // Add CSRF token for mutating requests
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method.toUpperCase()) && this.csrfToken) {
            headers['X-CSRF-Token'] = this.csrfToken;
        }

        const requestOptions = {
            method: method.toUpperCase(),
            headers,
            credentials: options.credentials || 'same-origin',
            ...options
        };

        if (data && !['GET', 'HEAD'].includes(method.toUpperCase())) {
            if (data instanceof FormData) {
                delete headers['Content-Type']; // Let browser set it
                requestOptions.body = data;
            } else {
                requestOptions.body = JSON.stringify(data);
            }
        }

        // Apply request interceptors
        const interceptedRequest = await this._applyRequestInterceptors({
            url,
            options: requestOptions,
            method,
            endpoint,
            data,
            params
        });

        try {
            const response = await fetch(interceptedRequest.url, interceptedRequest.options);
            
            // Apply response interceptors
            const interceptedResponse = await this._applyResponseInterceptors(response);

            if (!interceptedResponse.ok) {
                const error = await this._handleError(interceptedResponse);
                throw error;
            }

            return this._parseResponse(interceptedResponse);
        } catch (error) {
            if (error instanceof APIError) {
                throw error;
            }
            throw new APIError({
                message: error.message || 'Network error',
                code: 'NETWORK_ERROR',
                status: 0,
                originalError: error
            });
        }
    }

    /**
     * Handle error responses
     * @private
     * @param {Response} response - Error response
     */
    async _handleError(response) {
        let errorData;
        try {
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                errorData = await response.json();
            } else {
                errorData = { detail: await response.text() };
            }
        } catch {
            errorData = { detail: 'Unknown error' };
        }

        return new APIError({
            message: errorData.detail || errorData.message || 'Request failed',
            code: errorData.code || 'API_ERROR',
            status: response.status,
            data: errorData,
            url: response.url
        });
    }

    /**
     * Parse successful response
     * @private
     * @param {Response} response - Response object
     */
    async _parseResponse(response) {
        const contentType = response.headers.get('content-type');
        
        if (contentType && contentType.includes('application/json')) {
            return await response.json();
        } else if (contentType && contentType.includes('text/')) {
            return await response.text();
        } else {
            return await response.blob();
        }
    }

    // Convenience methods

    /**
     * GET request
     */
    async get(endpoint, params = {}, options = {}) {
        return this.request('GET', endpoint, null, params, options);
    }

    /**
     * POST request
     */
    async post(endpoint, data = {}, params = {}, options = {}) {
        return this.request('POST', endpoint, data, params, options);
    }

    /**
     * PUT request
     */
    async put(endpoint, data = {}, params = {}, options = {}) {
        return this.request('PUT', endpoint, data, params, options);
    }

    /**
     * PATCH request
     */
    async patch(endpoint, data = {}, params = {}, options = {}) {
        return this.request('PATCH', endpoint, data, params, options);
    }

    /**
     * DELETE request
     */
    async delete(endpoint, data = {}, params = {}, options = {}) {
        return this.request('DELETE', endpoint, data, params, options);
    }

    // Open-Omniscience specific API methods

    /**
     * Get articles with search and filters
     * @param {Object} options - Search options
     * @param {string} options.query - Search query
     * @param {string[]} options.sources - Source IDs to filter by
     * @param {string[]} options.tags - Tags to filter by
     * @param {string} options.dateFrom - Start date (YYYY-MM-DD)
     * @param {string} options.dateTo - End date (YYYY-MM-DD)
     * @param {number} options.page - Page number
     * @param {number} options.pageSize - Results per page
     * @param {string} options.sortBy - Sort field
     * @param {string} options.sortOrder - Sort order (asc/desc)
     */
    async searchArticles(options = {}) {
        const params = {
            q: options.query,
            sources: options.sources,
            tags: options.tags,
            date_from: options.dateFrom,
            date_to: options.dateTo,
            page: options.page || 1,
            page_size: options.pageSize || 20,
            sort_by: options.sortBy || 'published_at',
            sort_order: options.sortOrder || 'desc'
        };

        return this.get('/api/articles', params);
    }

    /**
     * Get article by ID
     * @param {string} articleId - Article ID
     */
    async getArticle(articleId) {
        return this.get(`/api/articles/${articleId}`);
    }

    /**
     * Get article content
     * @param {string} articleId - Article ID
     */
    async getArticleContent(articleId) {
        return this.get(`/api/articles/${articleId}/content`);
    }

    /**
     * Get article summary
     * @param {string} articleId - Article ID
     */
    async getArticleSummary(articleId) {
        return this.get(`/api/articles/${articleId}/summary`);
    }

    /**
     * Get all sources
     */
    async getSources() {
        return this.get('/api/sources');
    }

    /**
     * Get source by ID
     * @param {string} sourceId - Source ID
     */
    async getSource(sourceId) {
        return this.get(`/api/sources/${sourceId}`);
    }

    /**
     * Create a new source
     * @param {Object} sourceData - Source data
     */
    async createSource(sourceData) {
        return this.post('/api/sources', sourceData);
    }

    /**
     * Update a source
     * @param {string} sourceId - Source ID
     * @param {Object} sourceData - Updated source data
     */
    async updateSource(sourceId, sourceData) {
        return this.put(`/api/sources/${sourceId}`, sourceData);
    }

    /**
     * Delete a source
     * @param {string} sourceId - Source ID
     */
    async deleteSource(sourceId) {
        return this.delete(`/api/sources/${sourceId}`);
    }

    /**
     * Test source connection
     * @param {string} sourceId - Source ID
     */
    async testSource(sourceId) {
        return this.post(`/api/sources/${sourceId}/test`);
    }

    /**
     * Sync source (fetch new articles)
     * @param {string} sourceId - Source ID
     */
    async syncSource(sourceId) {
        return this.post(`/api/sources/${sourceId}/sync`);
    }

    /**
     * Get all tags
     */
    async getTags() {
        return this.get('/api/tags');
    }

    /**
     * Get articles by tag
     * @param {string} tag - Tag name
     * @param {Object} options - Search options
     */
    async getArticlesByTag(tag, options = {}) {
        return this.searchArticles({ ...options, tags: [tag] });
    }

    /**
     * Get statistics
     */
    async getStatistics() {
        return this.get('/api/statistics');
    }

    /**
     * Get user settings
     */
    async getSettings() {
        return this.get('/api/settings');
    }

    /**
     * Update user settings
     * @param {Object} settings - Settings to update
     */
    async updateSettings(settings) {
        return this.put('/api/settings', settings);
    }

    /**
     * Get saved searches
     */
    async getSavedSearches() {
        return this.get('/api/saved-searches');
    }

    /**
     * Create a saved search
     * @param {Object} searchData - Search data to save
     */
    async createSavedSearch(searchData) {
        return this.post('/api/saved-searches', searchData);
    }

    /**
     * Delete a saved search
     * @param {string} searchId - Saved search ID
     */
    async deleteSavedSearch(searchId) {
        return this.delete(`/api/saved-searches/${searchId}`);
    }

    /**
     * Get search history
     */
    async getSearchHistory() {
        return this.get('/api/search-history');
    }

    /**
     * Clear search history
     */
    async clearSearchHistory() {
        return this.delete('/api/search-history');
    }

    /**
     * Export articles
     * @param {Object} options - Export options
     */
    async exportArticles(options = {}) {
        const params = {
            format: options.format || 'csv',
            ...options
        };
        
        // For file downloads, we need to handle the response differently
        const response = await this.get('/api/articles/export', params, {
            headers: { 'Accept': 'application/octet-stream' }
        });
        
        return response;
    }

    /**
     * Get available export formats
     */
    async getExportFormats() {
        return this.get('/api/articles/export-formats');
    }

    /**
     * Get system info
     */
    async getSystemInfo() {
        return this.get('/api/system/info');
    }

    /**
     * Get health check
     */
    async healthCheck() {
        return this.get('/api/health');
    }

    /**
     * Discover new sources
     * @param {Object} options - Discovery options
     */
    async discoverSources(options = {}) {
        return this.get('/api/sources/discover', options);
    }

    /**
     * Get source categories
     */
    async getSourceCategories() {
        return this.get('/api/sources/categories');
    }

    /**
     * Get source icons
     */
    async getSourceIcons() {
        return this.get('/api/sources/icons');
    }

    /**
     * Batch update articles
     * @param {Object} updates - Batch update data
     */
    async batchUpdateArticles(updates) {
        return this.post('/api/articles/batch', updates);
    }

    /**
     * Get article count by date
     * @param {Object} options - Query options
     */
    async getArticleCountByDate(options = {}) {
        return this.get('/api/articles/count-by-date', options);
    }

    /**
     * Get top sources by article count
     * @param {Object} options - Query options
     */
    async getTopSources(options = {}) {
        return this.get('/api/sources/top', options);
    }

    /**
     * Get recent activity
     */
    async getRecentActivity() {
        return this.get('/api/activity/recent');
    }
}

/**
 * Custom API error class
 */
class APIError extends Error {
    /**
     * Create a new API error
     * @param {Object} options - Error options
     * @param {string} options.message - Error message
     * @param {string} options.code - Error code
     * @param {number} options.status - HTTP status code
     * @param {Object} options.data - Error data from server
     * @param {string} options.url - Request URL
     * @param {Error} options.originalError - Original error
     */
    constructor(options = {}) {
        super(options.message || 'API Error');
        this.name = 'APIError';
        this.code = options.code || 'API_ERROR';
        this.status = options.status || 0;
        this.data = options.data || null;
        this.url = options.url || null;
        this.originalError = options.originalError || null;
        this.timestamp = new Date();
        
        // Maintain proper stack trace
        if (Error.captureStackTrace) {
            Error.captureStackTrace(this, APIError);
        }
    }

    /**
     * Check if error is a network error
     */
    get isNetworkError() {
        return this.code === 'NETWORK_ERROR' || this.status === 0;
    }

    /**
     * Check if error is a server error
     */
    get isServerError() {
        return this.status >= 500;
    }

    /**
     * Check if error is a client error
     */
    get isClientError() {
        return this.status >= 400 && this.status < 500;
    }

    /**
     * Check if error is an authentication error
     */
    get isAuthError() {
        return this.status === 401 || this.status === 403;
    }

    /**
     * Check if error is a not found error
     */
    get isNotFound() {
        return this.status === 404;
    }

    /**
     * Convert to plain object
     */
    toJSON() {
        return {
            name: this.name,
            message: this.message,
            code: this.code,
            status: this.status,
            data: this.data,
            url: this.url,
            timestamp: this.timestamp.toISOString()
        };
    }
}

/**
 * Singleton API client instance
 */
let apiClient = null;

/**
 * Get or create the API client
 * @param {Object} options - Configuration options
 */
function getAPIClient(options = {}) {
    if (!apiClient) {
        apiClient = new APIClient(options);
    }
    return apiClient;
}

/**
 * Reset the API client (useful for testing)
 */
function resetAPIClient() {
    apiClient = null;
}

// Export for use in modules
export { APIClient, APIError, getAPIClient, resetAPIClient };
