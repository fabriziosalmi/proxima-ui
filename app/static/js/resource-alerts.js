/**
 * Resource Alerts Module
 * Handles monitoring of resource usage and displaying alerts when thresholds are exceeded
 */
const ResourceAlerts = (function() {
    // Default thresholds (will be overridden by user settings)
    let thresholds = {
        cpu: {
            warning: 75,
            critical: 90,
            enabled: true
        },
        memory: {
            warning: 80,
            critical: 95,
            enabled: true
        },
        storage: {
            warning: 85,
            critical: 95,
            enabled: true
        }
    };
    
    // Load thresholds from localStorage
    function loadThresholds() {
        const savedThresholds = localStorage.getItem('resource_thresholds');
        if (savedThresholds) {
            try {
                const parsedThresholds = JSON.parse(savedThresholds);
                thresholds = {...thresholds, ...parsedThresholds};
            } catch (e) {
                console.error('Failed to parse resource thresholds from localStorage:', e);
            }
        }
        
        // Check if notifications are enabled
        const alertsEnabled = localStorage.getItem('resource_alerts_enabled');
        if (alertsEnabled === null) {
            // Default to enabled
            localStorage.setItem('resource_alerts_enabled', 'true');
        }
    }
    
    // Save thresholds to localStorage
    function saveThresholds() {
        localStorage.setItem('resource_thresholds', JSON.stringify(thresholds));
    }
    
    // Check if resource alerts are enabled
    function areAlertsEnabled() {
        return localStorage.getItem('resource_alerts_enabled') !== 'false';
    }
    
    // Toggle resource alerts
    function toggleAlerts(enabled) {
        localStorage.setItem('resource_alerts_enabled', enabled.toString());
    }
    
    // Create alert element
    function createAlertElement(type, resource, value, threshold, resourceName, resourceId) {
        // If alerts are disabled, don't create any alerts
        if (!areAlertsEnabled()) {
            return null;
        }
        
        // Create alert element
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert ${type === 'warning' ? 'alert-warning' : 'alert-danger'} alert-dismissible fade show resource-alert`;
        alertDiv.setAttribute('role', 'alert');
        
        // Determine icon and text based on resource type
        let icon, text;
        switch (resource) {
            case 'cpu':
                icon = 'fas fa-microchip';
                text = `CPU usage at ${value.toFixed(1)}%`;
                break;
            case 'memory':
                icon = 'fas fa-memory';
                text = `Memory usage at ${value.toFixed(1)}%`;
                break;
            case 'storage':
                icon = 'fas fa-hdd';
                text = `Storage usage at ${value.toFixed(1)}%`;
                break;
            default:
                icon = 'fas fa-exclamation-triangle';
                text = `Resource usage high`;
        }
        
        // Add resource name if provided
        if (resourceName) {
            text += ` for ${resourceName}`;
            if (resourceId) {
                text += ` (${resourceId})`;
            }
        }
        
        // Add threshold information
        text += ` - ${type === 'warning' ? 'Warning' : 'Critical'} threshold: ${threshold}%`;
        
        // Build alert content
        alertDiv.innerHTML = `
            <i class="${icon} me-2"></i> ${text}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        
        return alertDiv;
    }
    
    // Play alert sound
    function playAlertSound(type) {
        if (!areAlertsEnabled()) {
            return;
        }
        
        const alertSound = new Audio('/static/sounds/resource-alert.mp3');
        alertSound.play().catch(e => {
            console.warn('Could not play alert sound:', e);
        });
    }
    
    // Show alert notification and sound
    function showAlert(type, resource, value, threshold, resourceName, resourceId, containerId) {
        // Create alert element
        const alertElement = createAlertElement(type, resource, value, threshold, resourceName, resourceId);
        if (!alertElement) {
            return;
        }
        
        // Add to container
        const container = document.getElementById(containerId || 'resource-alerts-container');
        if (container) {
            container.appendChild(alertElement);
            
            // Initialize the bootstrap alert
            new bootstrap.Alert(alertElement);
            
            // Automatically dismiss after 30 seconds
            setTimeout(() => {
                const bsAlert = bootstrap.Alert.getInstance(alertElement);
                if (bsAlert) {
                    bsAlert.close();
                }
            }, 30000);
            
            // Play sound for critical alerts only (to avoid too many sounds)
            if (type === 'critical') {
                playAlertSound(type);
            }
        }
    }
    
    // Check node resources against thresholds
    function checkNodeResources(nodeData) {
        const containerId = 'node-resource-alerts-container';
        
        // Check CPU
        if (thresholds.cpu.enabled) {
            if (nodeData.cpu >= thresholds.cpu.critical) {
                showAlert('critical', 'cpu', nodeData.cpu, thresholds.cpu.critical, `Node ${nodeData.name}`, null, containerId);
            } else if (nodeData.cpu >= thresholds.cpu.warning) {
                showAlert('warning', 'cpu', nodeData.cpu, thresholds.cpu.warning, `Node ${nodeData.name}`, null, containerId);
            }
        }
        
        // Check Memory
        if (thresholds.memory.enabled) {
            if (nodeData.memory_percent >= thresholds.memory.critical) {
                showAlert('critical', 'memory', nodeData.memory_percent, thresholds.memory.critical, `Node ${nodeData.name}`, null, containerId);
            } else if (nodeData.memory_percent >= thresholds.memory.warning) {
                showAlert('warning', 'memory', nodeData.memory_percent, thresholds.memory.warning, `Node ${nodeData.name}`, null, containerId);
            }
        }
        
        // Check Storage
        if (thresholds.storage.enabled) {
            if (nodeData.storage_percent >= thresholds.storage.critical) {
                showAlert('critical', 'storage', nodeData.storage_percent, thresholds.storage.critical, `Node ${nodeData.name}`, null, containerId);
            } else if (nodeData.storage_percent >= thresholds.storage.warning) {
                showAlert('warning', 'storage', nodeData.storage_percent, thresholds.storage.warning, `Node ${nodeData.name}`, null, containerId);
            }
        }
    }
    
    // Check VM resources against thresholds
    function checkVmResources(vmData) {
        const memoryPercent = (vmData.mem / vmData.maxmem) * 100;
        const containerId = 'node-resource-alerts-container';
        
        // Check CPU
        if (thresholds.cpu.enabled && vmData.cpu) {
            const cpuPercent = vmData.cpu * 100;
            if (cpuPercent >= thresholds.cpu.critical) {
                showAlert('critical', 'cpu', cpuPercent, thresholds.cpu.critical, `VM ${vmData.name}`, vmData.vmid, containerId);
            } else if (cpuPercent >= thresholds.cpu.warning) {
                showAlert('warning', 'cpu', cpuPercent, thresholds.cpu.warning, `VM ${vmData.name}`, vmData.vmid, containerId);
            }
        }
        
        // Check Memory
        if (thresholds.memory.enabled) {
            if (memoryPercent >= thresholds.memory.critical) {
                showAlert('critical', 'memory', memoryPercent, thresholds.memory.critical, `VM ${vmData.name}`, vmData.vmid, containerId);
            } else if (memoryPercent >= thresholds.memory.warning) {
                showAlert('warning', 'memory', memoryPercent, thresholds.memory.warning, `VM ${vmData.name}`, vmData.vmid, containerId);
            }
        }
        
        // Check Disks
        if (thresholds.storage.enabled && vmData.disks) {
            for (const [diskId, disk] of Object.entries(vmData.disks)) {
                const diskPercent = (disk.usage / disk.total) * 100;
                if (diskPercent >= thresholds.storage.critical) {
                    showAlert('critical', 'storage', diskPercent, thresholds.storage.critical, `VM ${vmData.name} Disk ${diskId}`, vmData.vmid, containerId);
                } else if (diskPercent >= thresholds.storage.warning) {
                    showAlert('warning', 'storage', diskPercent, thresholds.storage.warning, `VM ${vmData.name} Disk ${diskId}`, vmData.vmid, containerId);
                }
            }
        }
    }
    
    // Check Container resources against thresholds
    function checkContainerResources(containerData) {
        const memoryPercent = (containerData.mem / containerData.maxmem) * 100;
        const containerId = 'node-resource-alerts-container';
        
        // Check CPU
        if (thresholds.cpu.enabled && containerData.cpu) {
            const cpuPercent = containerData.cpu * 100;
            if (cpuPercent >= thresholds.cpu.critical) {
                showAlert('critical', 'cpu', cpuPercent, thresholds.cpu.critical, `Container ${containerData.name}`, containerData.vmid, containerId);
            } else if (cpuPercent >= thresholds.cpu.warning) {
                showAlert('warning', 'cpu', cpuPercent, thresholds.cpu.warning, `Container ${containerData.name}`, containerData.vmid, containerId);
            }
        }
        
        // Check Memory
        if (thresholds.memory.enabled) {
            if (memoryPercent >= thresholds.memory.critical) {
                showAlert('critical', 'memory', memoryPercent, thresholds.memory.critical, `Container ${containerData.name}`, containerData.vmid, containerId);
            } else if (memoryPercent >= thresholds.memory.warning) {
                showAlert('warning', 'memory', memoryPercent, thresholds.memory.warning, `Container ${containerData.name}`, containerData.vmid, containerId);
            }
        }
        
        // Check Root Filesystem
        if (thresholds.storage.enabled && containerData.rootfs) {
            const storagePercent = (containerData.rootfs.usage / containerData.rootfs.total) * 100;
            if (storagePercent >= thresholds.storage.critical) {
                showAlert('critical', 'storage', storagePercent, thresholds.storage.critical, `Container ${containerData.name} Root FS`, containerData.vmid, containerId);
            } else if (storagePercent >= thresholds.storage.warning) {
                showAlert('warning', 'storage', storagePercent, thresholds.storage.warning, `Container ${containerData.name} Root FS`, containerData.vmid, containerId);
            }
        }
    }
    
    // Initialize module
    function init() {
        loadThresholds();
    }
    
    // Public API
    return {
        init: init,
        getThresholds: () => thresholds,
        updateThresholds: (newThresholds) => {
            thresholds = {...thresholds, ...newThresholds};
            saveThresholds();
        },
        checkNodeResources: checkNodeResources,
        checkVmResources: checkVmResources,
        checkContainerResources: checkContainerResources,
        areAlertsEnabled: areAlertsEnabled,
        toggleAlerts: toggleAlerts
    };
})();

// Initialize the module when the document is ready
document.addEventListener('DOMContentLoaded', function() {
    ResourceAlerts.init();
    
    // Create a global alert container if it doesn't exist
    if (!document.getElementById('resource-alerts-container')) {
        const alertContainer = document.createElement('div');
        alertContainer.id = 'resource-alerts-container';
        alertContainer.className = 'resource-alerts-container';
        document.body.appendChild(alertContainer);
    }
});