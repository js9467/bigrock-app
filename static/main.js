new Vue({
    el: '#app',
    data: {
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
                } else if (
                    hookupId &&
                    (
                        action.includes('boated') ||
                        action.includes('released') ||
                        action.includes('pulled hook') ||
                        action.includes('wrong species')
                    )
                ) {
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
                        this.connectionStatus = `📡 Found ${data.networks.length} networks.`;
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
            this.connectionStatus = `🔌 Connecting to ${ssid}...`;

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
                        this.connectionStatus = `✅ Connected to ${ssid}`;
                        this.wifiConnected = true;
                    } else {
                        this.connectionStatus = `❌ Failed: ${data.error || 'Unknown error'}`;
                    }
                })
                .catch(() => {
                    this.connectionStatus = `❌ Error connecting to ${ssid}`;
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
        async loadEvents() {
            if (this.isSleepMode) return;
            try {
                this.error = null;
                const response = await fetch('/events');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.events = await response.json() || [];

                this.displayedEvents = [...this.events].reverse();

                if (this.settings.data_source === 'historical') {
                    this.startHistoricalScroll();
                } else {
                    this.stopHistoricalScroll();

                    const latestBoated = this.events
                        .filter(e => (e.action || '').toLowerCase() === 'boated')
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

                this.boatImages = this.participants.reduce((acc, participant) => {
                    if (participant.boat && participant.image) {
                        acc[participant.boat.toLowerCase()] = participant.image;
                    }
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
        watchLive() {
            this.showVideoPopup = false;
            this.showVideo = true;
        },
        dismissVideoPopup() {
            this.showVideoPopup = false;
        },
        closeVideo() {
            this.showVideo = false;
        },
        toggleHookedUpMinimized() {
            this.isHookedUpMinimized = !this.isHookedUpMinimized;
        },
        toggleScalesMinimized() {
            this.isScalesMinimized = !this.isScalesMinimized;
        },
        checkSleepMode() {
            if (this.settings.disable_sleep_mode) {
                this.isSleepMode = false;
                this.stopSlideshow();
                this.loadEvents();
                this.loadParticipants();
                this.loadLeaderboard();
                this.loadHookedBoats();
                this.loadScalesBoats();
                return;
            }
            const now = new Date();
            const month = now.getMonth() + 1;
            const day = now.getDate();
            const hour = now.getHours();
            const minute = now.getMinutes();
            const isTournamentDay = (
                (this.settings.tournament === 'Big Rock' && month === 6 && day >= 5 && day <= 13) ||
                (this.settings.tournament === 'Kids' && month === 7 && day >= 8 && day <= 11) ||
                (this.settings.tournament === 'KWLA' && month === 6 && day >= 5 && day <= 6)
            );
            const isFishingHours = hour >= 9 && hour < 15;
            const isWithinWeighInWindow = this.lastBoatedTime && (now - this.lastBoatedTime) < 30 * 60 * 1000;
            this.isSleepMode = !isTournamentDay || (isTournamentDay && !isFishingHours && !isWithinWeighInWindow);
            if (this.isSleepMode) {
                this.stopHistoricalScroll();
                this.loadGallery();
            } else {
                this.stopSlideshow();
                this.loadEvents();
                this.loadParticipants();
                this.loadLeaderboard();
                this.loadHookedBoats();
                this.loadScalesBoats();
            }
        },
        startSlideshow() {
            this.stopSlideshow();
            if (this.galleryImages.length > 0) {
                this.slideshowInterval = setInterval(() => {
                    this.currentImageIndex = (this.currentImageIndex + 1) % this.galleryImages.length;
                }, 5000);
            }
        },
        stopSlideshow() {
            if (this.slideshowInterval) {
                clearInterval(this.slideshowInterval);
                this.slideshowInterval = null;
            }
        },
        getBoatImage(boatName) {
            if (this.boatImages[boatName]) {
                return this.boatImages[boatName];
            }
            if (typeof known_boat_images !== 'undefined' && known_boat_images[boatName]) {
                return known_boat_images[boatName];
            }
            return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA6ElEQVR4nO3QwQ3AIBDAsNLJb3RWIC+EZE8QZc3Mx5n/dsBLzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCjbLZgJIjFtsAQAAAABJRU5ErkJggg==';
        },
        handleImageError(event) {
            event.target.src = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAA6ElEQVR4nO3QwQ3AIBDAsNLJb3RWIC+EZE8QZc3Mx5n/dsBLzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCswKzArMCjbLZgJIjFtsAQAAAABJRU5ErkJggg==';
        },
        startHistoricalScroll() {
            this.stopHistoricalScroll();
            this.displayedEvents = [];
            this.eventIndex = 0;
            this.scrollInterval = setInterval(() => {
                if (this.eventIndex < this.events.length) {
                    this.displayedEvents = [...this.displayedEvents, this.events[this.eventIndex]];
                    if (this.settings.sounds[this.events[this.eventIndex].action.toLowerCase().replace(' ', '')]) {
                        const sound = new Audio(`/static/sounds/${this.events[this.eventIndex].action.toLowerCase().replace(' ', '')}.mp3`);
                        sound.volume = this.settings.effects_volume;
                        sound.play().catch(e => console.error('Sound error:', e));
                    }
                    this.eventIndex++;
                    this.$nextTick(() => {
                        const feed = this.$refs.eventFeed;
                        if (feed) {
                            feed.scrollTop = feed.scrollHeight;
                        }
                    });
                } else {
                    this.stopHistoricalScroll();
                }
            }, 20000);
        },
        stopHistoricalScroll() {
            if (this.scrollInterval) {
                clearInterval(this.scrollInterval);
                this.scrollInterval = null;
            }
        },
        toggleRadio() {
            const player = document.getElementById('radio-player');
            const primaryStream = 'https://cs.ebmcdn.net/eastbay-live-hs-1/event/mp4:bigrockradio/playlist.m3u8';
            const fallbackStream = 'https://playertest.longtailvideo.com/adaptive/bbbfull/bbbfull.m3u8';
            const fallbackMessage = '🎣 Tournament VHF currently unavailable. Using test stream.';

            const playStream = (url, isFallback = false) => {
                if (Hls.isSupported()) {
                    this.hls = new Hls();
                    this.hls.loadSource(url);
                    this.hls.attachMedia(player);

                    this.hls.on(Hls.Events.MANIFEST_PARSED, () => {
                        player.volume = this.settings.radio_volume || 0.3;
                        player.play()
                            .then(() => {
                                this.radioPlaying = true;
                                this.error = isFallback ? fallbackMessage : null;
                                localStorage.setItem('radioPlaying', 'true');
                            })
                            .catch(err => {
                                console.error('🔊 Audio play failed:', err);
                                if (!isFallback) {
                                    this.hls.destroy();
                                    this.hls = null;
                                    playStream(fallbackStream, true);
                                } else {
                                    this.error = fallbackMessage;
                                    this.radioPlaying = false;
                                }
                            });
                    });

                    this.hls.on(Hls.Events.ERROR, (event, data) => {
                        if (data.fatal) {
                            console.warn('💥 HLS fatal error:', data);
                            this.hls.destroy();
                            this.hls = null;
                            if (!isFallback) {
                                playStream(fallbackStream, true);
                            } else {
                                this.error = fallbackMessage;
                                this.radioPlaying = false;
                            }
                        }
                    });
                } else if (player.canPlayType('application/vnd.apple.mpegurl')) {
                    player.src = url;
                    player.volume = this.settings.radio_volume || 0.3;
                    player.play()
                        .then(() => {
                            this.radioPlaying = true;
                            this.error = isFallback ? fallbackMessage : null;
                            localStorage.setItem('radioPlaying', 'true');
                        })
                        .catch(err => {
                            console.error('🔊 Native HLS play failed:', err);
                            if (!isFallback) {
                                playStream(fallbackStream, true);
                            } else {
                                this.error = fallbackMessage;
                                this.radioPlaying = false;
                            }
                        });
                } else {
                    this.error = fallbackMessage;
                    this.radioPlaying = false;
                }
            };

            if (this.radioPlaying) {
                if (this.hls) {
                    this.hls.destroy();
                    this.hls = null;
                }
                player.pause();
                player.src = '';
                this.radioPlaying = false;
                this.error = null;
                localStorage.setItem('radioPlaying', 'false');
            } else {
                playStream(primaryStream, false);
            }
        },
        goToSettings() {
            window.location.href = '/settings-page';
        },
        goToParticipants() {
            window.location.href = '/participants';
        },
        goToLeaderboard() {
            window.location.href = '/leaderboard';
        },
        goBack() {
            window.location.href = '/';
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
    async mounted() {
        console.log('Vue instance mounted for:', window.location.pathname);
        window.app = this;

        try {
            const res = await fetch("https://js9467.github.io/Brtourney/settings.json");
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            this.allTournaments = await res.json();

            this.isLoading = true;

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

            this.isLoading = false;
            this.appMounted = true;

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
            this.isLoading = false;
            this.appMounted = true;
        }
    }
});
