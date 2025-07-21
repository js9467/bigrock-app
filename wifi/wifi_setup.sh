#!/bin/bash

SSID="$1"
PASSWORD="$2"

# Stop access point
sudo systemctl stop hostapd
sudo systemctl stop dnsmasq

# Configure wpa_supplicant
sudo bash -c "wpa_passphrase \"$SSID\" \"$PASSWORD\" > /etc/wpa_supplicant/wpa_supplicant.conf"
sudo wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf

# Request DHCP
sudo dhclient wlan0

# Restart Flask to disable AP mode
sudo systemctl restart flask-app