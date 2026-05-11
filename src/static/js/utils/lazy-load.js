/**
 * Lazy Loading Utilities for Open-Omniscience
 * Handles lazy loading of images, iframes, and other resources
 */

const LazyLoadUtils = {
    /**
     * Default options for lazy loading
     */
    DEFAULT_OPTIONS: {
        threshold: 0.1,
        rootMargin: '0px',
        root: null,
        placeholder: 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgdmlld0JveD0iMCAwIDEwMCAxMDAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIiBmaWxsPSIjZjVmNWY1Ii8+Cjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsLCBzYW5zLXNlcmlmIiBmb250LXNpemU9IjE0IiBmaWxsPSIjNjY2IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5JbWFnZSBsb2FkaW5nPC90ZXh0Pgo8L3N2Zz4=',
        errorPlaceholder: 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgdmlld0JveD0iMCAwIDEwMCAxMDAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxyZWN0IHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIiBmaWxsPSIjZjVmNWY1Ii8+Cjx0ZXh0IHg9IjUwIiB5PSI1MCIgZm9udC1mYW1pbHk9IkFyaWFsLCBzYW5zLXNlcmlmIiBmb250LXNpemU9IjE0IiBmaWxsPSIjZjVmNWY1IiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj5JbWFnZSBlcnJvciA8L3RleHQ+Cjwvc3ZnPg==',
        loadClass: 'lazy-loaded',
        loadingClass: 'lazy-loading',
        errorClass: 'lazy-error',
        autoInit: true
    },

    /**
     * Intersection Observer instance
     */
    observer: null,

    /**
     * Elements being observed
     */
    observedElements: new Set(),

    /**
     * Initialize lazy loading
     * @param {Object} options - Lazy loading options
     */
    init(options = {}) {
        const mergedOptions = { ...this.DEFAULT_OPTIONS, ...options };

        // Create Intersection Observer if not already created
        if (!this.observer) {
            this.observer = new IntersectionObserver(
                this._handleIntersection.bind(this),
                {
                    threshold: mergedOptions.threshold,
                    rootMargin: mergedOptions.rootMargin,
                    root: mergedOptions.root
                }
            );
        }

        // Auto-initialize elements if enabled
        if (mergedOptions.autoInit) {
            this.observeAll();
        }

        return this;
    },

    /**
     * Handle intersection changes
     * @private
     * @param {Array} entries - Intersection entries
     */
    _handleIntersection(entries) {
        entries.forEach(entry => {
            const element = entry.target;

            if (entry.isIntersecting) {
                this._loadElement(element);
                this._unobserveElement(element);
            }
        });
    },

    /**
     * Load an element
     * @private
     * @param {HTMLElement} element - Element to load
     */
    _loadElement(element) {
        const tagName = element.tagName.toLowerCase();
        const options = this._getElementOptions(element);

        try {
            switch (tagName) {
                case 'img':
                    this._loadImage(element, options);
                    break;
                case 'iframe':
                    this._loadIframe(element, options);
                    break;
                case 'script':
                    this._loadScript(element, options);
                    break;
                case 'link':
                    this._loadStylesheet(element, options);
                    break;
                case 'video':
                case 'audio':
                    this._loadMedia(element, options);
                    break;
                case 'picture':
                    this._loadPicture(element, options);
                    break;
                default:
                    // Custom elements with data-src attribute
                    if (element.hasAttribute('data-src')) {
                        this._loadCustomElement(element, options);
                    }
                    break;
            }

            // Add loaded class
            element.classList.add(options.loadClass);
            element.classList.remove(options.loadingClass);

            // Trigger event
            element.dispatchEvent(new CustomEvent('lazyLoaded', {
                bubbles: true,
                cancelable: false
            }));

        } catch (error) {
            console.error('Failed to load element:', error);
            element.classList.add(options.errorClass);
            element.classList.remove(options.loadingClass);

            // Set error placeholder for images
            if (tagName === 'img' && options.errorPlaceholder) {
                element.src = options.errorPlaceholder;
            }

            // Trigger error event
            element.dispatchEvent(new CustomEvent('lazyError', {
                bubbles: true,
                cancelable: false,
                detail: { error }
            }));
        }
    },

    /**
     * Get options for an element
     * @private
     * @param {HTMLElement} element - Element
     * @returns {Object} Element options
     */
    _getElementOptions(element) {
        return {
            threshold: parseFloat(element.dataset.lazyThreshold) || this.DEFAULT_OPTIONS.threshold,
            placeholder: element.dataset.lazyPlaceholder || this.DEFAULT_OPTIONS.placeholder,
            errorPlaceholder: element.dataset.lazyErrorPlaceholder || this.DEFAULT_OPTIONS.errorPlaceholder,
            loadClass: element.dataset.lazyLoadClass || this.DEFAULT_OPTIONS.loadClass,
            loadingClass: element.dataset.lazyLoadingClass || this.DEFAULT_OPTIONS.loadingClass,
            errorClass: element.dataset.lazyErrorClass || this.DEFAULT_OPTIONS.errorClass
        };
    },

    /**
     * Load an image element
     * @private
     * @param {HTMLImageElement} img - Image element
     * @param {Object} options - Loading options
     */
    _loadImage(img, options) {
        // Set placeholder if available
        if (options.placeholder && !img.src) {
            img.src = options.placeholder;
        }

        // Get data-src
        const src = img.dataset.src || img.dataset.lazySrc;
        if (!src) return;

        // Set src to trigger loading
        img.src = src;

        // Remove data-src attribute
        img.removeAttribute('data-src');
        img.removeAttribute('data-lazy-src');

        // Set alt if not set
        if (!img.alt && img.dataset.lazyAlt) {
            img.alt = img.dataset.lazyAlt;
        }
    },

    /**
     * Load an iframe element
     * @private
     * @param {HTMLIFrameElement} iframe - Iframe element
     * @param {Object} options - Loading options
     */
    _loadIframe(iframe, options) {
        const src = iframe.dataset.src || iframe.dataset.lazySrc;
        if (!src) return;

        iframe.src = src;
        iframe.removeAttribute('data-src');
        iframe.removeAttribute('data-lazy-src');
    },

    /**
     * Load a script element
     * @private
     * @param {HTMLScriptElement} script - Script element
     * @param {Object} options - Loading options
     */
    _loadScript(script, options) {
        const src = script.dataset.src || script.dataset.lazySrc;
        if (!src) return;

        script.src = src;
        script.removeAttribute('data-src');
        script.removeAttribute('data-lazy-src');
    },

    /**
     * Load a stylesheet element
     * @private
     * @param {HTMLLinkElement} link - Link element
     * @param {Object} options - Loading options
     */
    _loadStylesheet(link, options) {
        const href = link.dataset.href || link.dataset.lazyHref;
        if (!href) return;

        link.href = href;
        link.removeAttribute('data-href');
        link.removeAttribute('data-lazy-href');
    },

    /**
     * Load a media element (video/audio)
     * @private
     * @param {HTMLMediaElement} media - Media element
     * @param {Object} options - Loading options
     */
    _loadMedia(media, options) {
        const src = media.dataset.src || media.dataset.lazySrc;
        if (!src) return;

        media.src = src;
        media.removeAttribute('data-src');
        media.removeAttribute('data-lazy-src');

        // Load the media
        media.load();
    },

    /**
     * Load a picture element
     * @private
     * @param {HTMLPictureElement} picture - Picture element
     * @param {Object} options - Loading options
     */
    _loadPicture(picture, options) {
        // Load all source elements
        const sources = picture.querySelectorAll('source[data-src], source[data-lazy-src]');
        sources.forEach(source => {
            const src = source.dataset.src || source.dataset.lazySrc;
            if (src) {
                source.srcset = src;
                source.removeAttribute('data-src');
                source.removeAttribute('data-lazy-src');
            }
        });

        // Load img element
        const img = picture.querySelector('img');
        if (img) {
            this._loadImage(img, options);
        }
    },

    /**
     * Load a custom element
     * @private
     * @param {HTMLElement} element - Custom element
     * @param {Object} options - Loading options
     */
    _loadCustomElement(element, options) {
        const src = element.dataset.src || element.dataset.lazySrc;
        if (!src) return;

        // Trigger custom load logic
        if (typeof element.lazyLoad === 'function') {
            element.lazyLoad(src);
        } else {
            // Default: set background image or content
            if (element.style.backgroundImage) {
                element.style.backgroundImage = `url(${src})`;
            } else if (element.dataset.lazyContent) {
                element.innerHTML = element.dataset.lazyContent;
            }
        }

        element.removeAttribute('data-src');
        element.removeAttribute('data-lazy-src');
    },

    /**
     * Observe an element for lazy loading
     * @param {HTMLElement} element - Element to observe
     * @param {Object} options - Lazy loading options
     */
    observe(element, options = {}) {
        if (!this.observer) {
            this.init(options);
        }

        if (this.observedElements.has(element)) {
            return this;
        }

        // Add loading class
        const elementOptions = this._getElementOptions(element);
        element.classList.add(elementOptions.loadingClass);

        // Observe the element
        this.observer.observe(element);
        this.observedElements.add(element);

        return this;
    },

    /**
     * Observe all elements matching a selector
     * @param {string} selector - CSS selector
     * @param {Object} options - Lazy loading options
     */
    observeAll(selector = '[data-src], [data-lazy-src]', options = {}) {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => this.observe(element, options));
        return this;
    },

    /**
     * Stop observing an element
     * @private
     * @param {HTMLElement} element - Element to stop observing
     */
    _unobserveElement(element) {
        if (this.observer && this.observedElements.has(element)) {
            this.observer.unobserve(element);
            this.observedElements.delete(element);
        }
    }

    /**
     * Stop observing all elements
     */
    unobserveAll() {
        if (this.observer) {
            this.observer.disconnect();
            this.observedElements.clear();
        }
        return this;
    }

    /**
     * Load all observed elements immediately
     */
    loadAll() {
        const elements = Array.from(this.observedElements);
        elements.forEach(element => this._loadElement(element));
        this.observedElements.clear();
        return this;
    }

    /**
     * Load all elements matching a selector immediately
     * @param {string} selector - CSS selector
     */
    loadAllMatching(selector = '[data-src], [data-lazy-src]') {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
            if (this.observedElements.has(element)) {
                this._loadElement(element);
                this._unobserveElement(element);
            } else {
                this._loadElement(element);
            }
        });
        return this;
    }

    /**
     * Destroy the lazy loader
     */
    destroy() {
        this.unobserveAll();
        this.observer = null;
        this.observedElements.clear();
        return this;
    }
};

