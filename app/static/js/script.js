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
    
    // Initialize optional columns display based on user settings
    initOptionalColumns();
    
    // Auto-close alerts after 5 seconds
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function(alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);
    
    // Add debouncing to search inputs
    const searchInputs = document.querySelectorAll('input[type="search"]');
    searchInputs.forEach(input => {
        const originalHandler = input.oninput;
        input.oninput = null;
        input.addEventListener('input', debounce(function(e) {
            if (originalHandler) {
                originalHandler.call(this, e);
            }
        }, 300));
    });

    // Properly handle history API for smoother page transitions
    window.addEventListener('popstate', function(event) {
        // Hide any loading indicators
        document.getElementById('page-loading-indicator').classList.add('d-none');
        document.querySelector('.content-container')?.classList.remove('opacity-50');
    });

    // Add keyboard shortcut (Ctrl+K or Command+K) for search modal
    document.addEventListener('keydown', function(e) {
        // Check if Ctrl+K or Command+K was pressed
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            
            // Show search modal
            const searchModal = new bootstrap.Modal(document.getElementById('searchModal'));
            searchModal.show();
            
            // Focus on search input after modal is shown
            document.getElementById('searchModal').addEventListener('shown.bs.modal', function() {
                document.getElementById('modal-global-search').focus();
            }, { once: true });
        }
    });
    
    // Initialize search modal auto focus
    const searchModal = document.getElementById('searchModal');
    if (searchModal) {
        searchModal.addEventListener('shown.bs.modal', function() {
            document.getElementById('modal-global-search').focus();
        });
        
        // Submit search form on Enter key
        const searchInput = document.getElementById('modal-global-search');
        if (searchInput) {
            searchInput.addEventListener('keydown', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    document.getElementById('searchForm').submit();
                }
            });
        }
    }
    
    // Improve modal backdrops with blur effect
    const modalBackdrops = document.querySelectorAll('.modal-backdrop');
    modalBackdrops.forEach(backdrop => {
        backdrop.style.backdropFilter = 'blur(4px)';
        backdrop.style.webkitBackdropFilter = 'blur(4px)';
    });
    
    // Initialize proper theme handling for modals
    const updateModalTheme = () => {
        const theme = document.body.getAttribute('data-bs-theme');
        const modals = document.querySelectorAll('.modal');
        
        modals.forEach(modal => {
            if (theme === 'dark') {
                modal.classList.add('modal-dark');
            } else {
                modal.classList.remove('modal-dark');
            }
        });
    };
    
    // Update modal theme when theme changes
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', updateModalTheme);
    }
    
    // Initial modal theme setup
    updateModalTheme();
    
    // Run on page load
    adjustBadgeColors();
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
    const refreshStatusElements = document.querySelectorAll('.refresh-status');
    
    refreshableContent.forEach((element, index) => {
        const refreshInterval = parseInt(element.getAttribute('data-refresh')) || 30000; // Default 30s
        const refreshUrl = element.getAttribute('data-refresh-url');
        
        if (refreshUrl) {
            let secondsLeft = refreshInterval / 1000;
            const statusElement = refreshStatusElements[index] || document.createElement('div');
            
            // Update countdown every second
            const countdownInterval = setInterval(() => {
                secondsLeft--;
                if (statusElement) {
                    statusElement.textContent = `Refreshing in ${secondsLeft}s`;
                }
                
                if (secondsLeft <= 0) {
                    clearInterval(countdownInterval);
                }
            }, 1000);
            
            // Set refresh interval
            setInterval(() => {
                element.classList.add('loading');
                
                fetch(refreshUrl)
                    .then(response => response.text())
                    .then(html => {
                        element.innerHTML = html;
                        element.classList.remove('loading');
                        secondsLeft = refreshInterval / 1000;
                    })
                    .catch(error => {
                        console.error('Error refreshing content:', error);
                        element.classList.remove('loading');
                    });
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
    
    // Show loading indicator in element
    if (loadingElement) {
        loadingElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
    }
    
    // Show full-screen loading overlay
    showLoadingOverlay(`Processing ${action}...`);
    
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
            // Success notification
            showNotification(`Successfully executed ${action}`, 'success');
            
            // Reload page after a delay to show updated status
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            // Error notification
            showNotification(`Error: ${data.error}`, 'danger');
            
            if (loadingElement) {
                loadingElement.innerHTML = originalContent;
            }
            
            // Hide loading overlay
            hideLoadingOverlay();
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('An unexpected error occurred', 'danger');
        
        if (loadingElement) {
            loadingElement.innerHTML = originalContent;
        }
        
        // Hide loading overlay
        hideLoadingOverlay();
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
    
    // Show full-screen loading overlay
    showLoadingOverlay(`Processing bulk ${action}...`);
    
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
            
            // Hide loading overlay
            hideLoadingOverlay();
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('An unexpected error occurred', 'danger');
        
        if (loadingElement) {
            loadingElement.innerHTML = '';
        }
        
        // Hide loading overlay
        hideLoadingOverlay();
    });
}

/**
 * Display an in-page notification
 */
function showNotification(message, type = 'info') {
    // Create notification container if it doesn't exist
    let container = document.getElementById('notification-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'notification-container';
        container.className = 'position-fixed top-0 end-0 p-3';
        container.style.zIndex = '1050';
        document.body.appendChild(container);
    }
    
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `toast align-items-center text-white bg-${type} border-0`;
    notification.setAttribute('role', 'alert');
    notification.setAttribute('aria-live', 'assertive');
    notification.setAttribute('aria-atomic', 'true');
    
    notification.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">
                ${message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
        </div>
    `;
    
    // Add to container
    container.appendChild(notification);
    
    // Initialize and show toast
    const toast = new bootstrap.Toast(notification, {
        autohide: true,
        delay: 3000
    });
    toast.show();
    
    // Remove from DOM after hiding
    notification.addEventListener('hidden.bs.toast', function() {
        notification.remove();
    });
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
 * Debounce function to limit how often a function can be called
 * @param {Function} func - The function to debounce
 * @param {number} wait - The debounce delay in milliseconds
 */
function debounce(func, wait = 300) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Enhanced table sorting with better performance
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
                // Show loading state
                const tableBody = this.closest('table').querySelector('tbody');
                tableBody.classList.add('loading');
                
                // Use setTimeout to allow the UI to update before performing the sort
                setTimeout(() => {
                    const sortKey = this.getAttribute('data-sort');
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
                    
                    // Use DocumentFragment for better performance
                    const fragment = document.createDocumentFragment();
                    
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
                    
                    // Append rows to fragment
                    rows.forEach(row => fragment.appendChild(row));
                    
                    // Clear and repopulate the table body
                    while (tableBody.firstChild) {
                        tableBody.removeChild(tableBody.firstChild);
                    }
                    tableBody.appendChild(fragment);
                    
                    // Remove loading state
                    tableBody.classList.remove('loading');
                }, 0);
            });
        });
    });
}

/**
 * Initialize optional columns display based on user settings
 */
function initOptionalColumns() {
    // Check for column visibility settings in cookies
    const showUsernameColumn = getCookie('show_username_column') === 'true';
    const showSslColumn = getCookie('show_ssl_column') === 'true';
    
    // Get column elements
    const usernameColumns = document.querySelectorAll('.username-column');
    const sslColumns = document.querySelectorAll('.ssl-column');
    
    // Apply visibility settings
    if (showUsernameColumn) {
        usernameColumns.forEach(col => col.classList.remove('d-none'));
    }
    
    if (showSslColumn) {
        sslColumns.forEach(col => col.classList.remove('d-none'));
    }
    
    // Add column visibility toggle to the Node Status table header
    const nodeTable = document.getElementById('nodesTable');
    if (nodeTable) {
        const tableCard = nodeTable.closest('.card');
        if (tableCard) {
            const cardHeader = tableCard.querySelector('.card-header');
            if (cardHeader) {
                // Create column visibility toggle button
                const toggleButton = document.createElement('button');
                toggleButton.className = 'btn btn-sm btn-outline-secondary ms-2';
                toggleButton.innerHTML = '<i class="fas fa-columns me-1"></i> Show/Hide Columns';
                toggleButton.setAttribute('data-bs-toggle', 'dropdown');
                toggleButton.setAttribute('aria-expanded', 'false');
                
                // Create dropdown menu
                const dropdownMenu = document.createElement('ul');
                dropdownMenu.className = 'dropdown-menu';
                
                // Username column toggle
                const usernameItem = document.createElement('li');
                const usernameCheck = document.createElement('div');
                usernameCheck.className = 'dropdown-item form-check';
                usernameCheck.innerHTML = `
                    <input class="form-check-input" type="checkbox" id="toggle-username-column" 
                        ${showUsernameColumn ? 'checked' : ''}>
                    <label class="form-check-label" for="toggle-username-column">
                        Show Username Column
                    </label>
                `;
                usernameItem.appendChild(usernameCheck);
                dropdownMenu.appendChild(usernameItem);
                
                // SSL column toggle
                const sslItem = document.createElement('li');
                const sslCheck = document.createElement('div');
                sslCheck.className = 'dropdown-item form-check';
                sslCheck.innerHTML = `
                    <input class="form-check-input" type="checkbox" id="toggle-ssl-column" 
                        ${showSslColumn ? 'checked' : ''}>
                    <label class="form-check-label" for="toggle-ssl-column">
                        Show SSL Column
                    </label>
                `;
                sslItem.appendChild(sslCheck);
                dropdownMenu.appendChild(sslItem);
                
                // Create dropdown container
                const dropdownContainer = document.createElement('div');
                dropdownContainer.className = 'dropdown d-inline-block';
                dropdownContainer.appendChild(toggleButton);
                dropdownContainer.appendChild(dropdownMenu);
                
                // Add to card header
                cardHeader.appendChild(dropdownContainer);
                
                // Add event listeners
                document.getElementById('toggle-username-column').addEventListener('change', function() {
                    const isChecked = this.checked;
                    document.cookie = `show_username_column=${isChecked};path=/;max-age=31536000`;
                    usernameColumns.forEach(col => {
                        if (isChecked) {
                            col.classList.remove('d-none');
                        } else {
                            col.classList.add('d-none');
                        }
                    });
                });
                
                document.getElementById('toggle-ssl-column').addEventListener('change', function() {
                    const isChecked = this.checked;
                    document.cookie = `show_ssl_column=${isChecked};path=/;max-age=31536000`;
                    sslColumns.forEach(col => {
                        if (isChecked) {
                            col.classList.remove('d-none');
                        } else {
                            col.classList.add('d-none');
                        }
                    });
                });
            }
        }
    }
}

/**
 * Get cookie value by name
 */
function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

// Fix for browser back button infinite loading issue
window.addEventListener('pageshow', function(event) {
    // Check if the page is being loaded from cache (back/forward navigation)
    if (event.persisted) {
        // Hide any loading indicators that might be stuck
        document.getElementById('page-loading-indicator').classList.add('d-none');
        document.querySelector('.content-container')?.classList.remove('opacity-50');
        
        // Refresh dynamic content if needed
        const refreshableContent = document.querySelectorAll('[data-refresh]');
        refreshableContent.forEach(element => {
            const refreshUrl = element.getAttribute('data-refresh-url');
            if (refreshUrl) {
                fetch(refreshUrl)
                    .then(response => response.text())
                    .then(html => {
                        element.innerHTML = html;
                    })
                    .catch(error => {
                        console.error('Error refreshing content:', error);
                    });
            }
        });
    }
});

/**
 * Enhanced loading overlay management
 */
function showLoadingOverlay(message = 'Loading...') {
    // Create loading overlay if it doesn't exist
    let overlay = document.querySelector('.loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'loading-overlay';
        
        // Apply theme class if needed
        if (document.body.getAttribute('data-bs-theme') === 'dark') {
            overlay.classList.add('theme-dark');
        }
        
        overlay.innerHTML = `
            <div class="loading-spinner"></div>
            <p class="loading-message">${message}</p>
        `;
        
        document.body.appendChild(overlay);
    } else {
        // Update existing overlay
        const messageElem = overlay.querySelector('.loading-message');
        if (messageElem) {
            messageElem.textContent = message;
        }
        overlay.classList.remove('d-none');
    }
    
    // Prevent scrolling on body
    document.body.style.overflow = 'hidden';
    
    return overlay;
}

function hideLoadingOverlay() {
    const overlay = document.querySelector('.loading-overlay');
    if (overlay) {
        // Add fade-out animation
        overlay.style.opacity = '0';
        
        // Remove after animation
        setTimeout(() => {
            overlay.remove();
            document.body.style.overflow = '';
        }, 300);
    }
}

/**
 * Add theme-based text color adjustment for all badge elements
 */
function adjustBadgeColors() {
    const isDarkTheme = document.body.getAttribute('data-bs-theme') === 'dark';
    const badges = document.querySelectorAll('.badge');
    
    badges.forEach(badge => {
        // Skip badges that already have explicit text color classes
        if (badge.classList.contains('text-white') || badge.classList.contains('text-dark')) {
            return;
        }
        
        // Apply appropriate text color based on theme
        if (isDarkTheme) {
            badge.classList.add('text-white');
            badge.classList.remove('text-dark');
        } else {
            badge.classList.add('text-dark');
            badge.classList.remove('text-white');
        }
    });
}

// Listen for theme changes
document.addEventListener('themeChanged', adjustBadgeColors);