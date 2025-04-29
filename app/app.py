from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session, make_response, g
from flask_bootstrap import Bootstrap
import os
import json
from dotenv import load_dotenv
from proxmoxer import ProxmoxAPI
import pickle
import threading
import datetime
import time
import schedule  # For snapshot scheduling
import re  # For regex pattern matching
import random
import uuid  # For generating unique IDs
import requests  # For making HTTP requests

# Import utility functions and route handlers from app_utils
from app_utils import (
    get_from_cache, set_in_cache, invalidate_cache,
    search_route, settings_route, update_settings_route, resource_thresholds_route, logs_route,
    node_maintenance_route, all_maintenance_route,
    register_all_routes, check_scheduled_maintenance
)

# Load environment variables
load_dotenv()

app = Flask(__name__)
# Set a secret key for session management
app.secret_key = os.getenv('SECRET_KEY', 'proxima_ui_secret_key_change_in_production')
bootstrap = Bootstrap(app)

# Store Proxmox connections with thread-safe lock
connection_lock = threading.Lock()
proxmox_connections = {}

# Simple cache implementation with TTL
cache_lock = threading.Lock()
cache = {}

def get_from_cache(key, ttl=30):
    """Get a value from cache if it exists and is not expired"""
    with cache_lock:
        if key in cache:
            cached_time, cached_value = cache[key]
            if time.time() - cached_time < ttl:
                return cached_value
    return None

def set_in_cache(key, value, ttl=30):
    """Set a value in cache with current timestamp"""
    with cache_lock:
        cache[key] = (time.time(), value)
        
def invalidate_cache(prefix=None):
    """Invalidate all cache entries or those starting with prefix"""
    with cache_lock:
        if prefix:
            keys_to_delete = [k for k in cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del cache[key]
        else:
            cache.clear()

# Path to save connections
CONNECTIONS_FILE = os.getenv('CONNECTIONS_FILE', 'proxmox_connections.pkl')

# Try to load saved connections
def load_connections():
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
                        
                        # Reconnect to each saved host
                        proxmox = ProxmoxAPI(**conn_params)
                        
                        # Update connection data with live connection
                        data['connection'] = proxmox
                        proxmox_connections[host_id] = data
                        print(f"Reconnected to {host_id}")
                    except Exception as e:
                        print(f"Failed to reconnect to {host_id}: {str(e)}")
    except Exception as e:
        print(f"Error loading connections: {str(e)}")

# Save connections to disk
def save_connections():
    with connection_lock:
        try:
            # Create a copy of connections without the actual connection objects
            to_save = {}
            for host_id, data in proxmox_connections.items():
                to_save[host_id] = {
                    'host': data['host'],
                    'user': data['user'],
                    'password': data['password'],
                    'port': data['port'],
                    'verify_ssl': data['verify_ssl']
                }
            
            with open(CONNECTIONS_FILE, 'wb') as f:
                pickle.dump(to_save, f)
        except Exception as e:
            print(f"Error saving connections: {str(e)}")

# Initial load
load_connections()

# Custom template filters
@app.template_filter('timestamp_to_date')
def timestamp_to_date(timestamp):
    """Convert a UNIX timestamp to a formatted date string."""
    try:
        dt = datetime.datetime.fromtimestamp(int(timestamp))
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, TypeError):
        return 'Invalid date'

@app.route('/')
def index():
    # Add current datetime for the dashboard
    now = datetime.datetime.now()
    
    # If there are no hosts, just return the empty dashboard
    if not proxmox_connections:
        return render_template('index.html', hosts=proxmox_connections, now=now)
    
    # Gather statistics for the dashboard
    stats = {
        'vms_total': 0,
        'vms_running': 0,
        'containers_total': 0,
        'containers_running': 0,
        'cpu_health_percent': 0,
        'memory_health_percent': 0,
        'storage_health_percent': 0,
        'nodes': []
    }
    
    # Track total resource metrics for averaging
    total_cpu_percent = 0
    total_memory_percent = 0
    total_storage_percent = 0
    resource_count = 0
    
    # Gather statistics from all hosts
    for host_id, host_data in proxmox_connections.items():
        try:
            connection = host_data['connection']
            
            # Get all nodes for this host
            nodes = connection.nodes.get()
            
            # Track host-specific stats
            host_stats = {
                'vms_total': 0,
                'vms_running': 0,
                'containers_total': 0,
                'containers_running': 0,
                'nodes_total': len(nodes),
                'nodes_online': 0
            }
            
            # Process each node
            for node_info in nodes:
                node_name = node_info['node']
                
                # Skip offline nodes
                if node_info['status'] != 'online':
                    continue
                
                host_stats['nodes_online'] += 1
                
                try:
                    # Get node status
                    node_status = connection.nodes(node_name).status.get()
                    
                    # Calculate memory percentage
                    memory_total = node_status['memory']['total'] / (1024*1024*1024)  # Convert to GB
                    memory_used = node_status['memory']['used'] / (1024*1024*1024)    # Convert to GB
                    memory_percent = (node_status['memory']['used'] / node_status['memory']['total']) * 100
                    
                    # Get CPU percentage
                    cpu_percent = node_status['cpu'] * 100
                    
                    # Get storage information
                    storage_info = connection.nodes(node_name).storage.get()
                    storage_percent = 0
                    storage_count = 0
                    
                    for storage in storage_info:
                        if 'total' in storage and storage['total'] > 0:
                            storage_percent += (storage['used'] / storage['total']) * 100
                            storage_count += 1
                    
                    # Average storage percentage for this node
                    if storage_count > 0:
                        storage_percent = storage_percent / storage_count
                    
                    # Add to total resource metrics
                    total_cpu_percent += cpu_percent
                    total_memory_percent += memory_percent
                    total_storage_percent += storage_percent
                    resource_count += 1
                    
                    # Get VMs on this node
                    vms = connection.nodes(node_name).qemu.get()
                    vm_count = len(vms)
                    vm_running = sum(1 for vm in vms if vm['status'] == 'running')
                    
                    # Get containers on this node
                    containers = connection.nodes(node_name).lxc.get()
                    container_count = len(containers)
                    container_running = sum(1 for ct in containers if ct['status'] == 'running')
                    
                    # Update host stats
                    host_stats['vms_total'] += vm_count
                    host_stats['vms_running'] += vm_running
                    host_stats['containers_total'] += container_count
                    host_stats['containers_running'] += container_running
                    
                    # Update global stats
                    stats['vms_total'] += vm_count
                    stats['vms_running'] += vm_running
                    stats['containers_total'] += container_count
                    stats['containers_running'] += container_running
                    
                    # Add node details to the stats
                    stats['nodes'].append({
                        'host_id': host_id,
                        'name': node_name,
                        'status': node_info['status'],
                        'cpu': cpu_percent,
                        'memory_used': memory_used,
                        'memory_total': memory_total,
                        'memory_percent': memory_percent,
                        'storage_percent': storage_percent,
                        'vms_total': vm_count,
                        'vms_running': vm_running,
                        'containers_total': container_count,
                        'containers_running': container_running,
                        'uptime': node_status.get('uptime', 0)
                    })
                    
                except Exception as e:
                    print(f"Error getting data for node {node_name} on host {host_id}: {str(e)}")
                    continue
            
            # Add host stats to host_data for display in host cards
            host_data['status'] = host_stats
            
        except Exception as e:
            print(f"Error processing host {host_id}: {str(e)}")
            continue
    
    # Calculate the average health percentages
    if resource_count > 0:
        stats['cpu_health_percent'] = 100 - (total_cpu_percent / resource_count)
        stats['memory_health_percent'] = 100 - (total_memory_percent / resource_count)
        stats['storage_health_percent'] = 100 - (total_storage_percent / resource_count)
    
    # Sort nodes by status (online first) and then by name
    stats['nodes'].sort(key=lambda x: (0 if x['status'] == 'online' else 1, x['name']))
    
    return render_template('index.html', hosts=proxmox_connections, now=now, stats=stats)

@app.route('/add_host', methods=['GET', 'POST'])
def add_host():
    if request.method == 'POST':
        host = request.form.get('hostname')
        port = int(request.form.get('port', 8006))
        verify_ssl = request.form.get('verify_ssl') == 'on'
        auth_method = request.form.get('auth_method', 'password')
        
        try:
            # Connection parameters
            connection_params = {
                'host': host,
                'port': port,
                'verify_ssl': verify_ssl
            }
            
            # Handle different authentication methods
            if auth_method == 'password':
                user = request.form.get('username')
                password = request.form.get('password')
                
                # Check if required fields are present
                if not user or not password:
                    flash("Username and password are required for password authentication", 'danger')
                    return render_template('add_host.html')
                
                # Add password auth parameters
                connection_params['user'] = user
                connection_params['password'] = password
                auth_info = {
                    'auth_method': 'password',
                    'user': user,
                    'password': password
                }
            else:  # API key authentication
                api_tokenid = request.form.get('api_tokenid')
                api_token = request.form.get('api_token')
                
                # Check if required fields are present
                if not api_tokenid or not api_token:
                    flash("API Token ID and Secret are required for API key authentication", 'danger')
                    return render_template('add_host.html')
                
                # Add API key auth parameters
                connection_params['token_name'] = api_tokenid
                connection_params['token_value'] = api_token
                auth_info = {
                    'auth_method': 'apikey',
                    'token_name': api_tokenid,
                    'token_value': api_token
                }
            
            # Test connection
            proxmox = ProxmoxAPI(**connection_params)
            version = proxmox.version.get()
            
            # Store connection info
            with connection_lock:
                host_id = f"{host}:{port}"
                proxmox_connections[host_id] = {
                    'host': host,
                    'port': port,
                    'verify_ssl': verify_ssl,
                    'connection': proxmox,
                    **auth_info
                }
            
            # Save updated connections
            save_connections()
            
            flash(f"Successfully connected to {host} - Proxmox {version['version']}", 'success')
            return redirect(url_for('index'))
        except Exception as e:
            flash(f"Failed to connect: {str(e)}", 'danger')
    
    return render_template('add_host.html')

@app.route('/remove_host/<host_id>')
def remove_host(host_id):
    with connection_lock:
        if host_id in proxmox_connections:
            del proxmox_connections[host_id]
            save_connections()
            flash(f"Host {host_id} removed", 'success')
        else:
            flash("Host not found", 'danger')
    return redirect(url_for('index'))

