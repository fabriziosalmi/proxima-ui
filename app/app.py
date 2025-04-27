from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_bootstrap import Bootstrap
import os
import json
from dotenv import load_dotenv
from proxmoxer import ProxmoxAPI
import pickle
import threading

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

@app.route('/')
def index():
    return render_template('index.html', hosts=proxmox_connections)

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)