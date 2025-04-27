# Proxmox UI

A simple Flask/Bootstrap web interface to manage Proxmox hosts, virtual machines, and containers.

## Features

- Connect to multiple Proxmox hosts
- View node details and status
- Manage virtual machines (start, stop, shutdown, reset)
- Manage LXC containers (start, stop, shutdown)
- Responsive Bootstrap UI
- Docker-based deployment for easy setup on macOS or any platform
- Persistent storage of host connections

## Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) installed on your system
- Access to one or more Proxmox hosts

## Getting Started

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/proxmox-ui.git
   cd proxmox-ui
   ```

2. Build and start the Docker container:
   ```
   docker-compose up -d
   ```

3. Access the application:
   Open your browser and navigate to [http://localhost:5000](http://localhost:5000)

4. Add a Proxmox host using the UI:
   - Click "Add Host" button
   - Enter your Proxmox host details (hostname/IP, port, username, password)
   - If your Proxmox host uses a self-signed certificate, uncheck "Verify SSL"
   - Click "Connect to Host"

## Security Considerations

This is a simple UI intended for personal use. The following security considerations should be noted:

- Passwords are stored in plain text in the pickle file. In a production environment, a more secure storage solution should be implemented.
- The application doesn't support HTTPS by default. For external access, consider placing it behind a reverse proxy with HTTPS.
- For production use, make sure to change the `SECRET_KEY` environment variable in docker-compose.yml.

## Development

### Project Structure

```
proxmox-ui/
├── app/                    # Flask application
│   ├── app.py              # Main application file
│   ├── static/             # Static assets
│   │   ├── css/            # CSS files
│   │   └── js/             # JavaScript files
│   └── templates/          # HTML templates
├── Dockerfile              # Docker configuration
├── docker-compose.yml      # Docker Compose configuration
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

### Running for Development

For development, you can use the following command to see the logs:

```
docker-compose up
```

Any changes to the Flask application will be automatically reloaded.

## License

MIT

## Acknowledgements

- [Flask](https://flask.palletsprojects.com/) - Python web framework
- [Bootstrap](https://getbootstrap.com/) - Frontend framework
- [Proxmoxer](https://github.com/proxmoxer/proxmoxer) - Python wrapper for Proxmox API