/**
 * Image Lazy Loader
 * Specialized lazy loader for images with additional features
 */
class ImageLazyLoader {
    /**
     * Create a new image lazy loader
     * @param {Object} options - Configuration options
     */
    constructor(options = {}) {
        this.options = {
            selector: 'img[data-src], img[data-lazy-src]',
            placeholder: LazyLoadUtils.DEFAULT_OPTIONS.placeholder,
            errorPlaceholder: LazyLoadUtils.DEFAULT_OPTIONS.errorPlaceholder,
            loadClass: LazyLoadUtils.DEFAULT_OPTIONS.loadClass,
            loadingClass: LazyLoadUtils.DEFAULT_OPTIONS.loadingClass,
            errorClass: LazyLoadUtils.DEFAULT_OPTIONS.errorClass,
            threshold: LazyLoadUtils.DEFAULT_OPTIONS.threshold,
            rootMargin: LazyLoadUtils.DEFAULT_OPTIONS.rootMargin,
            autoInit: true,
            ...options
        };

        this.observer = null;
        this.observedImages = new Set();

        if (this.options.autoInit) {
            this.init();
        }
    }

    /**
     * Initialize the image lazy loader
     */
    init() {
        this.observer = new IntersectionObserver(
            this._handleIntersection.bind(this),
            {
                threshold: this.options.threshold,
                rootMargin: this.options.rootMargin
            }
        );

        this.observeAll();
        return this;
    }

