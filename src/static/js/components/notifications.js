/**
 * Notifications Component for Open-Omniscience
 * Handles toast notifications, alerts, and notification center
 */

class NotificationManager {
    /**
     * Create a new notification manager
     * @param {Object} options - Configuration options
     * @param {string} options.containerId - ID of the notification container
     * @param {number} options.defaultDuration - Default duration in milliseconds
     * @param {number} options.maxNotifications - Maximum number of notifications to show
     * @param {boolean} options.preventDuplicates - Prevent duplicate notifications
     */
    constructor(options = {}) {
        this.containerId = options.containerId || 'toast-container';
        this.defaultDuration = options.defaultDuration || 5000;
        this.maxNotifications = options.maxNotifications || 5;
        this.preventDuplicates = options.preventDuplicates || true;
        this.notifications = new Map();
        this.queue = [];
        this._ensureContainer();
    }

    /**
     * Ensure the notification container exists
     * @private
     */
    _ensureContainer() {
        let container = document.getElementById(this.containerId);
        if (!container) {
            container = document.createElement('div');
            container.id = this.containerId;
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            container.setAttribute('aria-live', 'polite');
            container.setAttribute('aria-atomic', 'true');
            document.body.appendChild(container);
        }
        this.container = container;
    }

    /**
     * Notification types
     */
    static get TYPES() {
        return {
            SUCCESS: 'success',
            ERROR: 'error',
            WARNING: 'warning',
            INFO: 'info',
            PRIMARY: 'primary',
            SECONDARY: 'secondary'
        };
    }

    /**
     * Notification positions
     */
    static get POSITIONS() {
        return {
            TOP_LEFT: 'top-0 start-0',
            TOP_RIGHT: 'top-0 end-0',
            TOP_CENTER: 'top-0 start-50 translate-middle-x',
            BOTTOM_LEFT: 'bottom-0 start-0',
            BOTTOM_RIGHT: 'bottom-0 end-0',
            BOTTOM_CENTER: 'bottom-0 start-50 translate-middle-x'
        };
    }

    /**
     * Show a notification
     * @param {Object} options - Notification options
     * @param {string} options.message - Notification message
     * @param {string} options.type - Notification type (success, error, warning, info)
     * @param {string} options.title - Notification title
     * @param {number} options.duration - Duration in milliseconds (0 for persistent)
     * @param {string} options.icon - Icon class or HTML
     * @param {Function} options.onClick - Click handler
     * @param {Function} options.onClose - Close handler
     * @param {boolean} options.dismissible - Whether notification can be dismissed
     * @param {string} options.id - Unique notification ID
     * @param {string} options.position - Position override
     * @param {Object} options.data - Additional data
     */
    show(options = {}) {
        const {
            message = '',
            type = NotificationManager.TYPES.INFO,
            title = '',
            duration = this.defaultDuration,
            icon = this._getDefaultIcon(type),
            onClick = null,
            onClose = null,
            dismissible = true,
            id = this._generateId(),
            position = null,
            data = {}
        } = options;

        // Check for duplicates
        if (this.preventDuplicates && this.notifications.has(id)) {
            return null;
        }

        // Check if we need to queue
        if (this.notifications.size >= this.maxNotifications) {
            this.queue.push({ options, id });
            return null;
        }

        // Create notification element
        const notification = this._createNotificationElement({
            id,
            type,
            title,
            message,
            icon,
            dismissible,
            onClick,
            onClose: () => this._handleClose(id, onClose)
        });

        // Position notification
        if (position) {
            notification.className = `toast ${position} m-2`;
        }

        // Add to container
        this.container.appendChild(notification);
        this.notifications.set(id, { element: notification, options, timer: null });

        // Start auto-close timer if duration > 0
        if (duration > 0) {
            const timer = setTimeout(() => {
                this._handleClose(id, onClose);
            }, duration);
            this.notifications.get(id).timer = timer;
        }

        // Trigger event
        notification.dispatchEvent(new CustomEvent('shown', {
            detail: { id, type, title, message, data },
            bubbles: true
        }));

        // Process queue
        this._processQueue();

        return id;
    }

