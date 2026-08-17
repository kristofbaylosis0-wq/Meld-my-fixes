from pathlib import Path
import re


def replace(path, old, new, count=1):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing pattern in {path}: {old[:120]!r}")
    p.write_text(s.replace(old, new, count))


def ensure_import(path, imp):
    p = Path(path)
    s = p.read_text()
    if imp not in s:
        s = s.replace("\nimport ", f"\n{imp}\nimport ", 1)
        p.write_text(s)

# #223 / #239: Spotify pagination must not advertise a partial collection as complete,
# and page accumulation must be deterministic, stable-ID based and O(n).
playlist = 'app/src/main/kotlin/com/metrolist/music/viewmodels/SpotifyPlaylistViewModel.kt'
ensure_import(playlist, 'import java.util.LinkedHashMap')
replace(playlist,
'''            _playlistItems.value = firstItems
            _tracks.value = firstItems.mapNotNull { it.track }
            _isLoading.value = false

            val remaining = paging.total - paging.items.size
            if (remaining <= 0) return@onSuccess

            // Fetch remaining pages in parallel batches, emitting progressively
            val allItems = firstItems.toMutableList()
''',
'''            val allItemsByTrackId = LinkedHashMap<String, SpotifyPlaylistTrack>(paging.items.size)
            firstItems.forEach { item -> item.track?.let { allItemsByTrackId.putIfAbsent(it.id, item) } }
            _playlistItems.value = allItemsByTrackId.values.toList()
            _tracks.value = allItemsByTrackId.values.mapNotNull { it.track }

            val remaining = paging.total - paging.items.size
            if (remaining <= 0) {
                _isLoading.value = false
                return@onSuccess
            }

            // Keep loading=true until every page is available to playback.
''')
replace(playlist,
'''                        allItems.addAll(page.items.filter { it.track != null && !it.isLocal })
''',
'''                        page.items.filter { it.track != null && !it.isLocal }.forEach { item ->
                            item.track?.let { allItemsByTrackId.putIfAbsent(it.id, item) }
                        }
''')
replace(playlist,
'''                _playlistItems.value = allItems.toList()
                _tracks.value = allItems.mapNotNull { it.track }

                if (failed) break
            }
        }.onFailure { e ->
''',
'''                _playlistItems.value = allItemsByTrackId.values.toList()
                _tracks.value = allItemsByTrackId.values.mapNotNull { it.track }

                if (failed) break
            }
            _isLoading.value = false
        }.onFailure { e ->
''')

liked = 'app/src/main/kotlin/com/metrolist/music/viewmodels/SpotifyLikedSongsViewModel.kt'
ensure_import(liked, 'import java.util.LinkedHashMap')
replace(liked,
'''            _tracks.value = firstPage
            _isLoading.value = false

            val remaining = paging.total - paging.items.size
''',
'''            val allTracksById = LinkedHashMap<String, SpotifyTrack>(paging.items.size)
            firstPage.forEach { allTracksById.putIfAbsent(it.id, it) }
            _tracks.value = allTracksById.values.toList()

            val remaining = paging.total - paging.items.size
''')
replace(liked,
'''                Timber.d("SpotifyLikedSongs: Loaded ${firstPage.size} tracks (all in first page)")
                return@onSuccess
''',
'''                _isLoading.value = false
                Timber.d("SpotifyLikedSongs: Loaded ${allTracksById.size} tracks (all in first page)")
                return@onSuccess
''')
replace(liked, 'val allTracks = firstPage.toMutableList()', 'val allTracks = allTracksById')
replace(liked,
'''                        allTracks.addAll(page.items.map { it.track }.filter { !it.isLocal })
''',
'''                        page.items.map { it.track }.filter { !it.isLocal }.forEach { allTracks.putIfAbsent(it.id, it) }
''')
replace(liked,
'''                _tracks.value = allTracks.toList()

                if (failed) break
            }

            Timber.d("SpotifyLikedSongs: Loaded ${allTracks.size} tracks (total=${paging.total})")
''',
'''                _tracks.value = allTracks.values.toList()

                if (failed) break
            }
            _isLoading.value = false
            Timber.d("SpotifyLikedSongs: Loaded ${allTracks.size} tracks (total=${paging.total})")
''')

