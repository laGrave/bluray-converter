// BluRay Converter - Web UI Application Logic
// Main JavaScript for interface functionality

// Alpine.js application data and methods
function app() {
    return {
        // State
        loading: false,
        activeTab: 'dashboard',
        
        // Data
        tasks: [],
        filteredTasks: [],
        statistics: {},
        systemHealth: {},
        systemInfo: {},
        systemStatus: { connected: false },
        logs: '',
        
        // Filters and search
        taskFilter: '',
        searchQuery: '',
        
        // UI state
        notification: {
            show: false,
            type: 'info',
            title: '',
            message: ''
        },
        
        modal: {
            show: false,
            task: null
        },
        
        // Charts
        statusChart: null,
        timeChart: null,
        
        // Auto-refresh
        refreshInterval: null,
        refreshRate: 30000, // 30 seconds
        
        // Initialize application
        async init() {
            console.log('Initializing BluRay Converter Web UI...');
            
            // Load initial data
            await this.loadInitialData();
            
            // Initialize charts
            this.initializeCharts();
            
            // Start auto-refresh
            this.startAutoRefresh();
            
            // Load saved preferences
            this.loadUserPreferences();
            
            // Setup error handlers
            this.setupErrorHandlers();
            
            console.log('Application initialized successfully');
        },

        // Load all initial data
        async loadInitialData() {
            this.loading = true;
            
            try {
                // Load data in parallel
                await Promise.allSettled([
                    this.checkSystemHealth(),
                    this.loadStatistics(),
                    this.loadTasks(),
                    this.loadSystemInfo()
                ]);
                
                this.systemStatus.connected = true;
                
            } catch (error) {
                console.error('Failed to load initial data:', error);
                this.systemStatus.connected = false;
                this.showNotification('error', 'Connection Error', 'Failed to connect to the server');
            } finally {
                this.loading = false;
            }
        },

        // System health check
        async checkSystemHealth() {
            try {
                const response = await apiClient.checkHealth();
                if (response.success) {
                    this.systemHealth = response.data;
                    this.systemStatus.connected = true;
                } else {
                    throw new Error(response.error);
                }
            } catch (error) {
                this.systemStatus.connected = false;
                throw error;
            }
        },

        // Load system information
        async loadSystemInfo() {
            try {
                this.systemInfo = await apiClient.getSystemInfo();
            } catch (error) {
                console.error('Failed to load system info:', error);
            }
        },

        // Load statistics
        async loadStatistics() {
            try {
                this.statistics = await apiClient.getStatistics();
                this.updateCharts();
            } catch (error) {
                console.error('Failed to load statistics:', error);
                this.showNotification('error', 'Error', 'Failed to load statistics');
            }
        },

        // Load tasks
        async loadTasks() {
            try {
                const status = this.taskFilter || null;
                this.tasks = await apiClient.getTasks(status);
                this.filterTasks();
            } catch (error) {
                console.error('Failed to load tasks:', error);
                this.showNotification('error', 'Error', 'Failed to load tasks');
            }
        },

        // Load system logs
        async loadLogs() {
            try {
                const response = await apiClient.getLogs(100);
                if (typeof response === 'object' && response.logs) {
                    this.logs = response.logs.map(log => 
                        `[${log.timestamp}] ${log.level}: ${log.message}`
                    ).join('\n');
                } else if (typeof response === 'string') {
                    this.logs = response;
                } else {
                    this.logs = 'No logs available';
                }
            } catch (error) {
                console.error('Failed to load logs:', error);
                this.logs = 'Failed to load logs: ' + apiHelpers.formatError(error);
            }
        },

        // Filter tasks based on search query
        filterTasks() {
            let filtered = [...this.tasks];
            
            if (this.searchQuery) {
                const query = this.searchQuery.toLowerCase();
                filtered = filtered.filter(task => 
                    task.movie_name.toLowerCase().includes(query) ||
                    task.source_path.toLowerCase().includes(query)
                );
            }
            
            this.filteredTasks = filtered;
        },

        // Refresh all data
        async refreshData() {
            if (this.loading) return;
            
            await this.loadInitialData();
            this.showNotification('success', 'Refreshed', 'Data updated successfully');
        },

        // Scan for new movies
        async scanForMovies() {
            if (this.loading) return;
            
            this.loading = true;
            
            try {
                const response = await apiClient.scanForMovies();
                this.showNotification('success', 'Scan Started', response.message || 'Movie scan initiated');
                
                // Refresh data after a delay
                setTimeout(() => this.loadTasks(), 2000);
                
            } catch (error) {
                this.showNotification('error', 'Scan Failed', apiHelpers.formatError(error));
            } finally {
                this.loading = false;
            }
        },

        // Restart a task
        async restartTask(taskId) {
            if (this.loading) return;
            
            try {
                const response = await apiClient.restartTask(taskId);
                this.showNotification('success', 'Task Restarted', response.message);
                await this.loadTasks();
                
            } catch (error) {
                this.showNotification('error', 'Restart Failed', apiHelpers.formatError(error));
            }
        },

        // Delete a task
        async deleteTask(taskId) {
            if (!confirm('Are you sure you want to delete this task?')) {
                return;
            }
            
            if (this.loading) return;
            
            try {
                const response = await apiClient.deleteTask(taskId);
                this.showNotification('success', 'Task Deleted', response.message);
                await this.loadTasks();
                
            } catch (error) {
                this.showNotification('error', 'Delete Failed', apiHelpers.formatError(error));
            }
        },

        // View task details in modal
        viewTaskDetails(task) {
            this.modal.task = task;
            this.modal.show = true;
        },

        // Show system info modal
        showSystemInfo() {
            const info = {
                ...this.systemInfo,
                health: this.systemHealth
            };
            
            alert(JSON.stringify(info, null, 2));
        },

        // Initialize charts
        initializeCharts() {
            // Wait for DOM to be ready
            this.$nextTick(() => {
                this.createStatusChart();
                this.createTimeChart();
            });
        },

        // Create status distribution chart
        createStatusChart() {
            const ctx = document.getElementById('statusChart');
            if (!ctx) return;
            
            const data = {
                labels: ['Pending', 'Processing', 'Completed', 'Failed'],
                datasets: [{
                    data: [
                        this.statistics.pending_tasks || 0,
                        this.statistics.processing_tasks || 0,
                        this.statistics.completed_tasks || 0,
                        this.statistics.failed_tasks || 0
                    ],
                    backgroundColor: [
                        '#FCD34D', // Yellow for pending
                        '#60A5FA', // Blue for processing
                        '#34D399', // Green for completed
                        '#EF4444'  // Red for failed
                    ],
                    borderWidth: 0
                }]
            };
            
            this.statusChart = new Chart(ctx, {
                type: 'doughnut',
                data: data,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'bottom'
                        }
                    }
                }
            });
        },

        // Create time series chart
        createTimeChart() {
            const ctx = document.getElementById('timeChart');
            if (!ctx) return;
            
            // Generate sample data for now
            const labels = [];
            const data = [];
            const now = new Date();
            
            for (let i = 6; i >= 0; i--) {
                const date = new Date(now);
                date.setDate(date.getDate() - i);
                labels.push(date.toLocaleDateString());
                data.push(Math.floor(Math.random() * 10) + 1);
            }
            
            this.timeChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Completed Tasks',
                        data: data,
                        borderColor: '#3B82F6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        tension: 0.4,
                        fill: true
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                stepSize: 1
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: false
                        }
                    }
                }
            });
        },

        // Update charts with new data
        updateCharts() {
            if (this.statusChart) {
                this.statusChart.data.datasets[0].data = [
                    this.statistics.pending_tasks || 0,
                    this.statistics.processing_tasks || 0,
                    this.statistics.completed_tasks || 0,
                    this.statistics.failed_tasks || 0
                ];
                this.statusChart.update();
            }
        },

        // Start auto-refresh timer
        startAutoRefresh() {
            this.refreshInterval = setInterval(async () => {
                if (this.activeTab === 'dashboard') {
                    await this.loadStatistics();
                }
                
                // Always check system health
                try {
                    await this.checkSystemHealth();
                } catch (error) {
                    // Silent fail for background health checks
                }
            }, this.refreshRate);
        },

        // Stop auto-refresh timer
        stopAutoRefresh() {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        },

        // Show notification
        showNotification(type, title, message) {
            this.notification = {
                show: true,
                type,
                title,
                message
            };
            
            // Auto-hide after 5 seconds
            setTimeout(() => {
                this.notification.show = false;
            }, 5000);
        },

        // Load user preferences from localStorage
        loadUserPreferences() {
            this.activeTab = apiHelpers.storage.get('activeTab', 'dashboard');
            this.taskFilter = apiHelpers.storage.get('taskFilter', '');
            this.refreshRate = apiHelpers.storage.get('refreshRate', 30000);
        },

        // Save user preferences to localStorage
        saveUserPreferences() {
            apiHelpers.storage.set('activeTab', this.activeTab);
            apiHelpers.storage.set('taskFilter', this.taskFilter);
            apiHelpers.storage.set('refreshRate', this.refreshRate);
        },

        // Setup global error handlers
        setupErrorHandlers() {
            window.addEventListener('error', (event) => {
                console.error('Global error:', event.error);
                this.showNotification('error', 'Error', 'An unexpected error occurred');
            });
            
            window.addEventListener('unhandledrejection', (event) => {
                console.error('Unhandled promise rejection:', event.reason);
                this.showNotification('error', 'Error', 'An unexpected error occurred');
            });
        },

        // Helper methods that can be used in templates
        formatDate: apiHelpers.formatDate,
        getStatusColor: apiHelpers.getStatusColor,
        formatFileSize: apiHelpers.formatFileSize,
        formatDuration: apiHelpers.formatDuration,

        // Cleanup when component is destroyed
        destroy() {
            this.stopAutoRefresh();
            
            if (this.statusChart) {
                this.statusChart.destroy();
            }
            
            if (this.timeChart) {
                this.timeChart.destroy();
            }
        }
    };
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('BluRay Converter Web UI loaded');
});

// Handle page unload
window.addEventListener('beforeunload', () => {
    // Save preferences before leaving
    if (window.alpineApp) {
        window.alpineApp.saveUserPreferences();
        window.alpineApp.destroy();
    }
});

// Expose app for debugging
window.alpineApp = null;

// Alpine.js will call this automatically
window.app = app;