#!/bin/bash
sleep 15
# Force remove any leftover container (by name AND by storage)
podman rm -f angelina-app 2>/dev/null
podman container cleanup angelina-app 2>/dev/null
# Use --replace to handle any remaining name conflicts
podman run -d --replace --name angelina-app -p 8080:8080 -v /opt/angelina/data:/app/data:Z -v /opt/angelina/config:/app/config:Z --env-file /opt/angelina/.env --restart=always angelina:latest
echo Boot container started at 08/04/2026 12:42:11 >> /var/log/angelina/boot.log
