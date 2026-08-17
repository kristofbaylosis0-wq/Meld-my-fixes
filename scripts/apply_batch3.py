from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, pattern: str, replacement: str, flags: int = 0) -> None:
    file = ROOT / path
    text = file.read_text()
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"Expected exactly one match in {path}, got {count}: {pattern[:120]!r}")
    file.write_text(new_text)


# ---------------------------------------------------------------------------
# #244: Search "All" must aggregate every result category and paginate them.
# ---------------------------------------------------------------------------
search_vm = "app/src/main/kotlin/com/metrolist/music/viewmodels/OnlineSearchViewModel.kt"
replace_once(
    search_vm,
    r"import com\.metrolist\.music\.constants\.HideYoutubeShortsKey\n",
    "import com.metrolist.music.constants.HideYoutubeShortsKey\nimport com.metrolist.music.R\n",
)
replace_once(
    search_vm,
    r"import kotlinx\.coroutines\.Dispatchers\n",
    "import kotlinx.coroutines.Dispatchers\nimport kotlinx.coroutines.Job\nimport kotlinx.coroutines.async\nimport kotlinx.coroutines.awaitAll\n",
)
replace_once(
    search_vm,
    r"(val viewStateMap = mutableStateMapOf<String, ItemsPage\?>\(\))\n",
    r'''\1

    // The YouTube search-summary endpoint is intentionally lightweight, but it only
    // represents the first/top results for each section and does not expose a
    // continuation token. "All" therefore uses the real paginated category
    // endpoints and merges their pages into deterministic sections.
    private var allInitialized = false
    private var allLoadJob: Job? = null

    private fun allFilterSpecs(hideVideoSongs: Boolean): List<Pair<YouTube.SearchFilter, String>> {
        val specs = mutableListOf(
            YouTube.SearchFilter.FILTER_SONG to context.getString(R.string.filter_songs),
        )
        if (!hideVideoSongs) {
            specs += YouTube.SearchFilter.FILTER_VIDEO to context.getString(R.string.filter_videos)
        }
        specs += listOf(
            YouTube.SearchFilter.FILTER_ALBUM to context.getString(R.string.filter_albums),
            YouTube.SearchFilter.FILTER_ARTIST to context.getString(R.string.filter_artists),
            YouTube.SearchFilter.FILTER_COMMUNITY_PLAYLIST to context.getString(R.string.filter_community_playlists),
            YouTube.SearchFilter.FILTER_FEATURED_PLAYLIST to context.getString(R.string.filter_featured_playlists),
            YouTube.SearchFilter.FILTER_PODCAST to context.getString(R.string.filter_podcasts),
            YouTube.SearchFilter.FILTER_EPISODE to context.getString(R.string.filter_episodes),
            YouTube.SearchFilter.FILTER_PROFILE to context.getString(R.string.filter_profiles),
        )
        return specs
    }

    private fun applySearchFilters(items: List<YTItem>): List<YTItem> {
        val hideExplicit = context.dataStore.get(HideExplicitKey, false)
        val hideVideoSongs = context.dataStore.get(HideVideoSongsKey, false)
        val hideYoutubeShorts = context.dataStore.get(HideYoutubeShortsKey, false)
        return items
            .distinctBy { it.id }
            .filterExplicit(hideExplicit)
            .filterVideoSongs(hideVideoSongs)
            .filterYoutubeShorts(hideYoutubeShorts)
    }

    private fun rebuildAllSummary() {
        val hideVideoSongs = context.dataStore.get(HideVideoSongsKey, false)
        val summaries = allFilterSpecs(hideVideoSongs).mapNotNull { (filter, title) ->
            val items = viewStateMap[filter.value]?.items.orEmpty()
            items.takeIf { it.isNotEmpty() }?.let { SearchSummary(title = title, items = it) }
        }
        summaryPage = SearchSummaryPage(summaries = summaries)
    }

    fun hasMoreAll(): Boolean {
        val hideVideoSongs = context.dataStore.get(HideVideoSongsKey, false)
        return allFilterSpecs(hideVideoSongs).any { (filter, _) ->
            viewStateMap[filter.value]?.continuation != null
        }
    }

    private suspend fun loadAllPage() {
        if (allInitialized) {
            rebuildAllSummary()
            return
        }

        val hideVideoSongs = context.dataStore.get(HideVideoSongsKey, false)
        val specs = allFilterSpecs(hideVideoSongs)

        // Episode search has known parser incompatibilities on the dedicated endpoint;
        // use the already-parsed episode section from the summary response for that one
        // category while the rest use fully-paginated endpoints.
        val episodeSummaryDeferred = async(Dispatchers.IO) {
            YouTube.searchSummary(query).getOrNull()
        }

        val results = specs
            .filter { it.first != YouTube.SearchFilter.FILTER_EPISODE }
            .map { (filter, _) ->
                async(Dispatchers.IO) {
                    filter to YouTube.search(query, filter)
                        .getOrNull()
                }
            }
            .awaitAll()

        results.forEach { (filter, result) ->
            if (result != null) {
                viewStateMap[filter.value] =
                    ItemsPage(
                        items = applySearchFilters(result.items),
                        continuation = result.continuation,
                    )
            }
        }

        val episodeSummary = episodeSummaryDeferred.await()
        if (episodeSummary != null) {
            val filtered = episodeSummary
                .filterExplicit(context.dataStore.get(HideExplicitKey, false))
                .filterVideoSongs(hideVideoSongs)
                .filterYoutubeShorts(context.dataStore.get(HideYoutubeShortsKey, false))
            val episodeItems = filtered.summaries
                .firstOrNull { summary ->
                    summary.title.equals("Episodes", ignoreCase = true) ||
                        summary.title.equals(context.getString(R.string.filter_episodes), ignoreCase = true)
                }?.items.orEmpty()
            viewStateMap[YouTube.SearchFilter.FILTER_EPISODE.value] =
                ItemsPage(items = episodeItems.distinctBy { it.id }, continuation = null)
        }

        allInitialized = true
        rebuildAllSummary()
    }

''',
)
replace_once(
    search_vm,
    r"    private fun initYouTubeSearch\(\) \{.*?\n    \}\n\n    private fun initSpotifySearch",
    r'''    private fun initYouTubeSearch() {
        viewModelScope.launch {
            filter.collect { selectedFilter ->
                if (selectedFilter == null) {
                    loadAllPage()
                } else if (selectedFilter == YouTube.SearchFilter.FILTER_EPISODE) {
                    if (viewStateMap[selectedFilter.value] == null) {
                        loadAllPage()
                    }
                } else if (viewStateMap[selectedFilter.value] == null) {
                    loadSingleFilterPage(selectedFilter)
                }
            }
        }
    }

    private suspend fun loadSingleFilterPage(selectedFilter: YouTube.SearchFilter) {
        YouTube
            .search(query, selectedFilter)
            .onSuccess { result ->
                viewStateMap[selectedFilter.value] =
                    ItemsPage(
                        items = applySearchFilters(result.items),
                        continuation = result.continuation,
                    )
            }.onFailure {
                reportException(it)
            }
    }

    private fun initSpotifySearch''',
    flags=re.DOTALL,
)
replace_once(
    search_vm,
    r"    fun loadMore\(\) \{.*?\n    \}\n\n    private fun loadMoreSpotify",
    r'''    fun loadMore() {
        if (isSpotifySearch.value) {
            loadMoreSpotify()
        } else if (filter.value == null) {
            if (allLoadJob?.isActive == true) return
            allLoadJob =
                viewModelScope.launch {
                    val hideVideoSongs = context.dataStore.get(HideVideoSongsKey, false)
                    val specs = allFilterSpecs(hideVideoSongs)

                    val updates = coroutineScope {
                        specs.mapNotNull { (selectedFilter, _) ->
                            val current = viewStateMap[selectedFilter.value] ?: return@mapNotNull null
                            val continuation = current.continuation ?: return@mapNotNull null
                            async(Dispatchers.IO) {
                                val result = YouTube.searchContinuation(continuation).getOrNull()
                                selectedFilter to result
                            }
                        }.awaitAll()
                    }

                    updates.forEach { (selectedFilter, result) ->
                        if (result != null) {
                            val current = viewStateMap[selectedFilter.value] ?: return@forEach
                            val merged = applySearchFilters(current.items + result.items)
                            viewStateMap[selectedFilter.value] =
                                ItemsPage(items = merged, continuation = result.continuation)
                        }
                    }
                    rebuildAllSummary()
                }
        } else {
            loadMoreYouTube()
        }
    }

    private fun loadMoreYouTube() {
        val filterValue = filter.value?.value ?: return
        viewModelScope.launch {
            val viewState = viewStateMap[filterValue] ?: return@launch
            val continuation = viewState.continuation ?: return@launch
            val searchResult =
                YouTube.searchContinuation(continuation).getOrNull() ?: return@launch
            viewStateMap[filterValue] =
                ItemsPage(
                    items = applySearchFilters(viewState.items + searchResult.items),
                    continuation = searchResult.continuation,
                )
        }
    }

    private fun loadMoreSpotify''',
    flags=re.DOTALL,
)

