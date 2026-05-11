/**
 * Main Application Initialization for Open-Omniscience
 * Initializes all components and sets up the application
 */

// Import all required modules
import { APIClient, APIError, getAPIClient, resetAPIClient } from './api.js';
import { StorageUtils, SessionStorageUtils } from './utils/storage.js';
import { DOMUtils } from './utils/dom.js';
import { FormatUtils } from './utils/format.js';
import { ValidationUtils } from './utils/validation.js';
import { 
    NotificationManager, 
    AlertManager, 
    NotificationCenter,
    getNotificationManager,
    getAlertManager,
    getNotificationCenter,
    resetNotificationManagers 
} from './components/notifications.js';
import { TableManager, createTableManager } from './components/tables.js';
import { Dashboard, createDashboard } from './pages/dashboard.js';

/**
 * Open-Omniscience Application
 * Main application class that initializes and manages all components
 */
class OpenOmniscienceApp {
    /**
     * Create a new application instance
     * @param {Object} options - Configuration options
     */
    constructor(options = {}) {
        this.options = {
            baseUrl: '',
            debug: false,
            autoInit: true,
            ...options
        };

        this.components = {};
        this.initialized = false;
        this._initialize();
    }

    /**
     * Initialize the application
     * @private
     */
    _initialize() {
        if (this.initialized) return;

        // Set up global error handling
        this._setupErrorHandling();

        // Initialize API client
        this._initializeAPIClient();

        // Initialize utilities
        this._initializeUtilities();

        // Initialize components
        this._initializeComponents();

        // Initialize dashboard
        this._initializeDashboard();

        // Set up global event listeners
        this._setupGlobalEventListeners();

        // Apply theme from localStorage
        this._applyTheme();

        // Mark as initialized
        this.initialized = true;

        // Trigger ready event
        this._triggerReadyEvent();
    }

    /**
     * Setup global error handling
     * @private
     */
    _setupErrorHandling() {
        // Global error handler
        window.addEventListener('error', (event) => {
            console.error('Global error:', event.error);
            this.showError('An unexpected error occurred', event.error);
        });

        // Unhandled promise rejections
        window.addEventListener('unhandledrejection', (event) => {
            console.error('Unhandled rejection:', event.reason);
            this.showError('An unexpected error occurred', event.reason);
        });

        // API error interceptor
        const apiClient = getAPIClient();
        apiClient.addResponseInterceptor(async (response) => {
            if (!response.ok) {
                const error = await apiClient._handleError(response);
                if (error.status === 401 || error.status === 403) {
                    this.showError('Authentication failed', error);
                } else if (error.status >= 500) {
                    this.showError('Server error occurred', error);
                }
            }
            return response;
        });
    }

    /**
     * Initialize API client
     * @private
     */
    _initializeAPIClient() {
        // Configure API client with base URL
        const apiClient = getAPIClient({
            baseUrl: this.options.baseUrl
        });

        // Store reference
        this.components.apiClient = apiClient;

        // Make available globally for debugging
        if (this.options.debug) {
            window.apiClient = apiClient;
        }
    }

    /**
     * Initialize utilities
     * @private
     */
    _initializeUtilities() {
        // Make utilities available globally for debugging
        if (this.options.debug) {
            window.StorageUtils = StorageUtils;
            window.SessionStorageUtils = SessionStorageUtils;
            window.DOMUtils = DOMUtils;
            window.FormatUtils = FormatUtils;
            window.ValidationUtils = ValidationUtils;
        }
    }

    /**
     * Initialize components
     * @private
     */
    _initializeComponents() {
        // Initialize notification manager
        const notificationManager = getNotificationManager({
            containerId: 'toast-container',
            defaultDuration: 5000,
            maxNotifications: 5,
            preventDuplicates: true
        });
        this.components.notificationManager = notificationManager;

        // Initialize alert manager
        const alertManager = getAlertManager({
            containerSelector: '.alert-container'
        });
        this.components.alertManager = alertManager;

        // Initialize notification center
        const notificationCenter = getNotificationCenter({
            panelId: 'notification-center',
            toggleId: 'notification-center-toggle',
            badgeId: 'notification-center-badge'
        });
        this.components.notificationCenter = notificationCenter;

        // Make available globally for debugging
        if (this.options.debug) {
            window.notificationManager = notificationManager;
            window.alertManager = alertManager;
            window.notificationCenter = notificationCenter;
        }
    }

