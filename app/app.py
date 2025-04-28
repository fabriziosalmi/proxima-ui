from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_bootstrap import Bootstrap
import os
import json
from dotenv import load_dotenv
from proxmoxer import ProxmoxAPI
import pickle
import threading
import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-for-testing')
bootstrap = Bootstrap(app)

# Store Proxmox connections with thread-safe lock
connection_lock = threading.Lock()
proxmox_connections = {}

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
                        # Reconnect to each saved host
                        proxmox = ProxmoxAPI(
                            data['host'], 
                            user=data['user'], 
                            password=data['password'],
                            port=data['port'], 
                            verify_ssl=data['verify_ssl']
                        )
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
    return render_template('index.html', hosts=proxmox_connections, now=now)

@app.route('/add_host', methods=['GET', 'POST'])
def add_host():
    if request.method == 'POST':
        host = request.form.get('hostname')
        user = request.form.get('username')
        password = request.form.get('password')
        port = int(request.form.get('port', 8006))
        verify_ssl = request.form.get('verify_ssl') == 'on'
        
        try:
            # Test connection
            proxmox = ProxmoxAPI(host, user=user, password=password, 
                                 port=port, verify_ssl=verify_ssl)
            version = proxmox.version.get()
            
            # Store connection info
            with connection_lock:
                host_id = f"{host}:{port}"
                proxmox_connections[host_id] = {
                    'host': host,
                    'user': user,
                    'port': port,
                    'verify_ssl': verify_ssl,
                    'password': password,
                    'connection': proxmox
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
    
    return redirect(url_for('container_firewall', host_id=host_id, node=node, vmid=vmid))

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
                
        return render_template('template_management.html',
                            host_id=host_id,
                            node=node,
                            template_storages=template_storages,
                            iso_storages=iso_storages,
                            templates=templates,
                            iso_images=iso_images)
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
                containers.extend(node_containers)
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

@app.route('/host/<host_id>/migrate/vm', methods=['POST'])
def migrate_vm(host_id):
    if host_id not in proxmox_connections:
        flash("Host not found", 'danger')
        return redirect(url_for('index'))
    
    try:
        connection = proxmox_connections[host_id]['connection']
        
        # Get form data
        vm_type = request.form.get('vm_type')
        vmid = request.form.get('vmid')
        source_node = request.form.get('source_node')
        target_node = request.form.get('target_node')
        online = request.form.get('online') == 'on'
        with_local_disks = request.form.get('with_local_disks') == 'on'
        
        # Create migration parameters
        params = {
            'target': target_node
        }
        
        if online:
            params['online'] = 1
            
        if with_local_disks:
            params['with-local-disks'] = 1
        
        # Start migration
        if vm_type == 'qemu':
            connection.nodes(source_node).qemu(vmid).migrate.post(**params)
        elif vm_type == 'lxc':
            connection.nodes(source_node).lxc(vmid).migrate.post(**params)
        
        flash(f"Started migration of {vm_type.upper()} {vmid} to node {target_node}", 'success')
    except Exception as e:
        flash(f"Failed to start migration: {str(e)}", 'danger')
    
    return redirect(url_for('migrate_vm_form', host_id=host_id))

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)