    /**
     * Handle intersection changes
     * @private
     * @param {Array} entries - Intersection entries
     */
    _handleIntersection(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                this._loadImage(entry.target);
                this._unobserveImage(entry.target);
            }
        });
    }

    /**
     * Load an image
     * @private
     * @param {HTMLImageElement} img - Image to load
     */
    _loadImage(img) {
        // Set placeholder
        if (this.options.placeholder && !img.src) {
            img.src = this.options.placeholder;
        }

        // Get data-src
        const src = img.dataset.src || img.dataset.lazySrc;
        if (!src) return;

        // Set src
        img.src = src;

        // Remove data attributes
        img.removeAttribute('data-src');
        img.removeAttribute('data-lazy-src');

        // Add load class
        img.classList.add(this.options.loadClass);
        img.classList.remove(this.options.loadingClass);

        // Set alt if available
        if (!img.alt && img.dataset.lazyAlt) {
            img.alt = img.dataset.lazyAlt;
        }

        // Add error handler
        img.onerror = () => {
            img.classList.add(this.options.errorClass);
            img.classList.remove(this.options.loadingClass);
            if (this.options.errorPlaceholder) {
                img.src = this.options.errorPlaceholder;
            }
        };
    }

    /**
     * Observe an image
     * @param {HTMLImageElement} img - Image to observe
     */
    observe(img) {
        if (!this.observer) {
            this.init();
        }

        if (this.observedImages.has(img)) {
            return this;
        }

        img.classList.add(this.options.loadingClass);
        this.observer.observe(img);
        this.observedImages.add(img);

        return this;
    }

    /**
     * Observe all images matching selector
     */
    observeAll() {
        const images = document.querySelectorAll(this.options.selector);
        images.forEach(img => this.observe(img));
        return this;
    }

    /**
     * Stop observing an image
     * @private
     * @param {HTMLImageElement} img - Image to stop observing
     */
    _unobserveImage(img) {
        if (this.observer && this.observedImages.has(img)) {
            this.observer.unobserve(img);
            this.observedImages.delete(img);
        }
    }

    /**
     * Stop observing all images
     */
    unobserveAll() {
        if (this.observer) {
            this.observer.disconnect();
            this.observedImages.clear();
        }
        return this;
    }

    /**
     * Load all observed images immediately
     */
    loadAll() {
        const images = Array.from(this.observedImages);
        images.forEach(img => this._loadImage(img));
        this.observedImages.clear();
        return this;
    }

    /**
     * Destroy the image lazy loader
     */
    destroy() {
        this.unobserveAll();
        this.observer = null;
        this.observedImages.clear();
        return this;
    }
}