    /**
     * Initialize dashboard
     * @private
     */
    _initializeDashboard() {
        // Initialize dashboard
        const dashboard = createDashboard({
            apiClient: this.components.apiClient,
            autoLoad: true
        });
        this.components.dashboard = dashboard;

        // Make available globally for debugging
        if (this.options.debug) {
            window.dashboard = dashboard;
        }
    }

    /**
     * Setup global event listeners
     * @private
     */
    _setupGlobalEventListeners() {
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            // Ctrl/Cmd + K to focus search (alternative to Ctrl+F)
            if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                e.preventDefault();
                const searchInput = document.querySelector('[name="q"]');
                if (searchInput) {
                    searchInput.focus();
                }
            }

            // Ctrl/Cmd + / to open settings
            if ((e.ctrlKey || e.metaKey) && e.key === '/') {
                e.preventDefault();
                const settingsBtn = document.querySelector('[data-action="open-settings"]');
                if (settingsBtn) {
                    settingsBtn.click();
                }
            }

            // Ctrl/Cmd + R to refresh
            if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                e.preventDefault();
                if (this.components.dashboard) {
                    this.components.dashboard.refresh();
                }
            }
        });

        // Online/offline events
        window.addEventListener('online', () => {
            this.showSuccess('Back online');
            if (this.components.dashboard) {
                this.components.dashboard.refresh();
            }
        });

        window.addEventListener('offline', () => {
            this.showWarning('You are offline. Some features may not work.');
        });

        // Before unload - warn about unsaved changes
        window.addEventListener('beforeunload', (e) => {
            // Check if there are any unsaved changes
            // This could be expanded to check form states, etc.
            const hasUnsavedChanges = false;
            if (hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = 'You have unsaved changes. Are you sure you want to leave?';
                return e.returnValue;
            }
        });

        // Visibility change - pause/resume animations
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                // Pause animations when tab is not visible
                document.body.classList.add('tab-hidden');
            } else {
                // Resume animations when tab becomes visible
                document.body.classList.remove('tab-hidden');
            }
        });
    }

    /**
     * Apply theme from localStorage
     * @private
     */
    _applyTheme() {
        const theme = localStorage.getItem('theme') || 'system';

        if (theme === 'dark') {
            document.documentElement.classList.add('theme-dark');
        } else if (theme === 'light') {
            document.documentElement.classList.add('theme-light');
        } else {
            // System theme - check preference
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            if (prefersDark) {
                document.documentElement.classList.add('theme-dark');
            } else {
                document.documentElement.classList.add('theme-light');
            }
        }

        // Update theme toggle buttons
        const themeToggles = document.querySelectorAll('[data-action="toggle-theme"]');
        themeToggles.forEach(toggle => {
            const icon = toggle.querySelector('i');
            if (theme === 'dark' || 
                (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
                icon.className = 'fas fa-sun';
                toggle.setAttribute('aria-label', 'Switch to light mode');
            } else {
                icon.className = 'fas fa-moon';
                toggle.setAttribute('aria-label', 'Switch to dark mode');
            }
        });
    }

    /**
     * Trigger ready event
     * @private
     */
    _triggerReadyEvent() {
        // Dispatch custom event
        window.dispatchEvent(new CustomEvent('openOmniscience:ready', {
            detail: {
                app: this,
                timestamp: new Date()
            },
            bubbles: true,
            cancelable: false
        }));

        // Log initialization
        if (this.options.debug) {
            console.log('Open-Omniscience application initialized', {
                timestamp: new Date().toISOString(),
                components: Object.keys(this.components)
            });
        }
    }

    // Public methods

    /**
     * Get a component by name
     * @param {string} name - Component name
     * @returns {*} Component instance or null
     */
    getComponent(name) {
        return this.components[name] || null;
    }

    /**
     * Get the API client
     * @returns {APIClient} API client instance
     */
    getAPIClient() {
        return this.components.apiClient || getAPIClient();
    }

    /**
     * Get the dashboard
     * @returns {Dashboard} Dashboard instance
     */
    getDashboard() {
        return this.components.dashboard;
    }

    /**
     * Get the notification manager
     * @returns {NotificationManager} Notification manager instance
     */
    getNotificationManager() {
        return this.components.notificationManager || getNotificationManager();
    }

    /**
     * Show a success notification
     * @param {string} message - Message
     * @param {Object} options - Notification options
     */
    showSuccess(message, options = {}) {
        this.getNotificationManager().success(message, options);
    }

    /**
     * Show an error notification
     * @param {string} message - Message
     * @param {Error} error - Error object
     * @param {Object} options - Notification options
     */
    showError(message, error = null, options = {}) {
        const errorMessage = error ? `${message}: ${error.message}` : message;
        this.getNotificationManager().error(errorMessage, options);
    }

    /**
     * Show a warning notification
     * @param {string} message - Message
     * @param {Object} options - Notification options
     */
    showWarning(message, options = {}) {
        this.getNotificationManager().warning(message, options);
    }

    /**
     * Show an info notification
     * @param {string} message - Message
     * @param {Object} options - Notification options
     */
    showInfo(message, options = {}) {
        this.getNotificationManager().info(message, options);
    }

    /**
     * Refresh all data
     */
    async refresh() {
        if (this.components.dashboard) {
            await this.components.dashboard.refresh();
        }
    }

    /**
     * Destroy the application
     */
    destroy() {
        // Destroy all components
        for (const [name, component] of Object.entries(this.components)) {
            if (component && typeof component.destroy === 'function') {
                component.destroy();
            }
        }

        // Reset singletons
        resetAPIClient();
        resetNotificationManagers();

        // Clear references
        this.components = {};
        this.initialized = false;

        // Trigger destroy event
        window.dispatchEvent(new CustomEvent('openOmniscience:destroy', {
            detail: {
                timestamp: new Date()
            },
            bubbles: true,
            cancelable: false
        }));
    }
}