# Paged queue: stable-ID accumulation and correct coroutine cancellation.
queue = 'app/src/main/kotlin/com/metrolist/music/playback/queues/SpotifyPagedQueue.kt'
ensure_import(queue, 'import kotlinx.coroutines.CancellationException')
replace(queue,
'''    private val allTracks = mutableListOf<SpotifyTrack>()
''',
'''    private val allTracks = mutableListOf<SpotifyTrack>()
    private val seenSpotifyIds = HashSet<String>()

    private fun appendUniqueTracks(tracks: List<SpotifyTrack>) {
        tracks.forEach { if (seenSpotifyIds.add(it.id)) allTracks.add(it) }
    }
''')
p = Path(queue); s = p.read_text()
s = s.replace('allTracks.addAll(provided)', 'appendUniqueTracks(provided)')
s = s.replace('allTracks.addAll(page.tracks)', 'appendUniqueTracks(page.tracks)')
s = s.replace('allTracks.clear()\n            val provided = providedTracks', 'allTracks.clear()\n            seenSpotifyIds.clear()\n            val provided = providedTracks', 1)
s = s.replace('} catch (e: Exception) {\n            Timber.e(e, "$logTag: Failed initial fetch")', '} catch (e: CancellationException) {\n            throw e\n        } catch (e: Exception) {\n            Timber.e(e, "$logTag: Failed initial fetch")', 1)
s = s.replace('} catch (e: Exception) {\n            Timber.e(e, "$logTag: getFullStatus failed")', '} catch (e: CancellationException) {\n            throw e\n        } catch (e: Exception) {\n            Timber.e(e, "$logTag: getFullStatus failed")', 1)
s = s.replace('} catch (e: Exception) {\n            Timber.e(e, "$logTag: Failed to fetch next API page")', '} catch (e: CancellationException) {\n            throw e\n        } catch (e: Exception) {\n            Timber.e(e, "$logTag: Failed to fetch next API page")', 1)
p.write_text(s)

# #224: crossfade uses monotonic elapsed time rather than accumulated fixed delays.
music = 'app/src/main/kotlin/com/metrolist/music/playback/MusicService.kt'
p = Path(music); s = p.read_text()
ensure_import(music, 'import android.os.SystemClock')
p = Path(music); s = p.read_text()
pattern = re.compile(r'''                val duration = crossfadeDuration\.toLong\(\)\n                val steps = 20\n                val stepTime = duration / steps\n                val startVolume =\n                    try \{\n                        fadingPlayer\?\.volume \?: 1f\n                    \} catch \(e: Exception\) \{\n                        1f\n                    \}\n\n                for \(i in 0\.\.steps\) \{.*?\n                \}\n''', re.S)
replacement = '''                val duration = crossfadeDuration.toLong().coerceAtLeast(0L)
                val startVolume = try { fadingPlayer?.volume ?: 1f } catch (e: Exception) { 1f }

                if (duration > 0L) {
                    val startTime = SystemClock.elapsedRealtime()
                    while (isActive) {
                        while (!player.isPlaying && isActive) delay(100)
                        if (!isActive) break

                        val elapsed = (SystemClock.elapsedRealtime() - startTime).coerceAtLeast(0L)
                        val progress = (elapsed.toDouble() / duration.toDouble()).coerceIn(0.0, 1.0).toFloat()
                        val fadeIn = 1f - (1f - progress) * (1f - progress)
                        val fadeOut = (1f - progress) * (1f - progress)
                        try {
                            player.volume = startVolume * fadeIn
                            fadingPlayer?.volume = startVolume * fadeOut
                        } catch (e: Exception) {
                            break
                        }
                        if (progress >= 1f) break
                        delay((duration - elapsed).coerceAtMost(16L).coerceAtLeast(1L))
                    }
                }
'''
if not pattern.search(s): raise SystemExit('crossfade timing block not found')
s = pattern.sub(replacement, s, count=1)
s = s.replace('if (!crossfadeEnabled || player.duration == C.TIME_UNSET || player.duration <= crossfadeDuration) return', 'if (!crossfadeEnabled || crossfadeDuration <= 0f || player.duration == C.TIME_UNSET || player.duration <= crossfadeDuration) return', 1)

# #235: stale Spotify->YT mappings are invalidated and rematched once on playback failure.
s = s.replace('private var crossfadeTriggerJob: Job? = null', 'private var crossfadeTriggerJob: Job? = null\n    private val spotifyYouTubeMapper by lazy { SpotifyYouTubeMapper(database) }\n    private val spotifyRematchAttempts = java.util.concurrent.ConcurrentHashMap.newKeySet<String>()', 1)
marker = '        // Check if this song has failed too many times\n'
insert = '''        if (mediaId != null && spotifyRematchAttempts.add(mediaId)) {
            val spotifyTrack = SpotifyMetadataRegistry.get(mediaId)
            if (spotifyTrack != null) {
                scope.launch(SilentHandler) {
                    try {
                        spotifyYouTubeMapper.invalidateMatch(spotifyTrack.id)
                        val rematched = spotifyYouTubeMapper.resolveToMediaItem(spotifyTrack)
                        if (rematched != null && player.currentMediaItem?.mediaId == mediaId) {
                            player.setMediaItem(rematched, player.currentPosition.coerceAtLeast(0L))
                            player.prepare()
                            player.playWhenReady = true
                            Timber.tag(TAG).d("Recovered stale Spotify mapping for ${spotifyTrack.id}")
                        }
                    } catch (e: Exception) {
                        Timber.tag(TAG).w(e, "Spotify rematch failed for ${spotifyTrack.id}")
                    }
                }
                return
            }
        }

'''
if marker not in s: raise SystemExit('player error insertion point missing')
s = s.replace(marker, insert + marker, 1)
marker = '''            player.currentMediaItem?.mediaId?.let { mediaId ->
                resetRetryCount(mediaId)
'''
if marker in s:
    s = s.replace(marker, '''            player.currentMediaItem?.mediaId?.let { mediaId ->
                spotifyRematchAttempts.remove(mediaId)
                resetRetryCount(mediaId)
''', 1)
p.write_text(s)

