<template>
  <v-container>
    <v-row>
      <v-col cols="12" md="6">
        <v-card outlined>
          <v-card-title>🎛 General Settings</v-card-title>
          <v-card-text>
            <v-switch v-model="settings.sounds.hooked" label="Hooked Up Sound" />
            <v-switch v-model="settings.sounds.released" label="Released Sound" />
            <v-switch v-model="settings.sounds.boated" label="Boated Sound" />
            <v-switch v-model="settings.disable_sleep_mode" label="Disable Sleep Mode" />
            <v-slider v-model="settings.effects_volume" :max="1" :step="0.1" label="Effects Volume" />
            <v-slider v-model="settings.radio_volume" :max="1" :step="0.1" label="Radio Volume" />
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card outlined>
          <v-card-title>📶 Wi-Fi</v-card-title>
          <v-card-text>
            <!-- Connected status -->
            <div v-if="currentNetwork">
              <p>Connected to <strong>{{ currentNetwork }}</strong> {{ signalBars(currentSignal) }}</p>
              <v-btn @click="disconnectWifi">Disconnect</v-btn>
            </div>
            <div v-else>
              <p>Not connected.</p>
            </div>
            <v-btn :loading="connecting" @click="scanWifi">Scan Networks</v-btn>
            <p v-if="connectionStatus">{{ connectionStatus }}</p>

            <!-- Network Dialog -->
            <v-dialog v-model="showWifiModal" max-width="500">
              <v-card>
                <v-card-title>Select Network</v-card-title>
                <v-card-text>
                  <v-list>
                    <v-list-item v-for="net in sortedNetworks" :key="net.ssid">
                      <v-list-item-content>
                        <v-list-item-title>{{ net.ssid }}</v-list-item-title>
                      </v-list-item-content>
                      <v-btn small @click="selectNetwork(net)">Select</v-btn>
                    </v-list-item>
                  </v-list>
                </v-card-text>
              </v-card>
            </v-dialog>

            <!-- Password Dialog with Keyboard -->
            <v-dialog v-model="selectedNetwork" max-width="400">
              <v-card>
                <v-card-title>Enter Password for {{ selectedNetwork?.ssid }}</v-card-title>
                <v-card-text>
                  <v-text-field
                    v-model="selectedNetwork.password"
                    type="password"
                    label="Password"
                    prepend-icon="mdi-lock"
                    @focus.native="$keyboard.show()"
                  />
                </v-card-text>
                <v-card-actions>
                  <v-btn color="primary" @click="connectToWifi(selectedNetwork)">Connect</v-btn>
                  <v-btn @click="selectedNetwork = null">Cancel</v-btn>
                </v-card-actions>
              </v-card>
            </v-dialog>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card outlined>
          <v-card-title>🔊 Bluetooth</v-card-title>
          <v-card-text>
            <v-switch v-model="bluetoothOn" label="Bluetooth On" />
            <div>Status: {{ bluetoothStatus }}</div>
            <v-btn @click="discoverDevices">Discover Devices</v-btn>
            <v-dialog v-model="showModal" max-width="400">
              <v-card>
                <v-card-title>Bluetooth Devices</v-card-title>
                <v-list>
                  <v-list-item v-for="device in devices" :key="device.mac">
                    <v-list-item-content>{{ device.name }} ({{ device.mac }})</v-list-item-content>
                    <v-btn small @click="pairDevice(device.mac)">Pair</v-btn>
                  </v-list-item>
                </v-list>
              </v-card>
            </v-dialog>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  name: 'SettingsPage',
  data() {
    return {
      settings: {
        sounds: { hooked: true, released: true, boated: true },
        effects_volume: 0.5,
        radio_volume: 0.5,
        disable_sleep_mode: false
      },
      currentNetwork: '',
      currentSignal: 0,
      wifiNetworks: [],
      showWifiModal: false,
      selectedNetwork: null,
      connectionStatus: '',
      connecting: false,
      bluetoothOn: false,
      bluetoothStatus: 'Unknown',
      devices: [],
      showModal: false
    };
  },
  computed: {
    sortedNetworks() {
      const seen = new Set();
      return this.wifiNetworks
        .filter(n => {
          if (seen.has(n.ssid)) return false;
          seen.add(n.ssid);
          return true;
        })
        .sort((a, b) => b.signal - a.signal);
    }
  },
  methods: {
    signalBars(strength) {
      const level = Math.min(Math.floor(strength / 25), 4);
      return '📶'.repeat(level) + '⚪'.repeat(4 - level);
    },
    scanWifi() {
      this.connectionStatus = 'Scanning...';
      fetch('/wifi/scan')
        .then(res => res.json())
        .then(data => {
          this.wifiNetworks = data.networks || [];
          this.currentNetwork = data.current || '';
          const current = this.wifiNetworks.find(n => n.ssid === this.currentNetwork);
          this.currentSignal = current ? current.signal : 0;
          this.showWifiModal = true;
        })
        .catch(() => this.connectionStatus = '❌ Scan failed.');
    },
    selectNetwork(net) {
      this.selectedNetwork = { ...net, password: '' };
      this.showWifiModal = false;
    },
    connectToWifi(net) {
      this.connecting = true;
      this.connectionStatus = `Connecting to ${net.ssid}...`;
      fetch('/wifi/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssid: net.ssid, password: net.password || '' })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            this.connectionStatus = `✅ Connected to ${net.ssid}`;
            this.currentNetwork = net.ssid;
          } else {
            this.connectionStatus = `❌ Failed: ${data.error || 'Unknown error'}`;
          }
        })
        .catch(() => this.connectionStatus = `❌ Error connecting to ${net.ssid}`)
        .finally(() => {
          this.connecting = false;
          this.selectedNetwork = null;
        });
    },
    disconnectWifi() {
      fetch('/wifi/disconnect', { method: 'POST' })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            this.connectionStatus = 'Disconnected.';
            this.currentNetwork = '';
          } else {
            this.connectionStatus = '❌ Disconnect failed.';
          }
        });
    },
    discoverDevices() {
      fetch('/bluetooth?action=scan')
        .then(res => res.json())
        .then(data => {
          this.devices = data;
          this.showModal = true;
        })
        .catch(err => console.error(err));
    },
    pairDevice(mac) {
      fetch(`/bluetooth?action=pair&mac=${mac}`)
        .then(res => res.json())
        .then(data => console.log(data))
        .catch(err => console.error(err));
    }
  }
};
</script>

<style scoped>
/* Optional tweaks or layout overrides */
</style>
