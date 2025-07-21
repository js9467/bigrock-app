#!/bin/bash

sudo apt-get update
sudo apt-get install -y python3-pip chromium-browser unclutter hostapd dnsmasq
pip3 install flask

mkdir -p ~/.config/lxsession/LXDE-pi
echo "@chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:5000" > ~/.config/lxsession/LXDE-pi/autostart
echo "@unclutter -idle 0.01 -root" >> ~/.config/lxsession/LXDE-pi/autostart

sudo cp systemd/flask-app.service /etc/systemd/system/
sudo systemctl enable flask-app
sudo systemctl start flask-app

sudo cp wifi/hostapd.conf /etc/hostapd/hostapd.conf
sudo cp wifi/dnsmasq.conf /etc/dnsmasq.conf
sudo sed -i 's/#DAEMON_CONF=/DAEMON_CONF=\/etc\/hostapd\/hostapd.conf/' /etc/default/hostapd
sudo systemctl unmask hostapd
sudo systemctl enable hostapd
sudo systemctl enable dnsmasq

sudo bash -c 'echo -e "interface wlan0\nstatic ip_address=192.168.4.1/24\nnohook wpa_supplicant" >> /etc/dhcpcd.conf'

sudo systemctl enable ssh
sudo systemctl start ssh

chmod +x wifi/wifi_setup.sh

echo "Setup complete! Reboot with 'sudo reboot'."