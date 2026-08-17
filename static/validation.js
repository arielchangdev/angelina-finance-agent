/**
 * Chat UI Validation Module
 * Extracted from index.html for independent testing.
 *
 * validateMessage(message) checks:
 *   1. Empty or whitespace-only messages are rejected.
 *   2. Messages exceeding 2000 characters are rejected.
 *   3. All other messages are accepted.
 */

function validateMessage(message) {
    if (!message || message.trim() === '') {
        return { valid: false, error: 'Please enter a valid message.' };
    }
    if (message.length > 2000) {
        return { valid: false, error: 'Message exceeds 2000 character limit.' };
    }
    return { valid: true, error: null };
}

// Export for Node.js testing (when available)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { validateMessage };
}