# ---------------------------------------------------------------------------
# #244 UI: show an explicit continuation/loading row in the All tab and avoid
# O(n^2) key generation from indexOf().
# ---------------------------------------------------------------------------
search_ui = "app/src/main/kotlin/com/metrolist/music/ui/screens/search/OnlineSearchResult.kt"
replace_once(
    search_ui,
    r"key = \{ \"\$\{summary\.title\}/\$\{it\.id\}/\$\{summary\.items\.indexOf\(it\)\}\" \}",
    'key = { "${summary.title}/${it.id}" }',
)
replace_once(
    search_ui,
    r"(if \(searchSummary\?\.summaries\?\.isEmpty\(\) == true\) \{.*?\n                        \})",
    r'''\1

                        if (viewModel.hasMoreAll()) {
                            item(key = "loading") {
                                ShimmerHost {
                                    repeat(3) {
                                        ListItemPlaceHolder()
                                    }
                                }
                            }
                        }''',
    flags=re.DOTALL,
)

# ---------------------------------------------------------------------------
# #259: Android Auto needs a browsable library root. The app advertised a root
# item as non-browsable, so Android Auto could connect to the service but had no
# browseable tree to display.
# ---------------------------------------------------------------------------
callback = "app/src/main/kotlin/com/metrolist/music/playback/MediaLibrarySessionCallback.kt"
replace_once(
    callback,
    r"\.setIsBrowsable\(false\)\n\s+\.setMediaType\(MediaMetadata\.MEDIA_TYPE_FOLDER_MIXED\)",
    ".setIsBrowsable(true)\n                            .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_MIXED)",
)