    /**
     * Create notification element
     * @private
     * @param {Object} options - Notification options
     * @returns {HTMLElement} Notification element
     */
    _createNotificationElement(options) {
        const { id, type, title, message, icon, dismissible, onClick, onClose } = options;

        const notification = document.createElement('div');
        notification.className = `toast toast-${type} fade show`;
        notification.setAttribute('role', 'alert');
        notification.setAttribute('aria-live', 'assertive');
        notification.setAttribute('data-notification-id', id);
        notification.setAttribute('data-notification-type', type);

        // Build notification HTML
        const headerId = `toast-header-${id}`;
        const bodyId = `toast-body-${id}`;

        notification.innerHTML = `
            <div class="toast-header text-bg-${type}" id="${headerId}">
                ${icon ? `<span class="toast-icon me-2">${icon}</span>` : ''}
                <strong class="me-auto toast-title">${title || this._getDefaultTitle(type)}</strong>
                ${dismissible ? `<button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast" aria-label="Close"></button>` : ''}
            </div>
            <div class="toast-body" id="${bodyId}">${message}</div>
        `;

        // Add click handler
        if (onClick) {
            notification.addEventListener('click', (e) => {
                // Don't trigger click if clicking close button
                if (e.target.classList.contains('btn-close') || 
                    e.target.closest('.btn-close')) {
                    return;
                }
                onClick(e);
                this._handleClose(id, onClose);
            });
        }

        // Add close button handler
        const closeBtn = notification.querySelector('[data-bs-dismiss="toast"]');
        if (closeBtn) {
            closeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._handleClose(id, onClose);
            });
        }

        // Add keyboard support
        notification.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this._handleClose(id, onClose);
            }
        });

        // Add animation
        notification.style.animation = 'fadeIn 0.3s ease-out';

        return notification;
    }

    /**
     * Get default icon for notification type
     * @private
     * @param {string} type - Notification type
     * @returns {string} Icon HTML
     */
    _getDefaultIcon(type) {
        const icons = {
            success: '<i class="fas fa-check-circle"></i>',
            error: '<i class="fas fa-exclamation-circle"></i>',
            warning: '<i class="fas fa-exclamation-triangle"></i>',
            info: '<i class="fas fa-info-circle"></i>',
            primary: '<i class="fas fa-star"></i>',
            secondary: '<i class="fas fa-circle"></i>'
        };
        return icons[type] || icons.info;
    }

    /**
     * Get default title for notification type
     * @private
     * @param {string} type - Notification type
     * @returns {string} Default title
     */
    _getDefaultTitle(type) {
        const titles = {
            success: 'Success',
            error: 'Error',
            warning: 'Warning',
            info: 'Information',
            primary: 'Notice',
            secondary: 'Update'
        };
        return titles[type] || 'Notification';
    }

    /**
     * Generate unique notification ID
     * @private
     * @returns {string} Unique ID
     */
    _generateId() {
        return `notification-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    }

    /**
     * Handle notification close
     * @private
     * @param {string} id - Notification ID
     * @param {Function} onClose - Close callback
     */
    _handleClose(id, onClose) {
        const notification = this.notifications.get(id);
        if (!notification) return;

        // Clear timer
        if (notification.timer) {
            clearTimeout(notification.timer);
        }

        // Trigger close animation
        notification.element.style.animation = 'fadeOut 0.3s ease-out';

        // Remove after animation
        setTimeout(() => {
            if (notification.element.parentNode) {
                notification.element.parentNode.removeChild(notification.element);
            }
            this.notifications.delete(id);

            // Call close callback
            if (onClose) {
                onClose(id);
            }

            // Trigger event
            notification.element.dispatchEvent(new CustomEvent('hidden', {
                detail: { id },
                bubbles: true
            }));

            // Process queue
            this._processQueue();
        }, 300);
    }

    /**
     * Process notification queue
     * @private
     */
    _processQueue() {
        if (this.queue.length === 0 || this.notifications.size >= this.maxNotifications) {
            return;
        }

        const next = this.queue.shift();
        this.show(next.options);
    }

    /**
     * Hide a notification by ID
     * @param {string} id - Notification ID
     */
    hide(id) {
        this._handleClose(id, null);
    }

