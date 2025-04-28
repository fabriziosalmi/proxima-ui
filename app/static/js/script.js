// Custom JavaScript for Proxmox UI

/**
 * Initialize the UI when the document is ready
 */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize sidebar toggle
    initSidebar();
    
    // Enable tooltips
    enableTooltips();
    
    // Initialize table sorting
    initTableSorting();
    
    // Initialize dark mode
    initDarkMode();
    
    // Initialize action confirmations
    initActionConfirmations();
    
    // Set up auto-refresh for system status
    initAutoRefresh();
    
    // Initialize resource charts
    initResourceCharts();
    
    // Auto-close alerts after 5 seconds
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function(alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);
});

/**
 * Initialize sidebar toggle functionality
 */
function initSidebar() {
    const sidebarCollapse = document.getElementById('sidebarCollapse');
    const sidebar = document.getElementById('sidebar');
    
    if (sidebarCollapse && sidebar) {
        // Check for stored sidebar state
        const sidebarCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
        
        // Initialize sidebar state
        if (sidebarCollapsed) {
            sidebar.classList.add('collapsed');
        }
        
        // Toggle sidebar when button is clicked
        sidebarCollapse.addEventListener('click', function() {
            sidebar.classList.toggle('collapsed');
            
            // Store sidebar state
            localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
        });
    }
}

/**
 * Initialize tooltips across the application
 */
function enableTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl, {
            delay: { show: 300, hide: 100 }
        });
    });
}

/**
 * Initialize dark mode toggle functionality
 */
function initDarkMode() {
    const themeToggle = document.getElementById('theme-toggle');
    const body = document.body;
    const icon = themeToggle ? themeToggle.querySelector('i') : null;
    
    // Function to set theme based on preference
    function setTheme(darkMode) {
        // Update body attribute
        body.setAttribute('data-bs-theme', darkMode ? 'dark' : 'light');
        
        // Update button icon
        if (icon) {
            icon.className = darkMode ? 'fas fa-sun' : 'fas fa-moon';
        }
        
        // Store theme preference
        localStorage.setItem('darkMode', darkMode);
    }
    
    // Check for system preference first, if not overridden by user preference
    if (!localStorage.getItem('darkMode')) {
        const prefersDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
        setTheme(prefersDarkMode);
    } else {
        // Use stored preference
        const darkModeEnabled = localStorage.getItem('darkMode') === 'true';
        setTheme(darkModeEnabled);
    }
    
    // Add listener for system preference changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
        // Only apply if user hasn't set a preference
        if (!localStorage.getItem('darkMode')) {
            setTheme(e.matches);
        }
    });
    
    // Toggle theme when button is clicked
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            const currentTheme = body.getAttribute('data-bs-theme');
            const newDarkMode = currentTheme !== 'dark';
            setTheme(newDarkMode);
        });
    }
}

/**
 * Initialize action confirmations for dangerous operations
 */
function initActionConfirmations() {
    const confirmForms = document.querySelectorAll('form[data-confirm]');
    
    confirmForms.forEach(form => {
        form.addEventListener('submit', function(event) {
            const confirmMessage = this.getAttribute('data-confirm');
            
            if (!confirm(confirmMessage)) {
                event.preventDefault();
            }
        });
    });
    
    // Add confirmation for action buttons
    const confirmButtons = document.querySelectorAll('[data-confirm-action]');
    
    confirmButtons.forEach(button => {
        button.addEventListener('click', function(event) {
            const confirmMessage = this.getAttribute('data-confirm-action');
            
            if (!confirm(confirmMessage)) {
                event.preventDefault();
            }
        });
    });
}

/**
 * Initialize auto-refresh for system status pages
 */
function initAutoRefresh() {
    const refreshableContent = document.querySelectorAll('[data-refresh]');
    
    refreshableContent.forEach(element => {
        const refreshInterval = parseInt(element.getAttribute('data-refresh')) || 30000; // Default 30s
        const refreshUrl = element.getAttribute('data-refresh-url');
        
        if (refreshUrl) {
            setInterval(() => {
                fetch(refreshUrl)
                    .then(response => response.text())
                    .then(html => {
                        element.innerHTML = html;
                    })
                    .catch(error => console.error('Error refreshing content:', error));
            }, refreshInterval);
        }
    });
    
    // Auto-refresh toggle
    const refreshToggle = document.getElementById('refresh-toggle');
    
    if (refreshToggle) {
        refreshToggle.addEventListener('change', function() {
            const isEnabled = this.checked;
            
            if (isEnabled) {
                initAutoRefresh(); // Restart auto-refresh
            } else {
                // Clear all auto-refresh intervals
                for (let i = 1; i < 9999; i++) {
                    window.clearInterval(i);
                }
            }
            
            // Store preference
            localStorage.setItem('autoRefreshEnabled', isEnabled);
        });
        
        // Initialize toggle state from stored preference
        const autoRefreshEnabled = localStorage.getItem('autoRefreshEnabled') !== 'false';
        refreshToggle.checked = autoRefreshEnabled;
    }
}

/**
 * VM and Container action handlers
 */
