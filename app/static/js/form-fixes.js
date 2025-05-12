/**
 * Bootstrap 5 Form Compatibility Fixes
 * Updates Bootstrap 4 form classes to their Bootstrap 5 equivalents
 */
 
document.addEventListener('DOMContentLoaded', function() {
    // Update form-group classes to mb-3
    document.querySelectorAll('.form-group').forEach(function(formGroup) {
        formGroup.classList.remove('form-group');
        formGroup.classList.add('mb-3');
    });
    
    // Update form-row classes to row
    document.querySelectorAll('.form-row').forEach(function(formRow) {
        formRow.classList.remove('form-row');
        formRow.classList.add('row');
    });
    
    // Update form-control-input and form-control-label classes
    document.querySelectorAll('.form-group-input').forEach(function(input) {
        input.classList.remove('form-group-input');
        input.classList.add('form-control');
    });
    
    // Fix custom switches for Bootstrap 5
    document.querySelectorAll('.custom-switch').forEach(function(customSwitch) {
        customSwitch.classList.remove('custom-switch');
        customSwitch.classList.add('form-switch');
    });
    
    document.querySelectorAll('.custom-control').forEach(function(customControl) {
        customControl.classList.remove('custom-control');
        customControl.classList.add('form-check');
    });
    
    document.querySelectorAll('.custom-control-input').forEach(function(input) {
        input.classList.remove('custom-control-input');
        input.classList.add('form-check-input');
    });
    
    document.querySelectorAll('.custom-control-label').forEach(function(label) {
        label.classList.remove('custom-control-label');
        label.classList.add('form-check-label');
    });
});
