/**
 * Modal helpers for Bootstrap 5 compatibility
 * This file provides helper functions for working with Bootstrap 5 modals
 */

// Function to initialize modals on the page
function initializeModals() {
    // Get all modal elements
    const modalElements = document.querySelectorAll('.modal');
    
    // Initialize each modal
    modalElements.forEach(function(modalElement) {
        // Check if we have a modal ID
        const modalId = modalElement.id;
        if (!modalId) return;
        
        // Find all buttons or links that open this modal
        const modalTriggers = document.querySelectorAll(`[data-bs-target="#${modalId}"]`);
        
        // Add event listeners to modal triggers
        modalTriggers.forEach(function(trigger) {
            trigger.addEventListener('click', function(e) {
                e.preventDefault();
                
                // Initialize and show the modal
                const modal = new bootstrap.Modal(modalElement);
                modal.show();
            });
        });
    });
}

// Function to open a modal programmatically
function openModal(modalId) {
    const modalElement = document.getElementById(modalId);
    if (!modalElement) {
        console.error(`Modal with ID ${modalId} not found`);
        return;
    }
    
    const modal = new bootstrap.Modal(modalElement);
    modal.show();
}

// Function to close a modal programmatically
function closeModal(modalId) {
    const modalElement = document.getElementById(modalId);
    if (!modalElement) {
        console.error(`Modal with ID ${modalId} not found`);
        return;
    }
    
    const modal = bootstrap.Modal.getInstance(modalElement);
    if (modal) {
        modal.hide();
    }
}

// Initialize modals when the DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    // Initialize modals if Bootstrap is available
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        initializeModals();
    }
});