    /**
     * Hide all notifications
     */
    hideAll() {
        const ids = Array.from(this.notifications.keys());
        ids.forEach(id => this.hide(id));
    }

    /**
     * Hide all notifications of a specific type
     * @param {string} type - Notification type
     */
    hideByType(type) {
        const ids = Array.from(this.notifications.keys());
        ids.forEach(id => {
            const notification = this.notifications.get(id);
            if (notification && notification.options.type === type) {
                this.hide(id);
            }
        });
    }

    /**
     * Update a notification
     * @param {string} id - Notification ID
     * @param {Object} updates - Updates to apply
     */
    update(id, updates = {}) {
        const notification = this.notifications.get(id);
        if (!notification) return false;

        const { element, options } = notification;
        const newOptions = { ...options, ...updates };

        // Update message
        if (updates.message !== undefined) {
            const body = element.querySelector('.toast-body');
            if (body) {
                body.textContent = updates.message;
            }
        }

        // Update title
        if (updates.title !== undefined) {
            const titleEl = element.querySelector('.toast-title');
            if (titleEl) {
                titleEl.textContent = updates.title || this._getDefaultTitle(newOptions.type);
            }
        }

        // Update type
        if (updates.type !== undefined) {
            element.className = `toast toast-${updates.type} fade show`;
            const header = element.querySelector('.toast-header');
            if (header) {
                header.className = `toast-header text-bg-${updates.type}`;
            }
            const icon = element.querySelector('.toast-icon');
            if (icon) {
                icon.innerHTML = this._getDefaultIcon(updates.type);
            }
        }

        // Update icon
        if (updates.icon !== undefined) {
            const icon = element.querySelector('.toast-icon');
            if (icon) {
                icon.innerHTML = updates.icon;
            }
        }

        // Update notification in map
        notification.options = newOptions;

        return true;
    }

    /**
     * Get a notification by ID
     * @param {string} id - Notification ID
     * @returns {Object|null} Notification object or null
     */
    get(id) {
        return this.notifications.get(id) || null;
    }

    /**
     * Get all active notifications
     * @returns {Array} Array of notification objects
     */
    getAll() {
        return Array.from(this.notifications.values());
    }

    /**
     * Clear all notifications and queue
     */
    clear() {
        this.hideAll();
        this.queue = [];
    }

    /**
     * Show success notification
     * @param {string} message - Message
     * @param {Object} options - Additional options
     */
    success(message, options = {}) {
        return this.show({ 
            message, 
            type: NotificationManager.TYPES.SUCCESS,
            ...options 
        });
    }

    /**
     * Show error notification
     * @param {string} message - Message
     * @param {Object} options - Additional options
     */
    error(message, options = {}) {
        return this.show({ 
            message, 
            type: NotificationManager.TYPES.ERROR,
            duration: 8000, // Longer duration for errors
            ...options 
        });
    }

    /**
     * Show warning notification
     * @param {string} message - Message
     * @param {Object} options - Additional options
     */
    warning(message, options = {}) {
        return this.show({ 
            message, 
            type: NotificationManager.TYPES.WARNING,
            ...options 
        });
    }

    /**
     * Show info notification
     * @param {string} message - Message
     * @param {Object} options - Additional options
     */
    info(message, options = {}) {
        return this.show({ 
            message, 
            type: NotificationManager.TYPES.INFO,
            ...options 
        });
    }

    /**
     * Show primary notification
     * @param {string} message - Message
     * @param {Object} options - Additional options
     */
    primary(message, options = {}) {
        return this.show({ 
            message, 
            type: NotificationManager.TYPES.PRIMARY,
            ...options 
        });
    }

    /**
     * Show secondary notification
     * @param {string} message - Message
     * @param {Object} options - Additional options
     */
    secondary(message, options = {}) {
        return this.show({ 
            message, 
            type: NotificationManager.TYPES.SECONDARY,
            ...options 
        });
    }
}

/**
 * Alert Manager for inline alerts
 */
class AlertManager {
    /**
     * Create a new alert manager
     * @param {Object} options - Configuration options
     * @param {string} options.containerSelector - Selector for alert container
     */
    constructor(options = {}) {
        this.containerSelector = options.containerSelector || '.alert-container';
    }

