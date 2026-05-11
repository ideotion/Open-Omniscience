/**
 * Open Omniscience - Storage Utilities
 * Handles localStorage operations with error handling and fallbacks
 */

const StorageUtils = {
    /**
     * Check if localStorage is available
     * @returns {boolean} True if localStorage is available
     */
    isAvailable() {
        try {
            const testKey = '__test__';
            localStorage.setItem(testKey, testKey);
            localStorage.removeItem(testKey);
            return true;
        } catch (e) {
            return false;
        }
    },

    /**
     * Get item from localStorage
     * @param {string} key - The key to retrieve
     * @param {*} defaultValue - Default value if key doesn't exist
     * @returns {*} The stored value or default
     */
    get(key, defaultValue = null) {
        if (!this.isAvailable()) {
            return defaultValue;
        }
        
        try {
            const item = localStorage.getItem(key);
            if (item === null) {
                return defaultValue;
            }
            
            // Try to parse as JSON
            try {
                return JSON.parse(item);
            } catch (e) {
                return item;
            }
        } catch (e) {
            console.error(`Error reading from localStorage: ${e.message}`);
            return defaultValue;
        }
    },

    /**
     * Set item in localStorage
     * @param {string} key - The key to store
     * @param {*} value - The value to store
     * @returns {boolean} True if successful
     */
    set(key, value) {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            // Stringify if not a string
            const stringValue = typeof value === 'string' ? value : JSON.stringify(value);
            localStorage.setItem(key, stringValue);
            return true;
        } catch (e) {
            console.error(`Error writing to localStorage: ${e.message}`);
            return false;
        }
    },

    /**
     * Remove item from localStorage
     * @param {string} key - The key to remove
     * @returns {boolean} True if successful
     */
    remove(key) {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            localStorage.removeItem(key);
            return true;
        } catch (e) {
            console.error(`Error removing from localStorage: ${e.message}`);
            return false;
        }
    },

    /**
     * Clear all items from localStorage
     * @returns {boolean} True if successful
     */
    clear() {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            localStorage.clear();
            return true;
        } catch (e) {
            console.error(`Error clearing localStorage: ${e.message}`);
            return false;
        }
    },

    /**
     * Get all keys from localStorage
     * @returns {string[]} Array of keys
     */
    keys() {
        if (!this.isAvailable()) {
            return [];
        }
        
        try {
            return Object.keys(localStorage);
        } catch (e) {
            console.error(`Error getting keys from localStorage: ${e.message}`);
            return [];
        }
    },

    /**
     * Check if key exists in localStorage
     * @param {string} key - The key to check
     * @returns {boolean} True if key exists
     */
    has(key) {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            return localStorage.getItem(key) !== null;
        } catch (e) {
            console.error(`Error checking key in localStorage: ${e.message}`);
            return false;
        }
    },

    /**
     * Get all items from localStorage as an object
     * @returns {Object} All stored items
     */
    getAll() {
        if (!this.isAvailable()) {
            return {};
        }
        
        try {
            const items = {};
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                const value = localStorage.getItem(key);
                try {
                    items[key] = JSON.parse(value);
                } catch (e) {
                    items[key] = value;
                }
            }
            return items;
        } catch (e) {
            console.error(`Error getting all items from localStorage: ${e.message}`);
            return {};
        }
    },

    /**
     * Remove items that start with a prefix
     * @param {string} prefix - The prefix to match
     * @returns {number} Number of items removed
     */
    removeByPrefix(prefix) {
        if (!this.isAvailable()) {
            return 0;
        }
        
        try {
            let count = 0;
            const keys = Object.keys(localStorage);
            for (const key of keys) {
                if (key.startsWith(prefix)) {
                    localStorage.removeItem(key);
                    count++;
                }
            }
            return count;
        } catch (e) {
            console.error(`Error removing items by prefix: ${e.message}`);
            return 0;
        }
    },

    /**
     * Get expiration time for a key (if it has one)
     * @param {string} key - The key to check
     * @returns {number|null} Expiration timestamp or null if not expired
     */
    getExpiration(key) {
        if (!this.isAvailable()) {
            return null;
        }
        
        try {
            const item = localStorage.getItem(key);
            if (!item) {
                return null;
            }
            
            // Check if it's a JSON object with expiration
            try {
                const parsed = JSON.parse(item);
                if (parsed && typeof parsed === 'object' && parsed.__expires__) {
                    return parsed.__expires__;
                }
            } catch (e) {
                // Not JSON, no expiration
            }
            return null;
        } catch (e) {
            console.error(`Error getting expiration: ${e.message}`);
            return null;
        }
    },

    /**
     * Set item with expiration
     * @param {string} key - The key to store
     * @param {*} value - The value to store
     * @param {number} ttl - Time to live in milliseconds
     * @returns {boolean} True if successful
     */
    setWithExpiration(key, value, ttl) {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            const expires = Date.now() + ttl;
            const item = {
                __value__: value,
                __expires__: expires
            };
            localStorage.setItem(key, JSON.stringify(item));
            return true;
        } catch (e) {
            console.error(`Error setting with expiration: ${e.message}`);
            return false;
        }
    },

    /**
     * Get item with expiration check
     * @param {string} key - The key to retrieve
     * @param {*} defaultValue - Default value if key doesn't exist or is expired
     * @returns {*} The stored value or default
     */
    getWithExpiration(key, defaultValue = null) {
        if (!this.isAvailable()) {
            return defaultValue;
        }
        
        try {
            const item = localStorage.getItem(key);
            if (!item) {
                return defaultValue;
            }
            
            try {
                const parsed = JSON.parse(item);
                if (parsed && typeof parsed === 'object' && parsed.__expires__) {
                    if (Date.now() > parsed.__expires__) {
                        // Expired, remove and return default
                        localStorage.removeItem(key);
                        return defaultValue;
                    }
                    return parsed.__value__;
                }
                return parsed;
            } catch (e) {
                return item;
            }
        } catch (e) {
            console.error(`Error getting with expiration: ${e.message}`);
            return defaultValue;
        }
    },

    /**
     * Clean up expired items
     * @returns {number} Number of items removed
     */
    cleanupExpired() {
        if (!this.isAvailable()) {
            return 0;
        }
        
        try {
            let count = 0;
            const keys = Object.keys(localStorage);
            for (const key of keys) {
                const expires = this.getExpiration(key);
                if (expires && Date.now() > expires) {
                    localStorage.removeItem(key);
                    count++;
                }
            }
            return count;
        } catch (e) {
            console.error(`Error cleaning up expired items: ${e.message}`);
            return 0;
        }
    }
};

