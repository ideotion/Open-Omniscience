/**
 * Open Omniscience - Format Utilities
 * Functions for formatting dates, numbers, text, etc.
 */

const FormatUtils = {
    /**
     * Format date as relative time (e.g., "2 hours ago")
     * @param {Date|string|number} date - Date to format
     * @param {Object} [options] - Formatting options
     * @param {boolean} [options.short=false] - Use short format (e.g., "2h ago")
     * @param {Date} [options.now] - Reference date (defaults to now)
     * @returns {string} Formatted relative time
     */
    formatRelativeTime(date, options = {}) {
        const { short = false, now = new Date() } = options;
        
        // Parse date if it's a string or number
        const parsedDate = this.parseDate(date);
        if (!parsedDate) {
            return 'Invalid date';
        }
        
        const diff = now.getTime() - parsedDate.getTime();
        const diffInSeconds = Math.floor(diff / 1000);
        const diffInMinutes = Math.floor(diffInSeconds / 60);
        const diffInHours = Math.floor(diffInMinutes / 60);
        const diffInDays = Math.floor(diffInHours / 24);
        const diffInWeeks = Math.floor(diffInDays / 7);
        const diffInMonths = Math.floor(diffInDays / 30);
        const diffInYears = Math.floor(diffInDays / 365);
        
        const absDiffInSeconds = Math.abs(diffInSeconds);
        const absDiffInMinutes = Math.abs(diffInMinutes);
        const absDiffInHours = Math.abs(diffInHours);
        const absDiffInDays = Math.abs(diffInDays);
        const absDiffInWeeks = Math.abs(diffInWeeks);
        const absDiffInMonths = Math.abs(diffInMonths);
        const absDiffInYears = Math.abs(diffInYears);
        
        if (short) {
            if (absDiffInSeconds < 60) {
                return `${absDiffInSeconds}s ago`;
            }
            if (absDiffInMinutes < 60) {
                return `${absDiffInMinutes}m ago`;
            }
            if (absDiffInHours < 24) {
                return `${absDiffInHours}h ago`;
            }
            if (absDiffInDays < 7) {
                return `${absDiffInDays}d ago`;
            }
            if (absDiffInWeeks < 4) {
                return `${absDiffInWeeks}w ago`;
            }
            if (absDiffInMonths < 12) {
                return `${absDiffInMonths}mo ago`;
            }
            return `${absDiffInYears}y ago`;
        }
        
        // Full format
        if (absDiffInSeconds < 60) {
            return diffInSeconds > 0 
                ? `${absDiffInSeconds} second${absDiffInSeconds !== 1 ? 's' : ''} ago`
                : `in ${absDiffInSeconds} second${absDiffInSeconds !== 1 ? 's' : ''}`;
        }
        if (absDiffInMinutes < 60) {
            return diffInMinutes > 0
                ? `${absDiffInMinutes} minute${absDiffInMinutes !== 1 ? 's' : ''} ago`
                : `in ${absDiffInMinutes} minute${absDiffInMinutes !== 1 ? 's' : ''}`;
        }
        if (absDiffInHours < 24) {
            return diffInHours > 0
                ? `${absDiffInHours} hour${absDiffInHours !== 1 ? 's' : ''} ago`
                : `in ${absDiffInHours} hour${absDiffInHours !== 1 ? 's' : ''}`;
        }
        if (absDiffInDays < 7) {
            return diffInDays > 0
                ? `${absDiffInDays} day${absDiffInDays !== 1 ? 's' : ''} ago`
                : `in ${absDiffInDays} day${absDiffInDays !== 1 ? 's' : ''}`;
        }
        if (absDiffInWeeks < 4) {
            return diffInWeeks > 0
                ? `${absDiffInWeeks} week${absDiffInWeeks !== 1 ? 's' : ''} ago`
                : `in ${absDiffInWeeks} week${absDiffInWeeks !== 1 ? 's' : ''}`;
        }
        if (absDiffInMonths < 12) {
            return diffInMonths > 0
                ? `${absDiffInMonths} month${absDiffInMonths !== 1 ? 's' : ''} ago`
                : `in ${absDiffInMonths} month${absDiffInMonths !== 1 ? 's' : ''}`;
        }
        return diffInYears > 0
            ? `${absDiffInYears} year${absDiffInYears !== 1 ? 's' : ''} ago`
            : `in ${absDiffInYears} year${absDiffInYears !== 1 ? 's' : ''}`;
    },

    /**
     * Format date as human-readable string
     * @param {Date|string|number} date - Date to format
     * @param {Object} [options] - Formatting options
     * @param {string} [options.format='medium'] - Format type (short, medium, long, full)
     * @param {boolean} [options.time=true] - Include time
     * @param {boolean} [options.date=true] - Include date
     * @param {string} [options.locale] - Locale to use
     * @returns {string} Formatted date string
     */
    formatDate(date, options = {}) {
        const { format = 'medium', time = true, date = true, locale } = options;
        
        const parsedDate = this.parseDate(date);
        if (!parsedDate) {
            return 'Invalid date';
        }
        
        const userLocale = locale || navigator.language || 'en-US';
        
        const dateOptions = {
            year: 'numeric',
            month: 'short',
            day: 'numeric'
        };
        
        const timeOptions = {
            hour: '2-digit',
            minute: '2-digit'
        };
        
        switch (format) {
            case 'short':
                dateOptions.month = 'short';
                dateOptions.day = 'numeric';
                timeOptions.hour = '2-digit';
                timeOptions.minute = '2-digit';
                break;
            case 'medium':
                dateOptions.month = 'short';
                dateOptions.day = 'numeric';
                dateOptions.year = 'numeric';
                timeOptions.hour = '2-digit';
                timeOptions.minute = '2-digit';
                break;
            case 'long':
                dateOptions.month = 'long';
                dateOptions.day = 'numeric';
                dateOptions.year = 'numeric';
                timeOptions.hour = '2-digit';
                timeOptions.minute = '2-digit';
                timeOptions.second = '2-digit';
                break;
            case 'full':
                dateOptions.weekday = 'long';
                dateOptions.month = 'long';
                dateOptions.day = 'numeric';
                dateOptions.year = 'numeric';
                timeOptions.hour = '2-digit';
                timeOptions.minute = '2-digit';
                timeOptions.second = '2-digit';
                timeOptions.timeZoneName = 'short';
                break;
        }
        
        const parts = [];
        if (date) {
            parts.push(parsedDate.toLocaleDateString(userLocale, dateOptions));
        }
        if (time) {
            parts.push(parsedDate.toLocaleTimeString(userLocale, timeOptions));
        }
        
        return parts.join(' ');
    },

    /**
     * Format date for display in table
     * @param {Date|string|number} date - Date to format
     * @returns {string} Formatted date for table display
     */
    formatDateForTable(date) {
        const parsedDate = this.parseDate(date);
        if (!parsedDate) {
            return 'Invalid date';
        }
        
        const now = new Date();
        const diff = now.getTime() - parsedDate.getTime();
        const diffInDays = Math.floor(diff / (1000 * 60 * 60 * 24));
        
        // If within last 7 days, show relative time
        if (diffInDays < 7 && diffInDays >= 0) {
            return this.formatRelativeTime(date, { short: true });
        }
        
        // Otherwise show date
        return this.formatDate(date, { format: 'medium', time: false });
    },

    /**
     * Format date for input field (YYYY-MM-DD)
     * @param {Date|string|number} date - Date to format
     * @returns {string} Formatted date for input field
     */
    formatDateForInput(date) {
        const parsedDate = this.parseDate(date);
        if (!parsedDate) {
            return '';
        }
        
        const year = parsedDate.getFullYear();
        const month = String(parsedDate.getMonth() + 1).padStart(2, '0');
        const day = String(parsedDate.getDate()).padStart(2, '0');
        
        return `${year}-${month}-${day}`;
    },

    /**
     * Format date for API (ISO 8601)
     * @param {Date|string|number} date - Date to format
     * @param {boolean} [includeTime=true] - Include time component
     * @returns {string} ISO 8601 formatted date
     */
    formatDateForAPI(date, includeTime = true) {
        const parsedDate = this.parseDate(date);
        if (!parsedDate) {
            return '';
        }
        
        if (includeTime) {
            return parsedDate.toISOString();
        }
        
        return parsedDate.toISOString().split('T')[0];
    },

    /**
     * Parse date from various formats
     * @param {Date|string|number} date - Date to parse
     * @returns {Date|null} Parsed Date object or null if invalid
     */
    parseDate(date) {
        if (!date) {
            return null;
        }
        
        // Already a Date object
        if (date instanceof Date) {
            return isNaN(date.getTime()) ? null : date;
        }
        
        // Timestamp number
        if (typeof date === 'number') {
            const parsed = new Date(date);
            return isNaN(parsed.getTime()) ? null : parsed;
        }
        
        // String date
        if (typeof date === 'string') {
            // Try ISO 8601 first
            if (/^\d{4}-\d{2}-\d{2}/.test(date)) {
                const parsed = new Date(date);
                if (!isNaN(parsed.getTime())) {
                    return parsed;
                }
            }
            
            // Try RFC 2822
            try {
                const parsed = new Date(date);
                if (!isNaN(parsed.getTime())) {
                    return parsed;
                }
            } catch (e) {
                // Ignore
            }
            
            // Try custom formats
            const formats = [
                'YYYY-MM-DD',
                'MM/DD/YYYY',
                'DD/MM/YYYY',
                'YYYY-MM-DD HH:mm:ss',
                'MM/DD/YYYY HH:mm:ss',
                'DD/MM/YYYY HH:mm:ss'
            ];
            
            for (const format of formats) {
                const parsed = this.parseDateString(date, format);
                if (parsed) {
                    return parsed;
                }
            }
        }
        
        return null;
    },

    /**
     * Parse date string with specific format
     * @param {string} dateString - Date string to parse
     * @param {string} format - Format string (e.g., 'YYYY-MM-DD')
     * @returns {Date|null} Parsed Date object or null if invalid
     */
    parseDateString(dateString, format) {
        const formatParts = format.split(/[^A-Za-z]/);
        const dateParts = dateString.split(/[^0-9]/);
        
        if (formatParts.length !== dateParts.length) {
            return null;
        }
        
        const dateValues = {};
        for (let i = 0; i < formatParts.length; i++) {
            const part = formatParts[i];
            const value = parseInt(dateParts[i], 10);
            
            if (isNaN(value)) {
                return null;
            }
            
            switch (part) {
                case 'YYYY':
                    dateValues.year = value;
                    break;
                case 'MM':
                    dateValues.month = value - 1;
                    break;
                case 'DD':
                    dateValues.day = value;
                    break;
                case 'HH':
                    dateValues.hours = value;
                    break;
                case 'mm':
                    dateValues.minutes = value;
                    break;
                case 'ss':
                    dateValues.seconds = value;
                    break;
            }
        }
        
        // Validate required parts
        if (dateValues.year === undefined || dateValues.month === undefined || dateValues.day === undefined) {
            return null;
        }
        
        const date = new Date(
            dateValues.year,
            dateValues.month || 0,
            dateValues.day || 1,
            dateValues.hours || 0,
            dateValues.minutes || 0,
            dateValues.seconds || 0
        );
        
        return isNaN(date.getTime()) ? null : date;
    },

    /**
     * Format number with locale-aware formatting
     * @param {number} number - Number to format
     * @param {Object} [options] - Formatting options
     * @param {string} [options.style='decimal'] - Number style (decimal, currency, percent)
     * @param {string} [options.currency] - Currency code (for currency style)
     * @param {number} [options.minimumFractionDigits] - Minimum fraction digits
     * @param {number} [options.maximumFractionDigits] - Maximum fraction digits
     * @param {string} [options.locale] - Locale to use
     * @returns {string} Formatted number
     */
    formatNumber(number, options = {}) {
        const { 
            style = 'decimal', 
            currency,
            minimumFractionDigits,
            maximumFractionDigits,
            locale
        } = options;
        
        if (typeof number !== 'number' || isNaN(number)) {
            return 'Invalid number';
        }
        
        const userLocale = locale || navigator.language || 'en-US';
        
        const formatOptions = {};
        if (style === 'currency' && currency) {
            formatOptions.style = style;
            formatOptions.currency = currency;
        } else if (style === 'percent') {
            formatOptions.style = style;
        }
        
        if (minimumFractionDigits !== undefined) {
            formatOptions.minimumFractionDigits = minimumFractionDigits;
        }
        if (maximumFractionDigits !== undefined) {
            formatOptions.maximumFractionDigits = maximumFractionDigits;
        }
        
        try {
            return number.toLocaleString(userLocale, formatOptions);
        } catch (e) {
            return String(number);
        }
    },

    /**
     * Format file size
     * @param {number} bytes - Size in bytes
     * @param {Object} [options] - Formatting options
     * @param {number} [options.decimals=2] - Number of decimal places
     * @param {string} [options.unit='auto'] - Unit to use (auto, bytes, kb, mb, gb, tb)
     * @returns {string} Formatted file size
     */
    formatFileSize(bytes, options = {}) {
        const { decimals = 2, unit = 'auto' } = options;
        
        if (typeof bytes !== 'number' || isNaN(bytes) || bytes < 0) {
            return 'Invalid size';
        }
        
        const units = ['bytes', 'kb', 'mb', 'gb', 'tb'];
        const sizes = [1, 1024, 1024 * 1024, 1024 * 1024 * 1024, 1024 * 1024 * 1024 * 1024];
        
        if (unit !== 'auto') {
            const index = units.indexOf(unit.toLowerCase());
            if (index !== -1) {
                const size = bytes / sizes[index];
                return `${size.toFixed(decimals)} ${units[index]}`;
            }
        }
        
        // Auto detect unit
        let index = 0;
        while (bytes >= 1024 && index < sizes.length - 1) {
            bytes /= 1024;
            index++;
        }
        
        return `${bytes.toFixed(decimals)} ${units[index]}`;
    },

    /**
     * Format duration
     * @param {number} milliseconds - Duration in milliseconds
     * @param {Object} [options] - Formatting options
     * @param {boolean} [options.short=false] - Use short format
     * @param {boolean} [options.includeMilliseconds=false] - Include milliseconds
     * @param {number} [options.maxUnits=2] - Maximum number of units to show
     * @returns {string} Formatted duration
     */
    formatDuration(milliseconds, options = {}) {
        const { short = false, includeMilliseconds = false, maxUnits = 2 } = options;
        
        if (typeof milliseconds !== 'number' || isNaN(milliseconds) || milliseconds < 0) {
            return 'Invalid duration';
        }
        
        const seconds = Math.floor(milliseconds / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        const days = Math.floor(hours / 24);
        const weeks = Math.floor(days / 7);
        
        const remainingSeconds = seconds % 60;
        const remainingMinutes = minutes % 60;
        const remainingHours = hours % 24;
        const remainingDays = days % 7;
        
        const parts = [];
        
        if (weeks > 0) {
            parts.push({ value: weeks, unit: short ? 'w' : 'week', plural: short ? '' : 's' });
        }
        if (remainingDays > 0 && parts.length < maxUnits) {
            parts.push({ value: remainingDays, unit: short ? 'd' : 'day', plural: short ? '' : 's' });
        }
        if (remainingHours > 0 && parts.length < maxUnits) {
            parts.push({ value: remainingHours, unit: short ? 'h' : 'hour', plural: short ? '' : 's' });
        }
        if (remainingMinutes > 0 && parts.length < maxUnits) {
            parts.push({ value: remainingMinutes, unit: short ? 'm' : 'minute', plural: short ? '' : 's' });
        }
        if ((remainingSeconds > 0 || parts.length === 0) && parts.length < maxUnits) {
            parts.push({ value: remainingSeconds, unit: short ? 's' : 'second', plural: short ? '' : 's' });
        }
        if (includeMilliseconds && parts.length < maxUnits) {
            const remainingMs = milliseconds % 1000;
            if (remainingMs > 0) {
                parts.push({ value: remainingMs, unit: short ? 'ms' : 'millisecond', plural: short ? '' : 's' });
            }
        }
        
        return parts.map(part => {
            const value = part.value;
            const unit = part.unit + (value !== 1 || short ? part.plural : '');
            return short ? `${value}${unit}` : `${value} ${unit}`;
        }).join(short ? ' ' : ', ');
    },

    /**
     * Format percentage
     * @param {number} value - Value to format (0-1 or 0-100)
     * @param {Object} [options] - Formatting options
     * @param {boolean} [options.isDecimal=false] - Whether value is decimal (0-1) or percentage (0-100)
     * @param {number} [options.decimals=1] - Number of decimal places
     * @param {boolean} [options.showSymbol=true] - Show percent symbol
     * @returns {string} Formatted percentage
     */
    formatPercentage(value, options = {}) {
        const { isDecimal = false, decimals = 1, showSymbol = true } = options;
        
        if (typeof value !== 'number' || isNaN(value)) {
            return 'Invalid percentage';
        }
        
        const percentage = isDecimal ? value * 100 : value;
        const formatted = percentage.toFixed(decimals);
        
        return showSymbol ? `${formatted}%` : formatted;
    },

    /**
     * Truncate text with ellipsis
     * @param {string} text - Text to truncate
     * @param {Object} [options] - Truncation options
     * @param {number} [options.maxLength=100] - Maximum length
     * @param {string} [options.ellipsis='...'] - Ellipsis string
     * @param {boolean} [options.preserveWords=false] - Preserve whole words
     * @returns {string} Truncated text
     */
    truncate(text, options = {}) {
        const { maxLength = 100, ellipsis = '...', preserveWords = false } = options;
        
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        if (text.length <= maxLength) {
            return text;
        }
        
        if (preserveWords) {
            // Find the last space before maxLength
            let truncated = text.substring(0, maxLength);
            const lastSpace = truncated.lastIndexOf(' ');
            
            if (lastSpace > 0) {
                truncated = truncated.substring(0, lastSpace);
            }
            
            return truncated + ellipsis;
        }
        
        return text.substring(0, maxLength) + ellipsis;
    },

    /**
     * Capitalize first letter of string
     * @param {string} text - Text to capitalize
     * @returns {string} Capitalized text
     */
    capitalize(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.charAt(0).toUpperCase() + text.slice(1);
    },

    /**
     * Capitalize first letter of each word
     * @param {string} text - Text to capitalize
     * @returns {string} Capitalized text
     */
    capitalizeWords(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.split(' ').map(word => this.capitalize(word)).join(' ');
    },

    /**
     * Convert to lowercase
     * @param {string} text - Text to convert
     * @returns {string} Lowercase text
     */
    toLowerCase(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.toLowerCase();
    },

    /**
     * Convert to uppercase
     * @param {string} text - Text to convert
     * @returns {string} Uppercase text
     */
    toUpperCase(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.toUpperCase();
    },

    /**
     * Convert to sentence case
     * @param {string} text - Text to convert
     * @returns {string} Sentence case text
     */
    toSentenceCase(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return this.capitalize(text.toLowerCase());
    },

    /**
     * Convert to title case
     * @param {string} text - Text to convert
     * @returns {string} Title case text
     */
    toTitleCase(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        const smallWords = /^(a|an|and|as|at|but|by|en|for|if|in|nor|of|on|or|per|the|to|vs?\.?|via)$/i;
        
        return text.split(' ').map((word, index) => {
            if (index === 0 || !smallWords.test(word)) {
                return this.capitalize(word.toLowerCase());
            }
            return word.toLowerCase();
        }).join(' ');
    },

    /**
     * Convert to slug
     * @param {string} text - Text to convert
     * @param {Object} [options] - Options
     * @param {string} [options.separator='-'] - Separator character
     * @param {boolean} [options.lowercase=true] - Convert to lowercase
     * @returns {string} Slug
     */
    toSlug(text, options = {}) {
        const { separator = '-', lowercase = true } = options;
        
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        let slug = text
            .replace(/[^\w\s-]/g, '') // Remove special characters
            .replace(/[\s_-]+/g, separator) // Replace spaces and underscores
            .replace(/^-+|-+$/g, ''); // Remove leading/trailing separators
        
        if (lowercase) {
            slug = slug.toLowerCase();
        }
        
        return slug;
    },

    /**
     * Highlight text matches
     * @param {string} text - Text to highlight
     * @param {string|string[]} matches - String or array of strings to highlight
     * @param {Object} [options] - Options
     * @param {string} [options.tag='mark'] - HTML tag to use for highlighting
     * @param {string} [options.className] - CSS class for highlight
     * @returns {string} Text with highlighted matches
     */
    highlightMatches(text, matches, options = {}) {
        const { tag = 'mark', className } = options;
        
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        if (!matches) {
            return text;
        }
        
        const matchArray = Array.isArray(matches) ? matches : [matches];
        
        // Escape regex special characters
        const escapeRegex = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        
        // Sort by length (longest first) to handle nested matches
        const sortedMatches = matchArray
            .filter(match => match && typeof match === 'string')
            .sort((a, b) => b.length - a.length);
        
        let result = text;
        
        for (const match of sortedMatches) {
            const escapedMatch = escapeRegex(match);
            const regex = new RegExp(escapedMatch, 'gi');
            const replacement = `<${tag}${className ? ` class="${className}"` : ''}>$&</${tag}>`;
            result = result.replace(regex, replacement);
        }
        
        return result;
    },

    /**
     * Strip HTML tags
     * @param {string} html - HTML to strip
     * @returns {string} Text without HTML tags
     */
    stripHtml(html) {
        if (!html || typeof html !== 'string') {
            return '';
        }
        
        const div = document.createElement('div');
        div.innerHTML = html;
        return div.textContent || div.innerText || '';
    },

    /**
     * Strip all whitespace
     * @param {string} text - Text to strip
     * @returns {string} Text without whitespace
     */
    stripWhitespace(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.replace(/\s+/g, '');
    },

    /**
     * Trim whitespace from both ends
     * @param {string} text - Text to trim
     * @returns {string} Trimmed text
     */
    trim(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.trim();
    },

    /**
     * Trim whitespace from start
     * @param {string} text - Text to trim
     * @returns {string} Trimmed text
     */
    trimStart(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.trimStart();
    },

    /**
     * Trim whitespace from end
     * @param {string} text - Text to trim
     * @returns {string} Trimmed text
     */
    trimEnd(text) {
        if (!text || typeof text !== 'string') {
            return '';
        }
        
        return text.trimEnd();
    },

    /**
     * Repeat string
     * @param {string} text - Text to repeat
     * @param {number} count - Number of times to repeat
     * @returns {string} Repeated text
     */
    repeat(text, count) {
        if (!text || typeof text !== 'string' || count <= 0) {
            return '';
        }
        
        return text.repeat(count);
    },

    /**
     * Pad string to specified length
     * @param {string} text - Text to pad
     * @param {number} length - Target length
     * @param {string} [padChar=' '] - Character to pad with
     * @param {boolean} [padStart=false] - Pad at start instead of end
     * @returns {string} Padded text
     */
    pad(text, length, padChar = ' ', padStart = false) {
        if (!text || typeof text !== 'string' || length <= text.length) {
            return text || '';
        }
        
        const padLength = length - text.length;
        const padding = this.repeat(padChar, padLength);
        
        return padStart ? padding + text : text + padding;
    },

    /**
     * Pad number with leading zeros
     * @param {number} num - Number to pad
     * @param {number} length - Target length
     * @returns {string} Padded number
     */
    padNumber(num, length) {
        if (typeof num !== 'number' || isNaN(num)) {
            return '';
        }
        
        return String(num).padStart(length, '0');
    },

    /**
     * Check if string is empty (null, undefined, empty string, or whitespace only)
     * @param {string} text - Text to check
     * @returns {boolean} True if empty
     */
    isEmpty(text) {
        if (text === null || text === undefined) {
            return true;
        }
        
        if (typeof text !== 'string') {
            return false;
        }
        
        return text.trim().length === 0;
    },

    /**
     * Check if string is not empty
     * @param {string} text - Text to check
     * @returns {boolean} True if not empty
     */
    isNotEmpty(text) {
        return !this.isEmpty(text);
    },

    /**
     * Check if two values are equal (deep equality for objects)
     * @param {*} a - First value
     * @param {*} b - Second value
     * @returns {boolean} True if equal
     */
    isEqual(a, b) {
        if (a === b) {
            return true;
        }
        
        if (a === null || b === null) {
            return false;
        }
        
        if (typeof a !== 'object' || typeof b !== 'object') {
            return false;
        }
        
        const aKeys = Object.keys(a);
        const bKeys = Object.keys(b);
        
        if (aKeys.length !== bKeys.length) {
            return false;
        }
        
        for (const key of aKeys) {
            if (!bKeys.includes(key) || !this.isEqual(a[key], b[key])) {
                return false;
            }
        }
        
        return true;
    },

    /**
     * Clone object or array (shallow clone)
     * @param {*} obj - Object or array to clone
     * @returns {*} Cloned object or array
     */
    clone(obj) {
        if (obj === null || typeof obj !== 'object') {
            return obj;
        }
        
        if (Array.isArray(obj)) {
            return [...obj];
        }
        
        return { ...obj };
    },

    /**
     * Deep clone object or array
     * @param {*} obj - Object or array to clone
     * @returns {*} Deep cloned object or array
     */
    deepClone(obj) {
        if (obj === null || typeof obj !== 'object') {
            return obj;
        }
        
        if (Array.isArray(obj)) {
            return obj.map(item => this.deepClone(item));
        }
        
        if (obj instanceof Date) {
            return new Date(obj);
        }
        
        const cloned = {};
        for (const key of Object.keys(obj)) {
            cloned[key] = this.deepClone(obj[key]);
        }
        
        return cloned;
    },

    /**
     * Merge objects (deep merge)
     * @param {...Object} objects - Objects to merge
     * @returns {Object} Merged object
     */
    merge(...objects) {
        const result = {};
        
        for (const obj of objects) {
            if (!obj || typeof obj !== 'object') {
                continue;
            }
            
            for (const key of Object.keys(obj)) {
                const value = obj[key];
                
                if (value && typeof value === 'object' && !Array.isArray(value)) {
                    result[key] = this.merge(result[key] || {}, value);
                } else if (Array.isArray(value)) {
                    result[key] = [...(result[key] || []), ...value];
                } else {
                    result[key] = value;
                }
            }
        }
        
        return result;
    },

    /**
     * Pick properties from object
     * @param {Object} obj - Source object
     * @param {string[]} keys - Keys to pick
     * @returns {Object} Object with picked properties
     */
    pick(obj, keys) {
        if (!obj || typeof obj !== 'object') {
            return {};
        }
        
        const result = {};
        for (const key of keys) {
            if (key in obj) {
                result[key] = obj[key];
            }
        }
        
        return result;
    },

    /**
     * Omit properties from object
     * @param {Object} obj - Source object
     * @param {string[]} keys - Keys to omit
     * @returns {Object} Object without omitted properties
     */
    omit(obj, keys) {
        if (!obj || typeof obj !== 'object') {
            return {};
        }
        
        const result = {};
        for (const key of Object.keys(obj)) {
            if (!keys.includes(key)) {
                result[key] = obj[key];
            }
        }
        
        return result;
    }
};

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FormatUtils;
}