/**
 * Background Image Lazy Loader
 * Specialized lazy loader for background images
 */
class BackgroundLazyLoader {
    /**
     * Create a new background image lazy loader
     * @param {Object} options - Configuration options
     */
    constructor(options = {}) {
        this.options = {
            selector: '[data-bg-src], [data-lazy-bg-src]',
            placeholder: 'transparent',
            loadClass: 'bg-loaded',
            loadingClass: 'bg-loading',
            errorClass: 'bg-error',
            threshold: 0.1,
            rootMargin: '0px',
            autoInit: true,
            ...options
        };

        this.observer = null;
        this.observedElements = new Set();

        if (this.options.autoInit) {
            this.init();
        }
    }

    /**
     * Initialize the background lazy loader
     */
    init() {
        this.observer = new IntersectionObserver(
            this._handleIntersection.bind(this),
            {
                threshold: this.options.threshold,
                rootMargin: this.options.rootMargin
            }
        );

        this.observeAll();
        return this;
    }

    /**
     * Handle intersection changes
     * @private
     * @param {Array} entries - Intersection entries
     */
    _handleIntersection(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                this._loadBackground(entry.target);
                this._unobserveElement(entry.target);
            }
        });
    }

    /**
     * Load background image
     * @private
     * @param {HTMLElement} element - Element with background
     */
    _loadBackground(element) {
        const src = element.dataset.bgSrc || element.dataset.lazyBgSrc;
        if (!src) return;

        // Set background image
        element.style.backgroundImage = `url(${src})`;

        // Remove data attributes
        element.removeAttribute('data-bg-src');
        element.removeAttribute('data-lazy-bg-src');

        // Add classes
        element.classList.add(this.options.loadClass);
        element.classList.remove(this.options.loadingClass);

        // Add error handler (using image element to detect errors)
        const testImg = new Image();
        testImg.onerror = () => {
            element.classList.add(this.options.errorClass);
            element.classList.remove(this.options.loadingClass);
            element.style.backgroundImage = this.options.placeholder;
        };
        testImg.src = src;
    }

    /**
     * Observe an element
     * @param {HTMLElement} element - Element to observe
     */
    observe(element) {
        if (!this.observer) {
            this.init();
        }

        if (this.observedElements.has(element)) {
            return this;
        }

        element.classList.add(this.options.loadingClass);
        this.observer.observe(element);
        this.observedElements.add(element);

        return this;
    }

    /**
     * Observe all elements matching selector
     */
    observeAll() {
        const elements = document.querySelectorAll(this.options.selector);
        elements.forEach(element => this.observe(element));
        return this;
    }

    /**
     * Stop observing an element
     * @private
     * @param {HTMLElement} element - Element to stop observing
     */
    _unobserveElement(element) {
        if (this.observer && this.observedElements.has(element)) {
            this.observer.unobserve(element);
            this.observedElements.delete(element);
        }
    }

    /**
     * Stop observing all elements
     */
    unobserveAll() {
        if (this.observer) {
            this.observer.disconnect();
            this.observedElements.clear();
        }
        return this;
    }

    /**
     * Load all observed elements immediately
     */
    loadAll() {
        const elements = Array.from(this.observedElements);
        elements.forEach(element => this._loadBackground(element));
        this.observedElements.clear();
        return this;
    }

    /**
     * Destroy the background lazy loader
     */
    destroy() {
        this.unobserveAll();
        this.observer = null;
        this.observedElements.clear();
        return this;
    }
}

