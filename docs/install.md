# FreqID Installation & Deployment Guide

This guide describes how to install, configure, and operate FreqID in production environments.

---

## 1. System Requirements

### 1.1 Hardware Specifications

| Component | Minimum (Edge / Small Org) | Recommended (Enterprise / Campus) |
| :--- | :--- | :--- |
| **CPU Architecture** | x86_64 or aarch64 (ARMv8+) | x86_64 with AVX2 support or modern ARM |
| **CPU Cores** | 2 cores | 4+ cores |
| **System Memory (RAM)** | 2 GB available RAM | 4 to 8 GB available RAM |
| **Disk Storage** | 10 GB SSD | 50+ GB NVMe SSD |
| **Network Interface** | 100 Mbps Ethernet | 1 Gbps Ethernet with static IP |

### 1.2 Operating System & Prerequisites
- Linux Kernel 5.4+ (Ubuntu 22.04 LTS, Debian 12, RHEL 9, Alpine 3.19+)
- Docker Engine 24.0+
- Docker Compose v2.20+
- OpenSSL 3.0+ (for key generation and encrypted backups)

---

## 2. Docker Compose Deployment (Recommended)

The recommended production deployment utilizes Docker Compose with automated Caddy reverse proxy orchestration, unprivileged application containers, dropped capabilities, and isolated Docker bridge networks.

### 2.1 Clone Repository & Setup Working Directory
```bash
git clone https://github.com/p19racha/FreqID.git
cd FreqID/deploy
```

### 2.2 Initialize Secrets & Environment
FreqID includes an automated secret provisioning script `deploy/scripts/init.sh` that derives cryptographically secure random keys:
```bash
chmod +x scripts/init.sh scripts/backup.sh scripts/restore.sh
./scripts/init.sh
```
This script automatically:
1. Copies `.env.example` to `.env` if not already present.
2. Generates a 256-bit base64 master encryption key in `secrets/master.key` (mode `0600`).
3. Generates a random database password in `secrets/db_password.txt` (mode `0600`).
4. Generates a random JWT signing secret in `secrets/jwt_secret.txt` (mode `0600`).
5. Sets non-root host UID/GID permissions for container bind-mounts.

### 2.3 Configure Ingress & Domain
Edit `deploy/.env` to configure your public domain name:
```bash
# Set your fully qualified domain name for automated Let's Encrypt / ZeroSSL TLS certificates:
DOMAIN_NAME=freqid.yourdomain.com

# Ingress ports (Standard HTTPS: 443 / HTTP: 80)
FREQID_HTTP_PORT=80
FREQID_HTTPS_PORT=443
```
*Note for local or intranet testing*: If deploying without a public DNS domain, leave `DOMAIN_NAME=:80` and use `http://<server-ip>:8088`.

### 2.4 Acquire Model Checkpoint
Ensure the PartialFace ONNX model is located in `deploy/models/`:
```bash
# Model must be named partialface_ir_18.onnx and placed in deploy/models/
ls -lh deploy/models/partialface_ir_18.onnx
```

### 2.5 Launch the Stack
Execute Docker Compose:
```bash
docker compose up -d
```
Docker Compose orchestrates four services:
- `freqid-postgres`: PostgreSQL 16 database (internal backend network).
- `freqid-migrate`: Alembic migration container applying schema updates to `head`.
- `freqid-server`: Hardened FastAPI backend (unprivileged user, internal network).
- `freqid-admin-ui`: React SPA served via hardened Nginx (unprivileged user, internal network).
- `freqid-proxy`: Caddy 2.8 reverse proxy handling TLS, CSP, and route multiplexing.

### 2.6 Bootstrap Initial Owner Administrator
Passwords are typed interactively and never passed via flags or environment variables:
```bash
docker compose exec server freqid-admin create-owner --username admin
```
Enter a secure password when prompted. The owner account is created immediately and recorded in the audit log.

### 2.7 Verify Stack Health
```bash
curl -i http://localhost:80/healthz
curl -i http://localhost:80/metrics
```
Access the Admin Dashboard at `https://freqid.yourdomain.com` (or `http://localhost:8088`).

---

## 3. Bare-Metal / Manual Python Setup

For environments where container runtimes are prohibited:

### 3.1 Install System Dependencies
```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql postgresql-contrib openssl
```

### 3.2 Setup PostgreSQL Database
```bash
sudo -u postgres psql -c "CREATE USER freqid WITH PASSWORD 'your_strong_password';"
sudo -u postgres psql -c "CREATE DATABASE freqid OWNER freqid;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE freqid TO freqid;"
```

### 3.3 Create System User & Virtual Environment
```bash
sudo useradd -r -s /bin/false -d /opt/freqid freqid
sudo mkdir -p /opt/freqid /etc/freqid /var/log/freqid
sudo chown -R freqid:freqid /opt/freqid /etc/freqid /var/log/freqid

cd /opt/freqid
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip setuptools wheel
pip install ./core ./backend
```

### 3.4 Generate Master Key
```bash
sudo -u freqid openssl rand -base64 32 > /etc/freqid/master.key
sudo chmod 0600 /etc/freqid/master.key
```

### 3.5 Run Alembic Migrations
```bash
export FREQID_SERVER_DATABASE_URL="postgresql+asyncpg://freqid:your_strong_password@127.0.0.1:5432/freqid"
cd backend
alembic upgrade head
```

### 3.6 Create systemd Unit for Backend Service
Create `/etc/systemd/system/freqid-server.service`:
```ini
[Unit]
Description=FreqID Privacy-Preserving Biometric Server
After=network.target postgresql.service

[Service]
Type=simple
User=freqid
Group=freqid
WorkingDirectory=/opt/freqid
Environment="FREQID_SERVER_ENVIRONMENT=production"
Environment="FREQID_SERVER_HOST=127.0.0.1"
Environment="FREQID_SERVER_PORT=8000"
Environment="FREQID_SERVER_DATABASE_URL=postgresql+asyncpg://freqid:your_strong_password@127.0.0.1:5432/freqid"
Environment="FREQID_SERVER_MASTER_KEY_FILE=/etc/freqid/master.key"
Environment="FREQID_SERVER_MODEL_BACKEND=onnx"
Environment="FREQID_SERVER_MODEL_PATH=/opt/freqid/models/partialface_ir_18.onnx"
Environment="FREQID_SERVER_AUDIT_ENABLE_HASH_CHAIN=true"
ExecStart=/opt/freqid/.venv/bin/freqid-server
Restart=always
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/freqid

[Install]
WantedBy=multi-user.target
```
Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now freqid-server
```

---

## 4. Key Management & Disaster Recovery

### 4.1 Master Key Backup
The master key in `deploy/secrets/master.key` encrypts all stored templates. If lost, existing templates **cannot be decrypted or recovered**.
To back up the master key with Shamir's Secret Sharing:
```bash
python scripts/key_recovery.py split deploy/secrets/master.key --shares 5 --threshold 3
```
Distribute the generated shares to 5 independent key custodians.

### 4.2 Automated Encrypted Backups
Configure a cron job to execute `deploy/scripts/backup.sh` nightly:
```bash
0 2 * * * /path/to/FreqID/deploy/scripts/backup.sh >> /var/log/freqid/backup.log 2>&1
```
Backups are encrypted using OpenSSL AES-256-CBC and stored in `deploy/backups/`.
For disaster recovery procedures, refer to [docs/operations-runbook.md](file:///home/racha/FreqID/docs/operations-runbook.md).
