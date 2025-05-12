/**
 * Template Validator Script
 * Checks templates for Bootstrap 5 compatibility issues
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('Running template compatibility checker...');
    
    // Check for remaining Bootstrap 4 attributes
    const bs4Attributes = {
        'data-toggle': 'Should be data-bs-toggle',
        'data-target': 'Should be data-bs-target',
        'data-dismiss': 'Should be data-bs-dismiss',
        'data-ride': 'Should be data-bs-ride',
        'data-slide': 'Should be data-bs-slide',
        'data-slide-to': 'Should be data-bs-slide-to'
    };
    
    // Check for deprecated Bootstrap 4 classes
    const bs4Classes = {
        'custom-control': 'Should be form-check',
        'custom-checkbox': 'Should be form-check',
        'custom-radio': 'Should be form-check',
        'custom-switch': 'Should be form-switch',
        'custom-select': 'Should be form-select',
        'custom-file': 'Should be form-control',
        'custom-range': 'Should be form-range',
        'form-group': 'Should be mb-3',
        'form-row': 'Should be row',
        'form-inline': 'Should be added with utility classes',
        'custom-control-input': 'Should be form-check-input',
        'custom-control-label': 'Should be form-check-label',
        'custom-file-input': 'Should be form-control',
        'custom-file-label': 'Removed in Bootstrap 5',
        'close': 'Should be btn-close',
        'no-gutters': 'Should be g-0',
        'badge-primary': 'Should be bg-primary',
        'badge-secondary': 'Should be bg-secondary',
        'badge-success': 'Should be bg-success',
        'badge-danger': 'Should be bg-danger',
        'badge-warning': 'Should be bg-warning',
        'badge-info': 'Should be bg-info',
        'badge-light': 'Should be bg-light',
        'badge-dark': 'Should be bg-dark'
    };
    
    // Check attributes
    let attrIssues = 0;
    for (let attr in bs4Attributes) {
        const elements = document.querySelectorAll(`[${attr}]`);
        if (elements.length > 0) {
            console.warn(`Found ${elements.length} elements with deprecated attribute '${attr}'. ${bs4Attributes[attr]}`);
            attrIssues += elements.length;
        }
    }
    
    // Check classes
    let classIssues = 0;
    for (let cls in bs4Classes) {
        const elements = document.querySelectorAll(`.${cls}`);
        if (elements.length > 0) {
            console.warn(`Found ${elements.length} elements with deprecated class '${cls}'. ${bs4Classes[cls]}`);
            classIssues += elements.length;
        }
    }
    
    // Output summary
    if (attrIssues === 0 && classIssues === 0) {
        console.log('No Bootstrap 5 compatibility issues found! 🎉');
    } else {
        console.error(`Found ${attrIssues + classIssues} Bootstrap 5 compatibility issues.`);
    }
    
    // Check if modals are correctly initialized
    const modals = document.querySelectorAll('.modal');
    if (modals.length > 0) {
        console.log(`Found ${modals.length} modals. Make sure they're using data-bs-* attributes.`);
    }
    
    // Check if forms are using the correct structure
    const forms = document.querySelectorAll('form');
    console.log(`Found ${forms.length} forms. Verify they use mb-3 instead of form-group.`);
    
    // Report template check status
    const validation = {
        bootstrap5Compatible: (attrIssues === 0 && classIssues === 0),
        issuesFound: attrIssues + classIssues,
        attributeIssues: attrIssues,
        classIssues: classIssues
    };
    
    console.log('Validation complete:', validation);
});