// Singleton instances
let lazyLoadInstance = null;
let imageLazyLoadInstance = null;
let backgroundLazyLoadInstance = null;

/**
 * Get or create the lazy load instance
 * @param {Object} options - Configuration options
 */
function getLazyLoad(options = {}) {
    if (!lazyLoadInstance) {
        lazyLoadInstance = Object.create(LazyLoadUtils).init(options);
    }
    return lazyLoadInstance;
}

/**
 * Get or create the image lazy load instance
 * @param {Object} options - Configuration options
 */
function getImageLazyLoad(options = {}) {
    if (!imageLazyLoadInstance) {
        imageLazyLoadInstance = new ImageLazyLoader(options);
    }
    return imageLazyLoadInstance;
}

/**
 * Get or create the background lazy load instance
 * @param {Object} options - Configuration options
 */
function getBackgroundLazyLoad(options = {}) {
    if (!backgroundLazyLoadInstance) {
        backgroundLazyLoadInstance = new BackgroundLazyLoader(options);
    }
    return backgroundLazyLoadInstance;
}

/**
 * Reset all lazy load instances
 */
function resetLazyLoad() {
    if (lazyLoadInstance) {
        lazyLoadInstance.destroy();
        lazyLoadInstance = null;
    }
    if (imageLazyLoadInstance) {
        imageLazyLoadInstance.destroy();
        imageLazyLoadInstance = null;
    }
    if (backgroundLazyLoadInstance) {
        backgroundLazyLoadInstance.destroy();
        backgroundLazyLoadInstance = null;
    }
}

// Export for use in modules
export { 
    LazyLoadUtils,
    ImageLazyLoader,
    BackgroundLazyLoader,
    getLazyLoad,
    getImageLazyLoad,
    getBackgroundLazyLoad,
    resetLazyLoad
};
