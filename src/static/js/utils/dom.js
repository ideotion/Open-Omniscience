/**
 * Open Omniscience - DOM Utilities
 * Helper functions for DOM manipulation
 */

const DOMUtils = {
    /**
     * Create a DOM element
     * @param {string} tag - HTML tag name
     * @param {Object} options - Element options
     * @param {string} [options.className] - Class name(s)
     * @param {string} [options.id] - Element ID
     * @param {string} [options.text] - Text content
     * @param {string} [options.html] - HTML content
     * @param {Object} [options.attributes] - Attributes to set
     * @param {Object} [options.dataset] - Data attributes
     * @param {Object} [options.styles] - CSS styles
     * @param {HTMLElement[]} [options.children] - Child elements
     * @returns {HTMLElement} The created element
     */
    createElement(tag, options = {}) {
        const element = document.createElement(tag);
        
        if (options.className) {
            element.className = options.className;
        }
        
        if (options.id) {
            element.id = options.id;
        }
        
        if (options.text) {
            element.textContent = options.text;
        }
        
        if (options.html) {
            element.innerHTML = options.html;
        }
        
        if (options.attributes) {
            for (const [key, value] of Object.entries(options.attributes)) {
                element.setAttribute(key, value);
            }
        }
        
        if (options.dataset) {
            for (const [key, value] of Object.entries(options.dataset)) {
                element.dataset[key] = value;
            }
        }
        
        if (options.styles) {
            Object.assign(element.style, options.styles);
        }
        
        if (options.children) {
            for (const child of options.children) {
                element.appendChild(child);
            }
        }
        
        return element;
    },

    /**
     * Create an icon element
     * @param {string} iconClass - Font Awesome icon class (e.g., 'fa-search')
     * @param {Object} options - Icon options
     * @returns {HTMLElement} The created icon element
     */
    createIcon(iconClass, options = {}) {
        const icon = this.createElement('i', {
            className: `fas ${iconClass} ${options.className || ''}`,
            ...options
        });
        icon.setAttribute('aria-hidden', 'true');
        return icon;
    },

    /**
     * Create a button element
     * @param {Object} options - Button options
     * @param {string} [options.text] - Button text
     * @param {string} [options.icon] - Font Awesome icon class
     * @param {string} [options.className] - Additional class names
     * @param {Function} [options.onClick] - Click handler
     * @param {string} [options.type] - Button type
     * @param {boolean} [options.disabled] - Disabled state
     * @param {string} [options.title] - Tooltip title
     * @param {string} [options.ariaLabel] - ARIA label
     * @returns {HTMLButtonElement} The created button
     */
    createButton(options = {}) {
        const button = this.createElement('button', {
            className: `btn ${options.className || ''}`,
            text: options.text,
            type: options.type || 'button',
            disabled: options.disabled || false,
            title: options.title,
            attributes: {
                'aria-label': options.ariaLabel
            }
        });
        
        if (options.icon) {
            const icon = this.createIcon(options.icon);
            if (options.text) {
                button.insertBefore(icon, button.firstChild);
                button.insertBefore(document.createTextNode(' '), icon.nextSibling);
            } else {
                button.appendChild(icon);
            }
        }
        
        if (options.onClick) {
            button.addEventListener('click', options.onClick);
        }
        
        return button;
    },

    /**
     * Create a toast notification
     * @param {Object} options - Toast options
     * @param {string} options.message - Toast message
     * @param {string} [options.title] - Toast title
     * @param {string} [options.type='info'] - Toast type (info, success, warning, error, primary)
     * @param {number} [options.duration=5000] - Auto-close duration in ms (0 for no auto-close)
     * @param {boolean} [options.dismissible=true] - Whether toast can be dismissed
     * @param {string} [options.position='top-right'] - Toast position
     * @param {Function} [options.onClose] - Callback when toast closes
     * @returns {Object} Toast object with close method
     */
    createToast(options = {}) {
        const toastContainer = document.getElementById(options.containerId || 'toastContainer');
        if (!toastContainer) {
            console.warn('Toast container not found');
            return { close: () => {} };
        }
        
        const toast = this.createElement('div', {
            className: `toast toast-${options.type || 'info'}`
        });
        
        const toastContent = this.createElement('div', { className: 'toast-content' });
        
        if (options.title) {
            const title = this.createElement('div', {
                className: 'toast-title',
                text: options.title
            });
            toastContent.appendChild(title);
        }
        
        if (options.message) {
            const message = this.createElement('div', {
                className: 'toast-message',
                text: options.message
            });
            toastContent.appendChild(message);
        }
        
        if (options.icon) {
            const icon = this.createIcon(options.icon, { className: 'toast-icon' });
            toast.insertBefore(icon, toastContent);
        } else if (options.type) {
            // Default icons for each type
            const typeIcons = {
                success: 'fa-check-circle',
                error: 'fa-exclamation-circle',
                warning: 'fa-exclamation-triangle',
                info: 'fa-info-circle',
                primary: 'fa-star'
            };
            const iconClass = typeIcons[options.type] || 'fa-info-circle';
            const icon = this.createIcon(iconClass, { className: 'toast-icon' });
            toast.insertBefore(icon, toastContent);
        }
        
        toast.appendChild(toastContent);
        
        if (options.dismissible !== false) {
            const closeBtn = this.createElement('button', {
                className: 'toast-close',
                html: '<i class="fas fa-times" aria-hidden="true"></i>',
                title: 'Close',
                attributes: {
                    'aria-label': 'Close notification'
                }
            });
            closeBtn.addEventListener('click', () => close());
            toast.appendChild(closeBtn);
        }
        
        // Add to container
        toastContainer.appendChild(toast);
        
        // Trigger animation
        setTimeout(() => {
            toast.classList.add('active');
        }, 10);
        
        // Auto-close
        let timeoutId = null;
        if (options.duration && options.duration > 0) {
            timeoutId = setTimeout(() => {
                close();
            }, options.duration);
        }
        
        // Close function
        const close = () => {
            if (timeoutId) {
                clearTimeout(timeoutId);
            }
            toast.classList.add('hiding');
            toast.classList.remove('active');
            
            // Remove from DOM after animation
            setTimeout(() => {
                if (toast.parentNode) {
                    toast.parentNode.removeChild(toast);
                }
                if (options.onClose) {
                    options.onClose();
                }
            }, 300);
        };
        
        return { close };
    },

    /**
     * Show a loading state
     * @param {HTMLElement|string} element - Element or selector to show loading state
     * @param {Object} options - Loading options
     * @param {string} [options.message='Loading...'] - Loading message
     * @param {string} [options.submessage] - Submessage
     * @param {boolean} [options.overlay=true] - Whether to show overlay
     */
    showLoading(element, options = {}) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        } else {
            targetElement = document.body;
        }
        
        if (!targetElement) {
            console.warn('Loading target element not found');
            return;
        }
        
        // Create loading overlay if needed
        if (options.overlay !== false) {
            const loadingOverlay = this.createElement('div', {
                className: 'loading-overlay',
                styles: {
                    display: 'flex',
                    position: 'fixed',
                    top: '0',
                    left: '0',
                    right: '0',
                    bottom: '0',
                    backgroundColor: 'rgba(0, 0, 0, 0.5)',
                    zIndex: '9999',
                    alignItems: 'center',
                    justifyContent: 'center'
                }
            });
            
            const loadingContent = this.createElement('div', {
                className: 'loading-content',
                styles: {
                    backgroundColor: 'var(--container-bg)',
                    padding: '2rem',
                    borderRadius: 'var(--radius-xl)',
                    textAlign: 'center',
                    boxShadow: 'var(--shadow-xl)',
                    maxWidth: '400px'
                }
            });
            
            const spinner = this.createElement('div', {
                className: 'loading-spinner',
                styles: {
                    width: '60px',
                    height: '60px',
                    border: '6px solid var(--border-color)',
                    borderTopColor: 'var(--primary-color)',
                    borderRadius: '50%',
                    animation: 'loading-spin 1s linear infinite',
                    margin: '0 auto 1rem'
                }
            });
            
            const message = this.createElement('p', {
                className: 'loading-message',
                text: options.message || 'Loading...',
                styles: {
                    fontSize: 'var(--text-lg)',
                    color: 'var(--text-primary)',
                    marginBottom: '0.5rem'
                }
            });
            
            if (options.submessage) {
                const submessage = this.createElement('p', {
                    className: 'loading-submessage',
                    text: options.submessage,
                    styles: {
                        fontSize: 'var(--text-sm)',
                        color: 'var(--text-secondary)'
                    }
                });
                loadingContent.appendChild(submessage);
            }
            
            loadingContent.appendChild(spinner);
            loadingContent.appendChild(message);
            loadingOverlay.appendChild(loadingContent);
            
            document.body.appendChild(loadingOverlay);
            
            // Store reference for cleanup
            targetElement._loadingOverlay = loadingOverlay;
        }
    },

    /**
     * Hide loading state
     * @param {HTMLElement|string} element - Element or selector
     */
    hideLoading(element) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        } else {
            // Try to find any loading overlay
            const overlays = document.querySelectorAll('.loading-overlay');
            if (overlays.length > 0) {
                overlays.forEach(overlay => overlay.remove());
                return;
            }
            return;
        }
        
        if (targetElement && targetElement._loadingOverlay) {
            targetElement._loadingOverlay.remove();
            delete targetElement._loadingOverlay;
        }
    },

    /**
     * Toggle element visibility
     * @param {HTMLElement|string} element - Element or selector
     * @param {boolean} [visible] - Visibility state (toggle if undefined)
     * @param {string} [display='block'] - Display style when visible
     */
    toggleVisibility(element, visible, display = 'block') {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return;
        }
        
        if (visible === true) {
            targetElement.style.display = display;
            targetElement.setAttribute('aria-hidden', 'false');
        } else if (visible === false) {
            targetElement.style.display = 'none';
            targetElement.setAttribute('aria-hidden', 'true');
        } else {
            // Toggle
            if (targetElement.style.display === 'none' || targetElement.style.display === '') {
                targetElement.style.display = display;
                targetElement.setAttribute('aria-hidden', 'false');
            } else {
                targetElement.style.display = 'none';
                targetElement.setAttribute('aria-hidden', 'true');
            }
        }
    },

    /**
     * Show element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} [display='block'] - Display style
     */
    show(element, display = 'block') {
        this.toggleVisibility(element, true, display);
    },

    /**
     * Hide element
     * @param {HTMLElement|string} element - Element or selector
     */
    hide(element) {
        this.toggleVisibility(element, false);
    },

    /**
     * Add class to element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} className - Class name to add
     */
    addClass(element, className) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (targetElement) {
            targetElement.classList.add(className);
        }
    },

    /**
     * Remove class from element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} className - Class name to remove
     */
    removeClass(element, className) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (targetElement) {
            targetElement.classList.remove(className);
        }
    },

    /**
     * Toggle class on element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} className - Class name to toggle
     * @param {boolean} [force] - Force add or remove
     */
    toggleClass(element, className, force) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (targetElement) {
            targetElement.classList.toggle(className, force);
        }
    },

    /**
     * Check if element has class
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} className - Class name to check
     * @returns {boolean} True if element has the class
     */
    hasClass(element, className) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        return targetElement ? targetElement.classList.contains(className) : false;
    },

    /**
     * Get or set attribute on element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} name - Attribute name
     * @param {string} [value] - Attribute value (if setting)
     * @returns {string|undefined} Attribute value if getting
     */
    attr(element, name, value) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return undefined;
        }
        
        if (value !== undefined) {
            targetElement.setAttribute(name, value);
            return undefined;
        }
        
        return targetElement.getAttribute(name);
    },

    /**
     * Get or set data attribute on element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} name - Data attribute name (without 'data-' prefix)
     * @param {string} [value] - Data attribute value (if setting)
     * @returns {string|undefined} Data attribute value if getting
     */
    data(element, name, value) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return undefined;
        }
        
        if (value !== undefined) {
            targetElement.dataset[name] = value;
            return undefined;
        }
        
        return targetElement.dataset[name];
    },

    /**
     * Get or set CSS style on element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string|Object} name - CSS property name or object of properties
     * @param {string} [value] - CSS property value (if setting single property)
     * @returns {string|Object|undefined} CSS property value or all styles if getting
     */
    css(element, name, value) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return undefined;
        }
        
        if (typeof name === 'object') {
            // Set multiple styles
            Object.assign(targetElement.style, name);
            return undefined;
        }
        
        if (value !== undefined) {
            // Set single style
            targetElement.style[name] = value;
            return undefined;
        }
        
        // Get single style
        return targetElement.style[name] || getComputedStyle(targetElement)[name];
    },

    /**
     * Get element dimensions
     * @param {HTMLElement|string} element - Element or selector
     * @returns {Object} Object with width, height, offsetWidth, offsetHeight
     */
    getDimensions(element) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return { width: 0, height: 0, offsetWidth: 0, offsetHeight: 0 };
        }
        
        return {
            width: targetElement.clientWidth,
            height: targetElement.clientHeight,
            offsetWidth: targetElement.offsetWidth,
            offsetHeight: targetElement.offsetHeight,
            scrollWidth: targetElement.scrollWidth,
            scrollHeight: targetElement.scrollHeight
        };
    },

    /**
     * Get element position relative to viewport
     * @param {HTMLElement|string} element - Element or selector
     * @returns {Object} Object with top, left, right, bottom, width, height
     */
    getPosition(element) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };
        }
        
        const rect = targetElement.getBoundingClientRect();
        
        return {
            top: rect.top,
            left: rect.left,
            right: rect.right,
            bottom: rect.bottom,
            width: rect.width,
            height: rect.height
        };
    },

    /**
     * Check if element is in viewport
     * @param {HTMLElement|string} element - Element or selector
     * @param {Object} [options] - Options
     * @param {boolean} [options.partial=false] - Whether partial visibility counts
     * @returns {boolean} True if element is in viewport
     */
    isInViewport(element, options = {}) {
        const position = this.getPosition(element);
        const { partial = false } = options;
        
        const viewport = {
            top: 0,
            left: 0,
            right: window.innerWidth,
            bottom: window.innerHeight
        };
        
        if (partial) {
            return !(
                position.bottom < viewport.top ||
                position.top > viewport.bottom ||
                position.right < viewport.left ||
                position.left > viewport.right
            );
        }
        
        return (
            position.top >= viewport.top &&
            position.left >= viewport.left &&
            position.bottom <= viewport.bottom &&
            position.right <= viewport.right
        );
    },

    /**
     * Scroll element into view
     * @param {HTMLElement|string} element - Element or selector
     * @param {Object} [options] - Scroll options
     * @param {boolean} [options.smooth=true] - Smooth scrolling
     * @param {string} [options.position='start'] - Position to scroll to (start, center, end, nearest)
     */
    scrollIntoView(element, options = {}) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (targetElement) {
            targetElement.scrollIntoView({
                behavior: options.smooth !== false ? 'smooth' : 'auto',
                block: options.position || 'start',
                inline: 'nearest'
            });
        }
    },

    /**
     * Focus element
     * @param {HTMLElement|string} element - Element or selector
     * @param {Object} [options] - Focus options
     * @param {boolean} [options.select=true] - Select text content
     * @param {boolean} [options.scroll=true] - Scroll into view
     */
    focus(element, options = {}) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return;
        }
        
        if (options.scroll !== false) {
            this.scrollIntoView(targetElement);
        }
        
        targetElement.focus();
        
        if (options.select !== false && targetElement.select) {
            targetElement.select();
        }
    },

    /**
     * Trigger event on element
     * @param {HTMLElement|string} element - Element or selector
     * @param {string} eventName - Event name
     * @param {Object} [detail] - Event detail
     * @param {Object} [options] - Event options
     * @returns {boolean} True if event was triggered
     */
    triggerEvent(element, eventName, detail = {}, options = {}) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return false;
        }
        
        const event = new CustomEvent(eventName, {
            detail,
            bubbles: options.bubbles !== false,
            cancelable: options.cancelable !== false,
            composed: options.composed !== false
        });
        
        return targetElement.dispatchEvent(event);
    },

    /**
     * Debounce function
     * @param {Function} func - Function to debounce
     * @param {number} wait - Wait time in milliseconds
     * @param {Object} [options] - Options
     * @param {boolean} [options.immediate=false] - Trigger immediately on first call
     * @returns {Function} Debounced function
     */
    debounce(func, wait, options = {}) {
        let timeout;
        let args;
        let context;
        let timestamp;
        let result;
        
        const later = () => {
            const last = Date.now() - timestamp;
            
            if (last < wait && last >= 0) {
                timeout = setTimeout(later, wait - last);
            } else {
                timeout = null;
                if (!options.immediate) {
                    result = func.apply(context, args);
                    if (!timeout) {
                        context = args = null;
                    }
                }
            }
        };
        
        return function() {
            context = this;
            args = arguments;
            timestamp = Date.now();
            
            const callNow = options.immediate && !timeout;
            
            if (!timeout) {
                timeout = setTimeout(later, wait);
            }
            
            if (callNow) {
                result = func.apply(context, args);
                context = args = null;
            }
            
            return result;
        };
    },

    /**
     * Throttle function
     * @param {Function} func - Function to throttle
     * @param {number} limit - Maximum calls per wait period
     * @param {number} wait - Wait time in milliseconds
     * @returns {Function} Throttled function
     */
    throttle(func, limit, wait) {
        let inThrottle;
        let lastFunc;
        let lastRan;
        
        return function() {
            const context = this;
            const args = arguments;
            
            if (!inThrottle) {
                func.apply(context, args);
                lastRan = Date.now();
                inThrottle = true;
            } else {
                clearTimeout(lastFunc);
                lastFunc = setTimeout(() => {
                    if (Date.now() - lastRan >= wait) {
                        func.apply(context, args);
                        lastRan = Date.now();
                    }
                    inThrottle = false;
                }, wait - (Date.now() - lastRan));
            }
        };
    },

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    escapeHtml(text) {
        if (!text) return '';
        
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /**
     * Unescape HTML
     * @param {string} text - Text to unescape
     * @returns {string} Unescaped text
     */
    unescapeHtml(text) {
        if (!text) return '';
        
        const div = document.createElement('div');
        div.innerHTML = text;
        return div.textContent;
    },

    /**
     * Sanitize text for safe display
     * @param {string} text - Text to sanitize
     * @param {number} [maxLength] - Maximum length
     * @returns {string} Sanitized text
     */
    sanitizeText(text, maxLength) {
        if (!text) return '';
        
        let sanitized = this.escapeHtml(text.toString());
        
        if (maxLength && sanitized.length > maxLength) {
            sanitized = sanitized.substring(0, maxLength) + '...';
        }
        
        return sanitized;
    },

    /**
     * Check if element is visible
     * @param {HTMLElement|string} element - Element or selector
     * @returns {boolean} True if element is visible
     */
    isVisible(element) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (!targetElement) {
            return false;
        }
        
        const style = window.getComputedStyle(targetElement);
        return (
            style.display !== 'none' &&
            style.visibility !== 'hidden' &&
            style.opacity !== '0' &&
            targetElement.offsetWidth > 0 &&
            targetElement.offsetHeight > 0
        );
    },

    /**
     * Find closest ancestor matching selector
     * @param {HTMLElement} element - Starting element
     * @param {string} selector - CSS selector
     * @returns {HTMLElement|null} Closest matching ancestor or null
     */
    closest(element, selector) {
        if (!element) return null;
        
        if (element.matches(selector)) {
            return element;
        }
        
        return this.closest(element.parentElement, selector);
    },

    /**
     * Find all elements matching selector within container
     * @param {HTMLElement|string} container - Container element or selector
     * @param {string} selector - CSS selector
     * @returns {HTMLElement[]} Array of matching elements
     */
    findAll(container, selector) {
        let targetContainer;
        
        if (typeof container === 'string') {
            targetContainer = document.querySelector(container);
        } else if (container instanceof HTMLElement) {
            targetContainer = container;
        } else {
            targetContainer = document;
        }
        
        if (!targetContainer) {
            return [];
        }
        
        return Array.from(targetContainer.querySelectorAll(selector));
    },

    /**
     * Empty element (remove all children)
     * @param {HTMLElement|string} element - Element or selector
     */
    empty(element) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (targetElement) {
            while (targetElement.firstChild) {
                targetElement.removeChild(targetElement.firstChild);
            }
        }
    },

    /**
     * Remove element from DOM
     * @param {HTMLElement|string} element - Element or selector
     */
    remove(element) {
        let targetElement;
        
        if (typeof element === 'string') {
            targetElement = document.querySelector(element);
        } else if (element instanceof HTMLElement) {
            targetElement = element;
        }
        
        if (targetElement && targetElement.parentNode) {
            targetElement.parentNode.removeChild(targetElement);
        }
    },

    /**
     * Replace element with new element
     * @param {HTMLElement|string} oldElement - Element or selector to replace
     * @param {HTMLElement} newElement - New element
     */
    replace(oldElement, newElement) {
        let targetElement;
        
        if (typeof oldElement === 'string') {
            targetElement = document.querySelector(oldElement);
        } else if (oldElement instanceof HTMLElement) {
            targetElement = oldElement;
        }
        
        if (targetElement && targetElement.parentNode) {
            targetElement.parentNode.replaceChild(newElement, targetElement);
        }
    },

    /**
     * Insert element after another element
     * @param {HTMLElement} newElement - New element to insert
     * @param {HTMLElement|string} referenceElement - Reference element or selector
     */
    insertAfter(newElement, referenceElement) {
        let targetElement;
        
        if (typeof referenceElement === 'string') {
            targetElement = document.querySelector(referenceElement);
        } else if (referenceElement instanceof HTMLElement) {
            targetElement = referenceElement;
        }
        
        if (targetElement && targetElement.parentNode) {
            targetElement.parentNode.insertBefore(newElement, targetElement.nextSibling);
        }
    },

    /**
     * Insert element before another element
     * @param {HTMLElement} newElement - New element to insert
     * @param {HTMLElement|string} referenceElement - Reference element or selector
     */
    insertBefore(newElement, referenceElement) {
        let targetElement;
        
        if (typeof referenceElement === 'string') {
            targetElement = document.querySelector(referenceElement);
        } else if (referenceElement instanceof HTMLElement) {
            targetElement = referenceElement;
        }
        
        if (targetElement && targetElement.parentNode) {
            targetElement.parentNode.insertBefore(newElement, targetElement);
        }
    },

    /**
     * Prepend element to container
     * @param {HTMLElement} newElement - New element to prepend
     * @param {HTMLElement|string} container - Container element or selector
     */
    prepend(newElement, container) {
        let targetContainer;
        
        if (typeof container === 'string') {
            targetContainer = document.querySelector(container);
        } else if (container instanceof HTMLElement) {
            targetContainer = container;
        }
        
        if (targetContainer) {
            if (targetContainer.firstChild) {
                targetContainer.insertBefore(newElement, targetContainer.firstChild);
            } else {
                targetContainer.appendChild(newElement);
            }
        }
    },

    /**
     * Append element to container
     * @param {HTMLElement} newElement - New element to append
     * @param {HTMLElement|string} container - Container element or selector
     */
    append(newElement, container) {
        let targetContainer;
        
        if (typeof container === 'string') {
            targetContainer = document.querySelector(container);
        } else if (container instanceof HTMLElement) {
            targetContainer = container;
        }
        
        if (targetContainer) {
            targetContainer.appendChild(newElement);
        }
    }
};

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DOMUtils;
}
