/**
 * Service Worker for Open-Omniscience
 * Provides offline caching and performance optimizations
 */

// Cache names with versioning
const CACHE_VERSION = 'v2';
const CACHE_NAMES = {
    ASSETS: `open-omniscience-assets-${CACHE_VERSION}`,
    DATA: `open-omniscience-data-${CACHE_VERSION}`,
    FONTS: `open-omniscience-fonts-${CACHE_VERSION}`,
    IMAGES: `open-omniscience-images-${CACHE_VERSION}`
};

// Assets to cache on install - only current files
const ASSETS_TO_CACHE = [
    '/',
    '/static/index.html',
    '/static/source-manager.html',
    '/static/llm.html',
    '/static/llm.css',
    // CSS files
    '/static/css/variables.css',
    '/static/css/main.css',
    '/static/css/utilities.css',
    '/static/css/layouts/main.css',
    '/static/css/layouts/source-manager.css',
    '/static/css/components/buttons.css',
    '/static/css/components/forms.css',
    '/static/css/components/tables.css',
    '/static/css/components/modals.css',
    '/static/css/components/notifications.css',
    // JS files
    '/static/js/api.js',
    '/static/js/main.js',
    '/static/js/llm.js',
    '/static/js/utils/storage.js',
    '/static/js/utils/dom.js',
    '/static/js/utils/format.js',
    '/static/js/utils/validation.js',
    '/static/js/utils/lazy-load.js',
    '/static/js/utils/service-worker.js',
    '/static/js/components/notifications.js',
    '/static/js/components/tables.js',
    '/static/js/pages/dashboard.js',
    '/static/js/pages/source-manager.js'
];

// Font URLs to cache
const FONT_URLS = [
    'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap',
    'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-solid-900.woff2',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-regular-400.woff2',
    'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/webfonts/fa-brands-400.woff2'
];

// External library URLs to cache
const LIBRARY_URLS = [
    'https://unpkg.com/react@18/umd/react.production.min.js',
    'https://unpkg.com/react-dom@18/umd/react-dom.production.min.js',
    'https://unpkg.com/recharts@2.10.3/umd/Recharts.min.js',
    'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js'
];

// Maximum cache size in bytes (50MB)
const MAX_CACHE_SIZE = 50 * 1024 * 1024;

// Maximum age for cached items (7 days)
const MAX_CACHE_AGE = 7 * 24 * 60 * 60 * 1000;

/**
 * Install service worker
 */
self.addEventListener('install', (event) => {
    event.waitUntil(
        Promise.all([
            // Cache core assets
            caches.open(CACHE_NAMES.ASSETS)
                .then((cache) => cache.addAll(ASSETS_TO_CACHE)),
            // Cache fonts
            caches.open(CACHE_NAMES.FONTS)
                .then((cache) => cache.addAll(FONT_URLS)),
            // Cache libraries
            caches.open(CACHE_NAMES.ASSETS)
                .then((cache) => cache.addAll(LIBRARY_URLS))
        ]).then(() => {
            console.log('Service worker installed and assets cached');
            return self.skipWaiting();
        }).catch((error) => {
            console.error('Failed to cache assets:', error);
        })
    );
});

/**
 * Activate service worker
 */
self.addEventListener('activate', (event) => {
    event.waitUntil(
        Promise.all([
            // Clean up old caches
            self._cleanupOldCaches(),
            // Take control of all clients
            self.clients.claim()
        ]).then(() => {
            console.log('Service worker activated');
        })
    );
});

/**
 * Clean up old caches
 * @private
 */
self._cleanupOldCaches = async function() {
    const cacheNames = await caches.keys();
    const currentCacheNames = Object.values(CACHE_NAMES);

    for (const cacheName of cacheNames) {
        // Delete old version caches (v1) and any non-current caches
        if (!currentCacheNames.includes(cacheName) || 
            cacheName.includes('-v1') ||
            cacheName.includes('open-omniscience-assets') && !cacheName.includes(CACHE_VERSION) ||
            cacheName.includes('open-omniscience-data') && !cacheName.includes(CACHE_VERSION) ||
            cacheName.includes('open-omniscience-fonts') && !cacheName.includes(CACHE_VERSION) ||
            cacheName.includes('open-omniscience-images') && !cacheName.includes(CACHE_VERSION)) {
            await caches.delete(cacheName);
            console.log(`Deleted old cache: ${cacheName}`);
        }
    }
};