    /**
     * Alert types
     */
    static get TYPES() {
        return {
            SUCCESS: 'success',
            ERROR: 'danger',
            WARNING: 'warning',
            INFO: 'info',
            PRIMARY: 'primary',
            SECONDARY: 'secondary',
            LIGHT: 'light',
            DARK: 'dark'
        };
    }

    /**
     * Show an alert
     * @param {Object} options - Alert options
     * @param {string} options.message - Alert message
     * @param {string} options.type - Alert type
     * @param {string} options.title - Alert title
     * @param {boolean} options.dismissible - Whether alert can be dismissed
     * @param {Function} options.onClose - Close handler
     * @param {string} options.container - Custom container selector
     * @param {string} options.id - Alert ID
     */
    show(options = {}) {
        const {
            message = '',
            type = AlertManager.TYPES.INFO,
            title = '',
            dismissible = true,
            onClose = null,
            container = this.containerSelector,
            id = `alert-${Date.now()}`
        } = options;

        // Find or create container
        let containerEl = document.querySelector(container);
        if (!containerEl) {
            containerEl = document.createElement('div');
            containerEl.className = 'alert-container';
            document.body.appendChild(containerEl);
        }

        // Create alert element
        const alert = this._createAlertElement({
            id,
            type,
            title,
            message,
            dismissible,
            onClose
        });

        // Add to container
        containerEl.appendChild(alert);

        // Scroll to alert
        alert.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        return id;
    }

    /**
     * Create alert element
     * @private
     * @param {Object} options - Alert options
     * @returns {HTMLElement} Alert element
     */
    _createAlertElement(options) {
        const { id, type, title, message, dismissible, onClose } = options;

        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show`;
        alert.setAttribute('role', 'alert');
        alert.setAttribute('data-alert-id', id);

        const icon = this._getAlertIcon(type);
        const titleText = title || this._getAlertTitle(type);

        alert.innerHTML = `
            <div class="d-flex align-items-center">
                ${icon ? `<span class="alert-icon me-2">${icon}</span>` : ''}
                <div class="flex-grow-1">
                    ${titleText ? `<h5 class="alert-heading mb-1">${titleText}</h5>` : ''}
                    <div class="alert-message">${message}</div>
                </div>
                ${dismissible ? `<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>` : ''}
            </div>
        `;

        // Add close handler
        const closeBtn = alert.querySelector('[data-bs-dismiss="alert"]');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this._handleClose(alert, onClose);
            });
        }

        return alert;
    }

    /**
     * Get alert icon
     * @private
     * @param {string} type - Alert type
     * @returns {string} Icon HTML
     */
    _getAlertIcon(type) {
        const icons = {
            success: '<i class="fas fa-check-circle"></i>',
            danger: '<i class="fas fa-exclamation-circle"></i>',
            warning: '<i class="fas fa-exclamation-triangle"></i>',
            info: '<i class="fas fa-info-circle"></i>',
            primary: '<i class="fas fa-star"></i>',
            secondary: '<i class="fas fa-circle"></i>',
            light: '<i class="fas fa-sun"></i>',
            dark: '<i class="fas fa-moon"></i>'
        };
        return icons[type] || icons.info;
    }

    /**
     * Get alert title
     * @private
     * @param {string} type - Alert type
     * @returns {string} Title
     */
    _getAlertTitle(type) {
        const titles = {
            success: 'Success',
            danger: 'Error',
            warning: 'Warning',
            info: 'Information',
            primary: 'Notice',
            secondary: 'Update',
            light: 'Note',
            dark: 'Alert'
        };
        return titles[type] || '';
    }

    /**
     * Handle alert close
     * @private
     * @param {HTMLElement} alert - Alert element
     * @param {Function} onClose - Close callback
     */
    _handleClose(alert, onClose) {
        alert.style.animation = 'fadeOut 0.3s ease-out';
        setTimeout(() => {
            if (alert.parentNode) {
                alert.parentNode.removeChild(alert);
            }
            if (onClose) {
                onClose();
            }
        }, 300);
    }

    /**
     * Hide an alert by ID
     * @param {string} id - Alert ID
     * @param {string} container - Container selector
     */
    hide(id, container = this.containerSelector) {
        const containerEl = document.querySelector(container);
        if (!containerEl) return;

        const alert = containerEl.querySelector(`[data-alert-id="${id}"]`);
        if (alert) {
            this._handleClose(alert, null);
        }
    }

    /**
     * Hide all alerts in a container
     * @param {string} container - Container selector
     */
    hideAll(container = this.containerSelector) {
        const containerEl = document.querySelector(container);
        if (!containerEl) return;

        const alerts = containerEl.querySelectorAll('.alert');
        alerts.forEach(alert => this._handleClose(alert, null));
    }

    /**
     * Clear all alerts
     */
    clear() {
        document.querySelectorAll('.alert-container').forEach(container => {
            this.hideAll(`#${container.id}`);
        });
    }
}