// Singleton application instance
let appInstance = null;

/**
 * Get or create the application instance
 * @param {Object} options - Configuration options
 * @returns {OpenOmniscienceApp} Application instance
 */
function getApp(options = {}) {
    if (!appInstance) {
        appInstance = new OpenOmniscienceApp(options);
    }
    return appInstance;
}

/**
 * Initialize the application
 * @param {Object} options - Configuration options
 * @returns {OpenOmniscienceApp} Application instance
 */
function initApp(options = {}) {
    return getApp(options);
}

/**
 * Reset the application instance
 */
function resetApp() {
    if (appInstance) {
        appInstance.destroy();
        appInstance = null;
    }
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        // Only auto-initialize if there's a dashboard element
        if (document.querySelector('#results-table') || 
            document.querySelector('.dashboard') ||
            document.querySelector('.page-header')) {
            initApp();
        }
    });
} else {
    // DOM already loaded
    if (document.querySelector('#results-table') || 
        document.querySelector('.dashboard') ||
        document.querySelector('.page-header')) {
        initApp();
    }
}

// Export for use in modules
export { 
    OpenOmniscienceApp, 
    getApp, 
    initApp, 
    resetApp,
    // Re-export all components
    APIClient,
    APIError,
    getAPIClient,
    resetAPIClient,
    StorageUtils,
    SessionStorageUtils,
    DOMUtils,
    FormatUtils,
    ValidationUtils,
    NotificationManager,
    AlertManager,
    NotificationCenter,
    getNotificationManager,
    getAlertManager,
    getNotificationCenter,
    resetNotificationManagers,
    TableManager,
    createTableManager,
    Dashboard,
    createDashboard
};
