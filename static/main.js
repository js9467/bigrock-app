if (document.querySelector('#app') && document.querySelector('body.index')) {
  new Vue({
    el: '#app',
    data: {
      settings: { tournament: 'Big Rock' },
      allTournaments: {},
      followedBoats: [],
      radioPlaying: false,
      isSleepMode: false,
      isHookedUpMinimized: false,
      isScalesMinimized: false,
      displayedEvents: [],
      activeHookedBoats: [],
      activeScalesBoats: [],
      galleryImages: [],
      currentImageIndex: 0,
      showVideoPopup: false,
      videoBoat: '',
      videoETA: '',
      videoUrl: 'https://www.youtube.com/embed/live_stream?channel=UCuJ4Y3Z5Z5cJQbWxI6wovmw',
      showVideo: false,
      error: null
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
      async loadSettings() {
        try {
          const res = await fetch('/settings');
          if (res.ok) {
            const data = await res.json();
            this.settings = { ...this.settings, ...data };
            this.followedBoats = data.followed_boats || [];
          }
        } catch (e) {
          console.error('Failed to load settings:', e);
        }
      },
      async loadRemoteTournaments() {
        try {
          const res = await fetch('https://js9467.github.io/Brtourney/settings.json');
          if (res.ok) {
            this.allTournaments = await res.json();
          }
        } catch (e) {
          console.error('Failed to load tournaments:', e);
        }
      },
      toggleRadio() {
        this.radioPlaying = !this.radioPlaying;
        const player = document.getElementById('radio-player');
        if (this.radioPlaying) {
          player.src = 'https://your-stream-url';
          player.play();
        } else {
          player.pause();
          player.src = '';
        }
      },
      goToSettings() {
        window.location.href = '/settings-page';
      },
      toggleHookedUpMinimized() {
        this.isHookedUpMinimized = !this.isHookedUpMinimized;
      },
      toggleScalesMinimized() {
        this.isScalesMinimized = !this.isScalesMinimized;
      },
      formatTime(time) {
        return new Date(time).toLocaleTimeString();
      },
      formatETA(eta) {
        return eta || 'N/A';
      },
      handleImageError(e) {
        e.target.src = 'data:image/png;base64,...'; // fallback image
      },
      watchLive() {
        this.showVideo = true;
      },
      closeVideo() {
        this.showVideo = false;
      },
      dismissVideoPopup() {
        this.showVideoPopup = false;
      }
    },
    mounted() {
      this.loadSettings();
      this.loadRemoteTournaments();
    }
  });
}
