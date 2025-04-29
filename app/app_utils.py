from flask import (
    Flask, render_template, redirect, url_for, flash, 
    request, jsonify, session, make_response, g
)
import os
import json
import datetime
import time
import uuid
import pickle
import re  # Added for log file parsing
import threading  # Add missing threading import

# Cache implementation functions
def get_from_cache(key, ttl=30, cache=None, cache_lock=None):
    """Get a value from cache if it exists and is not expired"""
    with cache_lock:
        if key in cache:
            cached_time, cached_value = cache[key]
            if time.time() - cached_time < ttl:
                return cached_value
    return None

def set_in_cache(key, value, ttl=30, cache=None, cache_lock=None):
    """Set a value in cache with current timestamp"""
    with cache_lock:
        cache[key] = (time.time(), value)
        
def invalidate_cache(prefix=None, cache=None, cache_lock=None):
    """Invalidate all cache entries or those starting with prefix"""
    with cache_lock:
        if prefix:
            keys_to_delete = [k for k in cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del cache[key]
        else:
            cache.clear()

# Connection handling functions
def load_connections(CONNECTIONS_FILE, proxmox_connections, connection_lock):
    """Load saved Proxmox connections from disk"""
    try:
        if os.path.exists(CONNECTIONS_FILE):
            with open(CONNECTIONS_FILE, 'rb') as f:
                saved_data = pickle.load(f)
                for host_id, data in saved_data.items():
                    try:
                        # Build connection parameters
                        conn_params = {
                            'host': data['host'],
                            'port': data['port'],
                            'verify_ssl': data['verify_ssl']
                        }
                        
                        # Handle different authentication methods
                        if data.get('auth_method') == 'apikey':
                            # Use API key authentication
                            conn_params['token_name'] = data['token_name']
                            conn_params['token_value'] = data['token_value']
                        else:
                            # Default to username/password authentication
                            conn_params['user'] = data['user']
                            conn_params['password'] = data['password']
                        
                        # Import here to avoid circular imports
                        from proxmoxer import ProxmoxAPI
                        
                        # Reconnect to each saved host
                        proxmox = ProxmoxAPI(**conn_params)
                        
                        # Update connection data with live connection
                        data['connection'] = proxmox
                        with connection_lock:
                            proxmox_connections[host_id] = data
                        print(f"Reconnected to {host_id}")
                    except Exception as e:
                        print(f"Failed to reconnect to {host_id}: {str(e)}")
    except Exception as e:
        print(f"Error loading connections: {str(e)}")

def save_connections(CONNECTIONS_FILE, proxmox_connections, connection_lock):
    """Save Proxmox connections to disk"""
    with connection_lock:
        try:
            # Create a copy of connections without the actual connection objects
            to_save = {}
            for host_id, data in proxmox_connections.items():
                to_save[host_id] = {
                    'host': data['host'],
                    'user': data.get('user', ''),
                    'password': data.get('password', ''),
                    'port': data['port'],
                    'verify_ssl': data['verify_ssl'],
                    'auth_method': data.get('auth_method', 'password'),
                }
                
                # Include API key information if present
                if data.get('auth_method') == 'apikey':
                    to_save[host_id]['token_name'] = data.get('token_name', '')
                    to_save[host_id]['token_value'] = data.get('token_value', '')
            
            with open(CONNECTIONS_FILE, 'wb') as f:
                pickle.dump(to_save, f)
        except Exception as e:
            print(f"Error saving connections: {str(e)}")

# Utility Routes
def settings_route():
    """
    UI settings page for customizing the Proxmox UI application
    """
    # Base settings data from cookies
    settings_data = {
        'theme': request.cookies.get('theme', 'light'),
        'page_size': request.cookies.get('page_size', '20'),
        'refresh_interval': request.cookies.get('refresh_interval', '30'),
        'date_format': request.cookies.get('date_format', 'YYYY-MM-DD HH:mm:ss'),
        'default_view': request.cookies.get('default_view', 'list')
    }
    
    # Load resource threshold settings from session if available
    if 'resource_thresholds' in session:
        resource_settings = session['resource_thresholds']
        settings_data.update({
            'enable_resource_alerts': resource_settings.get('enable_resource_alerts', True),
            'cpu_threshold': resource_settings.get('cpu_threshold', 80),
            'cpu_alert_level': resource_settings.get('cpu_alert_level', 'warning'),
            'memory_threshold': resource_settings.get('memory_threshold', 85),
            'memory_alert_level': resource_settings.get('memory_alert_level', 'warning'),
            'storage_threshold': resource_settings.get('storage_threshold', 90),
            'storage_alert_level': resource_settings.get('storage_alert_level', 'danger'),
            'show_alerts_dashboard': resource_settings.get('show_alerts_dashboard', True),
            'show_popup_notifications': resource_settings.get('show_popup_notifications', True),
            'play_alert_sound': resource_settings.get('play_alert_sound', False)
        })
    
    return render_template('settings.html', settings=settings_data)

def update_settings_route():
    """
    Update UI settings and store in cookies
    """
    theme = request.form.get('theme', 'light')
    page_size = request.form.get('page_size', '20')
    refresh_interval = request.form.get('refresh_interval', '30')
    date_format = request.form.get('date_format', 'YYYY-MM-DD HH:mm:ss')
    default_view = request.form.get('default_view', 'list')
    
    # Create response object for redirecting
    response = make_response(redirect(url_for('settings')))
    
    # Set cookies with 365 days expiration
    response.set_cookie('theme', theme, max_age=31536000)
    response.set_cookie('page_size', page_size, max_age=31536000)
    response.set_cookie('refresh_interval', refresh_interval, max_age=31536000)
    response.set_cookie('date_format', date_format, max_age=31536000)
    response.set_cookie('default_view', default_view, max_age=31536000)
    
    flash("Settings updated successfully", 'success')
    return response

def logs_route():
    """
    View UI application logs - reads actual logs from the app.log file
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    log_level = request.args.get('level', 'all')
    
    # Set up log file path
    log_file_path = os.path.join(os.path.dirname(__file__), 'app.log')
    
    # Initialize empty log array
    app_logs = []
    
    # Common log patterns
    # Format: [2025-04-29 10:15:30,123] [INFO] [app] Message here
    log_pattern = r'\[([\d\-\s:,]+)\]\s+\[(INFO|WARNING|ERROR|DEBUG)\]\s+\[([^\]]+)\]\s+(.+)'
    
    if os.path.exists(log_file_path):
        try:
            # Read all logs, but we'll do it more efficiently for large files
            with open(log_file_path, 'r') as log_file:
                # Read the file in reverse to get the latest logs first
                log_entries = []
                
                # For large files, we read in chunks to avoid loading everything in memory at once
                log_file.seek(0, os.SEEK_END)
                file_size = log_file.tell()
                
                # Start from the end of the file and work backwards
                # We read in reasonably sized chunks (100KB)
                chunk_size = 100 * 1024
                
                # Initialize position at end of file
                position = file_size
                entries_found = 0
                max_entries = per_page * (page + 2)  # Read a bit more than we need for pagination
                
                # We'll use these to build up log entries that span multiple lines
                current_entry = None
                entry_buffer = []
                
                while position > 0 and entries_found < max_entries:
                    # Move back by chunk size or to start of file
                    chunk_end = position
                    position = max(0, position - chunk_size)
                    
                    # Read the chunk
                    log_file.seek(position)
                    chunk = log_file.read(chunk_end - position)
                    
                    # Split the chunk into lines
                    lines = chunk.splitlines()
                    
                    # If we're not at the beginning of the file, the first line might be partial
                    # We'll handle it in the next iteration
                    if position > 0 and len(lines) > 0:
                        partial_line = lines[0]
                        lines = lines[1:]
                    
                    # Process lines in reverse (since we're reading backwards)
                    for line in reversed(lines):
                        match = re.match(log_pattern, line)
                        
                        if match:
                            # If we were building a multiline entry, save it first
                            if entry_buffer:
                                if current_entry:
                                    # Append multiline content to the previous entry
                                    current_entry['message'] += '\n' + '\n'.join(reversed(entry_buffer))
                                entry_buffer = []
                            
                            # Parse the new log entry
                            timestamp_str, level, source, message = match.groups()
                            try:
                                # Parse timestamp from log entry
                                timestamp = datetime.datetime.strptime(timestamp_str.strip(), '%Y-%m-%d %H:%M:%S,%f')
                            except ValueError:
                                # Fallback in case timestamp format differs
                                timestamp = datetime.datetime.now()
                            
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level,
                                'source': source,
                                'message': message
                            }
                            
                            # Filter by log level if specified
                            if log_level == 'all' or level.lower() == log_level.lower():
                                log_entries.append(current_entry)
                                entries_found += 1
                        else:
                            # This is a continuation of a multiline log
                            entry_buffer.append(line)
                
                # Process logs in chronological order (newest first for display)
                app_logs = log_entries
        except Exception as e:
            # If there's an error reading the log file, show that as an error entry
            error_entry = {
                'timestamp': datetime.datetime.now(),
                'level': 'ERROR',
                'source': 'ui',
                'message': f"Error reading log file: {str(e)}"
            }
            app_logs.append(error_entry)
    else:
        # Create a sample entry if log file doesn't exist yet
        app_logs = [{
            'timestamp': datetime.datetime.now(),
            'level': 'INFO',
            'source': 'ui',
            'message': "No log file found. This is the first application log entry."
        }]
    
    # Simple pagination
    start = (page - 1) * per_page
    end = start + per_page
    logs_page = app_logs[start:end]
    total_pages = (len(app_logs) // per_page) + (1 if len(app_logs) % per_page else 0)
    
    return render_template('logs.html', 
                          logs=logs_page, 
                          page=page, 
                          total_pages=total_pages,
                          per_page=per_page,
                          log_level=log_level)

def resource_thresholds_route():
    """
    Save or retrieve resource usage threshold settings
    """
    if request.method == 'POST':
        settings = {
            'enable_resource_alerts': request.form.get('enable_resource_alerts') == 'true',
            'cpu_threshold': request.form.get('cpu_threshold', 80),
            'cpu_alert_level': request.form.get('cpu_alert_level', 'warning'),
            'memory_threshold': request.form.get('memory_threshold', 85),
            'memory_alert_level': request.form.get('memory_alert_level', 'warning'),
            'storage_threshold': request.form.get('storage_threshold', 90),
            'storage_alert_level': request.form.get('storage_alert_level', 'danger'),
            'show_alerts_dashboard': request.form.get('show_alerts_dashboard') == 'true',
            'show_popup_notifications': request.form.get('show_popup_notifications') == 'true',
            'play_alert_sound': request.form.get('play_alert_sound') == 'true'
        }
        
        # In a production environment, these settings would typically be saved to a database
        # For now, we'll use Flask's session to persist between requests
        session['resource_thresholds'] = settings
        
        return jsonify({'success': True})
    else:
        # Handle GET request - return current settings
        if 'resource_thresholds' in session:
            return jsonify({'success': True, 'settings': session['resource_thresholds']})
        else:
            # Return default settings if none are saved
            default_settings = {
                'enable_resource_alerts': True,
                'cpu_threshold': 80,
                'cpu_alert_level': 'warning',
                'memory_threshold': 85,
                'memory_alert_level': 'warning',
                'storage_threshold': 90,
                'storage_alert_level': 'danger',
                'show_alerts_dashboard': True,
                'show_popup_notifications': True,
                'play_alert_sound': False
            }
            return jsonify({'success': True, 'settings': default_settings})

def search_route(proxmox_connections):
    """
    Search functionality across VMs, containers, nodes, and storage
    """
    query = request.args.get('q', '')
    
    if not query:
        flash("Please enter a search term", 'warning')
        return redirect(url_for('index'))
    
    # Get search filters
    search_vms = request.args.get('search_vms', 'true') != 'false'
    search_containers = request.args.get('search_containers', 'true') != 'false'
    search_nodes = request.args.get('search_nodes', 'true') != 'false'
    search_storage = request.args.get('search_storage', 'true') != 'false'
    
    # Get additional filters
    status = request.args.get('status', '')
    resource_type = request.args.get('resource_type', '')
    selected_host_id = request.args.get('host_id', '')
    tag = request.args.get('tag', '')
    
    # Initialize results
    vm_results = []
    container_results = []
    node_results = []
    storage_results = []
    available_hosts = set()
    
    # Search across all hosts
    for host_id, host_data in proxmox_connections.items():
        try:
            connection = host_data['connection']
            available_hosts.add(host_id)
            
            # Filter by host if specified
            if selected_host_id and host_id != selected_host_id:
                continue
            
            # Search nodes if enabled
            if search_nodes:
                try:
                    nodes = connection.nodes.get()
                    for node in nodes:
                        # Apply filter if resource_type is specified
                        if resource_type and resource_type != 'node':
                            continue
                            
                        # Check if query matches
                        if (query.lower() in node['node'].lower() or 
                            query.lower() in str(node.get('status', '')).lower()):
                            
                            # Apply status filter if specified
                            if status and node.get('status') != status:
                                continue
                                
                            try:
                                # Get more node details
                                node_status = connection.nodes(node['node']).status.get()
                                
                                # Calculate metrics
                                cpu_usage = round(node_status.get('cpu', 0) * 100, 1)
                                memory_total = node_status.get('memory', {}).get('total', 0)
                                memory_used = node_status.get('memory', {}).get('used', 0)
                                memory_usage = round((memory_used / memory_total) * 100, 1) if memory_total > 0 else 0
                                
                                # Get VM and container counts
                                vm_count = len(connection.nodes(node['node']).qemu.get())
                                container_count = len(connection.nodes(node['node']).lxc.get())
                                
                                # Add additional info to node object
                                node['host_id'] = host_id
                                node['cpu_usage'] = cpu_usage
                                node['memory_usage'] = memory_usage
                                node['vm_count'] = vm_count
                                node['container_count'] = container_count
                                node['uptime'] = node_status.get('uptime', 0)
                                
                                node_results.append(node)
                            except Exception as e:
                                print(f"Error getting details for node {node['node']}: {str(e)}")
                except Exception as e:
                    print(f"Error searching nodes on host {host_id}: {str(e)}")
            
            # Get all nodes for VM and container searches
            nodes = connection.nodes.get()
            for node_info in nodes:
                node_name = node_info['node']
                
                # Skip offline nodes
                if node_info['status'] != 'online':
                    continue
                
                # Search VMs if enabled
                if search_vms:
                    try:
                        vms = connection.nodes(node_name).qemu.get()
                        for vm in vms:
                            # Apply filter if resource_type is specified
                            if resource_type and resource_type != 'vm':
                                continue
                                
                            vm_name = vm.get('name', '').lower()
                            vm_id = str(vm.get('vmid', ''))
                            vm_status = str(vm.get('status', '')).lower()
                            vm_tags = vm.get('tags', '').lower()
                            
                            # Apply status filter if specified
                            if status and vm.get('status') != status:
                                continue
                                
                            # Apply tag filter if specified
                            if tag and tag.lower() not in vm_tags:
                                continue
                            
                            if (query.lower() in vm_name or 
                                query.lower() in vm_id or 
                                query.lower() in vm_status or
                                query.lower() in vm_tags):
                                vm['host_id'] = host_id
                                vm['node'] = node_name
                                vm_results.append(vm)
                    except Exception as e:
                        print(f"Error searching VMs on node {node_name}: {str(e)}")
                
                # Search Containers if enabled
                if search_containers:
                    try:
                        containers = connection.nodes(node_name).lxc.get()
                        for container in containers:
                            # Apply filter if resource_type is specified
                            if resource_type and resource_type != 'container':
                                continue
                                
                            container_name = container.get('name', '').lower()
                            container_id = str(container.get('vmid', ''))
                            container_status = str(container.get('status', '')).lower()
                            container_tags = container.get('tags', '').lower()
                            
                            # Apply status filter if specified
                            if status and container.get('status') != status:
                                continue
                                
                            # Apply tag filter if specified
                            if tag and tag.lower() not in container_tags:
                                continue
                            
                            if (query.lower() in container_name or 
                                query.lower() in container_id or 
                                query.lower() in container_status or
                                query.lower() in container_tags):
                                container['host_id'] = host_id
                                container['node'] = node_name
                                container_results.append(container)
                    except Exception as e:
                        print(f"Error searching containers on node {node_name}: {str(e)}")
            
            # Search Storage if enabled
            if search_storage:
                try:
                    storage_pools = connection.storage.get()
                    for storage in storage_pools:
                        # Apply filter if resource_type is specified
                        if resource_type and resource_type != 'storage':
                            continue
                            
                        storage_id = storage.get('storage', '').lower()
                        storage_type = storage.get('type', '').lower()
                        storage_content = storage.get('content', '').lower()
                        
                        if (query.lower() in storage_id or 
                            query.lower() in storage_type or 
                            query.lower() in storage_content):
                            
                            # Get storage usage if available
                            if nodes:
                                try:
                                    node_name = nodes[0]['node']
                                    storage_details = connection.nodes(node_name).storage(storage['storage']).status.get()
                                    storage['used'] = storage_details.get('used', 0)
                                    storage['total'] = storage_details.get('total', 0)
                                    storage['usage_percent'] = round((storage['used'] / storage['total']) * 100, 1) if storage['total'] > 0 else 0
                                except:
                                    storage['used'] = 0
                                    storage['total'] = 0
                                    storage['usage_percent'] = 0
                            
                            storage['host_id'] = host_id
                            storage['node'] = nodes[0]['node'] if nodes else ''
                            storage_results.append(storage)
                except Exception as e:
                    print(f"Error searching storage on host {host_id}: {str(e)}")
                    
        except Exception as e:
            print(f"Error searching host {host_id}: {str(e)}")
            continue
    
    # Determine which tab should be active by default
    active_tab = None
    if vm_results and search_vms:
        active_tab = 'vms'
    elif container_results and search_containers:
        active_tab = 'containers'
    elif node_results and search_nodes:
        active_tab = 'nodes'
    elif storage_results and search_storage:
        active_tab = 'storage'
    
    return render_template('search_results.html',
                          query=query,
                          status=status,
                          resource_type=resource_type,
                          selected_host_id=selected_host_id,
                          tag=tag,
                          vm_results=vm_results,
                          container_results=container_results,
                          node_results=node_results,
                          storage_results=storage_results,
                          search_vms=search_vms,
                          search_containers=search_containers,
                          search_nodes=search_nodes,
                          search_storage=search_storage,
                          active_tab=active_tab,
                          available_hosts=list(available_hosts))

def search_resources_route(proxmox_connections):
    """
    Search and filter resources by type (host, vm, container)
    This route is used for the dashboard cards to show all resources of a specific type
    """
    resource_type = request.args.get('type', '')
    
    if not resource_type:
        flash("Resource type is required", 'warning')
        return redirect(url_for('index'))
    
    # Initialize results
    vm_results = []
    container_results = []
    node_results = []
    available_hosts = set()
    
    # Search across all hosts
    for host_id, host_data in proxmox_connections.items():
        try:
            connection = host_data['connection']
            available_hosts.add(host_id)
            
            # Get nodes for this host
            if resource_type == 'host':
                nodes = connection.nodes.get()
                for node in nodes:
                    # Get node status for more details
                    try:
                        node_status = connection.nodes(node['node']).status.get()
                        cpu_usage = node_status.get('cpu', 0) * 100  # CPU usage as percentage
                        memory_total = node_status.get('memory', {}).get('total', 0)
                        memory_used = node_status.get('memory', {}).get('used', 0)
                        memory_usage = (memory_used / memory_total * 100) if memory_total > 0 else 0
                        
                        # Get VM and container counts
                        vms = connection.nodes(node['node']).qemu.get()
                        containers = connection.nodes(node['node']).lxc.get()
                        vm_count = len(vms)
                        container_count = len(containers)
                    except Exception as e:
                        print(f"Error getting status for node {node['node']}: {e}")
                        cpu_usage = 0
                        memory_usage = 0
                        vm_count = 0
                        container_count = 0
                    
                    node_info = {
                        'host_id': host_id,
                        'node': node['node'],
                        'status': node.get('status', 'unknown'),
                        'uptime': node.get('uptime', 0),
                        'cpu': node.get('cpu', 0),
                        'memory': node.get('mem', 0),
                        'type': 'node',
                        'cpu_usage': round(cpu_usage, 1),
                        'memory_usage': round(memory_usage, 1),
                        'vm_count': vm_count,
                        'container_count': container_count
                    }
                    node_results.append(node_info)
            
            # Get VMs and containers if requested
            nodes = connection.nodes.get()
            for node in nodes:
                node_name = node['node']
                
                # Get VMs for this node
                if resource_type == 'vm':
                    try:
                        vms = connection.nodes(node_name).qemu.get()
                        for vm in vms:
                            vm_info = {
                                'host_id': host_id,
                                'node': node_name,
                                'vmid': vm['vmid'],
                                'name': vm.get('name', f"VM {vm['vmid']}"),
                                'status': vm.get('status', 'unknown'),
                                'cpu': vm.get('cpu', 0),
                                'cpus': vm.get('cpus', 1),
                                'maxmem': vm.get('maxmem', 0),
                                'maxdisk': vm.get('maxdisk', 0),
                                'uptime': vm.get('uptime', 0),
                                'type': 'qemu',
                                'tags': vm.get('tags', '')
                            }
                            vm_results.append(vm_info)
                    except Exception as e:
                        print(f"Error getting VMs for {node_name}: {e}")
                
                # Get containers for this node
                if resource_type == 'container':
                    try:
                        containers = connection.nodes(node_name).lxc.get()
                        for container in containers:
                            container_info = {
                                'host_id': host_id,
                                'node': node_name,
                                'vmid': container['vmid'],
                                'name': container.get('name', f"CT {container['vmid']}"),
                                'status': container.get('status', 'unknown'),
                                'cpu': container.get('cpu', 0),
                                'cpus': container.get('cpus', 1),
                                'maxmem': container.get('maxmem', 0),
                                'maxdisk': container.get('maxdisk', 0),
                                'uptime': container.get('uptime', 0),
                                'type': 'lxc',
                                'tags': container.get('tags', '')
                            }
                            container_results.append(container_info)
                    except Exception as e:
                        print(f"Error getting containers for {node_name}: {e}")
                    
        except Exception as e:
            print(f"Error querying host {host_id}: {e}")
    
    # Set the active tab based on the resource type
    if resource_type == 'host':
        active_tab = 'nodes'
    elif resource_type == 'vm':
        active_tab = 'vms'
    elif resource_type == 'container':
        active_tab = 'containers'
    else:
        active_tab = None
    
    # Set search flags based on resource type
    search_vms = resource_type == 'vm'
    search_containers = resource_type == 'container'
    search_nodes = resource_type == 'host'
    search_storage = False
    
    # Determine title for the search page
    if resource_type == 'host':
        title = "All Hosts"
    elif resource_type == 'vm':
        title = "All Virtual Machines"
    elif resource_type == 'container':
        title = "All Containers"
    else:
        title = "Search Results"
    
    return render_template('search_results.html',
                          query=title,
                          status='',
                          resource_type=resource_type,
                          selected_host_id='',
                          tag='',
                          vm_results=vm_results,
                          container_results=container_results,
                          node_results=node_results,
                          storage_results=[],
                          search_vms=search_vms,
                          search_containers=search_containers,
                          search_nodes=search_nodes,
                          search_storage=search_storage,
                          active_tab=active_tab,
                          available_hosts=list(available_hosts))

# Maintenance management functions
def check_scheduled_maintenance(proxmox_connections):
    """Check and start scheduled maintenance if needed"""
    if 'scheduled_maintenance' not in g:
        return
    
    now = datetime.datetime.now()
    
    for schedule in g.scheduled_maintenance:
        if not schedule.get('completed', False) and schedule['scheduled_start'] <= now < schedule['scheduled_end']:
            try:
                # Start maintenance
                host_id = schedule['host_id']
                node = schedule['node']
                
                if host_id not in proxmox_connections:
                    continue
                
                connection = proxmox_connections[host_id]['connection']
                
                # Get current node description
                node_config = connection.nodes(node).config.get()
                description = node_config.get('description', '')
                
                # Add maintenance flag if not already there
                if '[MAINTENANCE]' not in description:
                    new_description = '[MAINTENANCE] ' + description
                    connection.nodes(node).config.put(description=new_description)
                    
                    # Record maintenance start
                    if 'maintenance_history' not in g:
                        g.maintenance_history = []
                    
                    maintenance_record = {
                        'host_id': host_id,
                        'node': node,
                        'start_time': now,
                        'end_time': None,
                        'scheduled': True,
                        'scheduled_id': schedule['id'],
                        'migration_details': {},
                        'notes': schedule['notes']
                    }
                    g.maintenance_history.append(maintenance_record)
                    
                    # Handle migrations if configured
                    if schedule['migrate_vms'] and schedule['migration_target']:
                        # Code to migrate VMs and containers
                        # Would be implemented here
                        pass
                    
                    # Mark as started in the scheduled list
                    schedule['started'] = True
            except Exception as e:
                print(f"Error starting scheduled maintenance: {str(e)}")
                continue
        elif schedule.get('started', False) and now >= schedule['scheduled_end']:
            try:
                # End maintenance
                host_id = schedule['host_id']
                node = schedule['node']
                
                if host_id not in proxmox_connections:
                    continue
                
                connection = proxmox_connections[host_id]['connection']
                
                # Get current node description
                node_config = connection.nodes(node).config.get()
                description = node_config.get('description', '')
                
                # Remove maintenance flag
                new_description = description.replace('[MAINTENANCE] ', '')
                connection.nodes(node).config.put(description=new_description)
                
                # Update maintenance record
                for record in g.maintenance_history:
                    if record.get('scheduled_id') == schedule['id'] and record['end_time'] is None:
                        record['end_time'] = now
                        break
                
                # Mark as completed
                schedule['completed'] = True
            except Exception as e:
                print(f"Error ending scheduled maintenance: {str(e)}")
                continue

def all_maintenance_route(proxmox_connections):
    """View all maintenance activities across all nodes"""
    try:
        # Collect all maintenance information across all hosts
        all_history = []
        all_scheduled = []
        
        if 'maintenance_history' in g:
            all_history = g.maintenance_history
            
        if 'scheduled_maintenance' in g:
            all_scheduled = g.scheduled_maintenance
            
        # Get node and host information for easier display
        host_node_info = {}
        
        for host_id in proxmox_connections:
            try:
                connection = proxmox_connections[host_id]['connection']
                nodes = connection.nodes.get()
                
                host_node_info[host_id] = {
                    'name': host_id,
                    'nodes': {n['node']: n for n in nodes}
                }
            except Exception:
                continue
        
        return render_template('maintenance_all.html',
                              history=all_history,
                              scheduled=all_scheduled,
                              host_node_info=host_node_info)
        
    except Exception as e:
        flash(f"Failed to retrieve maintenance information: {str(e)}", 'danger')
        return redirect(url_for('index'))

def node_maintenance_route(host_id, node, proxmox_connections):
    """
    Manage maintenance mode for a node
    """
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get node information
        node_status = connection.nodes(node).status.get()
        
        # Get current maintenance status (stored in node description)
        node_config = connection.nodes(node).config.get()
        description = node_config.get('description', '')
        in_maintenance = '[MAINTENANCE]' in description
        
        # Get VMs and containers on this node for migration
        vms = connection.nodes(node).qemu.get()
        containers = connection.nodes(node).lxc.get()
        
        # Get other available nodes for migration targets
        available_nodes = []
        all_nodes = connection.nodes.get()
        for n in all_nodes:
            if n['node'] != node and n['status'] == 'online':
                available_nodes.append(n)
        
        # Check for scheduled maintenance
        scheduled_maintenance = None
        if 'scheduled_maintenance' in g:
            for sm in g.scheduled_maintenance:
                if sm['host_id'] == host_id and sm['node'] == node and not sm.get('completed', False):
                    scheduled_maintenance = sm
                    break
        
        # Initialize maintenance history if not already in g
        if 'maintenance_history' not in g:
            g.maintenance_history = []
        
        # Get maintenance history for this node
        node_history = [h for h in g.maintenance_history if h['host_id'] == host_id and h['node'] == node]
        
        if request.method == 'POST':
            action = request.form.get('action')
            
            if action == 'enable_maintenance':
                # Add maintenance flag to node description
                new_description = description
                if '[MAINTENANCE]' not in new_description:
                    new_description = '[MAINTENANCE] ' + new_description
                
                # Update node description
                connection.nodes(node).config.put(description=new_description)
                
                # Record maintenance start
                maintenance_record = {
                    'host_id': host_id,
                    'node': node,
                    'start_time': datetime.datetime.now(),
                    'end_time': None,
                    'scheduled': False,
                    'migration_details': {},
                    'notes': request.form.get('notes', '')
                }
                g.maintenance_history.append(maintenance_record)
                
                # Handle migration of resources if requested
                migrate_vms = request.form.get('migrate_vms') == 'on'
                target_node = request.form.get('target_node')
                
                if migrate_vms and target_node:
                    migration_started = 0
                    migration_errors = []
                    
                    # Params for migration
                    params = {
                        'target': target_node,
                        'with-local-disks': 1
                    }
                    
                    # Migrate running VMs first if online migration is enabled
                    online_migration = request.form.get('online_migration') == 'on'
                    if online_migration:
                        params['online'] = 1
                    
                    # Track which resources are being migrated
                    maintenance_record['migration_details'] = {
                        'target_node': target_node,
                        'online_migration': online_migration,
                        'vms': [],
                        'containers': []
                    }
                    
                    # Migrate VMs
                    for vm in vms:
                        # Skip VMs that have been explicitly excluded
                        if request.form.get(f"exclude_vm_{vm['vmid']}") == 'on':
                            continue
                        
                        try:
                            # Only attempt online migration for running VMs
                            if vm['status'] == 'running' and online_migration:
                                connection.nodes(node).qemu(vm['vmid']).migrate.post(**params)
                            elif vm['status'] != 'running':
                                # For stopped VMs, online param not needed
                                offline_params = params.copy()
                                if 'online' in offline_params:
                                    del offline_params['online']
                                connection.nodes(node).qemu(vm['vmid']).migrate.post(**offline_params)
                            else:
                                # Running VMs when online migration not enabled need to be skipped
                                continue
                            
                            migration_started += 1
                            maintenance_record['migration_details']['vms'].append({
                                'vmid': vm['vmid'],
                                'name': vm.get('name', f"VM-{vm['vmid']}"),
                                'status': vm['status']
                            })
                        except Exception as e:
                            migration_errors.append(f"Failed to migrate VM {vm['vmid']}: {str(e)}")
                    
                    # Migrate Containers
                    for container in containers:
                        # Skip containers that have been explicitly excluded
                        if request.form.get(f"exclude_ct_{container['vmid']}") == 'on':
                            continue
                        
                        try:
                            # Only attempt online migration for running containers
                            if container['status'] == 'running' and online_migration:
                                connection.nodes(node).lxc(container['vmid']).migrate.post(**params)
                            elif container['status'] != 'running':
                                # For stopped containers, online param not needed
                                offline_params = params.copy()
                                if 'online' in offline_params:
                                    del offline_params['online']
                                connection.nodes(node).lxc(container['vmid']).migrate.post(**offline_params)
                            else:
                                # Running containers when online migration not enabled need to be skipped
                                continue
                            
                            migration_started += 1
                            maintenance_record['migration_details']['containers'].append({
                                'vmid': container['vmid'],
                                'name': container.get('name', f"CT-{container['vmid']}"),
                                'status': container['status']
                            })
                        except Exception as e:
                            migration_errors.append(f"Failed to migrate container {container['vmid']}: {str(e)}")
                    
                    if migration_started > 0:
                        flash(f"Started migration of {migration_started} resources to node {target_node}", 'success')
                    
                    if migration_errors:
                        for error in migration_errors:
                            flash(error, 'warning')
                
                flash(f"Node {node} is now in maintenance mode", 'success')
                
            elif action == 'disable_maintenance':
                # Remove maintenance flag from node description
                new_description = description.replace('[MAINTENANCE] ', '')
                
                # Update node description
                connection.nodes(node).config.put(description=new_description)
                
                # Update maintenance record
                for record in g.maintenance_history:
                    if record['host_id'] == host_id and record['node'] == node and record['end_time'] is None:
                        record['end_time'] = datetime.datetime.now()
                        break
                
                flash(f"Maintenance mode disabled for node {node}", 'success')
                
            elif action == 'schedule_maintenance':
                start_date = request.form.get('start_date')
                start_time = request.form.get('start_time')
                duration_hours = int(request.form.get('duration_hours', 0))
                duration_minutes = int(request.form.get('duration_minutes', 0))
                notes = request.form.get('schedule_notes', '')
                
                # Validate inputs
                if not start_date or not start_time or (duration_hours == 0 and duration_minutes == 0):
                    flash("Please provide start date, time and duration", 'danger')
                else:
                    # Initialize scheduled maintenance list if not exists
                    if 'scheduled_maintenance' not in g:
                        g.scheduled_maintenance = []
                    
                    # Parse start datetime
                    start_datetime = datetime.datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
                    
                    # Calculate end datetime
                    duration_td = datetime.timedelta(hours=duration_hours, minutes=duration_minutes)
                    end_datetime = start_datetime + duration_td
                    
                    # Create scheduled maintenance record
                    maintenance_schedule = {
                        'id': str(uuid.uuid4()),
                        'host_id': host_id,
                        'node': node,
                        'scheduled_start': start_datetime,
                        'scheduled_end': end_datetime,
                        'migration_target': request.form.get('schedule_target_node', ''),
                        'migrate_vms': request.form.get('schedule_migrate_vms') == 'on',
                        'online_migration': request.form.get('schedule_online_migration') == 'on',
                        'notes': notes,
                        'created_at': datetime.datetime.now(),
                        'completed': False
                    }
                    
                    g.scheduled_maintenance.append(maintenance_schedule)
                    
                    # Format dates for display
                    start_str = start_datetime.strftime('%Y-%m-%d %H:%M')
                    end_str = end_datetime.strftime('%Y-%m-%d %H:%M')
                    
                    flash(f"Maintenance scheduled from {start_str} to {end_str}", 'success')
                    
            elif action == 'cancel_schedule':
                schedule_id = request.form.get('schedule_id')
                
                if 'scheduled_maintenance' in g:
                    g.scheduled_maintenance = [s for s in g.scheduled_maintenance 
                                             if not (s['id'] == schedule_id and 
                                                    s['host_id'] == host_id and 
                                                    s['node'] == node)]
                    
                    flash("Scheduled maintenance cancelled", 'success')
            
            # Redirect to refresh
            return redirect(url_for('node_maintenance', host_id=host_id, node=node))
        
        # GET request
        return render_template('node_maintenance.html',
                               host_id=host_id,
                               node=node,
                               node_status=node_status,
                               in_maintenance=in_maintenance,
                               vms=vms,
                               containers=containers,
                               available_nodes=available_nodes,
                               scheduled_maintenance=scheduled_maintenance,
                               maintenance_history=node_history)
                               
    except Exception as e:
        flash(f"Failed to access maintenance mode: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize cache and connection data structures
cache = {}
cache_lock = threading.Lock()
proxmox_connections = {}
connection_lock = threading.Lock()

# Load connections from disk
CONNECTIONS_FILE = 'connections.pkl'
load_connections(CONNECTIONS_FILE, proxmox_connections, connection_lock)

# Function to register all utility routes with the Flask app
def register_all_routes(app, proxmox_connections, cache, cache_lock):
    """
    Register all utility routes with the Flask application
    """
    # Register search routes with unique names to avoid conflicts
    @app.route('/api/search')
    def api_search():
        return search_route(proxmox_connections)
    
    @app.route('/api/search_resources')
    def api_search_resources():
        return search_resources_route(proxmox_connections)
    
    # Register settings routes with unique names to avoid conflicts
    @app.route('/api/settings')
    def api_settings():
        return settings_route()
    
    @app.route('/api/settings/update', methods=['POST'])
    def api_update_settings():
        return update_settings_route()
        
    @app.route('/api/settings/resource_thresholds', methods=['GET', 'POST'])
    def api_save_resource_thresholds():
        return resource_thresholds_route()
    
    # Register maintenance routes with unique names to avoid conflicts
    @app.route('/api/maintenance/all')
    def api_all_maintenance():
        return all_maintenance_route(proxmox_connections)
    
    @app.route('/api/node/<host_id>/<node>/maintenance', methods=['GET', 'POST'])
    def api_node_maintenance(host_id, node):
        return node_maintenance_route(host_id, node, proxmox_connections)
    
    # Register logs route
    @app.route('/api/logs')
    def api_logs():
        return logs_route()

# Register routes from app_utils
register_all_routes(app, proxmox_connections, cache, cache_lock)

# Check for scheduled maintenance
@app.before_request
def before_request():
    check_scheduled_maintenance(proxmox_connections)

# Run the Flask app
if __name__ == '__main__':
    app.run(debug=True)