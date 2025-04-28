// Custom JavaScript for Proxmox UI

// Function to enable Bootstrap tooltips
function enableTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
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
                    h.querySelector('i').className = 'fas fa-sort';
                });
                
                // Update sort indicator on clicked header
                this.querySelector('i').className = `fas fa-sort-${sortDirection === 'asc' ? 'up' : 'down'}`;
                
                // Sort the rows
                rows.sort((rowA, rowB) => {
                    const cellA = rowA.querySelector(`td:nth-child(${this.cellIndex + 1})`);
                    const cellB = rowB.querySelector(`td:nth-child(${this.cellIndex + 1})`);
                    
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

// Initialize when the document is ready
document.addEventListener('DOMContentLoaded', function() {
    // Enable tooltips
    enableTooltips();
    
    // Auto-close alerts after 5 seconds
    setTimeout(function() {
        const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
        alerts.forEach(function(alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        });
    }, 5000);

    // Initialize all sortable tables when the document is loaded
    initTableSorting();
});