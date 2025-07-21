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
    videoUrl: 'https://www.youtube.com/embed/live_stream?channel=UCuJ4Y3Z5Z5Q3--y1ayc6Evw'
  },
  computed: {
    logoSrc() {
      const t = this.settings?.tournament;
      const tournament = this.allTournaments?.[t];
      return tournament?.logo || '';
    },
    themeClass() {
      return 'theme-' + (this.settings.tournament || 'default').toLowerCase().replace(/\s+/g, '-');
    }
  },
  methods: {
    async loadRemoteTournaments() {
      try {
        const response = await fetch('https://js9467.github.io/Brtourney/settings.json');
        if (response.ok) {
          this.allTournaments = await response.json();
        }
      } catch (e) {
        console.error('Failed to fetch tournament settings:', e);
      }
    },
    async loadRemoteTournaments() { ... },

  loadSettings() { ... },

  loadEvents() { ... },

  toggleRadio() {     // 👈 INSERT HERE
    this.radioPlaying = !this.radioPlaying;
    const radioPlayer = document.getElementById('radio-player');
    if (this.radioPlaying) {
      radioPlayer.src = "/static/vhf.mp3";
      radioPlayer.play().catch(err => console.error("Radio play error:", err));
    } else {
      radioPlayer.pause();
      radioPlayer.src = "";
    }
  },
    loadSettings() {
      fetch('/settings')
        .then(res => res.json())
        .then(data => {
          this.settings = { ...this.settings, ...data };
        });
    },
    loadEvents() {
      fetch('/api/events')
        .then(res => res.json())
        .then(data => {
          this.events = data;
          this.displayedEvents = data;
        });
    },
    // other methods like toggleRadio, watchLive, handleImageError, etc.
  },
  mounted() {
    this.loadSettings();
    this.loadEvents();
    this.loadRemoteTournaments(); // ← now included!
    // optionally other initializers
  }
});
