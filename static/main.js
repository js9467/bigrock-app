new Vue({
  el: '#app',
  data() {
    return {
      allTournaments: {},
      events: [],
      displayedEvents: [],
      participants: [],
      boatImages: {},
      leaderboard: [],
      hookedBoats: [],
      scalesBoats: [],
      galleryImages: [],
      currentImageIndex: 0,
      settings: {
        sounds: { hooked: true, released: true, boated: true },
        followed_boats: [],
        effects_volume: 0.5,
        radio_volume: 0.5,
        tournament: 'Kids',
        data_source: 'current',
        disable_sleep_mode: false
      },
      radioPlaying: false,
      hls: null,
      eventIndex: 0,
      scrollInterval: null,
      slideshowInterval: null,
      error: null,
      showLeaderboard: false,
      isSleepMode: false,
      lastBoatedTime: null,
      showVideoPopup: false,
      showVideo: false,
      videoBoat: '',
      videoETA: '',
      videoUrl: 'https://www.youtube.com/embed/live_stream?channel=UCuJ4Y3Z5Z5Z5Z5Z5Z5Z5Z5Z',
      isHookedUpMinimized: false,
      isScalesMinimized: false,
      wifiConnected: true,
      isLoading: true,
      appMounted: false,
      wifiNetworks: [],
      selectedWifi: null,
      wifiPassword: '',
      connecting: false,
      connectionStatus: ''
    };
  },
  computed: {
    isDemoMode() {
      return this.settings.data_source === 'demo';
    },
    followedBoats() {
      return this.settings.followed_boats || [];
    },
    logoSrc() {
      const t = this.settings?.tournament;
      if (!t || !this.allTournaments || !this.allTournaments[t]) {
        return '/static/images/WHITELOGOBR.png';
      }
      const logo = this.allTournaments[t].logo;
      return logo ? logo : '/static/images/WHITELOGOBR.png';
    },
    enrichedHookedBoats() {
      const active = new Map();
      const resolvedHookups = new Set();
      for (const event of this.events) {
        const action = (event.action || '').toLowerCase();
        const hookupId = event.hookup_id;
        const boat = event.boat;
        const boatKey = boat?.toLowerCase();
        if (action.includes('hooked up')) {
          if (!resolvedHookups.has(hookupId)) {
            active.set(hookupId, {
              ...event,
              image: this.boatImages[boatKey] || '/static/images/placeholder.png'
            });
          }
        } else if (hookupId && ['boated', 'released', 'pulled hook', 'wrong species'].some(k => action.includes(k))) {
          resolvedHookups.add(hookupId);
          active.delete(hookupId);
        }
      }
      return Array.from(active.values());
    },
    activeScalesBoats() {
      return this.events.filter(e => (e.action || '').toLowerCase().includes('headed to scales'));
    }
  },
 
    methods: {
  scanWifi() {
    fetch('/wifi/scan')
      .then(res => res.json())
      .then(data => {
        if (data.networks) {
          this.wifiNetworks = data.networks;
          this.connectionStatus = 📡 Found ${data.networks.length} networks.;
        } else {
          this.connectionStatus = '⚠️ No networks found.';
        }
      })
      .catch(() => {
        this.connectionStatus = '❌ Failed to scan networks.';
      });
  },

  connectToWifi(ssid) {
    if (!ssid) {
      this.connectionStatus = '⚠️ SSID is required.';
      return;
    }

    this.connecting = true;
    this.connectionStatus = 🔌 Connecting to ${ssid}...;

    fetch('/wifi/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ssid: ssid,
        password: this.wifiPassword
      })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          this.connectionStatus = ✅ Connected to ${ssid};
          this.wifiConnected = true;
        } else {
          this.connectionStatus = ❌ Failed: ${data.error || 'Unknown error'};
        }
      })
      .catch(() => {
        this.connectionStatus = ❌ Error connecting to ${ssid};
      })
      .finally(() => {
        this.connecting = false;
      });
  },
        formatTime(timeStr) {
            const date = new Date(timeStr);
            return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
        },
        formatETA(etaStr) {
            try {
                const [hour, minute] = etaStr.split(':');
                const date = new Date();
                date.setHours(parseInt(hour));
                date.setMinutes(parseInt(minute));
                return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
            } catch (e) {
                return etaStr || 'Unknown ETA';
            }
        },
  watch: {
    settings: {
      handler() {
        this.saveSettings();
        localStorage.setItem('radioVolume', this.settings.radio_volume);
        const player = document.getElementById('radio-player');
        if (player && this.radioPlaying) {
          player.volume = this.settings.radio_volume;
        }
      },
      deep: true
    }
  },
  mounted: async function () {
    console.log('Vue instance mounted for:', window.location.pathname);
    window.app = this;

    this.isLoading = true;

    try {
      const res = await fetch("https://js9467.github.io/Brtourney/settings.json");
      const data = await res.json();
      this.allTournaments = data;

      await this.loadSettings();
      this.checkSleepMode();
      this.checkWifiStatus();

      if (localStorage.getItem('radioPlaying') === 'true') {
        this.toggleRadio();
      }

      await this.loadParticipants();
      console.log('✅ Participants loaded');

      await this.loadLeaderboard();
      console.log('✅ Leaderboard loaded');

      if (window.location.pathname !== '/leaderboard') {
        await this.loadEvents();
        await this.loadHookedBoats();
        await this.loadScalesBoats();
        await this.checkVideoTrigger();

        setInterval(() => {
          this.loadEvents();
          this.loadHookedBoats();
          this.loadScalesBoats();
        }, 30000);
      }

    } catch (err) {
      this.error = 'Error in initial data load: ' + err.message;
      console.error('❌ Initialization error:', err);
    } finally {
      this.isLoading = false;
      this.appMounted = true;
    }
  }
});