/**
 * Fetch handler
 */
self.addEventListener('fetch', (event) => {
    const request = event.request;
    const url = new URL(request.url);

    // Skip non-GET requests
    if (request.method !== 'GET') {
        return;
    }

    // Skip requests to other origins (except for known CDNs)
    const isSameOrigin = self.location.origin === url.origin;
    const isKnownCDN = [
        'fonts.googleapis.com',
        'fonts.gstatic.com',
        'cdnjs.cloudflare.com',
        'cdn.jsdelivr.net',
        'unpkg.com'
    ].some(domain => url.hostname.includes(domain));

    if (!isSameOrigin && !isKnownCDN) {
        return;
    }

    // Handle API requests
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(self._handleAPIRequest(event));
        return;
    }

    // Handle asset requests
    event.respondWith(self._handleAssetRequest(event));
});

/**
 * Handle API requests
 * @private
 * @param {FetchEvent} event - Fetch event
 * @returns {Promise<Response>} Response promise
 */
self._handleAPIRequest = async function(event) {
    const request = event.request;
    const url = new URL(request.url);

    // Don't cache API requests that should always be fresh
    const nonCacheablePaths = [
        '/api/health',
        '/api/system/info',
        '/api/statistics'
    ];

    if (nonCacheablePaths.some(path => url.pathname.startsWith(path))) {
        return self._fetchWithTimeout(request);
    }

    // Try to get from cache first (stale-while-revalidate)
    const cache = await caches.open(CACHE_NAMES.DATA);
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
        // Return cached response and update in background
        event.waitUntil(
            self._fetchWithTimeout(request)
                .then((response) => {
                    if (response.ok) {
                        cache.put(request, response.clone());
                    }
                })
        );
        return cachedResponse;
    }

    // Not in cache, fetch from network
    return self._fetchWithTimeout(request);
};

/**
 * Handle asset requests
 * @private
 * @param {FetchEvent} event - Fetch event
 * @returns {Promise<Response>} Response promise
 */
self._handleAssetRequest = async function(event) {
    const request = event.request;
    const url = new URL(request.url);

    // Check if this is a font request
    if (url.hostname.includes('fonts.googleapis.com') || 
        url.hostname.includes('fonts.gstatic.com') ||
        url.pathname.includes('.woff2') ||
        url.pathname.includes('.woff') ||
        url.pathname.includes('.ttf')) {
        
        return self._handleFontRequest(event);
    }

    // Check if this is an image request
    if (url.pathname.match(/\.(jpg|jpeg|png|gif|webp|svg|ico)$/i)) {
        return self._handleImageRequest(event);
    }

    // For other assets, try cache first, then network
    const cache = await caches.open(CACHE_NAMES.ASSETS);
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
        return cachedResponse;
    }

    // Not in cache, fetch from network
    return self._fetchWithTimeout(request).then((response) => {
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    });
};

/**
 * Handle font requests
 * @private
 * @param {FetchEvent} event - Fetch event
 * @returns {Promise<Response>} Response promise
 */
self._handleFontRequest = async function(event) {
    const request = event.request;
    const url = new URL(request.url);

    // For Google Fonts CSS, we need to cache and rewrite the URLs
    if (url.hostname.includes('fonts.googleapis.com') && 
        url.pathname.includes('css')) {
        
        const cache = await caches.open(CACHE_NAMES.FONTS);
        const cachedResponse = await cache.match(request);

        if (cachedResponse) {
            return cachedResponse;
        }

        // Fetch from network
        return self._fetchWithTimeout(request).then(async (response) => {
            if (response.ok) {
                // Cache the CSS
                cache.put(request, response.clone());
                
                // Also cache the font files referenced in the CSS
                const cssText = await response.text();
                const fontUrls = self._extractFontUrls(cssText);
                
                for (const fontUrl of fontUrls) {
                    try {
                        const fontRequest = new Request(fontUrl);
                        const fontResponse = await self._fetchWithTimeout(fontRequest);
                        if (fontResponse.ok) {
                            cache.put(fontRequest, fontResponse.clone());
                        }
                    } catch (error) {
                        console.warn(`Failed to cache font: ${fontUrl}`, error);
                    }
                }
            }
            return response;
        });
    }

    // For font files
    const cache = await caches.open(CACHE_NAMES.FONTS);
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
        return cachedResponse;
    }

    return self._fetchWithTimeout(request).then((response) => {
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    });
};

