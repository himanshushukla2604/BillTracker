#!/usr/bin/env bash
# Sets up Bill Tracker on a fresh Ubuntu VM (Oracle Cloud Always Free), with HTTPS.
# Run it on the VM; run it again later to update to the newest code. Your data is kept.
#
#   curl -fsSL https://raw.githubusercontent.com/himanshushukla2604/BillTracker/main/deploy/oracle-setup.sh | bash
#
# The address defaults to https://<your-ip-with-dashes>.sslip.io (a free name that points at your IP).
# To use your own name instead:  DOMAIN=bills.example.com bash oracle-setup.sh
set -euo pipefail

REPO=https://github.com/himanshushukla2604/BillTracker.git
APP_DIR=/opt/bill-tracker
DATA_DIR=/var/lib/bill-tracker   # the database and its daily backups live here

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

IP=$(curl -4 -fsS https://api.ipify.org)
DOMAIN=${DOMAIN:-${IP//./-}.sslip.io}

# The free AMD VM has 1 GB of memory; building the app needs a little more.
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q /swapfile; then
  say "Adding 2 GB of swap"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

say "Installing Docker and git"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io git >/dev/null
sudo systemctl enable --now docker >/dev/null

# Oracle's Ubuntu images block incoming traffic in the VM's own firewall, as well as in the cloud console.
say "Opening ports 80 and 443 in the VM firewall"
for port in 80 443; do
  sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
    || sudo iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save >/dev/null 2>&1 || true; fi

say "Fetching the newest code"
if [ -d "$APP_DIR/.git" ]; then
  sudo git -C "$APP_DIR" pull -q --ff-only
else
  sudo git clone -q "$REPO" "$APP_DIR"
fi

say "Building the app (a few minutes on the free VM)"
sudo docker build -q -t bill-tracker "$APP_DIR" >/dev/null

say "Starting the app"
sudo mkdir -p "$DATA_DIR"
sudo docker rm -f bill-tracker >/dev/null 2>&1 || true
# Only reachable from this VM; Caddy below is the public door and adds HTTPS.
sudo docker run -d --name bill-tracker --restart unless-stopped \
  -p 127.0.0.1:8080:8080 -v "$DATA_DIR":/data -e FT_REGISTRATION=0 \
  bill-tracker >/dev/null

say "Starting HTTPS for $DOMAIN"
sudo docker rm -f caddy >/dev/null 2>&1 || true
sudo docker run -d --name caddy --restart unless-stopped --network host \
  -v caddy_data:/data caddy:2 \
  caddy reverse-proxy --from "$DOMAIN" --to localhost:8080 >/dev/null

say "Waiting for the app to answer"
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:8080/api/health >/dev/null || { echo "The app did not start. Run: sudo docker logs bill-tracker"; exit 1; }

say "Done. Open https://$DOMAIN on your iPhone in Safari and create your account straight away."
echo "    (The first visit can take up to a minute while the HTTPS certificate is issued.)"
echo "    Sign-ups close after the first account, so nobody else can register."