function performAction(hostId, node, vmid, action, type = 'vm') {
    const endpoint = type === 'vm' ? '/api/vm/action' : '/api/container/action';
    const loadingElement = document.getElementById(`${type}-${vmid}-status`);
    const originalContent = loadingElement ? loadingElement.innerHTML : '';
    
    if (loadingElement) {
        loadingElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
    }
    
    const formData = new FormData();
    formData.append('host_id', hostId);
    formData.append('node', node);
    formData.append('vmid', vmid);
    formData.append('action', action);
    
    fetch(endpoint, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Success handling
            const successMessage = `Action ${action} was performed successfully`;
            showNotification(successMessage, 'success');
            
            // Reload page after a delay to show updated status
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            // Error handling
            showNotification(`Error: ${data.error}`, 'danger');
            
            if (loadingElement) {
                loadingElement.innerHTML = originalContent;
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('An unexpected error occurred', 'danger');
        
        if (loadingElement) {
            loadingElement.innerHTML = originalContent;
        }
    });
}

/**
 * Bulk action handler
 */
function performBulkAction(hostId, action, items, type = 'vm') {
    const endpoint = type === 'vm' ? '/api/bulk/vm/action' : '/api/bulk/container/action';
    const loadingElement = document.getElementById('bulk-status');
    
    if (loadingElement) {
        loadingElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing bulk action...';
    }
    
    const formData = new FormData();
    formData.append('host_id', hostId);
    formData.append('action', action);
    formData.append(type === 'vm' ? 'vms' : 'containers', JSON.stringify(items));
    
    fetch(endpoint, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Success handling
            showNotification(data.message, 'success');
            
            // If there are warnings, show them
            if (data.warnings && data.warnings.length > 0) {
                for (const warning of data.warnings) {
                    showNotification(warning, 'warning');
                }
            }
            
            // Reload page after a delay
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            // Error handling
            showNotification(`Error: ${data.error}`, 'danger');
            
            if (loadingElement) {
                loadingElement.innerHTML = '';
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('An unexpected error occurred', 'danger');
        
        if (loadingElement) {
            loadingElement.innerHTML = '';
        }
    });
}

/**
 * Display an in-page notification
 */
function showNotification(message, type = 'info') {
    const notificationArea = document.querySelector('.flash-messages');
    
    if (!notificationArea) return;
    
    const notification = document.createElement('div');
    notification.className = `alert alert-${type} alert-dismissible fade show`;
    notification.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    
    notificationArea.appendChild(notification);
    
    // Auto dismiss notification after 5 seconds
    setTimeout(() => {
        const bsAlert = new bootstrap.Alert(notification);
        bsAlert.close();
    }, 5000);
}

/**
 * Initialize resource usage charts
 */
function initResourceCharts() {
    const chartCanvases = document.querySelectorAll('canvas[data-chart]');
    
    chartCanvases.forEach(canvas => {
        const chartType = canvas.getAttribute('data-chart-type') || 'line';
        const chartData = JSON.parse(canvas.getAttribute('data-chart'));
        const chartOptions = JSON.parse(canvas.getAttribute('data-chart-options') || '{}');
        
        new Chart(canvas, {
            type: chartType,
            data: chartData,
            options: Object.assign({
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 1000,
                    easing: 'easeOutQuart'
                }
            }, chartOptions)
        });
    });
}

/**
 * Table sorting functionality
 */
function initTableSorting() {
    const tables = document.querySelectorAll('table');
    
    tables.forEach(table => {
        const headers = table.querySelectorAll('th.sortable');
        
        headers.forEach(header => {
            // Add sort icon if not already present
            if (!header.querySelector('i.fa-sort')) {
                const icon = document.createElement('i');
                icon.className = 'fas fa-sort ms-1';
                header.appendChild(icon);
            }
            
            header.addEventListener('click', function() {
                const sortKey = this.getAttribute('data-sort');
                const tableBody = this.closest('table').querySelector('tbody');
                const rows = Array.from(tableBody.querySelectorAll('tr'));
                
                // Get current sort direction or default to ascending
                let sortDirection = this.getAttribute('data-sort-direction') || 'asc';
                
                // Toggle sort direction
                sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
                
                // Update sort direction attribute
                this.setAttribute('data-sort-direction', sortDirection);
                
                // Reset sort indicators on all headers
                headers.forEach(h => {
                    const icon = h.querySelector('i');
                    if (icon) {
                        icon.className = 'fas fa-sort ms-1';
                    }
                });
                
                // Update sort indicator on clicked header
                const icon = this.querySelector('i');
                if (icon) {
                    icon.className = `fas fa-sort-${sortDirection === 'asc' ? 'up' : 'down'} ms-1`;
                }
                
                // Sort the rows
                rows.sort((rowA, rowB) => {
                    const cellA = rowA.querySelector(`td:nth-child(${this.cellIndex + 1})`);
                    const cellB = rowB.querySelector(`td:nth-child(${this.cellIndex + 1})`);
                    
                    if (!cellA || !cellB) return 0;
                    
                    // Use data-value attribute if available, otherwise use text content
                    const valueA = cellA.hasAttribute('data-value') ? cellA.getAttribute('data-value') : cellA.textContent.trim();
                    const valueB = cellB.hasAttribute('data-value') ? cellB.getAttribute('data-value') : cellB.textContent.trim();
                    
                    // Check if values are numbers
                    const numA = parseFloat(valueA);
                    const numB = parseFloat(valueB);
                    
                    if (!isNaN(numA) && !isNaN(numB)) {
                        // Sort numerically
                        return sortDirection === 'asc' ? numA - numB : numB - numA;
                    } else {
                        // Sort alphabetically
                        return sortDirection === 'asc' 
                            ? valueA.localeCompare(valueB) 
                            : valueB.localeCompare(valueA);
                    }
                });
                
                // Reorder the table rows
                rows.forEach(row => tableBody.appendChild(row));
            });
        });
    });
}