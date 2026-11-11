#!/usr/bin/env bash
# Rebuilds the obs-lab toolchain (Task 1). Run inside the VM as the vagrant user.
set -euo pipefail

echo "== Base packages =="
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git jq tree unzip

echo "== Docker Engine (official repository) =="
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"

echo "== MicroK8s (Kubernetes + kubectl + Helm) =="
sudo snap install microk8s --classic
sudo usermod -aG microk8s "$USER"
mkdir -p ~/.kube
sudo microk8s status --wait-ready
sudo microk8s enable dns hostpath-storage
sudo snap alias microk8s.kubectl kubectl
sudo snap alias microk8s.helm helm
echo "== Time: local timezone, VirtualBox Guest Additions keeps the clock in sync =="
sudo timedatectl set-timezone Asia/Dhaka
sudo timedatectl set-ntp false
echo "Done. Log out and back in so the docker and microk8s groups take effect."