mapper = 'app/src/main/kotlin/com/metrolist/music/playback/SpotifyYouTubeMapper.kt'
replace(mapper,
'''    /**
     * Persists a user-chosen YouTube match for a Spotify track.
''',
'''    /** Invalidates a stale Spotify match and its process-local cache entry. */
    suspend fun invalidateMatch(spotifyId: String) = withContext(Dispatchers.IO) {
        memoryCache.remove(spotifyId)
        database.deleteSpotifyMatch(spotifyId)
    }

    /**
     * Persists a user-chosen YouTube match for a Spotify track.
''')

# #241: Cast lifecycle is idempotent and local playback recovers after cast failure.
cast = 'app/src/gms/kotlin/com/metrolist/music/playback/CastConnectionHandler.kt'
p = Path(cast); s = p.read_text()
replace(cast, '    private var isReloadingQueue: Boolean = false\n', '    private var isReloadingQueue: Boolean = false\n    private var initialized = false\n    private var castWasPlayingBeforeEnd = false\n')
s = p.read_text()
s = s.replace('''        override fun onMediaError(error: com.google.android.gms.cast.MediaError) {
            Timber.e("Cast media error: ${error.reason}")
        }
''','''        override fun onMediaError(error: com.google.android.gms.cast.MediaError) {
            Timber.e("Cast media error: ${error.reason}")
            handleCastFailure("remote media error: ${error.reason}")
        }
''',1)
s = s.replace('client.queueAppendItem(itemsToAdd.first(), null)', 'itemsToAdd.forEach { client.queueAppendItem(it, null) }', 1)
marker = '    private val sessionManagerListener = object : SessionManagerListener<CastSession> {\n'
helper = '''    private fun attachRemoteMediaClient(client: RemoteMediaClient?) {
        remoteMediaClient?.unregisterCallback(remoteMediaClientCallback)
        remoteMediaClient = client
        remoteMediaClient?.registerCallback(remoteMediaClientCallback)
    }

    private fun detachRemoteMediaClient() {
        remoteMediaClient?.unregisterCallback(remoteMediaClientCallback)
        remoteMediaClient = null
    }

    private fun handleCastFailure(reason: String) {
        Timber.w("Cast failure: $reason")
        val resumeLocal = castWasPlayingBeforeEnd || musicService.player.playWhenReady
        detachRemoteMediaClient()
        stopPositionUpdates()
        _isCasting.value = false
        _isConnecting.value = false
        _castIsBuffering.value = false
        castSession = null
        if (resumeLocal && musicService.player.mediaItemCount > 0) musicService.player.play()
    }

'''
if marker not in s: raise SystemExit('Cast listener marker missing')
s=s.replace(marker,helper+marker,1)
s=s.replace('remoteMediaClient = session.remoteMediaClient\n            remoteMediaClient?.registerCallback(remoteMediaClientCallback)','attachRemoteMediaClient(session.remoteMediaClient)',2)
s=s.replace('''        override fun onSessionEnding(session: CastSession) {
            Timber.d("Cast session ending")
''','''        override fun onSessionEnding(session: CastSession) {
            Timber.d("Cast session ending")
            castWasPlayingBeforeEnd = remoteMediaClient?.isPlaying == true || musicService.player.playWhenReady
''',1)
s=s.replace('''            remoteMediaClient?.unregisterCallback(remoteMediaClientCallback)
            remoteMediaClient = null
            
            stopPositionUpdates()
            
            // Pause local playback when disconnecting from Cast
            musicService.player.pause()
''','''            detachRemoteMediaClient()
            stopPositionUpdates()
            if (castWasPlayingBeforeEnd && musicService.player.mediaItemCount > 0) musicService.player.play()
            castWasPlayingBeforeEnd = false
''',1)
s=s.replace('''    fun initialize(): Boolean {
        return try {
''','''    fun initialize(): Boolean {
        if (initialized) return true
        return try {
''',1)
s=s.replace('sessionManager?.addSessionManagerListener(sessionManagerListener, CastSession::class.java)','sessionManager?.addSessionManagerListener(sessionManagerListener, CastSession::class.java)\n            initialized = true',1)
s=s.replace('''    fun release() {
        stopPositionUpdates()
        remoteMediaClient?.unregisterCallback(remoteMediaClientCallback)
        sessionManager?.removeSessionManagerListener(sessionManagerListener, CastSession::class.java)
    }
''','''    fun release() {
        stopPositionUpdates()
        syncResetJob?.cancel()
        detachRemoteMediaClient()
        sessionManager?.removeSessionManagerListener(sessionManagerListener, CastSession::class.java)
        sessionManager = null
        castContext = null
        mediaRouter = null
        routeSelector = null
        castSession = null
        initialized = false
        _isCasting.value = false
        _isConnecting.value = false
    }
''',1)
p.write_text(s)

# Fail fast if the intended files were accidentally omitted.
for f in [playlist, liked, queue, music, mapper, cast]:
    assert Path(f).exists(), f