// Session storage utilities
const SessionStorageUtils = {
    /**
     * Check if sessionStorage is available
     * @returns {boolean} True if sessionStorage is available
     */
    isAvailable() {
        try {
            const testKey = '__test__';
            sessionStorage.setItem(testKey, testKey);
            sessionStorage.removeItem(testKey);
            return true;
        } catch (e) {
            return false;
        }
    },

    /**
     * Get item from sessionStorage
     * @param {string} key - The key to retrieve
     * @param {*} defaultValue - Default value if key doesn't exist
     * @returns {*} The stored value or default
     */
    get(key, defaultValue = null) {
        if (!this.isAvailable()) {
            return defaultValue;
        }
        
        try {
            const item = sessionStorage.getItem(key);
            if (item === null) {
                return defaultValue;
            }
            
            try {
                return JSON.parse(item);
            } catch (e) {
                return item;
            }
        } catch (e) {
            console.error(`Error reading from sessionStorage: ${e.message}`);
            return defaultValue;
        }
    },

    /**
     * Set item in sessionStorage
     * @param {string} key - The key to store
     * @param {*} value - The value to store
     * @returns {boolean} True if successful
     */
    set(key, value) {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            const stringValue = typeof value === 'string' ? value : JSON.stringify(value);
            sessionStorage.setItem(key, stringValue);
            return true;
        } catch (e) {
            console.error(`Error writing to sessionStorage: ${e.message}`);
            return false;
        }
    },

    /**
     * Remove item from sessionStorage
     * @param {string} key - The key to remove
     * @returns {boolean} True if successful
     */
    remove(key) {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            sessionStorage.removeItem(key);
            return true;
        } catch (e) {
            console.error(`Error removing from sessionStorage: ${e.message}`);
            return false;
        }
    },

    /**
     * Clear all items from sessionStorage
     * @returns {boolean} True if successful
     */
    clear() {
        if (!this.isAvailable()) {
            return false;
        }
        
        try {
            sessionStorage.clear();
            return true;
        } catch (e) {
            console.error(`Error clearing sessionStorage: ${e.message}`);
            return false;
        }
    }
};

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { StorageUtils, SessionStorageUtils };
}