# ---------------------------------------------------------------------------
# #258: a 403 indicates the currently prepared MediaSource is using an expired
# or otherwise rejected stream URL. Seeking + prepare() can reuse the existing
# MediaSource. Rebuild the current playlist source so ResolvingDataSource runs
# again and obtains a genuinely fresh URL, while preserving queue/order/position.
# Also make URL cache access thread-safe: the resolver and pre-cache job can run
# concurrently on different threads.
# ---------------------------------------------------------------------------
service = "app/src/main/kotlin/com/metrolist/music/playback/MusicService.kt"
replace_once(
    service,
    r"import java\.time\.LocalDateTime\n",
    "import java.time.LocalDateTime\nimport java.util.concurrent.ConcurrentHashMap\n",
)
replace_once(
    service,
    r"private val songUrlCache = HashMap<String, Pair<String, Long>\(\)>",
    "private val songUrlCache = ConcurrentHashMap<String, Pair<String, Long>>()",
)
replace_once(
    service,
    r"    private fun handleExpiredUrlError\(mediaId: String\?\) \{",
    r'''    private fun reprepareCurrentMediaSource() {
        val currentIndex = player.currentMediaItemIndex
        if (currentIndex == C.INDEX_UNSET || player.mediaItemCount == 0) return

        val position = player.currentPosition.coerceAtLeast(0L)
        val wasPlaying = player.playWhenReady
        val items = player.mediaItems

        // Replace the source graph, not just the playback position. This forces the
        // ResolvingDataSource resolver to run again instead of reusing a prepared
        // source that still contains the rejected URL.
        player.setMediaItems(items, currentIndex, position)
        player.prepare()
        player.playWhenReady = wasPlaying
    }

    private fun handleExpiredUrlError(mediaId: String?) {''',
)
replace_once(
    service,
    r"                // Seek to current position to force URL re-resolution\n                val currentPosition = player\.currentPosition\n                val currentIndex = player\.currentMediaItemIndex\n                player\.seekTo\(currentIndex, currentPosition\)\n                player\.prepare\(\)\n\n                Timber\.tag\(TAG\)\.d\(\"Retrying playback for \$mediaId after 403 error\"\)",
    r'''                // Rebuild the prepared MediaSource so the resolver fetches a fresh URL.
                reprepareCurrentMediaSource()

                Timber.tag(TAG).d("Retrying playback for $mediaId after 403 error with a fresh MediaSource")''',
)

print("Batch 3 source transformations applied.")
