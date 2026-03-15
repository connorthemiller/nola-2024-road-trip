<script>
    import { onMount } from 'svelte';
    import roadRouteData from '$lib/data/road_route.json';
    import trackData from '$lib/data/trip_tracks.json';

    let mapContainer;
    let map;
    let L;
    let selectedTrack = null;
    let trackMarkers = [];
    let activeFilter = 'all';
    let sidebarOpen = false;
    let isMobile = false;

    // Audio player state
    let audio = null;
    let isPlaying = false;
    let playProgress = 0;
    let playDuration = 0;
    let playerVisible = false;

    const accentColors = ['#ff3366', '#3366ff', '#ffcc00', '#00cc88', '#ff6633', '#cc33ff'];

    // Trip stats
    const totalTracks = trackData.length;
    const uniqueArtists = new Set(trackData.map(t => t.artistName)).size;
    const totalMs = trackData.reduce((sum, t) => sum + t.msPlayed, 0);
    const totalHrs = Math.floor(totalMs / 3600000);
    const totalMin = Math.floor((totalMs % 3600000) / 60000);

    // Group tracks by day
    const tracksByDay = trackData.reduce((acc, track) => {
        const date = track.startTime.split('T')[0];
        if (!acc[date]) acc[date] = [];
        acc[date].push(track);
        return acc;
    }, {});

    // Flat list for prev/next navigation
    const allTracks = trackData;

    const dayLabels = {
        '2024-06-04': { label: 'June 4', route: 'Detroit → Cincinnati', color: '#ff3366' },
        '2024-06-05': { label: 'June 5', route: 'Cincinnati → Nashville', color: '#3366ff' },
        '2024-06-06': { label: 'June 6', route: 'Nashville → New Orleans', color: '#ffcc00' },
        '2024-06-07': { label: 'June 7', route: 'New Orleans', color: '#00cc88' },
        '2024-06-08': { label: 'June 8', route: 'New Orleans', color: '#ff6633' },
        '2024-06-09': { label: 'June 9', route: 'New Orleans', color: '#cc33ff' },
        '2024-06-10': { label: 'June 10', route: 'New Orleans', color: '#ff3366' },
        '2024-06-11': { label: 'June 11', route: 'NOLA → Birmingham', color: '#3366ff' },
        '2024-06-12': { label: 'June 12', route: 'Birmingham → Memphis', color: '#ffcc00' },
        '2024-06-13': { label: 'June 13', route: 'Memphis → Indy', color: '#00cc88' },
        '2024-06-14': { label: 'June 14', route: 'Indy → Detroit', color: '#ff6633' },
    };

    function formatTime(isoString) {
        const d = new Date(isoString);
        return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    }

    function formatDuration(ms) {
        const min = Math.floor(ms / 60000);
        const sec = Math.floor((ms % 60000) / 1000);
        return `${min}:${sec.toString().padStart(2, '0')}`;
    }

    function formatAudioTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    function confidenceColor(conf) {
        if (conf === 'high') return '#00cc88';
        if (conf === 'medium') return '#ffcc00';
        return '#ff3366';
    }

    function confidenceLabel(conf) {
        if (conf === 'high') return 'LOCKED';
        if (conf === 'medium') return 'CLOSE';
        return 'APPROX';
    }

    function typeLabel(type) {
        if (type === 'stationary') return 'STATIONARY';
        if (type === 'driving') return 'EN ROUTE';
        return 'ESTIMATED';
    }

    function getFilteredTracks() {
        if (activeFilter === 'all') return trackData;
        if (activeFilter === 'high') return trackData.filter(t => t.locationConfidence === 'high');
        return trackData.filter(t => t.locationConfidence === 'high' || t.locationConfidence === 'medium');
    }

    // ---- AUDIO PLAYER ----
    function playTrack(track) {
        if (!track.previewUrl) return;

        if (audio) {
            audio.pause();
            audio.removeEventListener('timeupdate', onTimeUpdate);
            audio.removeEventListener('ended', onEnded);
        }

        audio = new Audio(track.previewUrl);
        audio.addEventListener('timeupdate', onTimeUpdate);
        audio.addEventListener('ended', onEnded);
        audio.addEventListener('loadedmetadata', () => {
            playDuration = audio.duration;
        });

        audio.play();
        isPlaying = true;
        playerVisible = true;
    }

    function togglePlay() {
        if (!audio) return;
        if (isPlaying) {
            audio.pause();
        } else {
            audio.play();
        }
        isPlaying = !isPlaying;
    }

    function onTimeUpdate() {
        if (audio) {
            playProgress = audio.currentTime;
            playDuration = audio.duration || 30;
        }
    }

    function onEnded() {
        isPlaying = false;
        playProgress = 0;
        // Auto-advance to next track
        skipNext();
    }

    function seekTo(e) {
        if (!audio) return;
        const bar = e.currentTarget;
        const rect = bar.getBoundingClientRect();
        const pct = (e.clientX - rect.left) / rect.width;
        audio.currentTime = pct * (audio.duration || 30);
    }

    function skipPrev() {
        if (!selectedTrack) return;
        const idx = allTracks.indexOf(selectedTrack);
        // Find previous track with a preview
        for (let i = idx - 1; i >= 0; i--) {
            if (allTracks[i].previewUrl) {
                selectTrack(allTracks[i]);
                return;
            }
        }
    }

    function skipNext() {
        if (!selectedTrack) return;
        const idx = allTracks.indexOf(selectedTrack);
        // Find next track with a preview
        for (let i = idx + 1; i < allTracks.length; i++) {
            if (allTracks[i].previewUrl) {
                selectTrack(allTracks[i]);
                return;
            }
        }
    }

    function selectTrackFromMap(track) {
        // When clicking on the map, just pan to center without changing zoom
        selectedTrack = track;
        if (map && track.lat && track.lng) {
            map.panTo([track.lat, track.lng], { animate: true, duration: 0.4 });
        }
        if (track.previewUrl) {
            playTrack(track);
        } else {
            playerVisible = true;
        }
    }

    function openMarkerPopup(track) {
        const marker = trackMarkers.find(m => m._trackRef === track);
        if (marker) {
            marker.openPopup();
        }
    }

    function selectTrack(track) {
        selectedTrack = track;
        if (map && track.lat && track.lng) {
            const zoom = isMobile ? 11 : 13;
            if (isMobile) {
                sidebarOpen = false;
                setTimeout(() => {
                    map.flyTo([track.lat, track.lng], zoom, { duration: 0.8 });
                    setTimeout(() => openMarkerPopup(track), 850);
                }, 350);
            } else if (sidebarOpen) {
                const targetLatLng = L.latLng(track.lat, track.lng);
                map.setView(targetLatLng, zoom, { animate: false });
                map.panBy([-190, 0], { animate: true, duration: 0.4 });
                setTimeout(() => openMarkerPopup(track), 450);
            } else {
                map.flyTo([track.lat, track.lng], zoom, { duration: 0.8 });
                setTimeout(() => openMarkerPopup(track), 850);
            }
        }
        if (track.previewUrl) {
            playTrack(track);
        } else {
            playerVisible = true;
        }
    }

    // ---- MAP ----
    let arrowMarkers = [];

    function addArrows(latlngs, color) {
        const arrowPoints = [];
        let accumulated = 0;
        const threshold = isMobile ? 200 : 150;

        for (let i = 1; i < latlngs.length; i++) {
            const p1 = map.latLngToContainerPoint(latlngs[i - 1]);
            const p2 = map.latLngToContainerPoint(latlngs[i]);
            const dx = p2.x - p1.x;
            const dy = p2.y - p1.y;
            const dist = Math.sqrt(dx * dx + dy * dy);
            accumulated += dist;

            if (accumulated >= threshold) {
                const angle = Math.atan2(dy, dx) * (180 / Math.PI);
                arrowPoints.push({ latlng: latlngs[i], angle });
                accumulated = 0;
            }
        }

        return arrowPoints.map(({ latlng, angle }) => {
            const icon = L.divIcon({
                className: 'route-arrow',
                html: `<div style="transform: rotate(${angle}deg); color: ${color}; font-size: 12px; opacity: 0.7;">▶</div>`,
                iconSize: [12, 12],
                iconAnchor: [6, 6],
            });
            return L.marker(latlng, { icon, interactive: false }).addTo(map);
        });
    }

    function updateArrows() {
        arrowMarkers.forEach(m => map.removeLayer(m));
        arrowMarkers = [];
        roadRouteData.forEach((segment) => {
            if (segment.length < 2) return;
            const latlngs = segment.map(p => L.latLng(p.lat, p.lng));
            arrowMarkers.push(...addArrows(latlngs, '#3366ff'));
        });
    }

    function buildMap() {
        roadRouteData.forEach((segment) => {
            if (segment.length < 2) return;
            const coords = segment.map(p => [p.lat, p.lng]);
            L.polyline(coords, { color: '#3366ff', weight: 8, opacity: 0.15 }).addTo(map);
            L.polyline(coords, { color: '#3366ff', weight: 3, opacity: 0.85 }).addTo(map);
        });
        updateArrows();
        map.on('zoomend', updateArrows);
        addTrackMarkers();
    }

    function addTrackMarkers() {
        trackMarkers.forEach(m => map.removeLayer(m));
        trackMarkers = [];

        const tracks = getFilteredTracks();
        tracks.forEach((track, idx) => {
            if (!track.lat || !track.lng) return;
            const accent = accentColors[idx % accentColors.length];
            const hasPreview = !!track.previewUrl;

            const marker = L.circleMarker([track.lat, track.lng], {
                radius: isMobile ? 7 : 6,
                color: '#1a1a1a',
                fillColor: accent,
                fillOpacity: hasPreview ? 0.9 : 0.4,
                weight: 2,
            }).addTo(map);

            marker.bindPopup(`
                <div class="popup-inner">
                    <div class="popup-status" style="color:${confidenceColor(track.locationConfidence)}">
                        ● ${confidenceLabel(track.locationConfidence)} · ${typeLabel(track.locationType)}
                    </div>
                    <div class="popup-track">${track.trackName}</div>
                    <div class="popup-artist">${track.artistName}</div>
                    <div class="popup-meta">${formatTime(track.startTime)} · ${formatDuration(track.msPlayed)}</div>
                    ${hasPreview ? '<div class="popup-play">TAP TO PLAY ▶</div>' : '<div class="popup-nopreview">NO PREVIEW</div>'}
                </div>
            `, { maxWidth: 280, className: 'memphis-popup' });

            marker.on('click', () => { selectTrackFromMap(track); });
            marker._trackRef = track;
            trackMarkers.push(marker);
        });
    }

    function checkMobile() {
        isMobile = window.innerWidth < 768;
    }

    onMount(async () => {
        checkMobile();
        window.addEventListener('resize', checkMobile);

        L = (await import('leaflet')).default;
        await import('leaflet/dist/leaflet.css');

        map = L.map(mapContainer, {
            zoomControl: false,
        }).setView([35.5, -87], isMobile ? 5 : 6);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OSM &copy; CARTO',
            maxZoom: 19,
        }).addTo(map);

        L.control.zoom({ position: 'bottomright' }).addTo(map);
        buildMap();

        return () => {
            window.removeEventListener('resize', checkMobile);
            if (audio) { audio.pause(); audio = null; }
        };
    });

    function setFilter(filter) {
        activeFilter = filter;
        if (map) addTrackMarkers();
    }
