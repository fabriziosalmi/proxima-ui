// Handle dark/light mode toggle and system preferences
function initDarkMode() {
    const themeToggleBtn = document.getElementById('theme-toggle');
    const storedTheme = localStorage.getItem('theme');
    
    // Check for system preference
    const prefersDarkScheme = window.matchMedia('(prefers-color-scheme: dark)');
    
    // Set initial theme based on stored preference or system default
    function setInitialTheme() {
        if (storedTheme === 'dark') {
            document.body.setAttribute('data-bs-theme', 'dark');
            updateThemeIcon(true);
        } else if (storedTheme === 'light') {
            document.body.setAttribute('data-bs-theme', 'light');
            updateThemeIcon(false);
        } else if (storedTheme === 'auto' || !storedTheme) {
            // Use system preference when set to auto or no setting
            if (prefersDarkScheme.matches) {
                document.body.setAttribute('data-bs-theme', 'dark');
                updateThemeIcon(true);
            } else {
                document.body.setAttribute('data-bs-theme', 'light');
                updateThemeIcon(false);
            }
        }
    }
    
    // Update the theme toggle icon
    function updateThemeIcon(isDark) {
        if (isDark) {
            themeToggleBtn.innerHTML = '<i class="fas fa-sun"></i>';
            themeToggleBtn.setAttribute('title', 'Switch to light mode');
        } else {
            themeToggleBtn.innerHTML = '<i class="fas fa-moon"></i>';
            themeToggleBtn.setAttribute('title', 'Switch to dark mode');
        }
    }
    
    // Toggle theme when button is clicked
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', function() {
            const currentTheme = document.body.getAttribute('data-bs-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            document.body.setAttribute('data-bs-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            updateThemeIcon(newTheme === 'dark');
            
            // Dispatch an event so other components can react to theme changes
            document.dispatchEvent(new CustomEvent('themeChanged', { 
                detail: { theme: newTheme } 
            }));
        });
    }
    
    // Listen for system preference changes
    prefersDarkScheme.addEventListener('change', function(e) {
        if (localStorage.getItem('theme') === 'auto' || !localStorage.getItem('theme')) {
            const newTheme = e.matches ? 'dark' : 'light';
            document.body.setAttribute('data-bs-theme', newTheme);
            updateThemeIcon(newTheme === 'dark');
        }
    });
    
    // Set the initial theme
    setInitialTheme();
}
