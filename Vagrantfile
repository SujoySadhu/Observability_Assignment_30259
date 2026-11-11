# -*- mode: ruby -*-
# vi: set ft=ruby :
# Observability lab VM - candidate 30259
Vagrant.configure("2") do |config|
  # 📦 Box: Ubuntu 26.04 LTS (the brief requires 26.04)
  config.vm.box = "bento/ubuntu-26.04"
  config.vm.box_version = "202606.01.0"
  config.vm.box_architecture = "amd64"
  config.vm.box_check_update = false

  # 📛 Hostname
  config.vm.hostname = "obs-lab"

  # ⏳ Slower boot under Hyper-V, so allow more time
  config.vm.boot_timeout = 600

  # 🌐 Host-only network: reachable from Windows only, never from your LAN
  config.vm.network "private_network", ip: "192.168.56.20"

  # 📁 Shared folder: used only to copy files in and evidence out
  config.vm.synced_folder ".", "/vagrant"

  # ⚙️ VM size
  config.vm.provider "virtualbox" do |vb|
    vb.name   = "obs-lab-30259"
    vb.memory = 6144
    vb.cpus   = 4
    vb.gui    = false
        # Clock fix: copy the time from Windows whenever the VM is >1s off (VirtualBox on Hyper-V drifts)
    vb.customize ["guestproperty", "set", :id, "/VirtualBox/GuestAdd/VBoxService/--timesync-set-threshold", "1000"]
    vb.customize ["guestproperty", "set", :id, "/VirtualBox/GuestAdd/VBoxService/--timesync-interval", "10000"]
  end
end