/**
 * Notification Center for persistent notifications
 */
class NotificationCenter {
    /**
     * Create a new notification center
     * @param {Object} options - Configuration options
     */
    constructor(options = {}) {
        this.panelId = options.panelId || 'notification-center';
        this.toggleId = options.toggleId || 'notification-center-toggle';
        this.badgeId = options.badgeId || 'notification-center-badge';
        this.notifications = [];
        this.unreadCount = 0;
        this._initialize();
    }

    /**
     * Initialize notification center
     * @private
     */
    _initialize() {
        // Create panel if it doesn't exist
        let panel = document.getElementById(this.panelId);
        if (!panel) {
            panel = document.createElement('div');
            panel.id = this.panelId;
            panel.className = 'notification-center offcanvas offcanvas-end';
            panel.setAttribute('tabindex', '-1');
            panel.innerHTML = `
                <div class="offcanvas-header">
                    <h5 class="offcanvas-title">Notifications</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
                </div>
                <div class="offcanvas-body">
                    <div class="notification-center-tabs mb-3">
                        <button class="btn btn-sm btn-outline-primary active" data-filter="all">All</button>
                        <button class="btn btn-sm btn-outline-primary ms-2" data-filter="unread">Unread</button>
                    </div>
                    <div class="notification-center-list"></div>
                </div>
                <div class="offcanvas-footer p-3 border-top">
                    <button class="btn btn-sm btn-outline-secondary me-2" data-action="mark-all-read">Mark all as read</button>
                    <button class="btn btn-sm btn-outline-danger" data-action="clear-all">Clear all</button>
                </div>
            `;
            document.body.appendChild(panel);
        }
        this.panel = panel;
        this.listEl = panel.querySelector('.notification-center-list');

        // Create toggle button if it doesn't exist
        let toggle = document.getElementById(this.toggleId);
        if (!toggle) {
            toggle = document.createElement('button');
            toggle.id = this.toggleId;
            toggle.className = 'btn btn-outline-secondary position-relative';
            toggle.setAttribute('data-bs-toggle', 'offcanvas');
            toggle.setAttribute('data-bs-target', `#${this.panelId}`);
            toggle.setAttribute('aria-controls', this.panelId);
            toggle.innerHTML = '<i class="fas fa-bell"></i> <span class="badge bg-danger" id="' + this.badgeId + '">0</span>';
            // Add to header or appropriate location
            const header = document.querySelector('.page-header') || document.querySelector('header');
            if (header) {
                header.appendChild(toggle);
            } else {
                document.body.appendChild(toggle);
            }
        }
        this.toggle = toggle;
        this.badge = document.getElementById(this.badgeId);

        // Setup event listeners
        this._setupEvents();
    }

