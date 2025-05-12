/**
 * Responsive Table Helper
 * Adds mobile-friendly features to tables
 */
document.addEventListener('DOMContentLoaded', function() {
    // Find all responsive tables that need stacked view on mobile
    const stackableTables = document.querySelectorAll('.table-responsive-stack');
    
    stackableTables.forEach(function(table) {
        // Prepare headers
        const headers = [];
        const headerCells = table.querySelectorAll('thead th');
        headerCells.forEach(function(th) {
            headers.push(th.textContent.trim());
        });
        
        // Add data-label attribute to each cell
        const dataCells = table.querySelectorAll('tbody td');
        dataCells.forEach(function(td, index) {
            const headerIndex = index % headers.length;
            td.setAttribute('data-label', headers[headerIndex]);
        });
    });
    
    // Add horizontal scroll to wide tables on small screens
    const scrollableTables = document.querySelectorAll('table:not(.table-responsive-stack)');
    scrollableTables.forEach(function(table) {
        // Check if the table isn't already in a .table-responsive container
        let parent = table.parentElement;
        let needsWrapper = true;
        
        while (parent && parent !== document.body) {
            if (parent.classList.contains('table-responsive') || parent.classList.contains('table-responsive-scroll')) {
                needsWrapper = false;
                break;
            }
            parent = parent.parentElement;
        }
        
        // If the table needs a responsive wrapper, add it
        if (needsWrapper) {
            const wrapper = document.createElement('div');
            wrapper.classList.add('table-responsive-scroll');
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
        }
    });
    
    // Make sortable tables work better on mobile
    document.querySelectorAll('.sortable').forEach(function(sortable) {
        // Make the sort icon more visible
        const icon = sortable.querySelector('i.fas');
        if (icon) {
            icon.classList.add('ms-1');
        }
        
        // Add proper cursor styling
        sortable.style.cursor = 'pointer';
    });
});