/**
 * Handle image requests
 * @private
 * @param {FetchEvent} event - Fetch event
 * @returns {Promise<Response>} Response promise
 */
self._handleImageRequest = async function(event) {
    const request = event.request;
    const url = new URL(request.url);

    // For images, use cache-first strategy with size limit
    const cache = await caches.open(CACHE_NAMES.IMAGES);
    const cachedResponse = await cache.match(request);

    if (cachedResponse) {
        return cachedResponse;
    }

    // Check cache size before adding new items
    const cacheKeys = await cache.keys();
    let cacheSize = 0;
    
    for (const key of cacheKeys) {
        const response = await cache.match(key);
        if (response) {
            const blob = await response.blob();
            cacheSize += blob.size;
        }
    }

    // If cache is too large, clean it up
    if (cacheSize > MAX_CACHE_SIZE) {
        await self._cleanupImageCache(cache);
    }

    // Fetch from network
    return self._fetchWithTimeout(request).then((response) => {
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    });
};

/**
 * Extract font URLs from CSS text
 * @private
 * @param {string} cssText - CSS text
 * @returns {Array} Array of font URLs
 */
self._extractFontUrls = function(cssText) {
    const urls = [];
    const urlRegex = /url\(['"]?(.*?)['"]?\)/gi;
    
    let match;
    while ((match = urlRegex.exec(cssText)) !== null) {
        let url = match[1];
        
        // Skip data URLs
        if (url.startsWith('data:')) {
            continue;
        }
        
        // Handle relative URLs
        if (url.startsWith('/')) {
            url = `https://fonts.googleapis.com${url}`;
        } else if (!url.includes('://')) {
            url = `https://fonts.gstatic.com${url}`;
        }
        
        urls.push(url);
    }
    
    return urls;
};

/**
 * Clean up image cache
 * @private
 * @param {Cache} cache - Cache to clean up
 */
self._cleanupImageCache = async function(cache) {
    const keys = await cache.keys();
    const now = Date.now();

    for (const key of keys) {
        const response = await cache.match(key);
        if (response) {
            const headers = response.headers;
            const dateHeader = headers.get('date');
            
            if (dateHeader) {
                const date = new Date(dateHeader).getTime();
                const age = now - date;
                
                if (age > MAX_CACHE_AGE) {
                    await cache.delete(key);
                }
            }
        }
    }
};

/**
 * Fetch with timeout
 * @private
 * @param {Request} request - Request to fetch
 * @param {number} timeout - Timeout in milliseconds (default: 10000)
 * @returns {Promise<Response>} Response promise
 */
self._fetchWithTimeout = function(request, timeout = 10000) {
    return new Promise((resolve, reject) => {
        const timeoutId = setTimeout(() => {
            reject(new Error(`Request timed out: ${request.url}`));
        }, timeout);

        fetch(request).then((response) => {
            clearTimeout(timeoutId);
            resolve(response);
        }).catch((error) => {
            clearTimeout(timeoutId);
            reject(error);
        });
    });
};

/**
 * Message handler for client communication
 */
self.addEventListener('message', (event) => {
    const data = event.data;

    switch (data.type) {
        case 'CACHE_ASSET':
            event.waitUntil(
                caches.open(CACHE_NAMES.ASSETS)
                    .then((cache) => cache.add(data.url))
                    .then(() => {
                        event.source.postMessage({
                            type: 'CACHE_SUCCESS',
                            url: data.url
                        });
                    })
                    .catch((error) => {
                        event.source.postMessage({
                            type: 'CACHE_ERROR',
                            url: data.url,
                            error: error.message
                        });
                    })
            );
            break;

        case 'CLEAR_CACHE':
            event.waitUntil(
                caches.delete(data.cacheName)
                    .then(() => {
                        event.source.postMessage({
                            type: 'CLEAR_CACHE_SUCCESS',
                            cacheName: data.cacheName
                        });
                    })
                    .catch((error) => {
                        event.source.postMessage({
                            type: 'CLEAR_CACHE_ERROR',
                            cacheName: data.cacheName,
                            error: error.message
                        });
                    })
            );
            break;

        case 'GET_CACHE_SIZE':
            event.waitUntil(
                caches.open(data.cacheName)
                    .then(async (cache) => {
                        const keys = await cache.keys();
                        let size = 0;
                        
                        for (const key of keys) {
                            const response = await cache.match(key);
                            if (response) {
                                const blob = await response.blob();
                                size += blob.size;
                            }
                        }
                        
                        event.source.postMessage({
                            type: 'CACHE_SIZE',
                            cacheName: data.cacheName,
                            size,
                            count: keys.length
                        });
                    })
                    .catch((error) => {
                        event.source.postMessage({
                            type: 'CACHE_SIZE_ERROR',
                            cacheName: data.cacheName,
                            error: error.message
                        });
                    })
            );
            break;

        case 'SKIP_WAITING':
            event.waitUntil(self.skipWaiting());
            break;
    }
});

/**
 * Push notification handler
 */
self.addEventListener('push', (event) => {
    const data = event.data?.json();
    
    if (!data) return;

    const title = data.title || 'Open-Omniscience';
    const options = {
        body: data.body || '',
        icon: data.icon || '/static/favicon.ico',
        badge: data.badge || '/static/favicon.ico',
        data: data.data || {},
        actions: data.actions || [],
        vibrate: data.vibrate || [200, 100, 200],
        tag: data.tag || 'open-omniscience-notification'
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

/**
 * Notification click handler
 */
self.addEventListener('notificationclick', (event) => {
    const notification = event.notification;
    const action = event.action;

    // Close the notification
    notification.close();

    // Handle action
    if (action) {
        // Open the appropriate URL based on action
        const urlToOpen = notification.data?.url || '/';
        
        event.waitUntil(
            self.clients.matchAll({
                type: 'window',
                includeUncontrolled: true
            }).then((clients) => {
                // If there's already a window open, focus it
                if (clients.length > 0) {
                    clients[0].focus();
                    clients[0].navigate(urlToOpen);
                } else {
                    // Otherwise, open a new window
                    self.clients.openWindow(urlToOpen);
                }
            })
        );
    }
});

/**
 * Notification close handler
 */
self.addEventListener('notificationclose', (event) => {
    // Could send analytics or clean up here
});

/**
 * Background sync handler
 */
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-articles') {
        event.waitUntil(self._syncArticles());
    }
});

/**
 * Sync articles in the background
 * @private
 */
self._syncArticles = async function() {
    try {
        // Get all clients
        const clients = await self.clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        });

        // Send sync message to each client
        for (const client of clients) {
            client.postMessage({
                type: 'SYNC_ARTICLES'
            });
        }

        console.log('Background sync triggered for articles');
    } catch (error) {
        console.error('Background sync failed:', error);
    }
};

/**
 * Periodic sync handler
 */
self.addEventListener('periodicsync', (event) => {
    if (event.tag === 'periodic-article-check') {
        event.waitUntil(self._checkForNewArticles());
    }
});

/**
 * Check for new articles periodically
 * @private
 */
self._checkForNewArticles = async function() {
    try {
        const clients = await self.clients.matchAll({
            type: 'window',
            includeUncontrolled: true
        });

        for (const client of clients) {
            client.postMessage({
                type: 'CHECK_NEW_ARTICLES'
            });
        }

        console.log('Periodic check for new articles');
    } catch (error) {
        console.error('Periodic check failed:', error);
    }
};

// Register periodic sync if supported
if ('periodicSync' in self.registration) {
    self.registration.periodicSync.register('periodic-article-check', {
        minInterval: 15 * 60 * 1000, // 15 minutes
        powerState: 'auto'
    }).catch((error) => {
        console.warn('Periodic sync registration failed:', error);
    });
}

console.log('Open-Omniscience Service Worker loaded');
