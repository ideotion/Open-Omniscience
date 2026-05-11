/**
 * Service Worker Utilities for Open-Omniscience
 * Handles service worker registration and management
 */

const ServiceWorkerUtils = {
    /**
     * Service worker file path
     */
    SW_PATH: '/static/sw.js',

    /**
     * Service worker registration
     */
    registration: null,

    /**
     * Whether service worker is supported
     */
    isSupported: 'serviceWorker' in navigator,

    /**
     * Whether service worker is ready
     */
    isReady: false,

    /**
     * Event listeners
     */
    listeners: {
        update: [],
        error: [],
        ready: []
    },

    /**
     * Initialize service worker
     * @param {Object} options - Initialization options
     * @param {string} options.scope - Service worker scope
     * @param {string} options.path - Service worker file path
     * @param {boolean} options.autoUpdate - Enable auto-update checking
     * @param {number} options.updateInterval - Update check interval in minutes
     */
    async init(options = {}) {
        if (!this.isSupported) {
            console.warn('Service Worker not supported in this browser');
            return false;
        }

        const {
            scope = '/',
            path = this.SW_PATH,
            autoUpdate = true,
            updateInterval = 60
        } = options;

        try {
            // Register service worker
            this.registration = await navigator.serviceWorker.register(path, {
                scope,
                type: 'module' // Use module type for modern service workers
            });

            console.log('Service Worker registered:', this.registration);

            // Setup event listeners
            this._setupEventListeners();

            // Check for updates if enabled
            if (autoUpdate) {
                this._startUpdateChecker(updateInterval);
            }

            // Mark as ready
            this.isReady = true;

            // Trigger ready event
            this._triggerEvent('ready', { registration: this.registration });

            return true;
        } catch (error) {
            console.error('Service Worker registration failed:', error);
            this._triggerEvent('error', { error });
            return false;
        }
    },

    /**
     * Setup event listeners
     * @private
     */
    _setupEventListeners() {
        if (!this.registration) return;

        // Update found
        this.registration.addEventListener('updatefound', () => {
            this._handleUpdateFound();
        });

        // Controller change
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            this._handleControllerChange();
        });

        // Message from service worker
        navigator.serviceWorker.addEventListener('message', (event) => {
            this._handleMessage(event);
        });

        // External message events
        window.addEventListener('message', (event) => {
            // Only handle messages from service worker
            if (event.source === navigator.serviceWorker.controller) {
                this._handleMessage(event);
            }
        });
    },

    /**
     * Handle update found
     * @private
     */
    _handleUpdateFound() {
        const installingWorker = this.registration.installing;

        installingWorker.addEventListener('statechange', () => {
            if (installingWorker.state === 'installed') {
                // New update is available
                this._triggerEvent('update', {
                    registration: this.registration,
                    newWorker: installingWorker
                });
            }
        });
    },

    /**
     * Handle controller change
     * @private
     */
    _handleControllerChange() {
        // A new service worker has taken control
        console.log('Service Worker controller changed');
        this._triggerEvent('controllerchange', {});
    },

    /**
     * Handle message from service worker
     * @private
     * @param {MessageEvent} event - Message event
     */
    _handleMessage(event) {
        const data = event.data;

        if (!data || !data.type) return;

        switch (data.type) {
            case 'CACHE_SUCCESS':
                console.log(`Asset cached: ${data.url}`);
                break;
            case 'CACHE_ERROR':
                console.error(`Failed to cache asset: ${data.url}`, data.error);
                break;
            case 'CLEAR_CACHE_SUCCESS':
                console.log(`Cache cleared: ${data.cacheName}`);
                break;
            case 'CLEAR_CACHE_ERROR':
                console.error(`Failed to clear cache: ${data.cacheName}`, data.error);
                break;
            case 'CACHE_SIZE':
                console.log(`Cache size: ${data.cacheName}`, {
                    size: data.size,
                    count: data.count
                });
                break;
            case 'SYNC_ARTICLES':
                // Forward to application
                window.dispatchEvent(new CustomEvent('syncArticles', {
                    detail: data
                }));
                break;
            case 'CHECK_NEW_ARTICLES':
                // Forward to application
                window.dispatchEvent(new CustomEvent('checkNewArticles', {
                    detail: data
                }));
                break;
            default:
                console.log('Unknown message from service worker:', data);
        }
    },

    /**
     * Start auto-update checker
     * @private
     * @param {number} interval - Check interval in minutes
     */
    _startUpdateChecker(interval) {
        // Check for updates every interval minutes
        setInterval(() => {
            this.checkForUpdates();
        }, interval * 60 * 1000);

        // Initial check
        setTimeout(() => {
            this.checkForUpdates();
        }, 5000);
    },

    /**
     * Check for service worker updates
     * @returns {Promise<boolean>} Whether an update was found
     */
    async checkForUpdates() {
        if (!this.registration) {
            return false;
        }

        try {
            const response = await fetch(this.SW_PATH, {
                cache: 'no-store',
                headers: {
                    'Cache-Control': 'no-cache'
                }
            });

            if (response.ok) {
                const currentHash = await this._getCurrentHash();
                const newHash = await this._getHashFromResponse(response);

                if (currentHash !== newHash) {
                    // Update available
                    await this.registration.update();
                    return true;
                }
            }

            return false;
        } catch (error) {
            console.error('Failed to check for updates:', error);
            return false;
        }
    },

    /**
     * Get hash of current service worker
     * @private
     * @returns {Promise<string>} Hash string
     */
    async _getCurrentHash() {
        try {
            const response = await fetch(this.SW_PATH, {
                cache: 'no-store'
            });
            return this._getHashFromResponse(response);
        } catch (error) {
            return '';
        }
    },

    /**
     * Get hash from response
     * @private
     * @param {Response} response - Response object
     * @returns {Promise<string>} Hash string
     */
    async _getHashFromResponse(response) {
        const text = await response.text();
        // Simple hash using length and first/last characters
        return `${text.length}-${text.substring(0, 10)}-${text.substring(-10)}`;
    },

    /**
     * Skip waiting and activate new service worker
     * @returns {Promise<void>}
     */
    async skipWaiting() {
        if (!this.registration || !this.registration.waiting) {
            return;
        }

        try {
            // Send skip waiting message to service worker
            this.registration.waiting.postMessage({
                type: 'SKIP_WAITING'
            });

            // Also use the API if available
            if (this.registration.waiting.skipWaiting) {
                await this.registration.waiting.skipWaiting();
            }

            console.log('Service Worker skipWaiting called');
        } catch (error) {
            console.error('Failed to skip waiting:', error);
        }
    },

    /**
     * Unregister service worker
     * @returns {Promise<boolean>} Whether unregistration was successful
     */
    async unregister() {
        if (!this.registration) {
            return false;
        }

        try {
            const result = await this.registration.unregister();
            this.registration = null;
            this.isReady = false;
            console.log('Service Worker unregistered:', result);
            return result;
        } catch (error) {
            console.error('Failed to unregister service worker:', error);
            return false;
        }
    },

    /**
     * Update service worker
     * @returns {Promise<void>}
     */
    async update() {
        if (!this.registration) {
            return;
        }

        try {
            await this.registration.update();
            console.log('Service Worker update called');
        } catch (error) {
            console.error('Failed to update service worker:', error);
        }
    },

    /**
     * Get current service worker state
     * @returns {Object} Service worker state
     */
    getState() {
        if (!this.registration) {
            return {
                supported: this.isSupported,
                ready: false,
                registration: null
            };
        }

        return {
            supported: this.isSupported,
            ready: this.isReady,
            registration: {
                scope: this.registration.scope,
                active: this.registration.active ? {
                    state: this.registration.active.state,
                    scriptURL: this.registration.active.scriptURL
                } : null,
                waiting: this.registration.waiting ? {
                    state: this.registration.waiting.state,
                    scriptURL: this.registration.waiting.scriptURL
                } : null,
                installing: this.registration.installing ? {
                    state: this.registration.installing.state,
                    scriptURL: this.registration.installing.scriptURL
                } : null
            }
        };
    },

    /**
     * Check if there's a new update available
     * @returns {Promise<boolean>} Whether an update is available
     */
    async isUpdateAvailable() {
        if (!this.registration) {
            return false;
        }

        // Check if there's a waiting service worker
        if (this.registration.waiting) {
            return true;
        }

        // Check for updates
        return this.checkForUpdates();
    },

    /**
     * Cache an asset
     * @param {string} url - URL to cache
     * @returns {Promise<boolean>} Whether caching was successful
     */
    async cacheAsset(url) {
        if (!this.registration || !this.registration.active) {
            return false;
        }

        try {
            // Send message to service worker to cache the asset
            this.registration.active.postMessage({
                type: 'CACHE_ASSET',
                url
            });

            return true;
        } catch (error) {
            console.error('Failed to cache asset:', error);
            return false;
        }
    },

    /**
     * Clear a cache
     * @param {string} cacheName - Name of cache to clear
     * @returns {Promise<boolean>} Whether clearing was successful
     */
    async clearCache(cacheName) {
        if (!this.registration || !this.registration.active) {
            return false;
        }

        try {
            this.registration.active.postMessage({
                type: 'CLEAR_CACHE',
                cacheName
            });

            return true;
        } catch (error) {
            console.error('Failed to clear cache:', error);
            return false;
        }
    },

    /**
     * Get cache size
     * @param {string} cacheName - Name of cache
     * @returns {Promise<Object>} Cache size information
     */
    async getCacheSize(cacheName) {
        if (!this.registration || !this.registration.active) {
            return { size: 0, count: 0 };
        }

        return new Promise((resolve) => {
            const messageHandler = (event) => {
                if (event.data.type === 'CACHE_SIZE' && 
                    event.data.cacheName === cacheName) {
                    
                    navigator.serviceWorker.removeEventListener('message', messageHandler);
                    resolve({
                        size: event.data.size,
                        count: event.data.count
                    });
                } else if (event.data.type === 'CACHE_SIZE_ERROR' && 
                           event.data.cacheName === cacheName) {
                    
                    navigator.serviceWorker.removeEventListener('message', messageHandler);
                    resolve({ size: 0, count: 0, error: event.data.error });
                }
            };

            navigator.serviceWorker.addEventListener('message', messageHandler);

            this.registration.active.postMessage({
                type: 'GET_CACHE_SIZE',
                cacheName
            });
        });
    },

    /**
     * Request permission for notifications
     * @returns {Promise<string>} Permission state ('granted', 'denied', 'default')
     */
    async requestNotificationPermission() {
        if (!('Notification' in window)) {
            return 'denied';
        }

        try {
            const permission = await Notification.requestPermission();
            return permission;
        } catch (error) {
            console.error('Failed to request notification permission:', error);
            return 'denied';
        }
    },

    /**
     * Check notification permission
     * @returns {string} Permission state ('granted', 'denied', 'default')
     */
    getNotificationPermission() {
        if (!('Notification' in window)) {
            return 'denied';
        }

        return Notification.permission;
    },

    /**
     * Show a notification
     * @param {Object} options - Notification options
     * @param {string} options.title - Notification title
     * @param {Object} options - Notification options
     * @returns {Promise<void>}
     */
    async showNotification(options = {}) {
        const {
            title = 'Open-Omniscience',
            body = '',
            icon = '/static/favicon.ico',
            badge = '/static/favicon.ico',
            data = {},
            actions = [],
            vibrate = [200, 100, 200],
            tag = 'open-omniscience-notification',
            renotify = false,
            requireInteraction = false
        } = options;

        if (!('Notification' in window)) {
            console.warn('Notifications not supported');
            return;
        }

        const permission = this.getNotificationPermission();
        if (permission !== 'granted') {
            console.warn('Notification permission not granted');
            return;
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            await registration.showNotification(title, {
                body,
                icon,
                badge,
                data,
                actions,
                vibrate,
                tag,
                renotify,
                requireInteraction
            });
        } catch (error) {
            console.error('Failed to show notification:', error);
        }
    },

    /**
     * Register for push notifications
     * @param {Object} options - Push registration options
     * @returns {Promise<string|null>} Push subscription JSON or null
     */
    async registerPush(options = {}) {
        if (!('PushManager' in window)) {
            console.warn('Push notifications not supported');
            return null;
        }

        const permission = this.getNotificationPermission();
        if (permission !== 'granted') {
            console.warn('Notification permission not granted');
            return null;
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: options.applicationServerKey || this._getVAPIDKey(),
                ...options
            });

            return JSON.stringify(subscription);
        } catch (error) {
            console.error('Failed to register for push notifications:', error);
            return null;
        }
    },

    /**
     * Unregister from push notifications
     * @returns {Promise<boolean>} Whether unregistration was successful
     */
    async unregisterPush() {
        if (!('PushManager' in window)) {
            return false;
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            const subscription = await registration.pushManager.getSubscription();

            if (subscription) {
                await subscription.unsubscribe();
                return true;
            }

            return false;
        } catch (error) {
            console.error('Failed to unregister from push notifications:', error);
            return false;
        }
    },

    /**
     * Get VAPID public key
     * @private
     * @returns {Uint8Array|null} VAPID public key
     */
    _getVAPIDKey() {
        // This should be replaced with your actual VAPID public key
        // For now, return null to indicate push notifications are not configured
        return null;
    },

    /**
     * Register a sync event
     * @param {string} tag - Sync tag
     * @returns {Promise<boolean>} Whether registration was successful
     */
    async registerSync(tag) {
        if (!('SyncManager' in window)) {
            console.warn('Background sync not supported');
            return false;
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            await registration.sync.register(tag);
            return true;
        } catch (error) {
            console.error('Failed to register sync:', error);
            return false;
        }
    },

    /**
     * Get sync registrations
     * @returns {Promise<Array>} Array of sync registrations
     */
    async getSyncRegistrations() {
        if (!('SyncManager' in window)) {
            return [];
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            return await registration.sync.getTags();
        } catch (error) {
            console.error('Failed to get sync registrations:', error);
            return [];
        }
    },

    /**
     * Register for periodic sync
     * @param {string} tag - Sync tag
     * @param {Object} options - Periodic sync options
     * @returns {Promise<boolean>} Whether registration was successful
     */
    async registerPeriodicSync(tag, options = {}) {
        if (!('PeriodicSyncManager' in window)) {
            console.warn('Periodic sync not supported');
            return false;
        }

        const {
            minInterval = 15 * 60 * 1000, // 15 minutes
            powerState = 'auto'
        } = options;

        try {
            const registration = await navigator.serviceWorker.ready;
            const result = await registration.periodicSync.register(tag, {
                minInterval,
                powerState
            });

            return result.state === 'granted';
        } catch (error) {
            console.error('Failed to register periodic sync:', error);
            return false;
        }
    },

    /**
     * Unregister periodic sync
     * @param {string} tag - Sync tag
     * @returns {Promise<boolean>} Whether unregistration was successful
     */
    async unregisterPeriodicSync(tag) {
        if (!('PeriodicSyncManager' in window)) {
            return false;
        }

        try {
            const registration = await navigator.serviceWorker.ready;
            await registration.periodicSync.unregister(tag);
            return true;
        } catch (error) {
            console.error('Failed to unregister periodic sync:', error);
            return false;
        }
    },

    // Event handling

    /**
     * Add event listener
     * @param {string} event - Event name
     * @param {Function} callback - Callback function
     */
    addEventListener(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event].push(callback);
        }
    },

    /**
     * Remove event listener
     * @param {string} event - Event name
     * @param {Function} callback - Callback function
     */
    removeEventListener(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event] = this.listeners[event].filter(
                cb => cb !== callback
            );
        }
    },

    /**
     * Trigger event
     * @private
     * @param {string} event - Event name
     * @param {Object} data - Event data
     */
    _triggerEvent(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`Error in ${event} listener:`, error);
                }
            });
        }

        // Also trigger custom event on window
        window.dispatchEvent(new CustomEvent(`sw:${event}`, {
            detail: data,
            bubbles: true,
            cancelable: false
        }));
    }
};

