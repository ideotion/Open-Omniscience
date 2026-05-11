/**
 * Validation Utilities for Open-Omniscience
 * Provides comprehensive form validation and data validation functions
 */

const ValidationUtils = {
    /**
     * Validation error types
     */
    ERROR_TYPES: {
        REQUIRED: 'required',
        MIN_LENGTH: 'min_length',
        MAX_LENGTH: 'max_length',
        PATTERN: 'pattern',
        EMAIL: 'email',
        URL: 'url',
        NUMBER: 'number',
        MIN: 'min',
        MAX: 'max',
        DATE: 'date',
        DATE_MIN: 'date_min',
        DATE_MAX: 'date_max',
        CUSTOM: 'custom'
    },

    /**
     * Common validation patterns
     */
    PATTERNS: {
        EMAIL: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
        URL: /^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$/,
        ALPHANUMERIC: /^[a-zA-Z0-9]+$/,
        ALPHANUMERIC_SPACE: /^[a-zA-Z0-9\s]+$/,
        SLUG: /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
        PHONE: /^[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,3}[-\s\.]?[0-9]{3,4}[-\s\.]?[0-9]{3,4}$/,
        UUID: /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
        HEX_COLOR: /^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/,
        RGB_COLOR: /^rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/,
        RGBA_COLOR: /^rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(0|1|0?\.\d+)\s*\)$/,
        INTEGER: /^-?\d+$/,
        DECIMAL: /^-?\d+(\.\d+)?$/,
        TIME: /^([01]?[0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?$/,
        DATE_ISO: /^\d{4}-\d{2}-\d{2}$/,
        DATE_TIME_ISO: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$/,
        IP_V4: /^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/,
        IP_V6: /^([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}$/,
        DOMAIN: /^([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,6}$/
    },

    /**
     * Validation result structure
     * @typedef {Object} ValidationResult
     * @property {boolean} isValid - Whether validation passed
     * @property {Array} errors - Array of error objects
     * @property {Object} errorMap - Map of field names to error messages
     */

    /**
     * Validate a single value against rules
     * @param {*} value - Value to validate
     * @param {Object|Array} rules - Validation rules
     * @param {Object} context - Additional context for validation
     * @returns {ValidationResult} Validation result
     */
    validate(value, rules, context = {}) {
        const errors = [];
        const errorMap = {};

        // Normalize rules to array
        const ruleList = Array.isArray(rules) ? rules : [rules];

        for (const rule of ruleList) {
            const error = this._validateRule(value, rule, context);
            if (error) {
                errors.push(error);
                if (rule.field) {
                    errorMap[rule.field] = error.message;
                }
            }
        }

        return {
            isValid: errors.length === 0,
            errors,
            errorMap
        };
    },

    /**
     * Validate an object against a schema
     * @param {Object} data - Data to validate
     * @param {Object} schema - Validation schema
     * @param {Object} options - Validation options
     * @returns {ValidationResult} Validation result
     */
    validateObject(data, schema, options = {}) {
        const errors = [];
        const errorMap = {};
        const { stopOnFirstError = false } = options;

        for (const [field, rules] of Object.entries(schema)) {
            const value = data[field];
            const fieldRules = Array.isArray(rules) ? rules : [rules];

            for (const rule of fieldRules) {
                // Skip conditional rules if condition is not met
                if (rule.when && !this._evaluateCondition(data, rule.when)) {
                    continue;
                }

                const error = this._validateRule(value, { ...rule, field }, data);
                if (error) {
                    errors.push({ ...error, field });
                    errorMap[field] = error.message;
                    if (stopOnFirstError) {
                        return {
                            isValid: false,
                            errors,
                            errorMap
                        };
                    }
                    break; // Only report first error per field
                }
            }
        }

        return {
            isValid: errors.length === 0,
            errors,
            errorMap
        };
    },

    /**
     * Validate a rule against a value
     * @private
     * @param {*} value - Value to validate
     * @param {Object} rule - Validation rule
     * @param {Object} context - Validation context
     * @returns {Object|null} Error object or null
     */
    _validateRule(value, rule, context) {
        const { type, message, field } = rule;

        // Handle required validation
        if (type === this.ERROR_TYPES.REQUIRED) {
            if (this._isEmpty(value)) {
                return {
                    type: this.ERROR_TYPES.REQUIRED,
                    message: message || `${field || 'Field'} is required`,
                    field
                };
            }
            return null;
        }

        // Skip validation if value is empty and not required
        if (this._isEmpty(value) && !rule.allowEmpty) {
            return null;
        }

        // Handle type-specific validations
        switch (type) {
            case this.ERROR_TYPES.MIN_LENGTH:
                if (String(value).length < rule.min) {
                    return {
                        type: this.ERROR_TYPES.MIN_LENGTH,
                        message: message || `${field || 'Field'} must be at least ${rule.min} characters`,
                        field,
                        expected: rule.min
                    };
                }
                break;

            case this.ERROR_TYPES.MAX_LENGTH:
                if (String(value).length > rule.max) {
                    return {
                        type: this.ERROR_TYPES.MAX_LENGTH,
                        message: message || `${field || 'Field'} must be at most ${rule.max} characters`,
                        field,
                        expected: rule.max
                    };
                }
                break;

            case this.ERROR_TYPES.PATTERN:
                if (!rule.pattern.test(String(value))) {
                    return {
                        type: this.ERROR_TYPES.PATTERN,
                        message: message || `${field || 'Field'} format is invalid`,
                        field,
                        pattern: rule.pattern
                    };
                }
                break;

            case this.ERROR_TYPES.EMAIL:
                if (!this.PATTERNS.EMAIL.test(String(value))) {
                    return {
                        type: this.ERROR_TYPES.EMAIL,
                        message: message || `${field || 'Email'} is invalid`,
                        field
                    };
                }
                break;

            case this.ERROR_TYPES.URL:
                if (!this.PATTERNS.URL.test(String(value))) {
                    return {
                        type: this.ERROR_TYPES.URL,
                        message: message || `${field || 'URL'} is invalid`,
                        field
                    };
                }
                break;

            case this.ERROR_TYPES.NUMBER:
                if (isNaN(Number(value))) {
                    return {
                        type: this.ERROR_TYPES.NUMBER,
                        message: message || `${field || 'Field'} must be a number`,
                        field
                    };
                }
                break;

            case this.ERROR_TYPES.MIN:
                if (Number(value) < rule.min) {
                    return {
                        type: this.ERROR_TYPES.MIN,
                        message: message || `${field || 'Field'} must be at least ${rule.min}`,
                        field,
                        expected: rule.min
                    };
                }
                break;

            case this.ERROR_TYPES.MAX:
                if (Number(value) > rule.max) {
                    return {
                        type: this.ERROR_TYPES.MAX,
                        message: message || `${field || 'Field'} must be at most ${rule.max}`,
                        field,
                        expected: rule.max
                    };
                }
                break;

            case this.ERROR_TYPES.DATE:
                if (!this.isValidDate(value)) {
                    return {
                        type: this.ERROR_TYPES.DATE,
                        message: message || `${field || 'Date'} is invalid`,
                        field
                    };
                }
                break;

            case this.ERROR_TYPES.DATE_MIN:
                if (!this.isValidDate(value) || new Date(value) < new Date(rule.min)) {
                    return {
                        type: this.ERROR_TYPES.DATE_MIN,
                        message: message || `${field || 'Date'} must be after ${rule.min}`,
                        field,
                        expected: rule.min
                    };
                }
                break;

            case this.ERROR_TYPES.DATE_MAX:
                if (!this.isValidDate(value) || new Date(value) > new Date(rule.max)) {
                    return {
                        type: this.ERROR_TYPES.DATE_MAX,
                        message: message || `${field || 'Date'} must be before ${rule.max}`,
                        field,
                        expected: rule.max
                    };
                }
                break;

            case this.ERROR_TYPES.CUSTOM:
                if (rule.validator && !rule.validator(value, context)) {
                    return {
                        type: this.ERROR_TYPES.CUSTOM,
                        message: message || (rule.validatorMessage || 'Validation failed'),
                        field
                    };
                }
                break;

            default:
                // Unknown type, skip validation
                break;
        }

        return null;
    },

    /**
     * Check if a value is empty
     * @private
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is empty
     */
    _isEmpty(value) {
        if (value === undefined || value === null) {
            return true;
        }
        if (typeof value === 'string') {
            return value.trim() === '';
        }
        if (Array.isArray(value)) {
            return value.length === 0;
        }
        if (typeof value === 'object') {
            return Object.keys(value).length === 0;
        }
        return false;
    },

    /**
     * Evaluate a condition for conditional validation
     * @private
     * @param {Object} data - Form data
     * @param {Function|Object} condition - Condition to evaluate
     * @returns {boolean} Whether condition is met
     */
    _evaluateCondition(data, condition) {
        if (typeof condition === 'function') {
            return condition(data);
        }
        if (typeof condition === 'object') {
            for (const [field, expected] of Object.entries(condition)) {
                const value = data[field];
                if (typeof expected === 'function') {
                    if (!expected(value)) return false;
                } else if (value !== expected) {
                    return false;
                }
            }
            return true;
        }
        return true;
    },

    // Individual validation functions

    /**
     * Check if value is required (not empty)
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is valid
     */
    isRequired(value) {
        return !this._isEmpty(value);
    },

    /**
     * Check if value has minimum length
     * @param {string} value - Value to check
     * @param {number} min - Minimum length
     * @returns {boolean} Whether value is valid
     */
    hasMinLength(value, min) {
        if (this._isEmpty(value)) return true;
        return String(value).length >= min;
    },

    /**
     * Check if value has maximum length
     * @param {string} value - Value to check
     * @param {number} max - Maximum length
     * @returns {boolean} Whether value is valid
     */
    hasMaxLength(value, max) {
        if (this._isEmpty(value)) return true;
        return String(value).length <= max;
    },

    /**
     * Check if value matches a pattern
     * @param {string} value - Value to check
     * @param {RegExp} pattern - Regular expression pattern
     * @returns {boolean} Whether value matches pattern
     */
    matchesPattern(value, pattern) {
        if (this._isEmpty(value)) return true;
        return pattern.test(String(value));
    },

    /**
     * Check if value is a valid email
     * @param {string} value - Email to validate
     * @returns {boolean} Whether email is valid
     */
    isValidEmail(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.EMAIL.test(String(value));
    },

    /**
     * Check if value is a valid URL
     * @param {string} value - URL to validate
     * @returns {boolean} Whether URL is valid
     */
    isValidUrl(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.URL.test(String(value));
    },

    /**
     * Check if value is a valid number
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is a valid number
     */
    isValidNumber(value) {
        if (this._isEmpty(value)) return true;
        return !isNaN(Number(value));
    },

    /**
     * Check if value is within a numeric range
     * @param {number} value - Value to check
     * @param {number} min - Minimum value
     * @param {number} max - Maximum value
     * @returns {boolean} Whether value is in range
     */
    isInRange(value, min, max) {
        if (this._isEmpty(value)) return true;
        const num = Number(value);
        return !isNaN(num) && num >= min && num <= max;
    },

    /**
     * Check if value is a valid date
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is a valid date
     */
    isValidDate(value) {
        if (this._isEmpty(value)) return true;
        const date = new Date(value);
        return !isNaN(date.getTime());
    },

    /**
     * Check if date is within a range
     * @param {Date|string} value - Date to check
     * @param {Date|string} minDate - Minimum date
     * @param {Date|string} maxDate - Maximum date
     * @returns {boolean} Whether date is in range
     */
    isDateInRange(value, minDate, maxDate) {
        if (this._isEmpty(value)) return true;
        const date = new Date(value);
        const min = new Date(minDate);
        const max = new Date(maxDate);
        return !isNaN(date.getTime()) && date >= min && date <= max;
    },

    /**
     * Check if value is a valid integer
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is a valid integer
     */
    isValidInteger(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.INTEGER.test(String(value));
    },

    /**
     * Check if value is a valid decimal
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is a valid decimal
     */
    isValidDecimal(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.DECIMAL.test(String(value));
    },

    /**
     * Check if value is a valid slug
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid slug
     */
    isValidSlug(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.SLUG.test(String(value));
    },

    /**
     * Check if value is a valid UUID
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid UUID
     */
    isValidUUID(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.UUID.test(String(value));
    },

    /**
     * Check if value is a valid hex color
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid hex color
     */
    isValidHexColor(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.HEX_COLOR.test(String(value));
    },

    /**
     * Check if value is a valid IP address (v4 or v6)
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid IP address
     */
    isValidIP(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.IP_V4.test(String(value)) || 
               this.PATTERNS.IP_V6.test(String(value));
    },

    /**
     * Check if value is a valid domain
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid domain
     */
    isValidDomain(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.DOMAIN.test(String(value));
    },

    /**
     * Check if value is a valid time (HH:MM or HH:MM:SS)
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid time
     */
    isValidTime(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.TIME.test(String(value));
    },

    /**
     * Check if value is a valid ISO date (YYYY-MM-DD)
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid ISO date
     */
    isValidISODate(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.DATE_ISO.test(String(value));
    },

    /**
     * Check if value is a valid ISO datetime
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid ISO datetime
     */
    isValidISODateTime(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.DATE_TIME_ISO.test(String(value));
    },

    // Form-specific validation helpers

    /**
     * Validate a form field
     * @param {HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement} field - Form field
     * @param {Object|Array} rules - Validation rules
     * @returns {ValidationResult} Validation result
     */
    validateField(field, rules) {
        const value = this._getFieldValue(field);
        return this.validate(value, rules, { field });
    },

    /**
     * Get value from a form field
     * @private
     * @param {HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement} field - Form field
     * @returns {*} Field value
     */
    _getFieldValue(field) {
        if (field.type === 'checkbox') {
            return field.checked;
        }
        if (field.type === 'radio') {
            const name = field.name;
            const selected = document.querySelector(`input[name="${name}"]:checked`);
            return selected ? selected.value : null;
        }
        if (field.type === 'file') {
            return field.files;
        }
        if (field.multiple) {
            const options = Array.from(field.selectedOptions || field.options);
            return options.map(opt => opt.value);
        }
        return field.value;
    },

    /**
     * Validate an entire form
     * @param {HTMLFormElement} form - Form element
     * @param {Object} schema - Validation schema
     * @param {Object} options - Validation options
     * @returns {ValidationResult} Validation result
     */
    validateForm(form, schema, options = {}) {
        const data = this._getFormData(form);
        return this.validateObject(data, schema, options);
    },

    /**
     * Get data from a form
     * @private
     * @param {HTMLFormElement} form - Form element
     * @returns {Object} Form data
     */
    _getFormData(form) {
        const data = {};
        const elements = form.elements;

        for (let i = 0; i < elements.length; i++) {
            const element = elements[i];
            const { name, type } = element;

            if (!name) continue;

            if (type === 'checkbox') {
                data[name] = element.checked;
            } else if (type === 'radio') {
                if (element.checked) {
                    data[name] = element.value;
                }
            } else if (type === 'file') {
                data[name] = element.files;
            } else if (element.multiple) {
                const options = Array.from(element.selectedOptions || element.options);
                data[name] = options.map(opt => opt.value);
            } else {
                data[name] = element.value;
            }
        }

        return data;
    },

    /**
     * Display validation errors on a form
     * @param {HTMLFormElement} form - Form element
     * @param {ValidationResult} result - Validation result
     * @param {Object} options - Display options
     */
    displayFormErrors(form, result, options = {}) {
        const { errorClass = 'is-invalid', successClass = 'is-valid', 
                errorMessageClass = 'invalid-feedback', 
                showFirstOnly = false } = options;

        // Clear existing errors
        this.clearFormErrors(form, { errorClass, successClass, errorMessageClass });

        if (result.isValid) {
            // Add success classes if all valid
            const fields = form.querySelectorAll('[name]');
            fields.forEach(field => {
                field.classList.add(successClass);
                field.classList.remove(errorClass);
            });
            return;
        }

        // Show errors
        for (const error of result.errors) {
            if (showFirstOnly && Object.keys(result.errorMap).indexOf(error.field) > 0) {
                continue;
            }

            const field = form.querySelector(`[name="${error.field}"]`);
            if (field) {
                field.classList.add(errorClass);
                field.classList.remove(successClass);

                // Create or update error message
                let messageEl = form.querySelector(`.${errorMessageClass}[data-field="${error.field}"]`);
                if (!messageEl) {
                    messageEl = document.createElement('div');
                    messageEl.className = errorMessageClass;
                    messageEl.setAttribute('data-field', error.field);
                    messageEl.setAttribute('role', 'alert');
                    messageEl.setAttribute('aria-live', 'polite');
                    
                    // Insert after field or its parent
                    if (field.parentNode.classList.contains('form-group') || 
                        field.parentNode.classList.contains('form-control')) {
                        field.parentNode.appendChild(messageEl);
                    } else {
                        field.insertAdjacentElement('afterend', messageEl);
                    }
                }
                messageEl.textContent = error.message;
                messageEl.style.display = 'block';
            }
        }
    },

    /**
     * Clear validation errors from a form
     * @param {HTMLFormElement} form - Form element
     * @param {Object} options - Clear options
     */
    clearFormErrors(form, options = {}) {
        const { errorClass = 'is-invalid', successClass = 'is-valid', 
                errorMessageClass = 'invalid-feedback' } = options;

        const fields = form.querySelectorAll('[name]');
        fields.forEach(field => {
            field.classList.remove(errorClass, successClass);
        });

        const errorMessages = form.querySelectorAll(`.${errorMessageClass}`);
        errorMessages.forEach(msg => {
            msg.style.display = 'none';
        });
    },

    /**
     * Add real-time validation to a form field
     * @param {HTMLInputElement|HTMLSelectElement|HTMLTextAreaElement} field - Form field
     * @param {Object|Array} rules - Validation rules
     * @param {Object} options - Validation options
     * @returns {Function} Cleanup function to remove event listeners
     */
    addFieldValidation(field, rules, options = {}) {
        const { validateOn = ['blur', 'input'], delay = 0 } = options;
        let timeoutId = null;

        const validate = () => {
            if (timeoutId) {
                clearTimeout(timeoutId);
            }
            
            const result = this.validateField(field, rules);
            
            // Apply visual feedback
            if (result.isValid) {
                field.classList.remove('is-invalid');
                field.classList.add('is-valid');
            } else {
                field.classList.remove('is-valid');
                field.classList.add('is-invalid');
            }

            // Trigger custom event
            field.dispatchEvent(new CustomEvent('validation', {
                detail: result,
                bubbles: true
            }));
        };

        const delayedValidate = () => {
            if (delay > 0) {
                timeoutId = setTimeout(validate, delay);
            } else {
                validate();
            }
        };

        // Add event listeners
        validateOn.forEach(event => {
            field.addEventListener(event, delayedValidate);
        });

        // Initial validation
        validate();

        // Return cleanup function
        return () => {
            validateOn.forEach(event => {
                field.removeEventListener(event, delayedValidate);
            });
            if (timeoutId) {
                clearTimeout(timeoutId);
            }
        };
    },

    /**
     * Add real-time validation to an entire form
     * @param {HTMLFormElement} form - Form element
     * @param {Object} schema - Validation schema
     * @param {Object} options - Validation options
     * @returns {Function} Cleanup function to remove all event listeners
     */
    addFormValidation(form, schema, options = {}) {
        const cleanupFunctions = [];
        const { validateOnSubmit = true } = options;

        // Add validation to each field
        for (const [fieldName, rules] of Object.entries(schema)) {
            const field = form.querySelector(`[name="${fieldName}"]`);
            if (field) {
                const cleanup = this.addFieldValidation(field, rules, options);
                cleanupFunctions.push(cleanup);
            }
        }

        // Add submit validation
        let submitCleanup = null;
        if (validateOnSubmit) {
            const handleSubmit = async (e) => {
                e.preventDefault();
                
                const result = this.validateForm(form, schema);
                this.displayFormErrors(form, result);

                if (result.isValid) {
                    // Trigger custom event for valid form
                    form.dispatchEvent(new CustomEvent('formValid', {
                        detail: result,
                        bubbles: true
                    }));
                } else {
                    // Prevent form submission
                    e.stopPropagation();
                    
                    // Focus on first invalid field
                    const firstError = result.errors[0];
                    if (firstError) {
                        const firstField = form.querySelector(`[name="${firstError.field}"]`);
                        if (firstField) {
                            firstField.focus();
                        }
                    }
                }
            };

            form.addEventListener('submit', handleSubmit);
            submitCleanup = () => form.removeEventListener('submit', handleSubmit);
        }

        // Return cleanup function
        return () => {
            cleanupFunctions.forEach(cleanup => cleanup());
            if (submitCleanup) {
                submitCleanup();
            }
        };
    },

    // Utility validation functions

    /**
     * Check if value is empty (null, undefined, empty string, empty array, empty object)
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is empty
     */
    isEmpty(value) {
        return this._isEmpty(value);
    },

    /**
     * Check if value is not empty
     * @param {*} value - Value to check
     * @returns {boolean} Whether value is not empty
     */
    isNotEmpty(value) {
        return !this._isEmpty(value);
    },

    /**
     * Check if value is one of the allowed values
     * @param {*} value - Value to check
     * @param {Array} allowedValues - Allowed values
     * @returns {boolean} Whether value is allowed
     */
    isOneOf(value, allowedValues) {
        return allowedValues.includes(value);
    },

    /**
     * Check if value is not one of the disallowed values
     * @param {*} value - Value to check
     * @param {Array} disallowedValues - Disallowed values
     * @returns {boolean} Whether value is allowed
     */
    isNotOneOf(value, disallowedValues) {
        return !disallowedValues.includes(value);
    },

    /**
     * Check if value equals another value
     * @param {*} value - Value to check
     * @param {*} other - Value to compare against
     * @returns {boolean} Whether values are equal
     */
    equals(value, other) {
        return value === other;
    },

    /**
     * Check if value does not equal another value
     * @param {*} value - Value to check
     * @param {*} other - Value to compare against
     * @returns {boolean} Whether values are not equal
     */
    notEquals(value, other) {
        return value !== other;
    },

    /**
     * Check if value is greater than another value
     * @param {number} value - Value to check
     * @param {number} other - Value to compare against
     * @returns {boolean} Whether value is greater
     */
    greaterThan(value, other) {
        return Number(value) > Number(other);
    },

    /**
     * Check if value is less than another value
     * @param {number} value - Value to check
     * @param {number} other - Value to compare against
     * @returns {boolean} Whether value is less
     */
    lessThan(value, other) {
        return Number(value) < Number(other);
    },

    /**
     * Check if value is greater than or equal to another value
     * @param {number} value - Value to check
     * @param {number} other - Value to compare against
     * @returns {boolean} Whether value is greater or equal
     */
    greaterThanOrEqual(value, other) {
        return Number(value) >= Number(other);
    },

    /**
     * Check if value is less than or equal to another value
     * @param {number} value - Value to check
     * @param {number} other - Value to compare against
     * @returns {boolean} Whether value is less or equal
     */
    lessThanOrEqual(value, other) {
        return Number(value) <= Number(other);
    },

    /**
     * Check if string contains only alphanumeric characters
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is alphanumeric
     */
    isAlphanumeric(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.ALPHANUMERIC.test(String(value));
    },

    /**
     * Check if string contains only alphanumeric characters and spaces
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is alphanumeric with spaces
     */
    isAlphanumericWithSpaces(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.ALPHANUMERIC_SPACE.test(String(value));
    },

    /**
     * Check if string is lowercase
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is lowercase
     */
    isLowercase(value) {
        if (this._isEmpty(value)) return true;
        return String(value) === String(value).toLowerCase();
    },

    /**
     * Check if string is uppercase
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is uppercase
     */
    isUppercase(value) {
        if (this._isEmpty(value)) return true;
        return String(value) === String(value).toUpperCase();
    },

    /**
     * Check if string starts with a specific prefix
     * @param {string} value - Value to check
     * @param {string} prefix - Prefix to check for
     * @returns {boolean} Whether value starts with prefix
     */
    startsWith(value, prefix) {
        if (this._isEmpty(value)) return true;
        return String(value).startsWith(prefix);
    },

    /**
     * Check if string ends with a specific suffix
     * @param {string} value - Value to check
     * @param {string} suffix - Suffix to check for
     * @returns {boolean} Whether value ends with suffix
     */
    endsWith(value, suffix) {
        if (this._isEmpty(value)) return true;
        return String(value).endsWith(suffix);
    },

    /**
     * Check if string contains a substring
     * @param {string} value - Value to check
     * @param {string} substring - Substring to check for
     * @returns {boolean} Whether value contains substring
     */
    contains(value, substring) {
        if (this._isEmpty(value)) return true;
        return String(value).includes(substring);
    },

    /**
     * Check if string does not contain a substring
     * @param {string} value - Value to check
     * @param {string} substring - Substring to check for
     * @returns {boolean} Whether value does not contain substring
     */
    notContains(value, substring) {
        if (this._isEmpty(value)) return true;
        return !String(value).includes(substring);
    },

    /**
     * Check if value is a valid credit card number (Luhn algorithm)
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid credit card number
     */
    isValidCreditCard(value) {
        if (this._isEmpty(value)) return true;
        
        const cleaned = String(value).replace(/\D/g, '');
        if (!cleaned || cleaned.length < 13) return false;

        let sum = 0;
        let shouldDouble = false;

        for (let i = cleaned.length - 1; i >= 0; i--) {
            let digit = parseInt(cleaned.charAt(i), 10);
            
            if (shouldDouble) {
                digit *= 2;
                if (digit > 9) {
                    digit = (digit % 10) + 1;
                }
            }

            sum += digit;
            shouldDouble = !shouldDouble;
        }

        return sum % 10 === 0;
    },

    /**
     * Check if value is a valid phone number
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid phone number
     */
    isValidPhone(value) {
        if (this._isEmpty(value)) return true;
        return this.PATTERNS.PHONE.test(String(value));
    },

    /**
     * Check if value is a valid timezone
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid timezone
     */
    isValidTimezone(value) {
        if (this._isEmpty(value)) return true;
        try {
            return Intl.DateTimeFormat().resolvedOptions().timeZone.includes(value) ||
                   new Date().toLocaleString('en-US', { timeZone: value }).length > 0;
        } catch {
            return false;
        }
    },

    /**
     * Check if value is a valid locale
     * @param {string} value - Value to check
     * @returns {boolean} Whether value is a valid locale
     */
    isValidLocale(value) {
        if (this._isEmpty(value)) return true;
        try {
            return new Intl.DateTimeFormat(value).format() !== '';
        } catch {
            return false;
        }
    }
};

// Export for use in modules
export { ValidationUtils };