</script>

<div class="app">
    <!-- MAP -->
    <div class="map-container" bind:this={mapContainer}></div>

    <!-- HUD: Trip stats (top-left, hidden on mobile when sidebar open) -->
    <div class="hud hud-stats" class:hidden={isMobile && sidebarOpen}>
        <div class="hud-label">◆ NOLA '24</div>
        <div class="hud-big">{totalTracks}</div>
        <div class="hud-sublabel">TRACKS PLAYED</div>
        <div class="hud-row">
            <div>
                <span class="hud-value">{uniqueArtists}</span>
                <span class="hud-unit">ARTISTS</span>
            </div>
            <div class="hud-divider"></div>
            <div>
                <span class="hud-value">{totalHrs}h{totalMin}m</span>
                <span class="hud-unit">LISTENED</span>
            </div>
        </div>
        <div class="hud-status">
            <span class="hud-dot" style="background:#00cc88"></span>
            JUN 4–14 ─── 2,820 MI
        </div>
    </div>

    <!-- HUD: Coordinates (top-right, desktop only) -->
    {#if !isMobile}
        <div class="hud hud-coords" class:hidden={sidebarOpen}>
            {#if selectedTrack}
                <span class="hud-coord-val">{selectedTrack.lat?.toFixed(4)}°N</span>
                <span class="hud-coord-val">{selectedTrack.lng?.toFixed(4)}°W</span>
            {:else}
                <span class="hud-coord-val">35.5000°N</span>
                <span class="hud-coord-val">-87.0000°W</span>
            {/if}
        </div>
    {/if}

    <!-- SIDEBAR TOGGLE -->
    <button class="sidebar-toggle" class:open={sidebarOpen} on:click={() => sidebarOpen = !sidebarOpen}>
        {sidebarOpen ? '✕' : '♫'}
    </button>

    <!-- SIDEBAR -->
    <div class="sidebar" class:open={sidebarOpen}>
        <div class="sidebar-header">
            <h1>TRACKLIST</h1>
            <div class="sidebar-subtitle">{totalTracks} songs · 11 days</div>
        </div>

        <div class="filters">
            <button class:active={activeFilter === 'all'} on:click={() => setFilter('all')}>ALL</button>
            <button class:active={activeFilter === 'medium'} on:click={() => setFilter('medium')}>MED+</button>
            <button class:active={activeFilter === 'high'} on:click={() => setFilter('high')}>LOCKED</button>
        </div>

        <div class="track-list">
            {#each Object.entries(tracksByDay) as [date, tracks], dayIdx}
                {@const day = dayLabels[date] || { label: date, route: '', color: '#888' }}
                <div class="day-group">
                    <div class="day-header" style="border-left: 4px solid {day.color}">
                        <span class="day-date">{day.label}</span>
                        <span class="day-route">{day.route}</span>
                        <span class="day-count">{tracks.length}</span>
                    </div>
                    {#each tracks as track, tIdx}
                        <button
                            class="track-item"
                            class:selected={selectedTrack === track}
                            class:has-preview={!!track.previewUrl}
                            on:click={() => selectTrack(track)}
                        >
                            <div class="track-color-bar" style="background:{accentColors[(dayIdx * 7 + tIdx) % accentColors.length]}"></div>
                            <div class="track-info">
                                <span class="track-name">
                                    {#if track.previewUrl}<span class="track-play-icon">▶</span>{/if}
                                    {track.trackName}
                                </span>
                                <span class="track-artist">{track.artistName}</span>
                            </div>
                            <div class="track-meta">
                                <span class="track-time">{formatTime(track.startTime)}</span>
                                <span class="track-confidence" style="color:{confidenceColor(track.locationConfidence)}">●</span>
                            </div>
                        </button>
                    {/each}
                </div>
            {/each}
        </div>
    </div>

    <!-- MUSIC PLAYER (bottom floating) -->
    {#if playerVisible && selectedTrack}
        <div class="player" class:sidebar-offset={sidebarOpen && !isMobile}>
            <!-- Artwork -->
            <div class="player-art">
                {#if selectedTrack.artworkUrl}
                    <img src={selectedTrack.artworkUrl} alt="" />
                {:else}
                    <div class="player-art-placeholder">♫</div>
                {/if}
            </div>

            <!-- Track info -->
            <div class="player-info">
                <div class="player-track">{selectedTrack.trackName}</div>
                <div class="player-artist">{selectedTrack.artistName}</div>
                <div class="player-location">
                    <span class="hud-dot" style="background:{confidenceColor(selectedTrack.locationConfidence)}"></span>
                    <span>{confidenceLabel(selectedTrack.locationConfidence)} · {typeLabel(selectedTrack.locationType)}</span>
                    <span class="player-time-stamp">{formatTime(selectedTrack.startTime)}</span>
                </div>
            </div>

            <!-- Controls -->
            <div class="player-controls">
                <button class="ctrl-btn" on:click={skipPrev} aria-label="Previous">◄◄</button>
                {#if selectedTrack.previewUrl}
                    <button class="ctrl-btn ctrl-play" on:click={togglePlay} aria-label={isPlaying ? 'Pause' : 'Play'}>
                        {isPlaying ? '▮▮' : '▶'}
                    </button>
                {:else}
                    <div class="ctrl-no-preview">NO PREVIEW</div>
                {/if}
                <button class="ctrl-btn" on:click={skipNext} aria-label="Next">►►</button>
            </div>

            <!-- Progress bar -->
            {#if selectedTrack.previewUrl}
                <div class="player-progress" on:click={seekTo} role="progressbar" tabindex="0"
                     aria-valuenow={playProgress} aria-valuemin="0" aria-valuemax={playDuration}>
                    <div class="progress-fill" style="width:{playDuration ? (playProgress / playDuration) * 100 : 0}%"></div>
                    <div class="progress-times">
                        <span>{formatAudioTime(playProgress)}</span>
                        <span>{formatAudioTime(playDuration || 30)}</span>
                    </div>
                </div>
            {/if}
        </div>
    {/if}
</div>

<style>
    :root {
        --bg-primary: #f5f0e0;
        --bg-panel: rgba(245, 240, 224, 0.88);
        --bg-dark: #1a1a1a;
        --accent-coral: #ff3366;
        --accent-blue: #3366ff;
        --accent-sunshine: #ffcc00;
        --accent-jade: #00cc88;
        --accent-tangerine: #ff6633;
        --accent-violet: #cc33ff;
        --text-primary: #1a1a1a;
        --text-secondary: #333333;
        --text-muted: #666666;
        --border: #1a1a1a;
        --font-heading: 'Outfit', 'DM Sans', sans-serif;
        --font-body: 'IBM Plex Sans', sans-serif;
        --font-mono: 'Space Mono', 'JetBrains Mono', monospace;
    }

    :global(body) {
        margin: 0;
        padding: 0;
        font-family: var(--font-body);
        background: var(--bg-primary);
        color: var(--text-primary);
        overflow: hidden;
    }

    .app {
        position: relative;
        width: 100vw;
        height: 100vh;
    }

    .hidden { display: none !important; }

    /* ---- MAP ---- */
    .map-container {
        position: absolute;
        inset: 0;
        z-index: 0;
    }

    /* ---- HUD PANELS ---- */
    .hud {
        position: absolute;
        z-index: 1000;
        background: var(--bg-panel);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 2px solid var(--border);
        font-family: var(--font-mono);
        pointer-events: auto;
    }

    .hud-stats {
        top: 12px;
        left: 12px;
        padding: 14px 16px;
        min-width: 200px;
        box-shadow: 4px 4px 0px var(--accent-coral);
        clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 0 100%);
    }

    .hud-label {
        font-size: 9px;
        letter-spacing: 3px;
        color: var(--text-muted);
        margin-bottom: 6px;
        font-weight: 700;
    }

    .hud-big {
        font-family: var(--font-heading);
        font-size: 36px;
        font-weight: 800;
        color: var(--accent-coral);
        line-height: 1;
    }

    .hud-sublabel {
        font-size: 8px;
        letter-spacing: 3px;
        color: var(--text-muted);
        margin-bottom: 10px;
    }

    .hud-row {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
    }

    .hud-value {
        font-size: 13px;
        font-weight: 700;
        color: var(--text-primary);
    }

    .hud-unit {
        font-size: 7px;
        letter-spacing: 2px;
        color: var(--text-muted);
        display: block;
    }

    .hud-divider {
        width: 1px;
        height: 20px;
        background: var(--border);
    }

    .hud-status {
        font-size: 8px;
        letter-spacing: 2px;
        color: var(--text-secondary);
        display: flex;
        align-items: center;
        gap: 6px;
    }

    .hud-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
        display: inline-block;
        flex-shrink: 0;
        animation: pulse 2s ease-in-out infinite;
    }

    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.4; }
    }

    .hud-coords {
        top: 12px;
        right: 12px;
        padding: 8px 12px;
        box-shadow: 4px 4px 0px var(--accent-blue);
        display: flex;
        flex-direction: column;
        gap: 2px;
    }

    .hud-coord-val {
        font-size: 10px;
        letter-spacing: 2px;
        color: var(--accent-blue);
    }

    /* ---- SIDEBAR ---- */
    .sidebar {
        position: absolute;
        top: 0;
        right: 0;
        width: 380px;
        height: 100vh;
        z-index: 1001;
        background: var(--bg-panel);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-left: 3px solid var(--border);
        display: flex;
        flex-direction: column;
        transform: translateX(100%);
        transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }

    .sidebar.open {
        transform: translateX(0);
    }

    .sidebar-toggle {
        position: absolute;
        top: 50%;
        right: 0;
        transform: translateY(-50%);
        z-index: 1002;
        width: 40px;
        height: 48px;
        background: var(--bg-dark);
        color: var(--accent-sunshine);
        border: 2px solid var(--border);
        border-right: none;
        border-radius: 8px 0 0 8px;
        font-size: 18px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: right 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        font-family: var(--font-body);
    }

    .sidebar-toggle.open {
        right: 380px;
    }

    .sidebar-header {
        padding: 16px 20px 12px;
        border-bottom: 2px solid var(--border);
        background: var(--bg-dark);
        color: #fff;
    }

    .sidebar-header h1 {
        margin: 0;
        font-family: var(--font-heading);
        font-size: 20px;
        font-weight: 800;
        letter-spacing: 4px;
    }

    .sidebar-subtitle {
        font-family: var(--font-mono);
        font-size: 9px;
        letter-spacing: 2px;
        color: var(--text-muted);
        margin-top: 4px;
    }

    .filters {
        display: flex;
        gap: 0;
        border-bottom: 2px solid var(--border);
        flex-shrink: 0;
    }

    .filters button {
        flex: 1;
        background: transparent;
        border: none;
        border-right: 2px solid var(--border);
        color: var(--text-muted);
        padding: 10px;
        font-family: var(--font-mono);
        font-size: 10px;
        letter-spacing: 2px;
        cursor: pointer;
        transition: all 0.15s;
    }

    .filters button:last-child { border-right: none; }
    .filters button:hover { background: rgba(0,0,0,0.04); color: var(--text-primary); }
    .filters button.active { background: var(--bg-dark); color: var(--accent-sunshine); }

    /* ---- TRACK LIST ---- */
    .track-list {
        overflow-y: auto;
        flex: 1;
        -webkit-overflow-scrolling: touch;
    }

    .day-group {
        border-bottom: 1px solid rgba(26, 26, 26, 0.15);
    }

    .day-header {
        position: sticky;
        top: 0;
        z-index: 1;
        background: var(--bg-panel);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        padding: 10px 16px 10px 12px;
        display: flex;
        align-items: baseline;
        gap: 8px;
        border-bottom: 1px solid rgba(26, 26, 26, 0.1);
    }

    .day-date {
        font-family: var(--font-heading);
        font-weight: 700;
        font-size: 13px;
        color: var(--text-primary);
    }

    .day-route {
        font-family: var(--font-mono);
        font-size: 8px;
        letter-spacing: 1px;
        color: var(--text-muted);
        flex: 1;
    }

    .day-count {
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-muted);
        background: rgba(26, 26, 26, 0.06);
        padding: 2px 6px;
        border: 1px solid rgba(26, 26, 26, 0.15);
    }

    .track-item {
        display: flex;
        align-items: center;
        width: 100%;
        padding: 10px 16px 10px 0;
        border: none;
        background: transparent;
        color: var(--text-primary);
        cursor: pointer;
        text-align: left;
        font-family: inherit;
        transition: all 0.15s;
        gap: 0;
    }

    .track-item:hover {
        background: rgba(26, 26, 26, 0.04);
        transform: translate(-2px, -2px);
        box-shadow: 2px 2px 0px rgba(26, 26, 26, 0.1);
    }

    .track-item.selected {
        background: rgba(51, 102, 255, 0.08);
        border-right: 3px solid var(--accent-blue);
    }

    .track-color-bar {
        width: 3px;
        align-self: stretch;
        flex-shrink: 0;
        margin-right: 10px;
    }

    .track-info {
        display: flex;
        flex-direction: column;
        min-width: 0;
        flex: 1;
    }

    .track-name {
        font-size: 13px;
        font-weight: 500;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--text-primary);
    }

    .track-play-icon {
        font-size: 9px;
        color: var(--accent-jade);
        margin-right: 4px;
    }

    .track-artist {
        font-size: 11px;
        color: var(--text-muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .track-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        margin-left: 12px;
        flex-shrink: 0;
    }

    .track-time {
        font-family: var(--font-mono);
        font-size: 9px;
        letter-spacing: 1px;
        color: var(--text-muted);
    }

    .track-confidence { font-size: 8px; }

    /* ---- MUSIC PLAYER ---- */
    .player {
        position: absolute;
        bottom: 16px;
        left: 16px;
        right: 16px;
        z-index: 1001;
        background: var(--bg-dark);
        border: 2px solid var(--border);
        box-shadow: 4px 4px 0px var(--accent-violet);
        display: grid;
        grid-template-columns: 56px 1fr auto;
        grid-template-rows: auto auto;
        gap: 0;
        overflow: hidden;
    }

    .player.sidebar-offset {
        right: 396px;
    }

    .player-art {
        grid-row: 1 / 3;
        width: 56px;
        height: 56px;
        background: #222;
        display: flex;
        align-items: center;
        justify-content: center;
        border-right: 2px solid #333;
    }

    .player-art img {
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .player-art-placeholder {
        color: var(--accent-violet);
        font-size: 24px;
    }

    .player-info {
        padding: 8px 12px;
        min-width: 0;
        grid-column: 2;
        grid-row: 1;
    }

    .player-track {
        font-family: var(--font-heading);
        font-weight: 700;
        font-size: 14px;
        color: #fff;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .player-artist {
        font-size: 12px;
        color: #999;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    .player-location {
        font-family: var(--font-mono);
        font-size: 8px;
        letter-spacing: 1px;
        color: #666;
        display: flex;
        align-items: center;
        gap: 5px;
        margin-top: 3px;
    }

    .player-time-stamp {
        color: #555;
        margin-left: auto;
    }

    .player-controls {
        display: flex;
        align-items: center;
        gap: 4px;
        padding: 8px 12px;
        grid-column: 3;
        grid-row: 1;
    }

    .ctrl-btn {
        background: transparent;
        border: none;
        color: #888;
        font-size: 12px;
        cursor: pointer;
        padding: 6px 8px;
        font-family: var(--font-mono);
        transition: color 0.15s;
    }

    .ctrl-btn:hover {
        color: #fff;
    }

    .ctrl-play {
        color: var(--accent-tangerine);
        font-size: 16px;
        border: 2px solid var(--accent-tangerine);
        border-radius: 0;
        width: 36px;
        height: 36px;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0;
    }

    .ctrl-play:hover {
        background: var(--accent-tangerine);
        color: var(--bg-dark);
    }

    .ctrl-no-preview {
        font-family: var(--font-mono);
        font-size: 8px;
        letter-spacing: 2px;
        color: #555;
        padding: 6px 8px;
    }

    .player-progress {
        grid-column: 1 / -1;
        grid-row: 2;
        height: 20px;
        background: #111;
        cursor: pointer;
        position: relative;
        border-top: 1px solid #333;
    }

    .progress-fill {
        height: 100%;
        background: var(--accent-sunshine);
        opacity: 0.8;
        transition: width 0.1s linear;
    }

    .progress-times {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 100%;
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 8px;
        font-family: var(--font-mono);
        font-size: 8px;
        letter-spacing: 1px;
        color: #888;
        pointer-events: none;
    }

    /* ---- ROUTE ARROWS ---- */
    :global(.route-arrow) {
        background: none !important;
        border: none !important;
    }

    /* ---- MAP POPUPS ---- */
    :global(.memphis-popup .leaflet-popup-content-wrapper) {
        background: var(--bg-panel) !important;
        color: var(--text-primary) !important;
        border: 2px solid var(--border) !important;
        border-radius: 0 !important;
        box-shadow: 4px 4px 0px #cc33ff !important;
    }

    :global(.memphis-popup .leaflet-popup-tip) {
        background: #f5f0e0 !important;
        border: 2px solid #1a1a1a !important;
        box-shadow: none !important;
    }

    :global(.popup-inner) { font-family: 'IBM Plex Sans', sans-serif; }
    :global(.popup-status) { font-family: 'Space Mono', monospace; font-size: 9px; letter-spacing: 2px; margin-bottom: 6px; }
    :global(.popup-track) { font-family: 'Outfit', sans-serif; font-weight: 700; font-size: 15px; color: #1a1a1a; }
    :global(.popup-artist) { font-size: 13px; color: #333; margin-top: 2px; }
    :global(.popup-meta) { font-family: 'Space Mono', monospace; font-size: 10px; color: #666; letter-spacing: 1px; margin-top: 6px; }
    :global(.popup-play) { font-family: 'Space Mono', monospace; font-size: 9px; letter-spacing: 2px; color: #00cc88; margin-top: 8px; font-weight: 700; }
    :global(.popup-nopreview) { font-family: 'Space Mono', monospace; font-size: 9px; letter-spacing: 2px; color: #999; margin-top: 8px; }

    /* ---- ZOOM CONTROLS ---- */
    :global(.leaflet-control-zoom a) {
        background: rgba(245, 240, 224, 0.88) !important;
        color: #1a1a1a !important;
        border: 2px solid #1a1a1a !important;
        border-radius: 0 !important;
        width: 32px !important;
        height: 32px !important;
        line-height: 28px !important;
        font-weight: 700 !important;
    }

    :global(.leaflet-control-zoom) {
        border: none !important;
        box-shadow: 4px 4px 0px #00cc88 !important;
    }

    /* ---- MOBILE RESPONSIVE ---- */
    @media (max-width: 767px) {
        .hud-stats {
            top: 8px;
            left: 8px;
            padding: 10px 12px;
            min-width: auto;
        }

        .hud-big { font-size: 28px; }
        .hud-row { gap: 8px; }
        .hud-value { font-size: 11px; }

        .sidebar {
            width: 100vw;
            border-left: none;
            border-top: 3px solid var(--border);
        }

        .sidebar-toggle {
            top: auto;
            bottom: 100px;
            right: 12px;
            transform: none;
            border-radius: 8px;
            border: 2px solid var(--border);
            width: 44px;
            height: 44px;
            box-shadow: 4px 4px 0px var(--accent-sunshine);
        }

        .sidebar-toggle.open {
            right: 12px;
            bottom: auto;
            top: 8px;
            z-index: 1003;
        }

        .player {
            bottom: 8px;
            left: 8px;
            right: 8px;
            grid-template-columns: 48px 1fr auto;
        }

        .player.sidebar-offset {
            right: 8px;
        }

        .player-art {
            width: 48px;
            height: 48px;
        }

        .player-info { padding: 6px 10px; }
        .player-track { font-size: 13px; }
        .player-artist { font-size: 11px; }
        .player-controls { padding: 6px 8px; gap: 2px; }

        .ctrl-play {
            width: 32px;
            height: 32px;
            font-size: 14px;
        }

        .track-item {
            padding: 12px 16px 12px 0;
        }

        :global(.leaflet-control-zoom) {
            display: none !important;
        }
    }
</style>