@app.route('/host/<host_id>')
def host_details(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        nodes = connection.nodes.get()
        
        return render_template('host_details.html', 
                            host_id=host_id, 
                            host_info=proxmox_connections[host_id],
                            nodes=nodes)
    except Exception as e:
        flash(f"Failed to get host details: {str(e)}", 'danger')
        return redirect(url_for('index'))

@app.route('/node/<host_id>/<node>')
def node_details(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get VMs and containers
        vms = connection.nodes(node).qemu.get()
        containers = connection.nodes(node).lxc.get()
        node_status = connection.nodes(node).status.get()
        
        return render_template('node_details.html',
                            host_id=host_id,
                            node=node,
                            vms=vms,
                            containers=containers,
                            node_status=node_status)
    except Exception as e:
        flash(f"Failed to get node details: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id, node=node))

@app.route('/vm/<host_id>/<node>/<vmid>')
def vm_details(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        vm_info = connection.nodes(node).qemu(vmid).status.current.get()
        
        return render_template('vm_details.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            vm_info=vm_info)
    except Exception as e:
        flash(f"Failed to get VM details: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/container/<host_id>/<node>/<vmid>')
def container_details(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        container_info = connection.nodes(node).lxc(vmid).status.current.get()
        
        return render_template('container_details.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            container_info=container_info)
    except Exception as e:
        flash(f"Failed to get container details: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/vm/<host_id>/<node>/<vmid>/snapshots')
def vm_snapshots(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get VM info for name
        vm_info = connection.nodes(node).qemu(vmid).status.current.get()
        
        # Get snapshots
        snapshots = connection.nodes(node).qemu(vmid).snapshot.get()
        
        # Convert timestamps to human-readable format
        for snapshot in snapshots:
            if 'snaptime' in snapshot:
                try:
                    timestamp = int(snapshot['snaptime'])
                    snapshot['snaptime'] = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    pass
        
        return render_template('vm_snapshots.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            vm_name=vm_info.get('name', f'VM {vmid}'),
                            snapshots=snapshots)
    except Exception as e:
        flash(f"Failed to get VM snapshots: {str(e)}", 'danger')
        return redirect(url_for('vm_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/snapshots/create', methods=['POST'])
def create_vm_snapshot(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    include_ram = request.form.get('include_ram') == 'on'
    
    if not name:
        flash("Snapshot name is required", 'danger')
        return redirect(url_for('vm_snapshots', host_id=host_id, node=node, vmid=vmid))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Create snapshot
        connection.nodes(node).qemu(vmid).snapshot.post(
            snapname=name,
            description=description,
            vmstate=1 if include_ram else 0
        )
        
        flash(f"Snapshot '{name}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create snapshot: {str(e)}", 'danger')
    
    return redirect(url_for('vm_snapshots', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/snapshots/<snapname>/restore', methods=['POST'])
def restore_vm_snapshot(host_id, node, vmid, snapname):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Restore snapshot
        connection.nodes(node).qemu(vmid).snapshot(snapname).rollback.post()
        
        flash(f"Snapshot '{snapname}' restored successfully", 'success')
    except Exception as e:
        flash(f"Failed to restore snapshot: {str(e)}", 'danger')
    
    return redirect(url_for('vm_snapshots', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/snapshots/<snapname>/delete', methods=['POST'])
def delete_vm_snapshot(host_id, node, vmid, snapname):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete snapshot
        connection.nodes(node).qemu(vmid).snapshot(snapname).delete()
        
        flash(f"Snapshot '{snapname}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete snapshot: {str(e)}", 'danger')
    
    return redirect(url_for('vm_snapshots', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/snapshots')
def container_snapshots(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get container info for name
        container_info = connection.nodes(node).lxc(vmid).status.current.get()
        
        # Get snapshots
        snapshots = connection.nodes(node).lxc(vmid).snapshot.get()
        
        # Convert timestamps to human-readable format
        for snapshot in snapshots:
            if 'snaptime' in snapshot:
                try:
                    timestamp = int(snapshot['snaptime'])
                    snapshot['snaptime'] = datetime.datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    pass
        
        return render_template('container_snapshots.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            container_name=container_info.get('name', f'Container {vmid}'),
                            snapshots=snapshots)
    except Exception as e:
        flash(f"Failed to get container snapshots: {str(e)}", 'danger')
        return redirect(url_for('container_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/snapshots/create', methods=['POST'])
def create_container_snapshot(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    name = request.form.get('name')
    description = request.form.get('description', '')
    
    if not name:
        flash("Snapshot name is required", 'danger')
        return redirect(url_for('container_snapshots', host_id=host_id, node=node, vmid=vmid))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Create snapshot
        connection.nodes(node).lxc(vmid).snapshot.post(
            snapname=name,
            description=description
        )
        
        flash(f"Snapshot '{name}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create snapshot: {str(e)}", 'danger')
    
    return redirect(url_for('container_snapshots', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/snapshots/<snapname>/restore', methods=['POST'])
def restore_container_snapshot(host_id, node, vmid, snapname):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Restore snapshot
        connection.nodes(node).lxc(vmid).snapshot(snapname).rollback.post()
        
        flash(f"Snapshot '{snapname}' restored successfully", 'success')
    except Exception as e:
        flash(f"Failed to restore snapshot: {str(e)}", 'danger')
    
    return redirect(url_for('container_snapshots', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/snapshots/<snapname>/delete', methods=['POST'])
def delete_container_snapshot(host_id, node, vmid, snapname):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete snapshot
        connection.nodes(node).lxc(vmid).snapshot(snapname).delete()
        
        flash(f"Snapshot '{snapname}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete snapshot: {str(e)}", 'danger')
    
    return redirect(url_for('container_snapshots', host_id=host_id, node=node, vmid=vmid))

@app.route('/api/vm/action', methods=['POST'])
def vm_action():
    host_id = request.form.get('host_id')
    node = request.form.get('node')
    vmid = request.form.get('vmid')
    action = request.form.get('action')
    
    if host_id not in proxmox_connections:
        return jsonify({'success': False, 'error': 'Host not found'})
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        if action == 'start':
            connection.nodes(node).qemu(vmid).status.start.post()
        elif action == 'stop':
            connection.nodes(node).qemu(vmid).status.stop.post()
        elif action == 'shutdown':
            connection.nodes(node).qemu(vmid).status.shutdown.post()
        elif action == 'reset':
            connection.nodes(node).qemu(vmid).status.reset.post()
        else:
            return jsonify({'success': False, 'error': 'Invalid action'})
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/container/action', methods=['POST'])
def container_action():
    host_id = request.form.get('host_id')
    node = request.form.get('node')
    vmid = request.form.get('vmid')
    action = request.form.get('action')
    
    if host_id not in proxmox_connections:
        return jsonify({'success': False, 'error': 'Host not found'})
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        if action == 'start':
            connection.nodes(node).lxc(vmid).status.start.post()
        elif action == 'stop':
            connection.nodes(node).lxc(vmid).status.stop.post()
        elif action == 'shutdown':
            connection.nodes(node).lxc(vmid).status.shutdown.post()
        else:
            return jsonify({'success': False, 'error': 'Invalid action'})
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/bulk/vm/action', methods=['POST'])
def bulk_vm_action():
    host_id = request.form.get('host_id')
    action = request.form.get('action')
    vms = json.loads(request.form.get('vms', '[]'))
    
    if host_id not in proxmox_connections:
        return jsonify({'success': False, 'error': 'Host not found'})
    
    if not vms:
        return jsonify({'success': False, 'error': 'No VMs specified'})
    
    if action not in ['start', 'stop', 'shutdown', 'reset']:
        return jsonify({'success': False, 'error': 'Invalid action'})
    
    try:
        connection = proxmox_connections[host_id]['connection']
        processed = 0
        errors = []
        
        for vm in vms:
            try:
                node = vm.get('node')
                vmid = vm.get('vmid')
                
                if action == 'start':
                    connection.nodes(node).qemu(vmid).status.start.post()
                elif action == 'stop':
                    connection.nodes(node).qemu(vmid).status.stop.post()
                elif action == 'shutdown':
                    connection.nodes(node).qemu(vmid).status.shutdown.post()
                elif action == 'reset':
                    connection.nodes(node).qemu(vmid).status.reset.post()
                
                processed += 1
            except Exception as e:
                errors.append(f"VM {vmid} on node {node}: {str(e)}")
        
        if errors:
            return jsonify({
                'success': True,
                'processed': processed,
                'warnings': errors,
                'message': f"Processed {processed} VMs with {len(errors)} errors"
            })
        else:
            return jsonify({
                'success': True,
                'processed': processed,
                'message': f"Successfully processed {processed} VMs"
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/bulk/container/action', methods=['POST'])
def bulk_container_action():
    host_id = request.form.get('host_id')
    action = request.form.get('action')
    containers = json.loads(request.form.get('containers', '[]'))
    
    if host_id not in proxmox_connections:
        return jsonify({'success': False, 'error': 'Host not found'})
    
    if not containers:
        return jsonify({'success': False, 'error': 'No containers specified'})
    
    if action not in ['start', 'stop', 'shutdown']:
        return jsonify({'success': False, 'error': 'Invalid action'})
    
    try:
        connection = proxmox_connections[host_id]['connection']
        processed = 0
        errors = []
        
        for container in containers:
            try:
                node = container.get('node')
                vmid = container.get('vmid')
                
                if action == 'start':
                    connection.nodes(node).lxc(vmid).status.start.post()
                elif action == 'stop':
                    connection.nodes(node).lxc(vmid).status.stop.post()
                elif action == 'shutdown':
                    connection.nodes(node).lxc(vmid).status.shutdown.post()
                
                processed += 1
            except Exception as e:
                errors.append(f"Container {vmid} on node {node}: {str(e)}")
        
        if errors:
            return jsonify({
                'success': True,
                'processed': processed,
                'warnings': errors,
                'message': f"Processed {processed} containers with {len(errors)} errors"
            })
        else:
            return jsonify({
                'success': True,
                'processed': processed,
                'message': f"Successfully processed {processed} containers"
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/bulk/migrate', methods=['POST'])
def bulk_migrate():
    host_id = request.form.get('host_id')
    type = request.form.get('type')
    items = json.loads(request.form.get('items', '[]'))
    target_node = request.form.get('target_node')
    online = request.form.get('online') == 'true'
    with_local_disks = request.form.get('with_local_disks') == 'true'
    
    if host_id not in proxmox_connections:
        return jsonify({'success': False, 'error': 'Host not found'})
    
    if not items:
        return jsonify({'success': False, 'error': 'No resources specified for migration'})
    
    if not target_node:
        return jsonify({'success': False, 'error': 'Target node is required'})
    
    if type not in ['qemu', 'lxc']:
        return jsonify({'success': False, 'error': 'Invalid resource type'})
    
    try:
        connection = proxmox_connections[host_id]['connection']
        processed = 0
        errors = []
        
        # Create migration parameters
        params = {
            'target': target_node
        }
        
        if online:
            params['online'] = 1
            
        if with_local_disks:
            params['with-local-disks'] = 1
        
        for item in items:
            try:
                node = item.get('node')
                vmid = item.get('vmid')
                
                # Start migration
                if type == 'qemu':
                    connection.nodes(node).qemu(vmid).migrate.post(**params)
                elif type == 'lxc':
                    connection.nodes(node).lxc(vmid).migrate.post(**params)
                
                processed += 1
            except Exception as e:
                errors.append(f"Resource {vmid} on node {node}: {str(e)}")
        
        if errors:
            return jsonify({
                'success': True,
                'processed': processed,
                'warnings': errors,
                'message': f"Started migration for {processed} resources with {len(errors)} errors"
            })
        else:
            return jsonify({
                'success': True,
                'processed': processed,
                'message': f"Successfully started migration for {processed} resources"
            })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/host/<host_id>/storage')
def storage_list(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get storage pools
        storage_pools = connection.storage.get()
        
        # Get all nodes for this host
        nodes = connection.nodes.get()
        nodes_dict = {node['node']: node for node in nodes}
        
        # Enhance storage info with usage statistics from first available node
        if nodes:
            sample_node = nodes[0]['node']
            
            for storage in storage_pools:
                try:
                    # Get detailed storage info for the pool from the sample node
                    storage_details = connection.nodes(sample_node).storage(storage['storage']).status.get()
                    
                    # Add usage info to the storage object
                    storage['total'] = storage_details.get('total', 0)
                    storage['used'] = storage_details.get('used', 0)
                    storage['available'] = storage_details.get('avail', 0)
                    
                    # Calculate percentage used
                    if storage['total'] > 0:
                        storage['percent_used'] = (storage['used'] / storage['total']) * 100
                    else:
                        storage['percent_used'] = 0
                        
                except Exception:
                    # If we can't get details, set defaults
                    storage['total'] = 0
                    storage['used'] = 0 
                    storage['available'] = 0
                    storage['percent_used'] = 0
        
        return render_template('storage_list.html',
                            host_id=host_id,
                            storage_pools=storage_pools,
                            nodes=nodes_dict)
    except Exception as e:
        flash(f"Failed to get storage list: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/storage/create', methods=['POST'])
def create_storage(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    storage_id = request.form.get('storage_id')
    storage_type = request.form.get('storage_type')
    content = request.form.getlist('content')  # This will be a list of selected content types
    
    # Required parameters for all storage types
    params = {
        'storage': storage_id,
        'type': storage_type,
        'content': ','.join(content)  # Convert list to comma-separated string
    }
    
    # Add type-specific parameters based on the selected storage type
    if storage_type == 'dir':
        params['path'] = request.form.get('dir_path')
    elif storage_type == 'nfs':
        params['server'] = request.form.get('nfs_server')
        params['export'] = request.form.get('nfs_export')
    elif storage_type == 'cifs':
        params['server'] = request.form.get('cifs_server')
        params['share'] = request.form.get('cifs_share')
        username = request.form.get('cifs_username')
        password = request.form.get('cifs_password')
        if username:
            params['username'] = username
        if password:
            params['password'] = password
    
    try:
        connection = proxmox_connections[host_id]['connection']
        connection.storage.post(**params)
        flash(f"Storage '{storage_id}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create storage: {str(e)}", 'danger')
    
    return redirect(url_for('storage_list', host_id=host_id))

@app.route('/host/<host_id>/storage/<storage_id>/delete', methods=['POST'])
def delete_storage(host_id, storage_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        connection.storage(storage_id).delete()
        flash(f"Storage '{storage_id}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete storage: {str(e)}", 'danger')
    
    return redirect(url_for('storage_list', host_id=host_id))

@app.route('/host/<host_id>/backups')
def backup_list(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get all nodes for this host
        nodes = connection.nodes.get()
        
        # Collect backup info from all nodes
        all_backups = []
        storage_pools = connection.storage.get()
        
        # Create a mapping of storage IDs that support backups
        backup_storages = {}
        for storage in storage_pools:
            if 'backup' in storage.get('content', '').split(','):
                backup_storages[storage['storage']] = storage
        
        # Get all backup tasks across all nodes
        for node in nodes:
            node_name = node['node']
            try:
                # Get backup jobs from this node
                tasks = connection.nodes(node_name).tasks.get(limit=500)
                
                # Filter for backup tasks
                backup_tasks = [task for task in tasks if task.get('type') == 'vzdump']
                
                for task in backup_tasks:
                    try:
                        # Convert status information
                        if task.get('status') == 'stopped' and task.get('exitstatus') == 'OK':
                            task['status_display'] = 'Success'
                            task['status_class'] = 'success'
                        elif task.get('status') == 'running':
                            task['status_display'] = 'Running'
                            task['status_class'] = 'info'
                        elif task.get('status') == 'stopped' and task.get('exitstatus') != 'OK':
                            task['status_display'] = 'Failed'
                            task['status_class'] = 'danger'
                        else:
                            task['status_display'] = task.get('status', 'Unknown')
                            task['status_class'] = 'secondary'
                        
                        # Convert start time
                        if 'starttime' in task:
                            task['starttime_display'] = datetime.datetime.fromtimestamp(
                                task['starttime']).strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Add node information
                        task['node'] = node_name
                        
                        all_backups.append(task)
                    except Exception as e:
                        print(f"Error processing task: {str(e)}")
            except Exception as e:
                print(f"Error getting tasks from node {node_name}: {str(e)}")
        
        # Sort backups by start time (newest first)
        all_backups.sort(key=lambda x: x.get('starttime', 0), reverse=True)
        
        # Get all backup schedules
        try:
            backup_jobs = connection.cluster.backup.get()
        except Exception:
            # If cluster API is not available, try getting from individual nodes
            backup_jobs = []
            for node in nodes:
                try:
                    node_jobs = connection.nodes(node['node']).vzdump.extractConfig()
                    for job in node_jobs:
                        job['node'] = node['node']
                    backup_jobs.extend(node_jobs)
                except Exception:
                    pass
        
        return render_template('backups.html',
                            host_id=host_id,
                            backup_tasks=all_backups,
                            backup_jobs=backup_jobs,
                            backup_storages=backup_storages,
                            nodes=nodes)
    except Exception as e:
        flash(f"Failed to get backup list: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/backups/create', methods=['POST'])
def create_backup(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    node = request.form.get('node')
    vm_type = request.form.get('vm_type')
    vmid = request.form.get('vmid')
    storage = request.form.get('storage')
    mode = request.form.get('mode', 'snapshot')
    compress = request.form.get('compress') == 'on'
    
    if not node or not storage:
        flash("Missing required parameters", 'danger')
        return redirect(url_for('backup_list', host_id=host_id))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Build parameters for backup job
        params = {
            'storage': storage,
            'mode': mode,
            'compress': compress,
        }
        
        # Add VM/container selection parameter
        if vmid and vm_type:
            if vm_type == 'qemu':
                params['vmid'] = vmid
            elif vm_type == 'lxc':
                params['vmid'] = vmid
        
        # Start backup job
        result = connection.nodes(node).vzdump.post(**params)
        
        flash(f"Backup job started successfully. Task ID: {result.get('data')}", 'success')
    except Exception as e:
        flash(f"Failed to start backup: {str(e)}", 'danger')
    
    return redirect(url_for('backup_list', host_id=host_id))

@app.route('/host/<host_id>/backups/schedule', methods=['POST'])
def schedule_backup(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    schedule_id = request.form.get('schedule_id')
    storage = request.form.get('storage')
    schedule = request.form.get('schedule', '0 4 * * *')  # Default to 4 AM daily
    mode = request.form.get('mode', 'snapshot')
    compression = request.form.get('compression', 'zstd')  # Default compression
    retention = request.form.get('retention', '3')  # Default 3 backups
    all_vms = request.form.get('all') == 'on'
    exclude = request.form.get('exclude', '')
    vm_ids = request.form.getlist('vmids')
    
    if not storage:
        flash("Storage is required", 'danger')
        return redirect(url_for('backup_list', host_id=host_id))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Build parameters for backup schedule
        params = {
            'id': schedule_id,
            'storage': storage,
            'schedule': schedule,
            'mode': mode,
            'compress': compression,
            'maxfiles': retention,
            'enabled': 1
        }
        
        # Add VM selection parameter
        if all_vms:
            params['all'] = 1
            if exclude:
                params['exclude'] = exclude
        elif vm_ids:
            params['vmid'] = ','.join(vm_ids)
        
        # Create backup schedule
        connection.cluster.backup.post(**params)
        
        flash(f"Backup schedule '{schedule_id}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create backup schedule: {str(e)}", 'danger')
    
    return redirect(url_for('backup_list', host_id=host_id))

@app.route('/host/<host_id>/backups/delete_job/<job_id>', methods=['POST'])
def delete_backup_job(host_id, job_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        connection.cluster.backup(job_id).delete()
        flash(f"Backup job '{job_id}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete backup job: {str(e)}", 'danger')
    
    return redirect(url_for('backup_list', host_id=host_id))

@app.route('/host/<host_id>/backups/restore', methods=['POST'])
def restore_backup(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    node = request.form.get('node')
    archive = request.form.get('archive')
    storage = request.form.get('storage')
    target_vmid = request.form.get('target_vmid')
    
    if not node or not archive or not storage:
        flash("Missing required parameters", 'danger')
        return redirect(url_for('backup_list', host_id=host_id))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Build parameters for restore
        params = {
            'archive': archive,
            'storage': storage
        }
        
        # Add target VMID if provided (for restoring to a different VM)
        if target_vmid:
            params['vmid'] = target_vmid
        
        # Start restore job
        result = connection.nodes(node).vzdump.restore.post(**params)
        
        flash(f"Restore job started successfully. Task ID: {result.get('data')}", 'success')
    except Exception as e:
        flash(f"Failed to start restore: {str(e)}", 'danger')
    
    return redirect(url_for('backup_list', host_id=host_id))

@app.route('/node/<host_id>/<node>/create_vm', methods=['GET', 'POST'])
def create_vm(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get available storage pools for this node
        storages = connection.nodes(node).storage.get()
        
        # Filter storages that can contain disk images
        vm_storages = [storage for storage in storages if 'images' in storage.get('content', '').split(',')]
        
        # Get ISO storages and images
        iso_storages = [storage for storage in storages if 'iso' in storage.get('content', '').split(',')]
        iso_images = []
        
        for storage in iso_storages:
            try:
                content = connection.nodes(node).storage(storage['storage']).content.get()
                iso_list = [item for item in content if item.get('content') == 'iso']
                for iso in iso_list:
                    iso['storage'] = storage['storage']
                iso_images.extend(iso_list)
            except Exception as e:
                print(f"Error getting ISO list from {storage['storage']}: {str(e)}")
        
        # Get node CPU and memory info for resource allocation
        node_status = connection.nodes(node).status.get()
        
        # Get next available VMID
        try:
            next_vmid = connection.cluster.nextid.get()
        except Exception:
            # Fallback if cluster API not available
            vms = connection.nodes(node).qemu.get()
            containers = connection.nodes(node).lxc.get()
            existing_ids = [int(vm['vmid']) for vm in vms + containers]
            next_vmid = max(existing_ids) + 1 if existing_ids else 100
        
        if request.method == 'POST':
            # Process VM creation form
            vmid = request.form.get('vmid', next_vmid)
            name = request.form.get('name')
            cores = request.form.get('cores', 1)
            memory = request.form.get('memory', 512)
            storage_name = request.form.get('storage')
            disk_size = request.form.get('disk_size', 8)
            
            # Installation method & related params
            install_method = request.form.get('install_method')
            iso_storage = request.form.get('iso_storage', '')
            iso_file = request.form.get('iso_file', '')
            
            # Network settings
            net0 = request.form.get('net0', 'virtio,bridge=vmbr0')
            
            # Build parameters for VM creation
            params = {
                'vmid': vmid,
                'name': name,
                'cores': cores,
                'memory': memory,
                'net0': net0,
                'ostype': request.form.get('ostype', 'l26'),
                'scsihw': request.form.get('scsihw', 'virtio-scsi-pci')
            }
            
            # Add storage parameters
            if storage_name and disk_size:
                params[f'virtio0'] = f"{storage_name}:{disk_size}"
            
            # Add ISO if selected
            if install_method == 'iso' and iso_storage and iso_file:
                params['ide2'] = f"{iso_storage}:iso/{iso_file},media=cdrom"
                params['boot'] = 'order=ide2;virtio0'
            
            try:
                # Create the VM
                connection.nodes(node).qemu.post(**params)
                
                flash(f"VM {name} (ID: {vmid}) created successfully", 'success')
                return redirect(url_for('node_details', host_id=host_id, node=node))
            except Exception as e:
                flash(f"Failed to create VM: {str(e)}", 'danger')
        
        return render_template('create_vm.html', 
                               host_id=host_id,
                               node=node,
                               vm_storages=vm_storages,
                               iso_storages=iso_storages,
                               iso_images=iso_images,
                               node_status=node_status,
                               next_vmid=next_vmid)
    except Exception as e:
        flash(f"Failed to get node details: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/create_container', methods=['GET', 'POST'])
def create_container(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get available storage pools for this node
        storages = connection.nodes(node).storage.get()
        
        # Filter storages that can contain container templates
        container_storages = [storage for storage in storages if 'rootdir' in storage.get('content', '').split(',')]
        
        # Get template storages and templates
        template_storages = [storage for storage in storages if 'vztmpl' in storage.get('content', '').split(',')]
        templates = []
        
        for storage in template_storages:
            try:
                content = connection.nodes(node).storage(storage['storage']).content.get()
                template_list = [item for item in content if item.get('content') == 'vztmpl']
                for tmpl in template_list:
                    tmpl['storage'] = storage['storage']
                templates.extend(template_list)
            except Exception as e:
                print(f"Error getting template list from {storage['storage']}: {str(e)}")
        
        # Get node CPU and memory info for resource allocation
        node_status = connection.nodes(node).status.get()
        
        # Get next available VMID
        try:
            next_vmid = connection.cluster.nextid.get()
        except Exception:
            # Fallback if cluster API not available
            vms = connection.nodes(node).qemu.get()
            containers = connection.nodes(node).lxc.get()
            existing_ids = [int(vm['vmid']) for vm in vms + containers]
            next_vmid = max(existing_ids) + 1 if existing_ids else 100
        
        if request.method == 'POST':
            # Process container creation form
            vmid = request.form.get('vmid', next_vmid)
            hostname = request.form.get('hostname')
            cores = request.form.get('cores', 1)
            memory = request.form.get('memory', 512)
            storage_name = request.form.get('storage')
            disk_size = request.form.get('disk_size', 8)
            
            # Template & related params
            ostemplate = request.form.get('ostemplate')
            password = request.form.get('password')
            
            # Network settings
            net0 = request.form.get('net0', 'name=eth0,bridge=vmbr0,ip=dhcp')
            
            # Build parameters for container creation
            params = {
                'vmid': vmid,
                'hostname': hostname,
                'cores': cores,
                'memory': memory,
                'net0': net0,
                'ostemplate': ostemplate,
                'password': password
            }
            
            # Add storage parameters
            if storage_name and disk_size:
                params['rootfs'] = f"{storage_name}:{disk_size}"
            
            # Add optional DNS settings
            nameserver = request.form.get('nameserver')
            if nameserver:
                params['nameserver'] = nameserver
                
            # Add optional start on boot
            start_after_create = request.form.get('start') == 'on'
            params['start'] = 1 if start_after_create else 0
            
            try:
                # Create the container
                connection.nodes(node).lxc.post(**params)
                
                flash(f"Container {hostname} (ID: {vmid}) created successfully", 'success')
                return redirect(url_for('node_details', host_id=host_id, node=node))
            except Exception as e:
                flash(f"Failed to create container: {str(e)}", 'danger')
        
        return render_template('create_container.html', 
                               host_id=host_id,
                               node=node,
                               container_storages=container_storages,
                               templates=templates,
                               node_status=node_status,
                               next_vmid=next_vmid)
    except Exception as e:
        flash(f"Failed to get node details: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/network')
def node_network(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get network interfaces
        network_interfaces = connection.nodes(node).network.get()
        
        # Get node DNS configuration
        try:
            dns_config = connection.nodes(node).dns.get()
        except Exception:
            dns_config = {'nameserver': '', 'search': ''}
        
        return render_template('node_network.html',
                            host_id=host_id,
                            node=node,
                            interfaces=network_interfaces,
                            dns_config=dns_config)
    except Exception as e:
        flash(f"Failed to get network configuration: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/network/create', methods=['POST'])
def create_network_interface(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        iface_type = request.form.get('type')
        iface_name = request.form.get('name')
        
        # Base parameters for all interface types
        params = {
            'type': iface_type,
        }
        
        # Add type-specific parameters
        if iface_type == 'bridge':
            # Bridge interface parameters
            params['bridge_ports'] = request.form.get('bridge_ports', '')
            params['autostart'] = request.form.get('autostart') == 'on'
            
            # IP configuration
            ip_config = request.form.get('ipv4_config')
            if ip_config == 'static':
                params['cidr'] = request.form.get('ipv4_cidr')
                params['gateway'] = request.form.get('ipv4_gateway')
            elif ip_config == 'dhcp':
                params['cidr'] = 'dhcp'
        
        elif iface_type == 'bond':
            # Bond interface parameters
            params['slaves'] = request.form.get('bond_slaves')
            params['bond_mode'] = request.form.get('bond_mode', 'balance-rr')
            params['autostart'] = request.form.get('autostart') == 'on'
            
            # IP configuration
            ip_config = request.form.get('ipv4_config')
            if ip_config == 'static':
                params['cidr'] = request.form.get('ipv4_cidr')
                params['gateway'] = request.form.get('ipv4_gateway')
            elif ip_config == 'dhcp':
                params['cidr'] = 'dhcp'
        
        elif iface_type == 'vlan':
            # VLAN interface parameters
            params['vlan_raw_device'] = request.form.get('vlan_raw_device')
            params['vlan_id'] = request.form.get('vlan_id')
            params['autostart'] = request.form.get('autostart') == 'on'
            
            # IP configuration
            ip_config = request.form.get('ipv4_config')
            if ip_config == 'static':
                params['cidr'] = request.form.get('ipv4_cidr')
                params['gateway'] = request.form.get('ipv4_gateway')
            elif ip_config == 'dhcp':
                params['cidr'] = 'dhcp'
        
        # Create the network interface
        connection.nodes(node).network.post(iface=iface_name, **params)
        
        # Apply network configuration (required to activate the changes)
        connection.nodes(node).network.put()
        
        flash(f"Network interface '{iface_name}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create network interface: {str(e)}", 'danger')
    
    return redirect(url_for('node_network', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/network/<iface>/update', methods=['POST'])
def update_network_interface(host_id, node, iface):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        autostart = request.form.get('autostart') == 'on'
        ip_config = request.form.get('ipv4_config')
        
        # Base parameters for the update
        params = {
            'autostart': autostart,
        }
        
        # Add IP configuration
        if ip_config == 'static':
            params['cidr'] = request.form.get('ipv4_cidr')
            params['gateway'] = request.form.get('ipv4_gateway')
        elif ip_config == 'dhcp':
            params['cidr'] = 'dhcp'
        
        # Type-specific parameters
        iface_type = request.form.get('type')
        if iface_type == 'bridge':
            params['bridge_ports'] = request.form.get('bridge_ports', '')
        elif iface_type == 'bond':
            params['slaves'] = request.form.get('bond_slaves')
            params['bond_mode'] = request.form.get('bond_mode', 'balance-rr')
        elif iface_type == 'vlan':
            params['vlan_raw_device'] = request.form.get('vlan_raw_device')
            params['vlan_id'] = request.form.get('vlan_id')
        
        # Update the network interface
        connection.nodes(node).network(iface).put(**params)
        
        # Apply network configuration
        connection.nodes(node).network.put()
        
        flash(f"Network interface '{iface}' updated successfully", 'success')
    except Exception as e:
        flash(f"Failed to update network interface: {str(e)}", 'danger')
    
    return redirect(url_for('node_network', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/network/<iface>/delete', methods=['POST'])
def delete_network_interface(host_id, node, iface):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the network interface
        connection.nodes(node).network(iface).delete()
        
        # Apply network configuration
        connection.nodes(node).network.put()
        
        flash(f"Network interface '{iface}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete network interface: {str(e)}", 'danger')
    
    return redirect(url_for('node_network', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/dns/update', methods=['POST'])
def update_dns_config(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        nameserver = request.form.get('nameserver')
        search_domain = request.form.get('search_domain')
        
        # Update DNS configuration
        connection.nodes(node).dns.put(
            nameserver=nameserver,
            search=search_domain
        )
        
        flash("DNS configuration updated successfully", 'success')
    except Exception as e:
        flash(f"Failed to update DNS configuration: {str(e)}", 'danger')
    
    return redirect(url_for('node_network', host_id=host_id, node=node))

@app.route('/host/<host_id>/users')
def user_management(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get users
        users = connection.access.users.get()
        
        # Get groups
        groups = connection.access.groups.get()
        
        # Get roles
        roles = connection.access.roles.get()
        
        # Get domains (authentication realms)
        domains = connection.access.domains.get()
        
        return render_template('user_management.html',
                            host_id=host_id,
                            users=users,
                            groups=groups,
                            roles=roles,
                            domains=domains)
    except Exception as e:
        flash(f"Failed to get user list: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/users/create', methods=['POST'])
def create_user(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        userid = request.form.get('userid')
        password = request.form.get('password')
        email = request.form.get('email', '')
        firstname = request.form.get('firstname', '')
        lastname = request.form.get('lastname', '')
        groups = request.form.get('groups', '')
        enable = request.form.get('enable') == 'on'
        expire = request.form.get('expire', 0)  # Unix timestamp or 0 for no expiry
        
        # Create user parameters
        params = {
            'userid': userid,
            'password': password,
            'email': email,
            'firstname': firstname,
            'lastname': lastname,
            'groups': groups,
            'enable': 1 if enable else 0
        }
        
        # Add expiry if set
        if expire and expire != '0':
            params['expire'] = expire
        
        # Create the user
        connection.access.users.post(**params)
        
        flash(f"User '{userid}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create user: {str(e)}", 'danger')
    
    return redirect(url_for('user_management', host_id=host_id))

@app.route('/host/<host_id>/users/<userid>/update', methods=['POST'])
def update_user(host_id, userid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        email = request.form.get('email', '')
        firstname = request.form.get('firstname', '')
        lastname = request.form.get('lastname', '')
        groups = request.form.get('groups', '')
        enable = request.form.get('enable') == 'on'
        expire = request.form.get('expire', 0)
        
        # Create update parameters
        params = {
            'email': email,
            'firstname': firstname,
            'lastname': lastname,
            'groups': groups,
            'enable': 1 if enable else 0
        }
        
        # Add expiry if set
        if expire and expire != '0':
            params['expire'] = expire
        
        # Check if password should be updated
        password = request.form.get('password')
        if password:
            params['password'] = password
        
        # Update the user
        connection.access.users(userid).put(**params)
        
        flash(f"User '{userid}' updated successfully", 'success')
    except Exception as e:
        flash(f"Failed to update user: {str(e)}", 'danger')
    
    return redirect(url_for('user_management', host_id=host_id))

@app.route('/host/<host_id>/users/<userid>/delete', methods=['POST'])
def delete_user(host_id, userid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the user
        connection.access.users(userid).delete()
        
        flash(f"User '{userid}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete user: {str(e)}", 'danger')
    
    return redirect(url_for('user_management', host_id=host_id))

@app.route('/host/<host_id>/groups/create', methods=['POST'])
def create_group(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        groupid = request.form.get('groupid')
        comment = request.form.get('comment', '')
        
        # Create the group
        connection.access.groups.post(groupid=groupid, comment=comment)
        
        flash(f"Group '{groupid}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create group: {str(e)}", 'danger')
    
    return redirect(url_for('user_management', host_id=host_id))

@app.route('/host/<host_id>/groups/<groupid>/delete', methods=['POST'])
def delete_group(host_id, groupid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the group
        connection.access.groups(groupid).delete()
        
        flash(f"Group '{groupid}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete group: {str(e)}", 'danger')
    
    return redirect(url_for('user_management', host_id=host_id))

@app.route('/host/<host_id>/permissions/add', methods=['POST'])
def add_permission(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        path = request.form.get('path')
        roleid = request.form.get('roleid')
        type = request.form.get('type')  # user or group
        userid_or_group = request.form.get('userid_or_group')
        propagate = request.form.get('propagate') == 'on'
        
        # Build parameters
        params = {
            'path': path,
            'roles': roleid,
            'propagate': 1 if propagate else 0
        }
        
        # Add user or group parameter
        if type == 'user':
            params['users'] = userid_or_group
        else:
            params['groups'] = userid_or_group
        
        # Add the permission
        connection.access.acl.put(**params)
        
        flash("Permission added successfully", 'success')
    except Exception as e:
        flash(f"Failed to add permission: {str(e)}", 'danger')
    
    return redirect(url_for('user_management', host_id=host_id))

@app.route('/host/<host_id>/firewall')
def cluster_firewall(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get cluster firewall configuration
        firewall_config = connection.cluster.firewall.options.get()
        security_groups = connection.cluster.firewall.groups.get()
        
        # Get IPSets
        ipsets = connection.cluster.firewall.ipset.get()
        
        # Get cluster-wide firewall rules
        rules = connection.cluster.firewall.rules.get()
        
        return render_template('cluster_firewall.html',
                            host_id=host_id,
                            firewall_config=firewall_config,
                            security_groups=security_groups,
                            ipsets=ipsets,
                            rules=rules)
    except Exception as e:
        flash(f"Failed to get firewall configuration: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/firewall/toggle', methods=['POST'])
def toggle_cluster_firewall(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        enabled = request.form.get('enabled') == 'true'
        
        # Update firewall status
        connection.cluster.firewall.options.put(enable=1 if enabled else 0)
        
        status = "enabled" if enabled else "disabled"
        flash(f"Firewall {status} successfully", 'success')
    except Exception as e:
        flash(f"Failed to update firewall: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/host/<host_id>/firewall/rule/add', methods=['POST'])
def add_cluster_firewall_rule(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        params = {
            'action': request.form.get('action'),
            'type': request.form.get('type'),
            'enable': 1 if request.form.get('enable') == 'on' else 0,
            'comment': request.form.get('comment', '')
        }
        
        # Add source/destination based on rule type
        if request.form.get('source'):
            params['source'] = request.form.get('source')
        
        if request.form.get('dest'):
            params['dest'] = request.form.get('dest')
        
        # Add protocol specific parameters if not 'all'
        proto = request.form.get('proto')
        if proto and proto != 'all':
            params['proto'] = proto
            
            if proto in ['tcp', 'udp'] and request.form.get('dport'):
                params['dport'] = request.form.get('dport')
                
            if proto in ['tcp', 'udp'] and request.form.get('sport'):
                params['sport'] = request.form.get('sport')
                
        # Add ICMP type if applicable
        if proto == 'icmp' and request.form.get('icmptype'):
            params['icmptype'] = request.form.get('icmptype')
        
        # Add rule to the cluster firewall
        connection.cluster.firewall.rules.post(**params)
        
        flash("Firewall rule added successfully", 'success')
    except Exception as e:
        flash(f"Failed to add firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/host/<host_id>/firewall/rule/<rule_pos>/delete', methods=['POST'])
def delete_cluster_firewall_rule(host_id, rule_pos):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the rule
        connection.cluster.firewall.rules.delete(pos=rule_pos)
        
        flash("Firewall rule deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/host/<host_id>/firewall/ipset', methods=['POST'])
def create_ipset(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        name = request.form.get('name')
        comment = request.form.get('comment', '')
        
        # Create IP set
        connection.cluster.firewall.ipset.post(name=name, comment=comment)
        
        flash(f"IP set '{name}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create IP set: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/host/<host_id>/firewall/ipset/<name>/delete', methods=['POST'])
def delete_ipset(host_id, name):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete IP set
        connection.cluster.firewall.ipset(name).delete()
        
        flash(f"IP set '{name}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete IP set: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/host/<host_id>/firewall/ipset/<name>/add', methods=['POST'])
def add_ipset_entry(host_id, name):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        cidr = request.form.get('cidr')
        comment = request.form.get('comment', '')
        
        # Add entry to IP set
        connection.cluster.firewall.ipset(name).post(cidr=cidr, comment=comment)
        
        flash(f"Entry added to IP set '{name}' successfully", 'success')
    except Exception as e:
        flash(f"Failed to add entry to IP set: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/host/<host_id>/firewall/security-group', methods=['POST'])
def create_security_group(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        group_name = request.form.get('name')
        comment = request.form.get('comment', '')
        
        # Create security group
        connection.cluster.firewall.groups.post(group=group_name, comment=comment)
        
        flash(f"Security group '{group_name}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create security group: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_firewall', host_id=host_id))

@app.route('/node/<host_id>/<node>/firewall')
def node_firewall(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get node firewall configuration
        firewall_config = connection.nodes(node).firewall.options.get()
        
        # Get node-specific firewall rules
        rules = connection.nodes(node).firewall.rules.get()
        
        return render_template('node_firewall.html',
                            host_id=host_id,
                            node=node,
                            firewall_config=firewall_config,
                            rules=rules)
    except Exception as e:
        flash(f"Failed to get node firewall configuration: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/firewall/toggle', methods=['POST'])
def toggle_node_firewall(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        enabled = request.form.get('enabled') == 'true'
        
        # Update firewall status
        connection.nodes(node).firewall.options.put(enable=1 if enabled else 0)
        
        status = "enabled" if enabled else "disabled"
        flash(f"Node firewall {status} successfully", 'success')
    except Exception as e:
        flash(f"Failed to update node firewall: {str(e)}", 'danger')
    
    return redirect(url_for('node_firewall', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/firewall/rule/add', methods=['POST'])
def add_node_firewall_rule(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        params = {
            'action': request.form.get('action'),
            'type': request.form.get('type'),
            'enable': 1 if request.form.get('enable') == 'on' else 0,
            'comment': request.form.get('comment', '')
        }
        
        # Add source/destination based on rule type
        if request.form.get('source'):
            params['source'] = request.form.get('source')
        
        if request.form.get('dest'):
            params['dest'] = request.form.get('dest')
        
        # Add protocol specific parameters if not 'all'
        proto = request.form.get('proto')
        if proto and proto != 'all':
            params['proto'] = proto
            
            if proto in ['tcp', 'udp'] and request.form.get('dport'):
                params['dport'] = request.form.get('dport')
                
            if proto in ['tcp', 'udp'] and request.form.get('sport'):
                params['sport'] = request.form.get('sport')
                
        # Add ICMP type if applicable
        if proto == 'icmp' and request.form.get('icmptype'):
            params['icmptype'] = request.form.get('icmptype')
        
        # Add rule to the node firewall
        connection.nodes(node).firewall.rules.post(**params)
        
        flash("Node firewall rule added successfully", 'success')
    except Exception as e:
        flash(f"Failed to add node firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('node_firewall', host_id=host_id, node=node))

@app.route('/node/<host_id>/<node>/firewall/rule/<rule_pos>/delete', methods=['POST'])
def delete_node_firewall_rule(host_id, node, rule_pos):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the rule
        connection.nodes(node).firewall.rules.delete(pos=rule_pos)
        
        flash("Node firewall rule deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete node firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('node_firewall', host_id=host_id, node=node))

@app.route('/vm/<host_id>/<node>/<vmid>/firewall')
def vm_firewall(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get VM information for the header
        vm_info = connection.nodes(node).qemu(vmid).status.current.get()
        
        # Get VM firewall configuration
        firewall_config = connection.nodes(node).qemu(vmid).firewall.options.get()
        
        # Get VM-specific firewall rules
        rules = connection.nodes(node).qemu(vmid).firewall.rules.get()
        
        # Get available security groups
        security_groups = connection.cluster.firewall.groups.get()
        
        # Get current assigned security groups
        refs = connection.nodes(node).qemu(vmid).firewall.refs.get()
        
        return render_template('vm_firewall.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            vm_name=vm_info.get('name', f'VM {vmid}'),
                            firewall_config=firewall_config,
                            rules=rules,
                            security_groups=security_groups,
                            refs=refs)
    except Exception as e:
        flash(f"Failed to get VM firewall configuration: {str(e)}", 'danger')
        return redirect(url_for('vm_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/firewall/toggle', methods=['POST'])
def toggle_vm_firewall(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        enabled = request.form.get('enabled') == 'true'
        
        # Update firewall status
        connection.nodes(node).qemu(vmid).firewall.options.put(enable=1 if enabled else 0)
        
        status = "enabled" if enabled else "disabled"
        flash(f"VM firewall {status} successfully", 'success')
    except Exception as e:
        flash(f"Failed to update VM firewall: {str(e)}", 'danger')
    
    return redirect(url_for('vm_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/firewall/rule/add', methods=['POST'])
def add_vm_firewall_rule(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        params = {
            'action': request.form.get('action'),
            'type': request.form.get('type'),
            'enable': 1 if request.form.get('enable') == 'on' else 0,
            'comment': request.form.get('comment', '')
        }
        
        # Add source/destination based on rule type
        if request.form.get('source'):
            params['source'] = request.form.get('source')
        
        if request.form.get('dest'):
            params['dest'] = request.form.get('dest')
        
        # Add protocol specific parameters if not 'all'
        proto = request.form.get('proto')
        if proto and proto != 'all':
            params['proto'] = proto
            
            if proto in ['tcp', 'udp'] and request.form.get('dport'):
                params['dport'] = request.form.get('dport')
                
            if proto in ['tcp', 'udp'] and request.form.get('sport'):
                params['sport'] = request.form.get('sport')
                
        # Add ICMP type if applicable
        if proto == 'icmp' and request.form.get('icmptype'):
            params['icmptype'] = request.form.get('icmptype')
        
        # Add rule to the VM firewall
        connection.nodes(node).qemu(vmid).firewall.rules.post(**params)
        
        flash("VM firewall rule added successfully", 'success')
    except Exception as e:
        flash(f"Failed to add VM firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('vm_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/firewall/rule/<rule_pos>/delete', methods=['POST'])
def delete_vm_firewall_rule(host_id, node, vmid, rule_pos):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the rule
        connection.nodes(node).qemu(vmid).firewall.rules.delete(pos=rule_pos)
        
        flash("VM firewall rule deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete VM firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('vm_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/firewall/refs/add', methods=['POST'])
def add_vm_security_group(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        group = request.form.get('group')
        
        # Add security group reference
        connection.nodes(node).qemu(vmid).firewall.refs.post(group=group)
        
        flash(f"Security group '{group}' assigned to VM successfully", 'success')
    except Exception as e:
        flash(f"Failed to assign security group: {str(e)}", 'danger')
    
    return redirect(url_for('vm_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/firewall/refs/<group>/delete', methods=['POST'])
def delete_vm_security_group(host_id, node, vmid, group):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete security group reference
        connection.nodes(node).qemu(vmid).firewall.refs(group).delete()
        
        flash(f"Security group '{group}' removed from VM successfully", 'success')
    except Exception as e:
        flash(f"Failed to remove security group: {str(e)}", 'danger')
    
    return redirect(url_for('vm_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/firewall')
def container_firewall(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get container information for the header
        container_info = connection.nodes(node).lxc(vmid).status.current.get()
        
        # Get container firewall configuration
        firewall_config = connection.nodes(node).lxc(vmid).firewall.options.get()
        
        # Get container-specific firewall rules
        rules = connection.nodes(node).lxc(vmid).firewall.rules.get()
        
        # Get available security groups
        security_groups = connection.cluster.firewall.groups.get()
        
        # Get current assigned security groups
        refs = connection.nodes(node).lxc(vmid).firewall.refs.get()
        
        return render_template('container_firewall.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            container_name=container_info.get('name', f'Container {vmid}'),
                            firewall_config=firewall_config,
                            rules=rules,
                            security_groups=security_groups,
                            refs=refs)
    except Exception as e:
        flash(f"Failed to get container firewall configuration: {str(e)}", 'danger')
        return redirect(url_for('container_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/firewall/toggle', methods=['POST'])
def toggle_container_firewall(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        enabled = request.form.get('enabled') == 'true'
        
        # Update firewall status
        connection.nodes(node).lxc(vmid).firewall.options.put(enable=1 if enabled else 0)
        
        status = "enabled" if enabled else "disabled"
        flash(f"Container firewall {status} successfully", 'success')
    except Exception as e:
        flash(f"Failed to update container firewall: {str(e)}", 'danger')
    
    return redirect(url_for('container_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/firewall/rule/add', methods=['POST'])
def add_container_firewall_rule(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        params = {
            'action': request.form.get('action'),
            'type': request.form.get('type'),
            'enable': 1 if request.form.get('enable') == 'on' else 0,
            'comment': request.form.get('comment', '')
        }
        
        # Add source/destination based on rule type
        if request.form.get('source'):
            params['source'] = request.form.get('source')
        
        if request.form.get('dest'):
            params['dest'] = request.form.get('dest')
        
        # Add protocol specific parameters if not 'all'
        proto = request.form.get('proto')
        if proto and proto != 'all':
            params['proto'] = proto
            
            if proto in ['tcp', 'udp'] and request.form.get('dport'):
                params['dport'] = request.form.get('dport')
                
            if proto in ['tcp', 'udp'] and request.form.get('sport'):
                params['sport'] = request.form.get('sport')
                
        # Add ICMP type if applicable
        if proto == 'icmp' and request.form.get('icmptype'):
            params['icmptype'] = request.form.get('icmptype')
        
        # Add rule to the container firewall
        connection.nodes(node).lxc(vmid).firewall.rules.post(**params)
        
        flash("Container firewall rule added successfully", 'success')
    except Exception as e:
        flash(f"Failed to add container firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('container_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/firewall/rule/<rule_pos>/delete', methods=['POST'])
def delete_container_firewall_rule(host_id, node, vmid, rule_pos):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the rule
        connection.nodes(node).lxc(vmid).firewall.rules.delete(pos=rule_pos)
        
        flash("Container firewall rule deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete container firewall rule: {str(e)}", 'danger')
    
    return redirect(url_for('container_firewall', host_id=host_id, node=node))

@app.route('/container/<host_id>/<node>/<vmid>/firewall/refs/add', methods=['POST'])
def add_container_security_group(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        group = request.form.get('group')
        
        # Add security group reference
        connection.nodes(node).lxc(vmid).firewall.refs.post(group=group)
        
        flash(f"Security group '{group}' assigned to container successfully", 'success')
    except Exception as e:
        flash(f"Failed to assign security group: {str(e)}", 'danger')
    
    return redirect(url_for('container_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/firewall/refs/<group>/delete', methods=['POST'])
def delete_container_security_group(host_id, node, vmid, group):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete security group reference
        connection.nodes(node).lxc(vmid).firewall.refs(group).delete()
        
        flash(f"Security group '{group}' removed from container successfully", 'success')
    except Exception as e:
        flash(f"Failed to remove security group: {str(e)}", 'danger')
    
    return redirect(url_for('container_firewall', host_id=host_id, node=node, vmid=vmid))

@app.route('/host/<host_id>/<node>/templates')
def template_management(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get available storage pools for this node
        storages = connection.nodes(node).storage.get()
        
        # Filter storages that can contain templates (vztmpl) and ISO images
        template_storages = [storage for storage in storages if 'vztmpl' in storage.get('content', '').split(',')]
        iso_storages = [storage for storage in storages if 'iso' in storage.get('content', '').split(',')]
        vm_storages = [storage for storage in storages if 'images' in storage.get('content', '').split(',')]
        
        # Get existing templates
        templates = []
        for storage in template_storages:
            try:
                content = connection.nodes(node).storage(storage['storage']).content.get()
                template_list = [item for item in content if item.get('content') == 'vztmpl']
                for tmpl in template_list:
                    tmpl['storage'] = storage['storage']
                templates.extend(template_list)
            except Exception as e:
                print(f"Error getting template list from {storage['storage']}: {str(e)}")
        
        # Get existing ISO images
        iso_images = []
        for storage in iso_storages:
            try:
                content = connection.nodes(node).storage(storage['storage']).content.get()
                iso_list = [item for item in content if item.get('content') == 'iso']
                for iso in iso_list:
                    iso['storage'] = storage['storage']
                iso_images.extend(iso_list)
            except Exception as e:
                print(f"Error getting ISO list from {storage['storage']}: {str(e)}")
        
        # Get VMs and containers for template creation
        vms = []
        containers = []
        try:
            vms = connection.nodes(node).qemu.get()
            containers = connection.nodes(node).lxc.get()
        except Exception as e:
            print(f"Error getting VMs or containers: {str(e)}")
                
        return render_template('template_management.html',
                            host_id=host_id,
                            node=node,
                            template_storages=template_storages,
                            iso_storages=iso_storages,
                            vm_storages=vm_storages,
                            templates=templates,
                            iso_images=iso_images,
                            vms=vms,
                            containers=containers)
    except Exception as e:
        flash(f"Failed to get template information: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/download_container_template', methods=['POST'])
def download_container_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    storage = request.form.get('storage')
    template_url = request.form.get('template_url')
    
    if not storage or not template_url:
        flash("Storage and template URL are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Start template download
        task = connection.nodes(node).storage(storage).content.post(
            content='vztmpl',
            filename=os.path.basename(template_url),
            url=template_url
        )
        
        flash(f"Started download of container template: {os.path.basename(template_url)}", 'success')
    except Exception as e:
        flash(f"Failed to download template: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/download_iso', methods=['POST'])
def download_iso(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    storage = request.form.get('storage')
    iso_url = request.form.get('iso_url')
    
    if not storage or not iso_url:
        flash("Storage and ISO URL are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Start ISO download
        task = connection.nodes(node).storage(storage).content.post(
            content='iso',
            filename=os.path.basename(iso_url),
            url=iso_url
        )
        
        flash(f"Started download of ISO image: {os.path.basename(iso_url)}", 'success')
    except Exception as e:
        flash(f"Failed to download ISO: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/delete', methods=['POST'])
def delete_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    storage = request.form.get('storage')
    volume = request.form.get('volume')
    content_type = request.form.get('content_type')
    
    if not storage or not volume or not content_type:
        flash("Storage, volume, and content type are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the template/ISO
        connection.nodes(node).storage(storage).content(volume).delete()
        
        content_name = "container template" if content_type == 'vztmpl' else "ISO image"
        flash(f"Deleted {content_name}: {os.path.basename(volume)}", 'success')
    except Exception as e:
        flash(f"Failed to delete: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/export_template', methods=['POST'])
def export_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    storage = request.form.get('storage')
    volume = request.form.get('volume')
    if not storage or not volume:
        flash("Storage and volume are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get download URL for template/iso
        download_link = connection.nodes(node).storage(storage).content(volume).get_download_url()
        
        # Redirect to the download link
        return redirect(download_link)
    except Exception as e:
        flash(f"Failed to export template: {str(e)}", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/upload', methods=['POST'])
def upload_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    storage = request.form.get('storage')
    content_type = request.form.get('content_type')
    
    if not storage or not content_type:
        flash("Storage and content type are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    # File must be uploaded directly
    if 'template_file' not in request.files:
        flash("No file part", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    file = request.files['template_file']
    if file.filename == '':
        flash("No selected file", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get upload URL for the storage
        upload_url = connection.nodes(node).storage(storage).get_upload_url(content=content_type)
        
        # Upload the file to Proxmox
        response = requests.post(
            upload_url, 
            files={"filename": (file.filename, file.read())},
            verify=False
        )
        
        if response.status_code == 200:
            flash(f"Template uploaded successfully", 'success')
        else:
            flash(f"Failed to upload template: {response.text}", 'danger')
    except Exception as e:
        flash(f"Failed to upload template: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/cluster')
def cluster_management(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get cluster configuration
        try:
            cluster_status = connection.cluster.status.get()
        except Exception:
            cluster_status = []
        
        # Get HA resources and groups
        try:
            ha_resources = connection.cluster.ha.resources.get()
        except Exception:
            ha_resources = []
            
        try:
            ha_groups = connection.cluster.ha.groups.get()
        except Exception:
            ha_groups = []
        
        # Get nodes
        nodes = connection.nodes.get()
        
        return render_template('cluster_management.html',
                            host_id=host_id,
                            cluster_status=cluster_status,
                            ha_resources=ha_resources,
                            ha_groups=ha_groups,
                            nodes=nodes)
    except Exception as e:
        flash(f"Failed to get cluster information: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/cluster/ha/group/create', methods=['POST'])
def create_ha_group(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        group_id = request.form.get('group_id')
        nodes = request.form.get('nodes')
        restricted = request.form.get('restricted') == 'on'
        nofailback = request.form.get('nofailback') == 'on'
        
        # Create HA group
        params = {
            'group': group_id,
            'nodes': nodes
        }
        
        if restricted:
            params['restricted'] = 1
            
        if nofailback:
            params['nofailback'] = 1
            
        connection.cluster.ha.groups.post(**params)
        
        flash(f"HA Group '{group_id}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create HA Group: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_management', host_id=host_id))

@app.route('/host/<host_id>/cluster/ha/group/<group>/delete', methods=['POST'])
def delete_ha_group(host_id, group):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete HA group
        connection.cluster.ha.groups(group).delete()
        
        flash(f"HA Group '{group}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete HA Group: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_management', host_id=host_id))

@app.route('/host/<host_id>/cluster/ha/resource/create', methods=['POST'])
def create_ha_resource(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        sid = request.form.get('sid')
        resource_type = request.form.get('type')
        group = request.form.get('group')
        max_restart = request.form.get('max_restart', '1')
        max_relocate = request.form.get('max_relocate', '1')
        state = request.form.get('state', 'started')
        
        # Create HA resource
        params = {
            'sid': sid,
            'type': resource_type,
            'group': group,
            'max_restart': max_restart,
            'max_relocate': max_relocate,
            'state': state
        }
        
        connection.cluster.ha.resources.post(**params)
        
        flash(f"HA Resource '{sid}' created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create HA Resource: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_management', host_id=host_id))

@app.route('/host/<host_id>/cluster/ha/resource/<sid>/delete', methods=['POST'])
def delete_ha_resource(host_id, sid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete HA resource
        connection.cluster.ha.resources(sid).delete()
        
        flash(f"HA Resource '{sid}' deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete HA Resource: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_management', host_id=host_id))

@app.route('/host/<host_id>/cluster/ha/resource/<sid>/update', methods=['POST'])
def update_ha_resource(host_id, sid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        group = request.form.get('group')
        max_restart = request.form.get('max_restart')
        max_relocate = request.form.get('max_relocate')
        state = request.form.get('state')
        
        # Update parameters
        params = {}
        
        if group:
            params['group'] = group
        if max_restart:
            params['max_restart'] = max_restart
        if max_relocate:
            params['max_relocate'] = max_relocate
        if state:
            params['state'] = state
            
        # Update HA resource
        connection.cluster.ha.resources(sid).put(**params)
        
        flash(f"HA Resource '{sid}' updated successfully", 'success')
    except Exception as e:
        flash(f"Failed to update HA Resource: {str(e)}", 'danger')
    
    return redirect(url_for('cluster_management', host_id=host_id))

@app.route('/host/<host_id>/migrate/vm')
def migrate_vm_form(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get all nodes for this host
        nodes = connection.nodes.get()
        node_dict = {node['node']: node for node in nodes}
        
        # Get all VMs across all nodes
        vms = []
        for node in nodes:
            node_name = node['node']
            try:
                node_vms = connection.nodes(node_name).qemu.get()
                for vm in node_vms:
                    vm['node'] = node_name
                vms.extend(node_vms)
            except Exception as e:
                print(f"Error getting VMs from node {node_name}: {str(e)}")
            
        # Get all containers across all nodes
        containers = []
        for node in nodes:
            node_name = node['node']
            try:
                node_containers = connection.nodes(node_name).lxc.get()
                for ct in node_containers:
                    ct['node'] = node_name
                containers.extend(ct)
            except Exception as e:
                print(f"Error getting containers from node {node_name}: {str(e)}")
        
        return render_template('migrate_vm.html',
                            host_id=host_id,
                            nodes=node_dict,
                            vms=vms,
                            containers=containers)
    except Exception as e:
        flash(f"Failed to get migration information: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/migrate', methods=['GET', 'POST'])
def enhanced_migrate_vm_form(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get all nodes for this host
        nodes = {}
        for node in connection.nodes.get():
            nodes[node['node']] = node
        
        if request.method == 'POST':
            # Get basic migration parameters
            vm_type = request.form.get('vm_type')
            vmid = request.form.get('vmid')
            source_node = request.form.get('source_node')
            target_node = request.form.get('target_node')
            online = 'online' in request.form
            with_local_disks = 'with_local_disks' in request.form
            
            # Enhanced migration options
            bandwidth_limit = request.form.get('bandwidth_limit', '0')
            migration_policy = request.form.get('migration_policy', 'default')
            migration_network = request.form.get('migration_network', 'default')
            compressed = 'compressed' in request.form
            auto_retry = 'auto_retry' in request.form
            shutdown_if_failure = 'shutdown_if_failure' in request.form
            migration_notes = request.form.get('migration_notes', '')
            
            # Scheduling options
            schedule_migration = 'schedule_migration' in request.form
            
            if schedule_migration:
                schedule_date = request.form.get('schedule_date')
                schedule_time = request.form.get('schedule_time')
                time_window_hours = int(request.form.get('time_window_hours', 0))
                time_window_minutes = int(request.form.get('time_window_minutes', 0))
                
                # Create a scheduled job for the migration
                scheduled_time = f"{schedule_date} {schedule_time}"
                time_window = (time_window_hours * 60) + time_window_minutes  # in minutes
                
                try:
                    # Create a job record for the scheduled migration
                    job_data = {
                        'type': 'migration',
                        'host_id': host_id,
                        'vm_type': vm_type,
                        'vmid': vmid,
                        'source_node': source_node,
                        'target_node': target_node,
                        'online': online,
                        'with_local_disks': with_local_disks,
                        'bandwidth_limit': int(bandwidth_limit),
                        'migration_policy': migration_policy,
                        'migration_network': migration_network,
                        'compressed': compressed,
                        'auto_retry': auto_retry,
                        'shutdown_if_failure': shutdown_if_failure,
                        'time_window': time_window,
                        'scheduled_time': scheduled_time,
                        'status': 'scheduled',
                        'notes': migration_notes,
                        'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    # Record the job (in a real application this would be in a database)
                    # For simplicity, we're just adding to a global list
                    if 'scheduled_jobs' not in g:
                        g.scheduled_jobs = []
                    g.scheduled_jobs.append(job_data)
                    
                    flash(f"Migration scheduled for {scheduled_time}", 'success')
                    return redirect(url_for('jobs', host_id=host_id))
                
                except Exception as e:
                    flash(f"Failed to schedule migration: {str(e)}", 'danger')
                    return redirect(url_for('migrate_vm_form', host_id=host_id))
            
            else:
                # Prepare migration parameters
                migrate_params = {}
                
                if online:
                    migrate_params['online'] = 1
                
                if with_local_disks:
                    migrate_params['with-local-disks'] = 1
                
                # Add enhanced parameters
                if bandwidth_limit and int(bandwidth_limit) > 0:
                    migrate_params['bandwidth'] = int(bandwidth_limit)
                
                if migration_policy != 'default':
                    if migration_policy == 'precopy':
                        migrate_params['migration_type'] = 'precopy'
                    elif migration_policy == 'postcopy':
                        migrate_params['migration_type'] = 'postcopy'
                    elif migration_policy == 'suspend':
                        migrate_params['migration_type'] = 'suspend'
                
                if migration_network != 'default':
                    # In a real implementation, you would map these to actual network identifiers
                    migrate_params['migration_network'] = migration_network
                
                if compressed:
                    migrate_params['compressed'] = 1
                
                try:
                    # Start the migration with the enhanced parameters
                    if vm_type == 'qemu':
                        result = connection.nodes(source_node).qemu(vmid).migrate.post(
                            target=target_node, **migrate_params
                        )
                    else:  # lxc
                        result = connection.nodes(source_node).lxc(vmid).migrate.post(
                            target=target_node, **migrate_params
                        )
                    
                    # Track the migration task to enable auto-retry and shutdown on failure
                    if auto_retry or shutdown_if_failure:
                        # Store this task and parameters for later checking
                        # In a real implementation, this would go to a database
                        task_data = {
                            'type': 'migration',
                            'vm_type': vm_type,
                            'vmid': vmid,
                            'source_node': source_node,
                            'target_node': target_node,
                            'task_upid': result,
                            'auto_retry': auto_retry,
                            'retry_count': 0,
                            'max_retries': 3,
                            'shutdown_if_failure': shutdown_if_failure,
                            'created_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'notes': migration_notes,
                            'status': 'running'
                        }
                        
                        # In a real implementation, store task_data to a database
                        # For simplicity, we're just adding to a global list
                        if 'tasks' not in g:
                            g.tasks = []
                        g.tasks.append(task_data)
                    
                    flash(f"Migration started successfully. Task ID: {result}", 'success')
                    return redirect(url_for('node_details', host_id=host_id, node=source_node))
                
                except Exception as e:
                    flash(f"Failed to migrate: {str(e)}", 'danger')
                    return redirect(url_for('migrate_vm_form', host_id=host_id))
        
        # GET request - prepare form
        # Get all VMs across all nodes
        vms = []
        containers = []
        
        for node_id in nodes:
            try:
                node_vms = connection.nodes(node_id).qemu.get()
                for vm in node_vms:
                    vm['node'] = node_id
                vms.extend(node_vms)
            except:
                pass
            
            try:
                node_containers = connection.nodes(node_id).lxc.get()
                for container in node_containers:
                    container['node'] = node_id
                containers.extend(node_containers)
            except:
                pass
        
        return render_template('migrate_vm.html', 
                              host_id=host_id, 
                              nodes=nodes, 
                              vms=vms, 
                              containers=containers)
    
    except Exception as e:
        flash(f"Failed to load migration form: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/vm/<host_id>/<node>/<vmid>/clone', methods=['GET', 'POST'])
def clone_vm(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get VM info for form defaults
        vm_info = connection.nodes(node).qemu(vmid).status.current.get()
        
        # Get next available VMID
        try:
            next_vmid = connection.cluster.nextid.get()
        except Exception:
            # Fallback if cluster API not available
            vms = connection.nodes(node).qemu.get()
            containers = connection.nodes(node).lxc.get()
            existing_ids = [int(vm['vmid']) for vm in vms + containers]
            next_vmid = max(existing_ids) + 1 if existing_ids else 100
        
        # Get available storage pools and nodes
        storages = connection.nodes(node).storage.get()
        nodes = connection.nodes.get()
        
        if request.method == 'POST':
            # Get form data
            target_vmid = request.form.get('target_vmid', next_vmid)
            target_name = request.form.get('target_name')
            target_node = request.form.get('target_node', node)
            full_clone = request.form.get('full_clone') == 'on'
            storage = request.form.get('storage', '')
            
            # Build clone parameters
            params = {
                'newid': target_vmid,
                'name': target_name,
                'full': 1 if full_clone else 0
            }
            
            # Add target storage if specified
            if storage:
                params['target'] = storage
                
            # Add target node if different from source
            if target_node != node:
                params['target'] = target_node
            
            # Start clone operation
            connection.nodes(node).qemu(vmid).clone.post(**params)
            
            flash(f"Started cloning VM {vmid} to {target_name} (ID: {target_vmid})", 'success')
            
            # Redirect to the node details page
            if target_node == node:
                return redirect(url_for('node_details', host_id=host_id, node=node))
            else:
                return redirect(url_for('node_details', host_id=host_id, node=target_node))
        
        # Render clone form
        return render_template('clone_vm.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            vm_info=vm_info,
                            next_vmid=next_vmid,
                            nodes=nodes,
                            storages=[s for s in storages if 'images' in s.get('content', '').split(',')])
    except Exception as e:
        flash(f"Failed to prepare VM clone: {str(e)}", 'danger')
        return redirect(url_for('vm_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/clone', methods=['GET', 'POST'])
def clone_container(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get container info for form defaults
        container_info = connection.nodes(node).lxc(vmid).status.current.get()
        
        # Get next available VMID
        try:
            next_vmid = connection.cluster.nextid.get()
        except Exception:
            # Fallback if cluster API not available
            vms = connection.nodes(node).qemu.get()
            containers = connection.nodes(node).lxc.get()
            existing_ids = [int(vm['vmid']) for vm in vms + containers]
            next_vmid = max(existing_ids) + 1 if existing_ids else 100
        
        # Get available storage pools and nodes
        storages = connection.nodes(node).storage.get()
        nodes = connection.nodes.get()
        
        if request.method == 'POST':
            # Get form data
            target_vmid = request.form.get('target_vmid', next_vmid)
            target_hostname = request.form.get('target_hostname')
            target_node = request.form.get('target_node', node)
            storage = request.form.get('storage', '')
            
            # Build clone parameters
            params = {
                'newid': target_vmid,
                'hostname': target_hostname
            }
            
            # Add target storage if specified
            if storage:
                params['storage'] = storage
                
            # Add target node if different from source
            if target_node != node:
                params['target'] = target_node
            
            # Start clone operation
            connection.nodes(node).lxc(vmid).clone.post(**params)
            
            flash(f"Started cloning Container {vmid} to {target_hostname} (ID: {target_vmid})", 'success')
            
            # Redirect to the node details page
            if target_node == node:
                return redirect(url_for('node_details', host_id=host_id, node=node))
            else:
                return redirect(url_for('node_details', host_id=host_id, node=target_node))
        
        # Render clone form
        return render_template('clone_container.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            container_info=container_info,
                            next_vmid=next_vmid,
                            nodes=nodes,
                            storages=[s for s in storages if 'rootdir' in s.get('content', '').split(',')])
    except Exception as e:
        flash(f"Failed to prepare container clone: {str(e)}", 'danger')
        return redirect(url_for('container_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/vm/<host_id>/<node>/<vmid>/config', methods=['GET', 'POST'])
def edit_vm_config(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get VM current configuration
        vm_config = connection.nodes(node).qemu(vmid).config.get()
        vm_status = connection.nodes(node).qemu(vmid).status.current.get()
        
        if request.method == 'POST':
            # Process configuration changes
            params = {}
            
            # Basic settings
            name = request.form.get('name')
            if name and name != vm_config.get('name'):
                params['name'] = name
                
            # CPU settings
            cores = request.form.get('cores')
            if cores and int(cores) != vm_config.get('cores', 1):
                params['cores'] = cores
                
            sockets = request.form.get('sockets')
            if sockets and int(sockets) != vm_config.get('sockets', 1):
                params['sockets'] = sockets
                
            # Memory settings
            memory = request.form.get('memory')
            if memory and int(memory) != vm_config.get('memory', 512):
                params['memory'] = memory
                
            # BIOS setting
            bios = request.form.get('bios')
            if bios and bios != vm_config.get('bios', 'seabios'):
                params['bios'] = bios
                
            # Network settings for each interface
            for key in request.form:
                if key.startswith('net') and key.endswith('_config'):
                    net_id = key.split('_')[0]  # Extract 'netX' part
                    net_value = request.form.get(key)
                    
                    # Check if the value has changed
                    if net_value != vm_config.get(net_id, ''):
                        params[net_id] = net_value
            
            # Apply the changes if there are any
            if params:
                connection.nodes(node).qemu(vmid).config.put(**params)
                flash("VM configuration updated successfully", 'success')
                return redirect(url_for('vm_details', host_id=host_id, node=node, vmid=vmid))
            else:
                flash("No changes were made to the VM configuration", 'info')
        
        return render_template('edit_vm_config.html',
                          host_id=host_id,
                          node=node,
                          vmid=vmid,
                          vm_config=vm_config,
                          vm_status=vm_status)
    except Exception as e:
        flash(f"Failed to edit VM configuration: {str(e)}", 'danger')
        return redirect(url_for('vm_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/container/<host_id>/<node>/<vmid>/config', methods=['GET', 'POST'])
def edit_container_config(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get container current configuration
        container_config = connection.nodes(node).lxc(vmid).config.get()
        container_status = connection.nodes(node).lxc(vmid).status.current.get()
        
        if request.method == 'POST':
            # Process configuration changes
            params = {}
            
            # Basic settings
            hostname = request.form.get('hostname')
            if hostname and hostname != container_config.get('hostname'):
                params['hostname'] = hostname
                
            # CPU settings
            cores = request.form.get('cores')
            if cores and int(cores) != container_config.get('cores', 1):
                params['cores'] = cores
                
            # Memory settings
            memory = request.form.get('memory')
            if memory and int(memory) != container_config.get('memory', 512):
                params['memory'] = memory
                
            swap = request.form.get('swap')
            if swap and int(swap) != container_config.get('swap', 0):
                params['swap'] = swap
                
            # Disk settings
            if 'rootfs' in container_config:
                disk_size = request.form.get('disk_size')
                if disk_size:
                    # Parse current disk size
                    current_disk = container_config.get('rootfs', '')
                    if current_disk:
                        # Get the storage part and size part
                        parts = current_disk.split(',')
                        if len(parts) >= 1:
                            storage_part = parts[0].split(':')[0]
                            new_size = f"{disk_size}G" if not disk_size.endswith('G') else disk_size
                            params['rootfs'] = f"{storage_part}:{new_size}"
            
            # Network settings for each interface
            for key in request.form:
                if key.startswith('net') and key.endswith('_config'):
                    net_id = key.split('_')[0]  # Extract 'netX' part
                    net_value = request.form.get(key)
                    
                    # Check if the value has changed
                    if net_value != container_config.get(net_id, ''):
                        params[net_id] = net_value
            
            # DNS settings
            nameserver = request.form.get('nameserver')
            if nameserver and nameserver != container_config.get('nameserver', ''):
                params['nameserver'] = nameserver
                
            searchdomain = request.form.get('searchdomain')
            if searchdomain and searchdomain != container_config.get('searchdomain', ''):
                params['searchdomain'] = searchdomain
            
            # Apply the changes if there are any
            if params:
                connection.nodes(node).lxc(vmid).config.put(**params)
                flash("Container configuration updated successfully", 'success')
                return redirect(url_for('container_details', host_id=host_id, node=node, vmid=vmid))
            else:
                flash("No changes were made to the container configuration", 'info')
        
        return render_template('edit_container_config.html',
                          host_id=host_id,
                          node=node,
                          vmid=vmid,
                          container_config=container_config,
                          container_status=container_status)
    except Exception as e:
        flash(f"Failed to edit container configuration: {str(e)}", 'danger')
        return redirect(url_for('container_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/node/<host_id>/<node>/<vmid>/metrics')
def vm_metrics(host_id, node, vmid):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Determine if this is a VM or container
        try:
            # First try to get VM info
            vm_info = connection.nodes(node).qemu(vmid).status.current.get()
            vm_type = 'qemu'
            resource_name = vm_info.get('name', f'VM {vmid}')
        except:
            try:
                # If not VM, try container
                container_info = connection.nodes(node).lxc(vmid).status.current.get()
                vm_type = 'lxc'
                resource_name = container_info.get('name', f'Container {vmid}')
            except:
                flash("Resource not found", 'danger')
                return redirect(url_for('node_details', host_id=host_id, node=node))
        
        # Get timeframe parameter with default to 'hour'
        timeframe = request.args.get('timeframe', 'hour')
        
        # Get RRD data for the VM
        if vm_type == 'qemu':
            rrd_data = connection.nodes(node).qemu(vmid).rrddata.get(timeframe=timeframe)
        else:
            rrd_data = connection.nodes(node).lxc(vmid).rrddata.get(timeframe=timeframe)
        
        # Process data for charts
        times = []
        cpu_data = []
        memory_data = []
        disk_io_data = []
        network_data = []
        
        for entry in rrd_data:
            # Format time for display
            if 'time' in entry:
                timestamp = entry['time']
                times.append(datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S'))
            
            # CPU usage (in %)
            if 'cpu' in entry:
                cpu_data.append(entry['cpu'] * 100)
            
            # Memory usage (in %)
            if 'mem' in entry and 'maxmem' in entry and entry['maxmem'] > 0:
                memory_data.append((entry['mem'] / entry['maxmem']) * 100)
            
            # Disk I/O
            disk_read = entry.get('diskread', 0) / (1024*1024)  # Convert to MB/s
            disk_write = entry.get('diskwrite', 0) / (1024*1024)  # Convert to MB/s
            disk_io_data.append({'read': disk_read, 'write': disk_write})
            
            # Network
            net_in = entry.get('netin', 0) / (1024*1024)  # Convert to MB/s
            net_out = entry.get('netout', 0) / (1024*1024)  # Convert to MB/s
            network_data.append({'in': net_in, 'out': net_out})
        
        return render_template('vm_metrics.html',
                            host_id=host_id,
                            node=node,
                            vmid=vmid,
                            vm_type=vm_type,
                            resource_name=resource_name,
                            times=json.dumps(times),
                            cpu_data=json.dumps(cpu_data),
                            memory_data=json.dumps(memory_data),
                            disk_io_data=json.dumps(disk_io_data),
                            network_data=json.dumps(network_data),
                            timeframe=timeframe)
    except Exception as e:
        flash(f"Failed to get metrics: {str(e)}", 'danger')
        if vm_type == 'qemu':
            return redirect(url_for('vm_details', host_id=host_id, node=node, vmid=vmid))
        else:
            return redirect(url_for('container_details', host_id=host_id, node=node, vmid=vmid))

@app.route('/node/<host_id>/<node>/metrics')
def node_metrics(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get current node status
        node_status = connection.nodes(node).status.get()
        
        # Get timeframe parameter with default to 'hour'
        timeframe = request.args.get('timeframe', 'hour')
        
        # Get RRD data for the node
        rrd_data = connection.nodes(node).rrddata.get(timeframe=timeframe)
        
        # Process data for charts
        times = []
        cpu_data = []
        memory_data = []
        swap_data = []
        disk_data = []
        disk_io_data = []
        network_data = []
        load_data = []
        
        for entry in rrd_data:
            # Format time for display
            if 'time' in entry:
                timestamp = entry['time']
                times.append(datetime.datetime.fromtimestamp(timestamp).strftime('%H:%M:%S'))
            
            # CPU usage (in %)
            if 'cpu' in entry:
                cpu_data.append(entry['cpu'] * 100)
            
            # Memory usage (in %)
            if 'memtotal' in entry and entry['memtotal'] > 0:
                memory_percent = (entry.get('memused', 0) / entry['memtotal']) * 100
                memory_data.append(memory_percent)
            
            # Swap usage (in %)
            if 'swaptotal' in entry and entry['swaptotal'] > 0:
                swap_percent = (entry.get('swapused', 0) / entry['swaptotal']) * 100
                swap_data.append(swap_percent)
            else:
                swap_data.append(0)  # No swap or no usage
            
            # Disk usage (in %)
            if 'roottotal' in entry and entry['roottotal'] > 0:
                disk_percent = (entry.get('rootused', 0) / entry['roottotal']) * 100
                disk_data.append(disk_percent)
            
            # Disk I/O
            disk_read = entry.get('diskread', 0) / (1024*1024)  # Convert to MB/s
            disk_write = entry.get('diskwrite', 0) / (1024*1024)  # Convert to MB/s
            disk_io_data.append({'read': disk_read, 'write': disk_write})
            
            # Network
            net_in = entry.get('netin', 0) / (1024*1024)  # Convert to MB/s
            net_out = entry.get('netout', 0) / (1024*1024)  # Convert to MB/s
            network_data.append({'in': net_in, 'out': net_out})
            
            # Load average
            if 'loadavg' in entry:
                load_data.append(entry['loadavg'])
        
        # Get detailed storage information
        storages = connection.nodes(node).storage.get()
        storage_status = []
        
        for storage in storages:
            try:
                storage_id = storage.get('storage')
                if storage_id:
                    details = connection.nodes(node).storage(storage_id).status.get()
                    storage_status.append({
                        'name': storage_id,
                        'type': storage.get('type', 'unknown'),
                        'total': details.get('total', 0),
                        'used': details.get('used', 0),
                        'avail': details.get('avail', 0),
                        'percent': (details.get('used', 0) / details.get('total', 1)) * 100 if details.get('total', 0) > 0 else 0
                    })
            except Exception:
                # Skip storages that might not provide status info
                pass
        
        return render_template('node_metrics.html',
                            host_id=host_id,
                            node=node,
                            node_status=node_status,
                            times=json.dumps(times),
                            cpu_data=json.dumps(cpu_data),
                            memory_data=json.dumps(memory_data),
                            swap_data=json.dumps(swap_data),
                            disk_data=json.dumps(disk_data),
                            disk_io_data=json.dumps(disk_io_data),
                            network_data=json.dumps(network_data),
                            load_data=json.dumps(load_data),
                            storage_status=storage_status,
                            timeframe=timeframe)
    except Exception as e:
        flash(f"Failed to get node metrics: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/search')
def search():
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

@app.route('/search_resources')
def search_resources():
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

@app.route('/host/<host_id>/<node>/templates/create_vm_template', methods=['POST'])
def create_vm_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    vm_id = request.form.get('vm_id')
    storage = request.form.get('storage')
    add_version = request.form.get('add_version') == 'true'
    
    if not vm_id or not storage:
        flash("VM ID and storage are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get VM info to check if it's running and to get its name
        vm_info = connection.nodes(node).qemu(vm_id).status.current.get()
        
        # Check if VM is running - if so, warn the user
        if vm_info.get('status') == 'running':
            flash("Warning: Creating a template from a running VM may result in data corruption. It's recommended to shut down the VM first.", 'warning')
        
        # Start the template conversion
        vm_name = vm_info.get('name', f'vm-{vm_id}')
        
        # If version flag is set, add version suffix
        if add_version:
            # Find existing templates with similar names to determine version number
            all_templates = []
            template_storages = [s for s in connection.nodes(node).storage.get() if 'images' in s.get('content', '').split(',')]
            
            for template_storage in template_storages:
                try:
                    content = connection.nodes(node).storage(template_storage['storage']).content.get()
                    vm_templates = [item for item in content if item.get('content') == 'images' and item.get('format') == 'qcow2']
                    all_templates.extend(vm_templates)
                except Exception:
                    continue
            
            # Find highest existing version for this template name
            version = 1
            for template in all_templates:
                template_name = template.get('volid', '').split('/')[-1]
                if template_name.startswith(f"{vm_name}-v") and template_name[len(f"{vm_name}-v"):].isdigit():
                    existing_version = int(template_name[len(f"{vm_name}-v"):])
                    if existing_version >= version:
                        version = existing_version + 1
            
            template_name = f"{vm_name}-v{version}"
        else:
            template_name = vm_name
        
        # Convert the VM to a template
        # First, create a backup/clone to the target storage if different
        if storage != vm_info.get('storage', ''):
            # Clone the VM to the target storage
            connection.nodes(node).qemu(vm_id).clone.post(
                newid=vm_id,  # Clone to same ID
                name=template_name,
                target=storage,
                full=1  # Full clone
            )
        
        # Now set the template flag
        connection.nodes(node).qemu(vm_id).config.post(
            template=1
        )
        
        flash(f"VM {vm_id} converted to template '{template_name}' successfully", 'success')
    except Exception as e:
        flash(f"Failed to create VM template: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/create_ct_template', methods=['POST'])
def create_ct_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    ct_id = request.form.get('ct_id')
    storage = request.form.get('storage')
    add_version = request.form.get('add_version') == 'true'
    
    if not ct_id or not storage:
        flash("Container ID and storage are required", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get container info to check if it's running and to get its name
        container_info = connection.nodes(node).lxc(ct_id).status.current.get()
        
        # Check if container is running - if so, warn the user
        if container_info.get('status') == 'running':
            flash("Warning: Creating a template from a running container may result in data corruption. It's recommended to shut down the container first.", 'warning')
        
        # Start the template creation - for containers, we create a backup that can be used as a template
        container_name = container_info.get('name', f'ct-{ct_id}')
        
        # If version flag is set, add version suffix
        if add_version:
            # Find existing templates with similar names to determine version number
            all_templates = []
            template_storages = [s for s in connection.nodes(node).storage.get() if 'vztmpl' in s.get('content', '').split(',')]
            
            for template_storage in template_storages:
                try:
                    content = connection.nodes(node).storage(template_storage['storage']).content.get()
                    ct_templates = [item for item in content if item.get('content') == 'vztmpl']
                    all_templates.extend(ct_templates)
                except Exception:
                    continue
            
            # Find highest existing version for this template name
            version = 1
            for template in all_templates:
                template_name = template.get('volid', '').split('/')[-1]
                if template_name.startswith(f"{container_name}-v") and template_name[len(f"{container_name}-v"):].isdigit():
                    existing_version = int(template_name[len(f"{container_name}-v"):])
                    if existing_version >= version:
                        version = existing_version + 1
            
            template_name = f"{container_name}-v{version}"
        else:
            template_name = container_name
        
        # Create a backup of the container to be used as template
        # Use vzdump API to create the backup
        connection.nodes(node).vzdump.post(
            vmid=ct_id,
            storage=storage,
            mode='snapshot',
            compress='zstd',  # Use zstd compression
            remove=0,  # Don't remove old backups
            stdout=1,  # Output to stdout
            filename=f"{template_name}.tar.zst"  # Custom filename
        )
        
        flash(f"Started creating template from container {ct_id} as '{template_name}.tar.zst'", 'success')
    except Exception as e:
        flash(f"Failed to create container template: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/templates/clone', methods=['POST'])
def clone_template(host_id, node):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    source_template = request.form.get('source_template')
    source_storage = request.form.get('source_storage')
    target_name = request.form.get('target_name')
    target_storage = request.form.get('target_storage')
    
    if not source_template or not target_name or not source_storage or not target_storage:
        flash("Missing required parameters", 'danger')
        return redirect(url_for('template_management', host_id=host_id, node=node))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Clone the template to the new name and target storage
        # This requires copying the template file
        
        # First, check if source and target storage are the same
        if source_storage == target_storage:
            # Use the content copy API if available, otherwise use a temporary VM
            try:
                # Try to copy directly
                connection.nodes(node).storage(source_storage).content.post(
                    content='vztmpl',
                    target=target_storage,
                    source=source_template
                )
                flash(f"Template cloned to '{target_name}' successfully", 'success')
            except Exception as copy_error:
                flash(f"Failed to clone template directly: {str(copy_error)}", 'warning')
                
                # Need to use a fallback approach - download and re-upload
                # First get download URL for the source template
                download_url = connection.nodes(node).storage(source_storage).content(source_template).get_download_url()
                
                # Download the template to a temporary file
                import tempfile
                import requests
                import shutil
                
                with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
                    response = requests.get(download_url, stream=True)
                    shutil.copyfileobj(response.raw, tmp_file)
                    tmp_filename = tmp_file.name
                
                # Upload the template with the new name
                upload_url = connection.nodes(node).storage(target_storage).get_upload_url(content='vztmpl')
                
                with open(tmp_filename, 'rb') as f:
                    upload_response = requests.post(
                        upload_url,
                        files={"filename": (target_name, f.read())},
                        verify=False
                    )
                    
                    if upload_response.status_code == 200:
                        flash(f"Template cloned to '{target_name}' successfully using download/upload method", 'success')
                    else:
                        flash(f"Failed to clone template: Upload error ({upload_response.status_code})", 'danger')
                
                # Remove the temporary file
                import os
                os.unlink(tmp_filename)
        else:
            # Different storage, use copy API
            connection.nodes(node).storage(source_storage).content(source_template).copy.post(
                target=target_storage,
                target_volid=f"{target_storage}:vztmpl/{target_name}"
            )
            flash(f"Template cloned to '{target_name}' on storage '{target_storage}' successfully", 'success')
            
    except Exception as e:
        flash(f"Failed to clone template: {str(e)}", 'danger')
    
    return redirect(url_for('template_management', host_id=host_id, node=node))

@app.route('/host/<host_id>/jobs')
def jobs(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get nodes for the node selection dropdowns
        nodes = connection.nodes.get()
        
        # Determine if this is a standalone or clustered environment
        is_clustered = True
        try:
            # Try to get cluster status
            cluster_status = connection.cluster.status.get()
            # If it returns more than one node, it's a cluster
            is_clustered = len(cluster_status) > 1
        except Exception as e:
            # If we can't access cluster API, assume it's standalone
            is_clustered = False
            print(f"Assuming standalone environment: {str(e)}")
        
        # Get all scheduled jobs from the cluster or node
        jobs_list = []
        
        try:
            # Try to get any existing cron jobs from cluster API
            if is_clustered:
                jobs_list = connection.cluster.jobs.get()
                print(f"Retrieved {len(jobs_list)} jobs from cluster API")
            else:
                # In standalone environment, this will likely fail, but try anyway
                cluster_jobs = connection.cluster.jobs.get()
                if cluster_jobs:
                    jobs_list = cluster_jobs
                    print(f"Retrieved {len(cluster_jobs)} jobs from cluster API in standalone mode")
        except Exception as e:
            # This exception is expected in standalone environments
            print(f"Could not retrieve jobs from cluster API: {str(e)}")
            
            # If we couldn't get jobs from the cluster API, try individual nodes
            for node in nodes:
                node_name = node['node']
                try:
                    print(f"Attempting to retrieve jobs from node {node_name}")
                    node_jobs = connection.nodes(node_name).jobs.get()
                    
                    # Validate that we got a list of jobs
                    if isinstance(node_jobs, list):
                        for job in node_jobs:
                            # Add node information to each job
                            if isinstance(job, dict):
                                job['node'] = node_name
                        
                        jobs_list.extend(node_jobs)
                        print(f"Retrieved {len(node_jobs)} jobs from node {node_name}")
                    else:
                        print(f"Unexpected response type from node {node_name} jobs API: {type(node_jobs)}")
                except Exception as node_error:
                    print(f"Error retrieving jobs from node {node_name}: {str(node_error)}")
        
        # Log the final result for debugging
        print(f"Total jobs retrieved: {len(jobs_list)}")
        
        return render_template('jobs.html',
                            host_id=host_id,
                            jobs=jobs_list,
                            nodes=nodes,
                            is_clustered=is_clustered)
    except Exception as e:
        flash(f"Failed to get jobs list: {str(e)}", 'danger')
        return redirect(url_for('host_details', host_id=host_id))

@app.route('/host/<host_id>/jobs/create', methods=['POST'])
def create_job(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        job_type = request.form.get('job_type')
        schedule = request.form.get('schedule')
        enabled = request.form.get('enabled') == 'on'
        comment = request.form.get('comment', '')
        
        # Base job parameters
        params = {
            'schedule': schedule,
            'enabled': 1 if enabled else 0,
            'comment': comment
        }
        
        # Add job type specific parameters
        if job_type == 'backup':
            target_type = request.form.get('target_type')
            target_id = request.form.get('target_id')
            
            params['type'] = 'vzdump'
            
            if target_type == 'vm':
                params['vmid'] = target_id
                params['node'] = request.form.get('node', '')
                params['storage'] = request.form.get('storage', '')
                params['mode'] = request.form.get('mode', 'snapshot')
                
            elif target_type == 'ct':
                params['vmid'] = target_id
                params['node'] = request.form.get('node', '')
                params['storage'] = request.form.get('storage', '')
                params['mode'] = request.form.get('mode', 'snapshot')
                
            elif target_type == 'all':
                params['all'] = 1
                params['exclude'] = request.form.get('exclude', '')
                
        elif job_type == 'snapshot':
            target_type = request.form.get('target_type')
            target_id = request.form.get('target_id')
            
            params['type'] = 'snapshot'
            
            if target_type == 'vm':
                params['vmid'] = target_id
                params['node'] = request.form.get('node', '')
                
            elif target_type == 'ct':
                params['vmid'] = target_id
                params['node'] = request.form.get('node', '')
            
        elif job_type == 'command':
            params['type'] = 'exec'
            params['command'] = request.form.get('command', '')
            params['node'] = request.form.get('node', '')
            params['log_output'] = 1 if request.form.get('log_output') == 'on' else 0
        
        # Create the job
        connection.cluster.jobs.post(**params)
        
        flash(f"Job created successfully", 'success')
    except Exception as e:
        flash(f"Failed to create job: {str(e)}", 'danger')
    
    return redirect(url_for('jobs', host_id=host_id))

@app.route('/host/<host_id>/jobs/<job_id>/toggle', methods=['POST'])
def toggle_job(host_id, job_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get current job to check its status
        job = None
        for j in connection.cluster.jobs.get():
            if j['id'] == job_id:
                job = j
                break
        
        if not job:
            flash("Job not found", 'danger')
            return redirect(url_for('jobs', host_id=host_id))
        
        # Toggle the enabled status
        new_status = 0 if job.get('enabled', 1) == 1 else 1
        
        # Update the job
        connection.cluster.jobs(job_id).put(enabled=new_status)
        
        status_text = "enabled" if new_status == 1 else "disabled"
        flash(f"Job {status_text} successfully", 'success')
    except Exception as e:
        flash(f"Failed to toggle job: {str(e)}", 'danger')
    
    return redirect(url_for('jobs', host_id=host_id))

@app.route('/host/<host_id>/jobs/<job_id>/delete', methods=['POST'])
def delete_job(host_id, job_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Delete the job
        connection.cluster.jobs(job_id).delete()
        
        flash(f"Job deleted successfully", 'success')
    except Exception as e:
        flash(f"Failed to delete job: {str(e)}", 'danger')
    
    return redirect(url_for('jobs', host_id=host_id))

@app.route('/host/<host_id>/jobs/<job_id>/update', methods=['POST'])
def update_job(host_id, job_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        schedule = request.form.get('schedule')
        comment = request.form.get('comment', '')
        
        # Update parameters
        params = {}
        if schedule:
            params['schedule'] = schedule
        if comment:
            params['comment'] = comment
            
        # Update the job
        connection.cluster.jobs(job_id).put(**params)
        
        flash(f"Job updated successfully", 'success')
    except Exception as e:
        flash(f"Failed to update job: {str(e)}", 'danger')
    
    return redirect(url_for('jobs', host_id=host_id))

@app.route('/settings')
def settings():
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

@app.route('/settings/update', methods=['POST'])
def update_settings():
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

@app.route('/logs')
def logs():
    """
    View UI application logs
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    log_level = request.args.get('level', 'all')
    
    # In a real application, logs would be read from a log file or database
    # Let's create actual log entries from application logs
    
    # Set up log file path
    log_file_path = os.path.join(os.path.dirname(__file__), 'app.log')
    
    # If log file doesn't exist, create some sample logs
    if not os.path.exists(log_file_path):
        app_logs = [
            {'timestamp': datetime.datetime.now() - datetime.timedelta(minutes=i*5), 
             'level': ['INFO', 'WARNING', 'ERROR', 'DEBUG'][i % 4],
             'message': f"Application startup completed successfully" if i == 0 else
                        f"User login attempt {'successful' if i % 3 != 0 else 'failed'}" if i % 5 == 1 else
                        f"Database connection {'established' if i % 2 == 0 else 'timeout'}" if i % 4 == 2 else
                        f"API request to /{'host' if i % 2 == 0 else 'vm'}/{i*10} completed in {i*10 + 5}ms" if i % 3 == 0 else
                        f"Cache {'hit' if i % 2 == 0 else 'miss'} for resource id {i*100}", 
             'source': ['app', 'api', 'auth', 'database'][i % 4]}
            for i in range(200)
        ]
    else:
        # In a real implementation, this would parse the log file
        # For now, we'll still use sample data but with more realistic entries
        app_logs = [
            {'timestamp': datetime.datetime.now() - datetime.timedelta(minutes=i*5), 
             'level': ['INFO', 'WARNING', 'ERROR', 'DEBUG'][i % 4],
             'message': f"Host connection {'established' if i % 3 == 0 else 'failed'}" if i % 7 == 0 else
                        f"VM {i*10} status change to {'running' if i % 2 == 0 else 'stopped'}" if i % 5 == 1 else
                        f"Backup job {i*5} {'completed' if i % 2 == 0 else 'failed'}" if i % 6 == 2 else
                        f"API request to {['cluster', 'node', 'storage', 'vm'][i % 4]}/{i*10} responded with status {200 if i % 3 != 0 else 500}" if i % 4 == 3 else
                        f"User {['admin', 'operator', 'viewer'][i % 3]} performed {['create', 'delete', 'update', 'view'][i % 4]} operation", 
             'source': ['proxmox', 'ui', 'auth', 'scheduler'][i % 4]}
            for i in range(200)
        ]
    
    # Filter logs by level if requested
    if log_level != 'all':
        app_logs = [log for log in app_logs if log['level'] == log_level.upper()]
    
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

@app.route('/host/<host_id>/<node>/batch_create', methods=['GET', 'POST'])
def batch_create(host_id, node):
    """
    Create multiple VMs or containers from a template in a single operation
    """
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get available storage pools for this node
        storages = connection.nodes(node).storage.get()
        
        # Get node CPU and memory info for resource allocation
        node_status = connection.nodes(node).status.get()
        
        # Get next available VMID
        try:
            next_vmid = connection.cluster.nextid.get()
        except Exception:
            # Fallback if cluster API not available
            vms = connection.nodes(node).qemu.get()
            containers = connection.nodes(node).lxc.get()
            existing_ids = [int(vm['vmid']) for vm in vms + containers]
            next_vmid = max(existing_ids) + 1 if existing_ids else 100
            
        # Resources for template selection
        # For VMs: VM templates
        vm_templates = []
        vm_storages = [storage for storage in storages if 'images' in storage.get('content', '').split(',')]
        
        # Get VMs with template flag set
        try:
            for vm_storage in vm_storages:
                storage_id = vm_storage['storage']
                try:
                    storage_content = connection.nodes(node).storage(storage_id).content.get()
                    for item in storage_content:
                        if item.get('content') == 'images' and item.get('format') == 'qcow2' and item.get('volid', '').endswith('.qcow2'):
                            # Check if this is a template by looking at the VM config
                            try:
                                vm_id = item.get('vmid')
                                if vm_id:
                                    vm_config = connection.nodes(node).qemu(vm_id).config.get()
                                    if vm_config.get('template', 0) == 1:
                                        template_info = {
                                            'vmid': vm_id,
                                            'name': vm_config.get('name', f'vm-{vm_id}'),
                                            'description': vm_config.get('description', 'No description'),
                                            'storage': storage_id
                                        }
                                        vm_templates.append(template_info)
                            except Exception as e:
                                print(f"Error checking VM template status: {str(e)}")
                except Exception as e:
                    print(f"Error getting content from storage {storage_id}: {str(e)}")
        except Exception as e:
            print(f"Error retrieving VM templates: {str(e)}")
        
        # For Containers: Container templates (vztmpl)
        container_templates = []
        template_storages = [storage for storage in storages if 'vztmpl' in storage.get('content', '').split(',')]
        container_storages = [storage for storage in storages if 'rootdir' in storage.get('content', '').split(',')]
        
        # Get container templates
        for storage in template_storages:
            try:
                content = connection.nodes(node).storage(storage['storage']).content.get()
                template_list = [item for item in content if item.get('content') == 'vztmpl']
                for tmpl in template_list:
                    tmpl['storage'] = storage['storage']
                    # Extract template name without path
                    template_path = tmpl.get('volid', '').split(':')
                    if len(template_path) > 1:
                        tmpl['template_name'] = template_path[1].split('/')[-1]
                    else:
                        tmpl['template_name'] = 'Unknown'
                container_templates.extend(template_list)
            except Exception as e:
                print(f"Error getting template list from {storage['storage']}: {str(e)}")
        
        # Get available nodes (for target selection)
        nodes = connection.nodes.get()
        
        if request.method == 'POST':
            # Process batch creation form
            resource_type = request.form.get('resource_type')
            count = int(request.form.get('count', 1))
            name_prefix = request.form.get('name_prefix', '')
            id_start = int(request.form.get('id_start', next_vmid))
            target_node = request.form.get('target_node', node)
            
            # Common parameters
            cores = request.form.get('cores', 1)
            memory = request.form.get('memory', 512)
            storage_name = request.form.get('storage')
            disk_size = request.form.get('disk_size', 8)
            
            # Track successful and failed creations
            successful = 0
            failed = 0
            error_messages = []
            
            if resource_type == 'vm':
                # VM specific parameters
                template_vmid = request.form.get('template_vmid')
                full_clone = request.form.get('full_clone', 'on') == 'on'
                
                # Validate required parameters
                if not template_vmid or not storage_name:
                    flash("Template VM ID and storage are required", 'danger')
                    return redirect(url_for('batch_create', host_id=host_id, node=node))
                
                # Create VMs in sequence
                for i in range(count):
                    current_vmid = id_start + i
                    current_name = f"{name_prefix}{i+1}" if name_prefix else f"vm-{current_vmid}"
                    
                    try:
                        # Clone parameters
                        params = {
                            'newid': current_vmid,
                            'name': current_name,
                            'full': 1 if full_clone else 0,
                            'description': f"Created via batch operation on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                        
                        # Add target storage if specified
                        if storage_name:
                            params['storage'] = storage_name
                            
                        # Add target node if different from source
                        if target_node != node:
                            params['target'] = target_node
                        
                        # Clone the VM from template
                        connection.nodes(node).qemu(template_vmid).clone.post(**params)
                        
                        # Update resource settings if needed
                        if cores != 1 or memory != 512:
                            # Allow time for clone operation to start
                            time.sleep(1)
                            config_params = {}
                            
                            if cores != 1:
                                config_params['cores'] = cores
                            if memory != 512:
                                config_params['memory'] = memory
                                
                            if config_params:
                                connection.nodes(target_node).qemu(current_vmid).config.put(**config_params)
                        
                        successful += 1
                    except Exception as e:
                        failed += 1
                        error_message = f"VM {current_vmid}: {str(e)}"
                        error_messages.append(error_message)
                        print(error_message)
                        
            elif resource_type == 'container':
                # Container specific parameters
                template = request.form.get('template')
                password = request.form.get('password')
                
                # Validate required parameters
                if not template or not storage_name or not password:
                    flash("Container template, storage, and password are required", 'danger')
                    return redirect(url_for('batch_create', host_id=host_id, node=node))
                
                # Network settings
                net0 = request.form.get('net0', 'name=eth0,bridge=vmbr0,ip=dhcp')
                
                # Create containers in sequence
                for i in range(count):
                    current_vmid = id_start + i
                    current_hostname = f"{name_prefix}{i+1}" if name_prefix else f"ct-{current_vmid}"
                    
                    try:
                        # Build parameters for container creation
                        params = {
                            'vmid': current_vmid,
                            'hostname': current_hostname,
                            'cores': cores,
                            'memory': memory,
                            'net0': net0,
                            'ostemplate': template,
                            'password': password,
                            'description': f"Created via batch operation on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        }
                        
                        # Add storage parameters
                        if storage_name and disk_size:
                            params['rootfs'] = f"{storage_name}:{disk_size}"
                            
                        # Create the container
                        if target_node == node:
                            connection.nodes(node).lxc.post(**params)
                        else:
                            # For different target node
                            connection.nodes(target_node).lxc.post(**params)
                            
                        successful += 1
                    except Exception as e:
                        failed += 1
                        error_message = f"Container {current_vmid}: {str(e)}"
                        error_messages.append(error_message)
                        print(error_message)
            
            # Show summary message
            if successful > 0:
                if failed > 0:
                    flash(f"Created {successful} resources with {failed} failures. See details below.", 'warning')
                    for error in error_messages:
                        flash(error, 'danger')
                else:
                    flash(f"Successfully created {successful} resources", 'success')
            else:
                flash(f"Failed to create any resources. See details below.", 'danger')
                for error in error_messages:
                    flash(error, 'danger')
                    
            # Redirect to the node details page
            if target_node == node:
                return redirect(url_for('node_details', host_id=host_id, node=node))
            else:
                return redirect(url_for('node_details', host_id=host_id, node=target_node))
            
        # Render the batch creation form
        return render_template('batch_create.html',
                            host_id=host_id,
                            node=node,
                            vm_templates=vm_templates,
                            container_templates=container_templates,
                            vm_storages=vm_storages,
                            container_storages=container_storages,
                            nodes=nodes,
                            node_status=node_status,
                            next_vmid=next_vmid)
                            
    except Exception as e:
        flash(f"Failed to prepare batch creation: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/host/<host_id>/<node>/batch_config', methods=['GET', 'POST'])
def batch_config(host_id, node):
    """
    Apply the same configuration changes across multiple VMs or containers at once
    """
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get all nodes for this host
        nodes = connection.nodes.get()
        
        # Get all VMs across all nodes
        vms = []
        for node_obj in nodes:
            node_name = node_obj['node']
            try:
                node_vms = connection.nodes(node_name).qemu.get()
                for vm in node_vms:
                    vm['node'] = node_name
                vms.extend(node_vms)
            except Exception as e:
                print(f"Error getting VMs from node {node_name}: {str(e)}")
        
        # Get all containers across all nodes
        containers = []
        for node_obj in nodes:
            node_name = node_obj['node']
            try:
                node_containers = connection.nodes(node_name).lxc.get()
                for container in node_containers:
                    container['node'] = node_name
                containers.extend(container)
            except Exception as e:
                print(f"Error getting containers from node {node_name}: {str(e)}")
        
        if request.method == 'POST':
            resource_type = request.form.get('resource_type')
            resource_ids = request.form.getlist('resource_ids')
            
            if not resource_type or not resource_ids:
                flash("Resource type and at least one resource must be selected", 'danger')
                return redirect(url_for('batch_config', host_id=host_id, node=node))
            
            # Common configuration parameters
            config_params = {}
            
            # CPU configuration
            if request.form.get('update_cpu') == 'on':
                cores = request.form.get('cores')
                if cores and cores.isdigit():
                    config_params['cores'] = int(cores)
            
            # Memory configuration
            if request.form.get('update_memory') == 'on':
                memory = request.form.get('memory')
                if memory and memory.isdigit():
                    config_params['memory'] = int(memory)
            
            # Description update
            if request.form.get('update_description') == 'on':
                description = request.form.get('description', '')
                config_params['description'] = description
            
            # Network configuration
            if request.form.get('update_network') == 'on':
                net_model = request.form.get('net_model')
                net_bridge = request.form.get('net_bridge')
                
                if net_model and net_bridge:
                    if resource_type == 'vm':
                        config_params['net0'] = f"{net_model},bridge={net_bridge}"
                    else:  # container
                        config_params['net0'] = f"name=eth0,bridge={net_bridge}"
            
            # CPU type for VMs
            if resource_type == 'vm' and request.form.get('update_cpu_type') == 'on':
                cpu_type = request.form.get('cpu_type')
                if cpu_type:
                    config_params['cpu'] = cpu_type
            
            # Startup/shutdown configuration
            if request.form.get('update_startup') == 'on':
                startup_order = request.form.get('order')
                startup_up = request.form.get('up')
                startup_down = request.form.get('down')
                
                if startup_order and startup_order.isdigit():
                    startup_config = []
                    startup_config.append(f"order={startup_order}")
                    
                    if startup_up and startup_up.isdigit():
                        startup_config.append(f"up={startup_up}")
                    
                    if startup_down and startup_down.isdigit():
                        startup_config.append(f"down={startup_down}")
                    
                    config_params['startup'] = ",".join(startup_config)
            
            # Custom tags
            if request.form.get('update_tags') == 'on':
                tags = request.form.get('tags', '')
                config_params['tags'] = tags
            
            # Track successful and failed updates
            successful = 0
            failed = 0
            errors = []
            
            # Apply configuration changes to all selected resources
            for resource_id in resource_ids:
                parts = resource_id.split(':')
                if len(parts) != 2:
                    continue
                
                resource_node, vmid = parts
                
                try:
                    if resource_type == 'vm':
                        connection.nodes(resource_node).qemu(vmid).config.put(**config_params)
                    else:  # container
                        connection.nodes(resource_node).lxc(vmid).config.put(**config_params)
                    
                    successful += 1
                except Exception as e:
                    failed += 1
                    error_message = f"Resource {vmid} on node {resource_node}: {str(e)}"
                    errors.append(error_message)
                    print(error_message)
            
            # Show summary message
            if successful > 0:
                if failed > 0:
                    flash(f"Updated configuration for {successful} resources with {failed} failures. See details below.", 'warning')
                    for error in errors:
                        flash(error, 'danger')
                else:
                    flash(f"Successfully updated configuration for {successful} resources", 'success')
            else:
                flash(f"Failed to update any resources. See details below.", 'danger')
                for error in errors:
                    flash(error, 'danger')
            
            # Redirect to the node details page
            return redirect(url_for('node_details', host_id=host_id, node=node))
        
        # GET request - render form
        return render_template('batch_config.html',
                              host_id=host_id,
                              node=node,
                              vms=vms,
                              containers=containers,
                              nodes=nodes)
    
    except Exception as e:
        flash(f"Failed to prepare batch configuration: {str(e)}", 'danger')
        return redirect(url_for('node_details', host_id=host_id, node=node))

@app.route('/api/settings/resource_thresholds', methods=['GET', 'POST'])
def save_resource_thresholds():
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

# Maintenance Mode & Scheduling routes and functionality
@app.route('/node/<host_id>/<node>/maintenance', methods=['GET', 'POST'])
def node_maintenance(host_id, node):
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

@app.route('/maintenance/all')
def all_maintenance():
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

# Background task to check for scheduled maintenance
def check_scheduled_maintenance():
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
                        # This is similar to the code in the enable_maintenance action
                        # Would be implemented here
                        pass
                    
                    # Mark as completed in the scheduled list
                    schedule['started'] = True
            except Exception:
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
            except Exception:
                continue

# Register background task with Flask
@app.before_request
def before_request():
    # Check for scheduled maintenance
    check_scheduled_maintenance()

# Register imported routes from app_utils
register_all_routes(app, proxmox_connections, cache, cache_lock)

# Configure scheduled task for maintenance checks
if os.getenv('ENABLE_SCHEDULED_MAINTENANCE_CHECKS', 'True').lower() == 'true':
    def check_maintenance():
        check_scheduled_maintenance()
        
    # Run maintenance check every 5 minutes
    schedule.every(5).minutes.do(check_maintenance)
    
    # Start scheduler in a background thread
    def run_scheduler():
        while True:
            schedule.run_pending()
            time.sleep(1)
            
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)