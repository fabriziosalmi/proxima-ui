/**
 * Advanced Resource Charts Module
 * Provides enhanced chart visualizations for resource usage
 */

const AdvancedCharts = (function() {
    // Store chart instances for future reference
    const chartInstances = {};
    
    // Color schemes that work in both light and dark modes
    const colorSchemes = {
        light: {
            cpu: {
                gradient: ['rgba(52, 152, 219, 0.1)', 'rgba(52, 152, 219, 0.8)'],
                border: 'rgba(52, 152, 219, 1)'
            },
            memory: {
                gradient: ['rgba(155, 89, 182, 0.1)', 'rgba(155, 89, 182, 0.8)'],
                border: 'rgba(155, 89, 182, 1)'
            },
            network: {
                in: {
                    gradient: ['rgba(46, 204, 113, 0.1)', 'rgba(46, 204, 113, 0.8)'],
                    border: 'rgba(46, 204, 113, 1)'
                },
                out: {
                    gradient: ['rgba(231, 76, 60, 0.1)', 'rgba(231, 76, 60, 0.8)'],
                    border: 'rgba(231, 76, 60, 1)'
                }
            },
            disk: {
                gradient: ['rgba(241, 196, 15, 0.1)', 'rgba(241, 196, 15, 0.8)'],
                border: 'rgba(241, 196, 15, 1)'
            }
        },
        dark: {
            cpu: {
                gradient: ['rgba(52, 152, 219, 0.1)', 'rgba(52, 152, 219, 0.6)'],
                border: 'rgba(52, 152, 219, 1)'
            },
            memory: {
                gradient: ['rgba(155, 89, 182, 0.1)', 'rgba(155, 89, 182, 0.6)'],
                border: 'rgba(155, 89, 182, 1)'
            },
            network: {
                in: {
                    gradient: ['rgba(46, 204, 113, 0.1)', 'rgba(46, 204, 113, 0.6)'],
                    border: 'rgba(46, 204, 113, 1)'
                },
                out: {
                    gradient: ['rgba(231, 76, 60, 0.1)', 'rgba(231, 76, 60, 0.6)'],
                    border: 'rgba(231, 76, 60, 1)'
                }
            },
            disk: {
                gradient: ['rgba(241, 196, 15, 0.1)', 'rgba(241, 196, 15, 0.6)'],
                border: 'rgba(241, 196, 15, 1)'
            }
        }
    };
    
    // Helper function to create gradient
    function createGradient(ctx, colors) {
        const gradient = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height);
        gradient.addColorStop(0, colors[1]);
        gradient.addColorStop(1, colors[0]);
        return gradient;
    }
    
    // Get current color scheme based on theme
    function getCurrentColorScheme() {
        const isDarkMode = document.body.getAttribute('data-bs-theme') === 'dark';
        return isDarkMode ? colorSchemes.dark : colorSchemes.light;
    }
    
    // Create line chart with area fill
    function createAreaChart(elementId, title, labels, data, type = 'cpu') {
        const ctx = document.getElementById(elementId)?.getContext('2d');
        if (!ctx) return null;
        
        const colorScheme = getCurrentColorScheme()[type];
        const gradient = createGradient(ctx, colorScheme.gradient);
        
        const chartConfig = {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: title,
                    data: data,
                    borderColor: colorScheme.border,
                    backgroundColor: gradient,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: colorScheme.border,
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        padding: 10,
                        cornerRadius: 4,
                        caretSize: 6
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            callback: function(value) {
                                return value + '%';
                            }
                        }
                    }
                },
                animation: {
                    duration: 1000,
                    easing: 'easeOutQuart'
                },
                hover: {
                    mode: 'nearest',
                    intersect: true
                }
            }
        };
        
        // Store chart instance for future reference
        if (chartInstances[elementId]) {
            chartInstances[elementId].destroy();
        }
        
        chartInstances[elementId] = new Chart(ctx, chartConfig);
        return chartInstances[elementId];
    }
    
    // Create network chart with dual datasets for in/out
    function createNetworkChart(elementId, title, labels, dataIn, dataOut) {
        const ctx = document.getElementById(elementId)?.getContext('2d');
        if (!ctx) return null;
        
        const colorScheme = getCurrentColorScheme().network;
        const gradientIn = createGradient(ctx, colorScheme.in.gradient);
        const gradientOut = createGradient(ctx, colorScheme.out.gradient);
        
        const chartConfig = {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Incoming',
                        data: dataIn,
                        borderColor: colorScheme.in.border,
                        backgroundColor: gradientIn,
                        tension: 0.4,
                        fill: true,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: colorScheme.in.border,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2
                    },
                    {
                        label: 'Outgoing',
                        data: dataOut,
                        borderColor: colorScheme.out.border,
                        backgroundColor: gradientOut,
                        tension: 0.4,
                        fill: true,
                        pointRadius: 3,
                        pointHoverRadius: 5,
                        pointBackgroundColor: colorScheme.out.border,
                        pointBorderColor: '#fff',
                        pointBorderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(0, 0, 0, 0.7)',
                        padding: 10,
                        cornerRadius: 4,
                        caretSize: 6,
                        callbacks: {
                            label: function(context) {
                                let value = context.raw;
                                let unit = 'KB/s';
                                
                                if (value >= 1024) {
                                    value = (value / 1024).toFixed(2);
                                    unit = 'MB/s';
                                }
                                
                                if (value >= 1024) {
                                    value = (value / 1024).toFixed(2);
                                    unit = 'GB/s';
                                }
                                
                                return `${context.dataset.label}: ${value} ${unit}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                if (value === 0) return '0';
                                
                                let unit = 'KB/s';
                                let valueToDisplay = value;
                                
                                if (value >= 1024) {
                                    valueToDisplay = (value / 1024).toFixed(1);
                                    unit = 'MB/s';
                                }
                                
                                if (valueToDisplay >= 1024) {
                                    valueToDisplay = (valueToDisplay / 1024).toFixed(1);
                                    unit = 'GB/s';
                                }
                                
                                return valueToDisplay + ' ' + unit;
                            }
                        }
                    }
                },
                animation: {
                    duration: 1000,
                    easing: 'easeOutQuart'
                },
                hover: {
                    mode: 'nearest',
                    intersect: true
                }
            }
        };
        
        // Store chart instance for future reference
        if (chartInstances[elementId]) {
            chartInstances[elementId].destroy();
        }
        
        chartInstances[elementId] = new Chart(ctx, chartConfig);
        return chartInstances[elementId];
    }
    
    // Update chart themes when the theme changes
    function handleThemeChange() {
        // Listen for theme changes
        document.addEventListener('themeChanged', function() {
            // Redraw all charts with new theme
            Object.keys(chartInstances).forEach(chartId => {
                const chart = chartInstances[chartId];
                const datasets = chart.data.datasets;
                
                // Determine chart type from the chart's ID or other attributes
                const chartType = chartId.includes('cpu') ? 'cpu' : 
                                 chartId.includes('memory') ? 'memory' : 
                                 chartId.includes('disk') ? 'disk' : 'cpu';
                
                const colorScheme = getCurrentColorScheme();
                
                if (chartId.includes('network')) {
                    // Special handling for network charts with dual datasets
                    const ctx = chart.ctx;
                    datasets[0].backgroundColor = createGradient(ctx, colorScheme.network.in.gradient);
                    datasets[0].borderColor = colorScheme.network.in.border;
                    datasets[1].backgroundColor = createGradient(ctx, colorScheme.network.out.gradient);
                    datasets[1].borderColor = colorScheme.network.out.border;
                } else {
                    // Standard charts
                    const ctx = chart.ctx;
                    datasets[0].backgroundColor = createGradient(ctx, colorScheme[chartType].gradient);
                    datasets[0].borderColor = colorScheme[chartType].border;
                }
                
                chart.update();
            });
        });
    }
    
    // Public API
    return {
        createAreaChart,
        createNetworkChart,
        handleThemeChange,
        updateChart: function(chartId, newData) {
            if (chartInstances[chartId]) {
                chartInstances[chartId].data.datasets[0].data = newData;
                chartInstances[chartId].update();
            }
        },
        updateNetworkChart: function(chartId, newDataIn, newDataOut) {
            if (chartInstances[chartId]) {
                chartInstances[chartId].data.datasets[0].data = newDataIn;
                chartInstances[chartId].data.datasets[1].data = newDataOut;
                chartInstances[chartId].update();
            }
        },
        initCharts: function() {
            handleThemeChange();
        }
    };
})();