    /**
     * Setup event listeners
     * @private
     */
    _setupEvents() {
        // Filter buttons
        const filterBtns = this.panel.querySelectorAll('[data-filter]');
        filterBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                filterBtns.forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this._filterNotifications(e.target.dataset.filter);
            });
        });

        // Action buttons
        const actionBtns = this.panel.querySelectorAll('[data-action]');
        actionBtns.forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.target.dataset.action;
                switch (action) {
                    case 'mark-all-read':
                        this.markAllAsRead();
                        break;
                    case 'clear-all':
                        this.clearAll();
                        break;
                }
            });
        });
    }

    /**
     * Add a notification to the center
     * @param {Object} notification - Notification object
     */
    add(notification = {}) {
        const {
            id = `nc-${Date.now()}`,
            title = 'Notification',
            message = '',
            type = 'info',
            icon = this._getIcon(type),
            time = new Date(),
            read = false,
            data = {}
        } = notification;

        const existingIndex = this.notifications.findIndex(n => n.id === id);
        if (existingIndex >= 0) {
            // Update existing notification
            this.notifications[existingIndex] = { ...this.notifications[existingIndex], ...notification };
        } else {
            // Add new notification
            this.notifications.unshift({ id, title, message, type, icon, time, read, data });
            if (!read) {
                this.unreadCount++;
            }
        }

        this._updateBadge();
        this._renderList();
        this._saveToStorage();

        return id;
    }

    /**
     * Get icon for notification type
     * @private
     * @param {string} type - Notification type
     * @returns {string} Icon HTML
     */
    _getIcon(type) {
        const icons = {
            success: '<i class="fas fa-check-circle text-success"></i>',
            error: '<i class="fas fa-exclamation-circle text-danger"></i>',
            warning: '<i class="fas fa-exclamation-triangle text-warning"></i>',
            info: '<i class="fas fa-info-circle text-info"></i>'
        };
        return icons[type] || icons.info;
    }

    /**
     * Update badge count
     * @private
     */
    _updateBadge() {
        if (this.badge) {
            this.badge.textContent = this.unreadCount;
            this.badge.style.display = this.unreadCount > 0 ? 'inline' : 'none';
        }
    }

    /**
     * Render notification list
     * @private
     */
    _renderList() {
        if (!this.listEl) return;

        const activeFilter = this.panel.querySelector('[data-filter].active')?.dataset.filter || 'all';
        let notifications = this.notifications;

        if (activeFilter === 'unread') {
            notifications = notifications.filter(n => !n.read);
        }

        this.listEl.innerHTML = notifications.map(notification => this._createNotificationItem(notification)).join('');
    }

    /**
     * Create notification item HTML
     * @private
     * @param {Object} notification - Notification object
     * @returns {string} HTML string
     */
    _createNotificationItem(notification) {
        const { id, title, message, type, icon, time, read } = notification;
        const timeAgo = this._formatTimeAgo(time);
        const unreadClass = read ? '' : 'notification-unread';

        return `
            <div class="notification-item ${unreadClass}" data-notification-id="${id}">
                <div class="notification-icon me-3">${icon}</div>
                <div class="notification-content flex-grow-1">
                    <div class="notification-header d-flex justify-content-between align-items-center">
                        <h6 class="notification-title mb-0">${title}</h6>
                        <small class="notification-time text-muted">${timeAgo}</small>
                    </div>
                    <div class="notification-message">${message}</div>
                </div>
                <div class="notification-actions ms-3">
                    <button class="btn btn-sm btn-outline-${type} notification-action-read" 
                            data-action="mark-read" 
                            data-notification-id="${id}" 
                            title="Mark as read">
                        <i class="fas fa-envelope-open"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger notification-action-remove" 
                            data-action="remove" 
                            data-notification-id="${id}" 
                            title="Remove">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `;
    }

    /**
     * Format time ago
     * @private
     * @param {Date} date - Date object
     * @returns {string} Formatted time ago string
     */
    _formatTimeAgo(date) {
        const now = new Date();
        const diff = now - new Date(date);
        
        const seconds = Math.floor(diff / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);

        if (days > 0) {
            return `${days}d ago`;
        } else if (hours > 0) {
            return `${hours}h ago`;
        } else if (minutes > 0) {
            return `${minutes}m ago`;
        } else if (seconds > 0) {
            return `${seconds}s ago`;
        }
        return 'Just now';
    }

    /**
     * Filter notifications
     * @private
     * @param {string} filter - Filter type (all, unread)
     */
    _filterNotifications(filter) {
        this._renderList();
    }

    /**
     * Mark notification as read
     * @param {string} id - Notification ID
     */
    markAsRead(id) {
        const notification = this.notifications.find(n => n.id === id);
        if (notification && !notification.read) {
            notification.read = true;
            this.unreadCount--;
            this._updateBadge();
            this._renderList();
            this._saveToStorage();
        }
    }

    /**
     * Mark all notifications as read
     */
    markAllAsRead() {
        let changed = false;
        this.notifications.forEach(notification => {
            if (!notification.read) {
                notification.read = true;
                changed = true;
            }
        });
        
        if (changed) {
            this.unreadCount = 0;
            this._updateBadge();
            this._renderList();
            this._saveToStorage();
        }
    }

    /**
     * Remove a notification
     * @param {string} id - Notification ID
     */
    remove(id) {
        const index = this.notifications.findIndex(n => n.id === id);
        if (index >= 0) {
            const notification = this.notifications[index];
            if (!notification.read) {
                this.unreadCount--;
            }
            this.notifications.splice(index, 1);
            this._updateBadge();
            this._renderList();
            this._saveToStorage();
        }
    }

    /**
     * Clear all notifications
     */
    clearAll() {
        this.notifications = [];
        this.unreadCount = 0;
        this._updateBadge();
        this._renderList();
        this._saveToStorage();
    }

    /**
     * Get notification by ID
     * @param {string} id - Notification ID
     * @returns {Object|null} Notification or null
     */
    get(id) {
        return this.notifications.find(n => n.id === id) || null;
    }

    /**
     * Get all notifications
     * @returns {Array} Array of notifications
     */
    getAll() {
        return [...this.notifications];
    }

    /**
     * Get unread count
     * @returns {number} Unread count
     */
    getUnreadCount() {
        return this.unreadCount;
    }

    /**
     * Save notifications to localStorage
     * @private
     */
    _saveToStorage() {
        try {
            const data = this.notifications.map(n => ({
                id: n.id,
                title: n.title,
                message: n.message,
                type: n.type,
                time: n.time.toISOString(),
                read: n.read,
                data: n.data
            }));
            localStorage.setItem(`${this.panelId}-notifications`, JSON.stringify(data));
        } catch (e) {
            console.warn('Failed to save notifications to storage:', e);
        }
    }

    /**
     * Load notifications from localStorage
     */
    loadFromStorage() {
        try {
            const data = localStorage.getItem(`${this.panelId}-notifications`);
            if (data) {
                const parsed = JSON.parse(data);
                this.notifications = parsed.map(n => ({
                    ...n,
                    time: new Date(n.time),
                    icon: this._getIcon(n.type)
                }));
                this.unreadCount = this.notifications.filter(n => !n.read).length;
                this._updateBadge();
                this._renderList();
            }
        } catch (e) {
            console.warn('Failed to load notifications from storage:', e);
        }
    }

    /**
     * Show the notification center
     */
    show() {
        const offcanvas = new bootstrap.Offcanvas(this.panel);
        offcanvas.show();
    }

    /**
     * Hide the notification center
     */
    hide() {
        const offcanvas = bootstrap.Offcanvas.getInstance(this.panel);
        if (offcanvas) {
            offcanvas.hide();
        }
    }

    /**
     * Toggle the notification center
     */
    toggle() {
        const offcanvas = bootstrap.Offcanvas.getInstance(this.panel);
        if (offcanvas) {
            offcanvas.toggle();
        }
    }
}

// Singleton instances
let notificationManager = null;
let alertManager = null;
let notificationCenter = null;

/**
 * Get or create the notification manager
 * @param {Object} options - Configuration options
 */
function getNotificationManager(options = {}) {
    if (!notificationManager) {
        notificationManager = new NotificationManager(options);
    }
    return notificationManager;
}

/**
 * Get or create the alert manager
 * @param {Object} options - Configuration options
 */
function getAlertManager(options = {}) {
    if (!alertManager) {
        alertManager = new AlertManager(options);
    }
    return alertManager;
}

/**
 * Get or create the notification center
 * @param {Object} options - Configuration options
 */
function getNotificationCenter(options = {}) {
    if (!notificationCenter) {
        notificationCenter = new NotificationCenter(options);
    }
    return notificationCenter;
}

/**
 * Reset all managers (useful for testing)
 */
function resetNotificationManagers() {
    notificationManager = null;
    alertManager = null;
    notificationCenter = null;
}

// Export for use in modules
export { 
    NotificationManager, 
    AlertManager, 
    NotificationCenter,
    getNotificationManager,
    getAlertManager,
    getNotificationCenter,
    resetNotificationManagers
};
