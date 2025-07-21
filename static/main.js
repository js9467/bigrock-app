
new Vue({
  el: '#app',
  data: {
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
      tournament: 'Big Rock',
      data_source: 'current',
      disable_sleep_mode: false
    },
    allTournaments: {},
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
    videoUrl: 'https://www.youtube.com/embed/live_stream?channel=UCuJ4Y3Z5Z5Q3--y1ayc6Evw',
    isHookedUpMinimized: false,
    isScalesMinimized: false
  },
  computed: {
    logoSrc() {
      const t = this.settings && this.settings.tournament;
      const tournament = this.allTournaments && this.allTournaments[t];
      return tournament && tournament.logo ? tournament.logo : '';
    },
    themeClass() {
      return 'theme-' + (this.settings.tournament || 'default').toLowerCase().replace(/\s+/g, '-');
    }
  },
  methods: {
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
async loadEvents() {
    if (this.isSleepMode) return;
    try {
        this.error = null;
        const response = await fetch('/events');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        this.events = await response.json() || [];

        // Use reversed copy for display
        this.displayedEvents = [...this.events].reverse();

        if (this.settings.data_source === 'historical') {
            this.startHistoricalScroll();
        } else {
            this.stopHistoricalScroll();

            const latestBoated = this.events
                .filter(e => e.action.toLowerCase() === 'boated')
                .slice(-1)[0];
            if (latestBoated) {
                this.lastBoatedTime = new Date(latestBoated.time);
            }
        }
    } catch (err) {
        this.error = 'Error loading events: ' + err.message;
        console.error('⚠️ Error loading events:', err);
    }
},

        async loadParticipants() {
    try {
        this.error = null;
        const response = await fetch('/api/participants');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        this.participants = await response.json() || [];

        // ✅ Use 'boat' instead of missing 'name'
        this.boatImages = this.participants.reduce((acc, participant) => {
            acc[participant.boat] = participant.image;
            return acc;
        }, {});

        console.log('✅ Participants loaded:', this.participants.map(p => p.boat));
    } catch (e) {
        this.error = 'Failed to load participants: ' + e.message;
        console.error('Error loading participants:', e);
        this.participants = [];
        this.boatImages = typeof known_boat_images !== 'undefined' ? known_boat_images : {};
    }
},

        async loadLeaderboard() {
            try {
                this.error = null;
                const response = await fetch('/leaderboard');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.leaderboard = await response.json() || [];
                console.log('Leaderboard loaded:', this.leaderboard);
            } catch (e) {
                this.error = 'Failed to load leaderboard: ' + e.message;
                console.error('Error loading leaderboard:', e);
                this.leaderboard = [];
            }
        },
        async loadHookedBoats() {
            if (this.isSleepMode) return;
            try {
                this.error = null;
                const response = await fetch('/hooked');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.hookedBoats = await response.json() || [];
                this.hookedBoats.reverse();
                console.log('Hooked boats loaded:', this.hookedBoats);
            } catch (e) {
                this.error = 'Failed to load hooked boats: ' + e.message;
                console.error('Error loading hooked boats:', e);
                this.hookedBoats = [];
            }
        },
        async loadScalesBoats() {
            if (this.isSleepMode) return;
            try {
                this.error = null;
                const response = await fetch('/scales');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.scalesBoats = await response.json() || [];
                console.log('Scales boats loaded:', this.scalesBoats);
            } catch (e) {
                this.error = 'Failed to load scales boats: ' + e.message;
                console.error('Error loading scales boats:', e);
                this.scalesBoats = [];
            }
        },
        async loadGallery() {
            try {
                this.error = null;
                const response = await fetch('/gallery');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.galleryImages = await response.json() || [];
                console.log('Gallery images loaded:', this.galleryImages);
                if (this.isSleepMode) {
                    this.startSlideshow();
                }
            } catch (e) {
                this.error = 'Failed to load gallery: ' + e.message;
                console.error('Error loading gallery:', e);
                this.galleryImages = [];
            }
        },
        async loadSettings() {
            try {
                this.error = null;
                const response = await fetch('/settings');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.settings = { ...this.settings, ...await response.json() };
                this.checkSleepMode();
            } catch (e) {
                this.error = 'Failed to load settings: ' + e.message;
                console.error('Error loading settings:', e);
            }
        },
        async saveSettings() {
            try {
                await fetch('/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.settings)
                });
                this.checkSleepMode();
                if (!this.isSleepMode) {
                    await Promise.all([
                        this.loadEvents(),
                        this.loadParticipants(),
                        this.loadLeaderboard(),
                        this.loadHookedBoats(),
                        this.loadScalesBoats()
                    ]);
                } else {
                    this.loadGallery();
                }
            } catch (e) {
                this.error = 'Failed to save settings: ' + e.message;
                console.error('Error saving settings:', e);
            }
        },
        async checkVideoTrigger() {
            try {
                const response = await fetch('/check-video-trigger');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                if (data.trigger && !this.showVideoPopup && !this.showVideo) {
                    this.showVideoPopup = true;
                    this.videoBoat = typeof data.boat === 'string' ? data.boat : 'Unknown Boat';
                    this.videoETA = typeof data.eta === 'string' ? data.eta : 'Unknown ETA';
                    console.log('Video trigger data:', { boat: this.videoBoat, eta: this.videoETA });
                } else {
                    this.showVideoPopup = false;
                }
            } catch (e) {
                this.showVideoPopup = false;
                console.error('Error checking video trigger:', e);
            }
        },
        async checkWifiStatus() {
            try {
                const response = await fetch('/wifi-status');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                this.wifiConnected = data.connected;
            } catch (e) {
                console.error('Error checking WiFi status:', e);
                this.wifiConnected = false;
            }
        },
  mounted() {
    this.loadSettings();
    this.loadEvents();
    this.loadRemoteTournaments();
  }
});
