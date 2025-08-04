// BluRay Converter - Web UI API Client
// JavaScript functions for API communication

class APIClient {
    constructor(baseURL = '/api') {
        this.baseURL = baseURL;
        this.timeout = 30000; // 30 seconds
    }

    // Generic request method
    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            timeout: this.timeout,
        };

        const config = { ...defaultOptions, ...options };

        // Add timeout to fetch
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), config.timeout);
        
        try {
            const response = await fetch(url, {
                ...config,
                signal: controller.signal,
            });

            clearTimeout(timeoutId);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                return await response.json();
            } else {
                return await response.text();
            }
        } catch (error) {
            clearTimeout(timeoutId);
            
            if (error.name === 'AbortError') {
                throw new Error('Request timeout');
            }
            
            throw error;
        }
    }

    // GET request
    async get(endpoint) {
        return this.request(endpoint, { method: 'GET' });
    }

    // POST request
    async post(endpoint, data = null) {
        return this.request(endpoint, {
            method: 'POST',
            body: data ? JSON.stringify(data) : null,
        });
    }

    // PUT request
    async put(endpoint, data = null) {
        return this.request(endpoint, {
            method: 'PUT',
            body: data ? JSON.stringify(data) : null,
        });
    }

    // DELETE request
    async delete(endpoint) {
        return this.request(endpoint, { method: 'DELETE' });
    }

    // Health check
    async checkHealth() {
        try {
            const response = await this.get('/health');
            return {
                success: true,
                data: response,
            };
        } catch (error) {
            return {
                success: false,
                error: error.message,
            };
        }
    }

    // System information
    async getSystemInfo() {
        return this.get('/info');
    }

    // Statistics
    async getStatistics() {
        return this.get('/statistics');
    }

    // Tasks
    async getTasks(status = null, limit = 100, offset = 0) {
        let endpoint = `/tasks?limit=${limit}&offset=${offset}`;
        if (status) {
            endpoint += `&status=${status}`;
        }
        return this.get(endpoint);
    }

    async getTask(taskId) {
        return this.get(`/tasks/${taskId}`);
    }

    async scanForMovies() {
        return this.post('/tasks/scan');
    }

    async restartTask(taskId) {
        return this.post(`/tasks/${taskId}/restart`);
    }

    async deleteTask(taskId) {
        return this.delete(`/tasks/${taskId}`);
    }

    async setTaskPriority(taskId, priority) {
        return this.post(`/tasks/${taskId}/priority?priority=${priority}`);
    }

    // Logs
    async getLogs(limit = 100, level = null) {
        let endpoint = `/logs?limit=${limit}`;
        if (level) {
            endpoint += `&level=${level}`;
        }
        return this.get(endpoint);
    }

    // Webhook test
    async testWebhook() {
        return this.post('/webhook/test');
    }
}

// Export singleton instance
window.apiClient = new APIClient();

// Helper functions for common API patterns
window.apiHelpers = {
    // Retry failed requests
    async withRetry(apiCall, maxRetries = 3, delay = 1000) {
        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                return await apiCall();
            } catch (error) {
                if (attempt === maxRetries) {
                    throw error;
                }
                
                // Exponential backoff
                await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, attempt - 1)));
            }
        }
    },

    // Format error messages
    formatError(error) {
        if (typeof error === 'string') {
            return error;
        }
        
        if (error.message) {
            return error.message;
        }
        
        if (error.detail) {
            return error.detail;
        }
        
        return 'Unknown error occurred';
    },

    // Check if error is network-related
    isNetworkError(error) {
        return error.message.includes('fetch') || 
               error.message.includes('network') || 
               error.message.includes('timeout') ||
               error.message.includes('Failed to fetch');
    },

    // Debounce function for search
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // Format file sizes
    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    // Format duration
    formatDuration(seconds) {
        if (!seconds || seconds < 0) return '0 seconds';
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}h ${minutes}m ${secs}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    },

    // Format dates
    formatDate(dateString) {
        if (!dateString) return 'N/A';
        
        const date = new Date(dateString);
        if (isNaN(date.getTime())) return 'Invalid Date';
        
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);
        
        if (diffMins < 1) {
            return 'Just now';
        } else if (diffMins < 60) {
            return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`;
        } else if (diffHours < 24) {
            return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`;
        } else if (diffDays < 7) {
            return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`;
        } else {
            return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
        }
    },

    // Get status color class
    getStatusColor(status) {
        const statusColors = {
            'pending': 'bg-yellow-100 text-yellow-800',
            'sent': 'bg-purple-100 text-purple-800',
            'processing': 'bg-blue-100 text-blue-800',
            'completed': 'bg-green-100 text-green-800',
            'failed': 'bg-red-100 text-red-800',
            'retrying': 'bg-orange-100 text-orange-800',
        };
        
        return statusColors[status?.toLowerCase()] || 'bg-gray-100 text-gray-800';
    },

    // Validate task data
    validateTask(task) {
        const required = ['movie_name', 'source_path'];
        const missing = required.filter(field => !task[field]);
        
        if (missing.length > 0) {
            throw new Error(`Missing required fields: ${missing.join(', ')}`);
        }
        
        return true;
    },

    // Local storage helpers
    storage: {
        get(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(key);
                return item ? JSON.parse(item) : defaultValue;
            } catch {
                return defaultValue;
            }
        },
        
        set(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
            } catch (error) {
                console.warn('Failed to store data:', error);
            }
        },
        
        remove(key) {
            try {
                localStorage.removeItem(key);
            } catch (error) {
                console.warn('Failed to remove data:', error);
            }
        }
    },

    // URL helpers
    updateQueryParams(params) {
        const url = new URL(window.location);
        Object.entries(params).forEach(([key, value]) => {
            if (value) {
                url.searchParams.set(key, value);
            } else {
                url.searchParams.delete(key);
            }
        });
        window.history.replaceState({}, '', url);
    },

    getQueryParam(key, defaultValue = null) {
        const url = new URL(window.location);
        return url.searchParams.get(key) || defaultValue;
    }
};