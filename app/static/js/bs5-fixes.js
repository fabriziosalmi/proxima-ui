/**
 * Bootstrap 5 compatibility fixes
 * This file provides fixes for code that was written for Bootstrap 4
 * but needs to work with Bootstrap 5.
 */

document.addEventListener('DOMContentLoaded', function() {
    // Fix all data-toggle="modal" attributes to data-bs-toggle="modal"
    document.querySelectorAll('[data-toggle="modal"]').forEach(function(el) {
        el.setAttribute('data-bs-toggle', 'modal');
        el.removeAttribute('data-toggle');
    });

    // Fix all data-target attributes to data-bs-target
    document.querySelectorAll('[data-target]').forEach(function(el) {
        el.setAttribute('data-bs-target', el.getAttribute('data-target'));
        el.removeAttribute('data-target');
    });

    // Fix all data-dismiss="modal" to data-bs-dismiss="modal"
    document.querySelectorAll('[data-dismiss="modal"]').forEach(function(el) {
        el.setAttribute('data-bs-dismiss', 'modal');
        el.removeAttribute('data-dismiss');
    });

    // Fix all data-toggle="tab" to data-bs-toggle="tab"
    document.querySelectorAll('[data-toggle="tab"]').forEach(function(el) {
        el.setAttribute('data-bs-toggle', 'tab');
        el.removeAttribute('data-toggle');
    });

    // Fix all data-toggle="collapse" to data-bs-toggle="collapse"
    document.querySelectorAll('[data-toggle="collapse"]').forEach(function(el) {
        el.setAttribute('data-bs-toggle', 'collapse');
        el.removeAttribute('data-toggle');
    });

    // Fix all data-toggle="dropdown" to data-bs-toggle="dropdown"
    document.querySelectorAll('[data-toggle="dropdown"]').forEach(function(el) {
        el.setAttribute('data-bs-toggle', 'dropdown');
        el.removeAttribute('data-toggle');
    });

    // Fix all data-toggle="tooltip" to data-bs-toggle="tooltip"
    document.querySelectorAll('[data-toggle="tooltip"]').forEach(function(el) {
        el.setAttribute('data-bs-toggle', 'tooltip');
        el.removeAttribute('data-toggle');
    });

    // Fix all data-toggle="popover" to data-bs-toggle="popover"
    document.querySelectorAll('[data-toggle="popover"]').forEach(function(el) {
        el.setAttribute('data-bs-toggle', 'popover');
        el.removeAttribute('data-toggle');
    });

    // Fix badge classes - replace badge-* with bg-*
    document.querySelectorAll('.badge').forEach(function(badge) {
        Array.from(badge.classList).forEach(function(className) {
            if (className.startsWith('badge-')) {
                const newClass = 'bg-' + className.substring(6);
                badge.classList.remove(className);
                badge.classList.add(newClass);
            }
        });
    });

    // Fix close button classes
    document.querySelectorAll('.close').forEach(function(closeButton) {
        closeButton.classList.remove('close');
        closeButton.classList.add('btn-close');
        
        // Remove any child text nodes or elements (like ×)
        while (closeButton.firstChild) {
            closeButton.removeChild(closeButton.firstChild);
        }
    });

    // Fix custom-control and custom-switch classes for forms
    document.querySelectorAll('.custom-control').forEach(function(control) {
        control.classList.remove('custom-control');
        control.classList.add('form-check');
    });

    document.querySelectorAll('.custom-switch').forEach(function(switchEl) {
        switchEl.classList.remove('custom-switch');
        switchEl.classList.add('form-switch');
    });

    document.querySelectorAll('.custom-control-input').forEach(function(input) {
        input.classList.remove('custom-control-input');
        input.classList.add('form-check-input');
    });

    document.querySelectorAll('.custom-control-label').forEach(function(label) {
        label.classList.remove('custom-control-label');
        label.classList.add('form-check-label');
    });

    document.querySelectorAll('.custom-select').forEach(function(select) {
        select.classList.remove('custom-select');
        select.classList.add('form-select');
    });

    // Update form-row with row
    document.querySelectorAll('.form-row').forEach(function(row) {
        row.classList.remove('form-row');
        row.classList.add('row');
    });

    // Fix form-group with mb-3
    document.querySelectorAll('.form-group').forEach(function(group) {
        group.classList.remove('form-group');
        group.classList.add('mb-3');
    });

    // Fix text-* utilities with text-opacity (for muted)
    document.querySelectorAll('.text-muted').forEach(function(elem) {
        if (!elem.classList.contains('form-text')) {
            elem.classList.add('text-opacity-50');
        }
    });

    // Fix toast handling
    document.querySelectorAll('.toast').forEach(function(toastEl) {
        if (toastEl.hasAttribute('data-autohide')) {
            // Convert data-autohide to data-bs-autohide
            const autoHide = toastEl.getAttribute('data-autohide') === 'true';
            toastEl.setAttribute('data-bs-autohide', autoHide);
            toastEl.removeAttribute('data-autohide');
        }
        
        if (toastEl.hasAttribute('data-delay')) {
            // Convert data-delay to data-bs-delay
            toastEl.setAttribute('data-bs-delay', toastEl.getAttribute('data-delay'));
            toastEl.removeAttribute('data-delay');
        }
    });

    // Initialize all tooltips
    if (typeof bootstrap !== 'undefined' && bootstrap.Tooltip) {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl, {
                boundary: document.body
            });
        });
    }

    // Initialize all popovers
    if (typeof bootstrap !== 'undefined' && bootstrap.Popover) {
        const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
        popoverTriggerList.map(function (popoverTriggerEl) {
            return new bootstrap.Popover(popoverTriggerEl);
        });
    }

    // Fix tab initialization
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function(tabEl) {
        tabEl.addEventListener('click', function(e) {
            e.preventDefault();
            if (typeof bootstrap !== 'undefined' && bootstrap.Tab) {
                const tab = new bootstrap.Tab(this);
                tab.show();
            }
        });
    });
});
});