// Singleton instance
let serviceWorkerInstance = null;

/**
 * Get or create the service worker instance
 * @param {Object} options - Initialization options
 */
function getServiceWorker(options = {}) {
    if (!serviceWorkerInstance) {
        serviceWorkerInstance = Object.create(ServiceWorkerUtils);
        serviceWorkerInstance.init(options);
    }
    return serviceWorkerInstance;
}

/**
 * Initialize service worker
 * @param {Object} options - Initialization options
 */
function initServiceWorker(options = {}) {
    return getServiceWorker(options);
}

/**
 * Reset service worker instance
 */
function resetServiceWorker() {
    if (serviceWorkerInstance) {
        serviceWorkerInstance = null;
    }
}

// Auto-initialize if service worker is supported
if ('serviceWorker' in navigator) {
    // Only auto-initialize if the page is secure (HTTPS) or localhost
    if (window.location.protocol === 'https:' || 
        window.location.hostname === 'localhost' ||
        window.location.hostname === '127.0.0.1') {
        
        // Initialize when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => {
                initServiceWorker();
            });
        } else {
            initServiceWorker();
        }
    }
}

// Export for use in modules
export { 
    ServiceWorkerUtils,
    getServiceWorker,
    initServiceWorker,
    resetServiceWorker
};
