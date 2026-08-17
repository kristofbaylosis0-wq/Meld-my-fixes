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


# Prevent duplicate concurrent network requests caused by rapid UI emissions or
# repeated pagination callbacks. The keys are cheap, bounded by active requests,
# and removed in finally blocks so failures never permanently suppress a request.
search_vm = "app/src/main/kotlin/com/metrolist/music/viewmodels/OnlineSearchViewModel.kt"
replace_once(
    search_vm,
    r"import java\.net\.URLDecoder\n",
    "import java.net.URLDecoder\nimport java.util.concurrent.ConcurrentHashMap\n",
)
replace_once(
    search_vm,
    r"(private var allLoadJob: Job\? = null)\n",
    r'''\1
    private val inFlightRequests = ConcurrentHashMap.newKeySet<String>()
''',
)
replace_once(
    search_vm,
    r"    private suspend fun loadSingleFilterPage\(selectedFilter: YouTube\.SearchFilter\) \{\n        YouTube\n            \.search\(query, selectedFilter\)\n            \.onSuccess \{ result ->([\s\S]*?)            \}\.onFailure \{\n                reportException\(it\)\n            \}\n    \}",
    lambda m: '''    private suspend fun loadSingleFilterPage(selectedFilter: YouTube.SearchFilter) {
        val requestKey = "search:${selectedFilter.value}"
        if (!inFlightRequests.add(requestKey)) return
        try {
            YouTube
                .search(query, selectedFilter)
                .onSuccess { result ->''' + m.group(1) + '''            }.onFailure {
                    reportException(it)
                }
        } finally {
            inFlightRequests.remove(requestKey)
        }
    }''',
)
replace_once(
    search_vm,
    r"            val continuation = current\.continuation \?: return@mapNotNull\n            async\(Dispatchers\.IO\) \{\n                val result = YouTube\.searchContinuation\(continuation\)\.getOrNull\(\)\n                selectedFilter to result\n            \}",
    r'''            val continuation = current.continuation ?: return@mapNotNull
            val requestKey = "all-more:${selectedFilter.value}:$continuation"
            if (!inFlightRequests.add(requestKey)) return@mapNotNull null
            async(Dispatchers.IO) {
                try {
                    val result = YouTube.searchContinuation(continuation).getOrNull()
                    selectedFilter to result
                } finally {
                    inFlightRequests.remove(requestKey)
                }
            }''',
)
replace_once(
    search_vm,
    r"        val viewState = viewStateMap\[filterValue\] \?: return@launch\n        val continuation = viewState\.continuation \?: return@launch\n        val searchResult =",
    r'''        val viewState = viewStateMap[filterValue] ?: return@launch
        val continuation = viewState.continuation ?: return@launch
        val requestKey = "more:$filterValue:$continuation"
        if (!inFlightRequests.add(requestKey)) return@launch
        val searchResult =''',
)
replace_once(
    search_vm,
    r"        viewStateMap\[filterValue\] =\n                ItemsPage\(\n                    items = applySearchFilters\(viewState\.items \+ searchResult\.items\),\n                    continuation = searchResult\.continuation,\n                \)\n        \}\n    \}",
    r'''        try {
            viewStateMap[filterValue] =
                ItemsPage(
                    items = applySearchFilters(viewState.items + searchResult.items),
                    continuation = searchResult.continuation,
                )
        } finally {
            inFlightRequests.remove(requestKey)
        }
        }
    }''',
)

# Spotify pagination gets the same de-duplication guarantee. This avoids a burst
# of identical API requests when the footer is recomposed/tapped repeatedly.
replace_once(
    search_vm,
    r"            val continuation = viewState\.continuation \?: return@launch\n\n            // Parse continuation",
    r'''            val continuation = viewState.continuation ?: return@launch
            val requestKey = "spotify-more:$filterType:$continuation"
            if (!inFlightRequests.add(requestKey)) return@launch

            // Parse continuation''',
)
replace_once(
    search_vm,
    r"            Spotify\.search\(\n                query = query,",
    r'''            try {
                Spotify.search(
                    query = query,''',
)
replace_once(
    search_vm,
    r"            \}\.onFailure \{\n                Timber\.e\(it, \"SearchVM: Spotify loadMore failed\"\)\n                reportException\(it\)\n            \}\n        \}",
    r'''                }.onFailure {
                    Timber.e(it, "SearchVM: Spotify loadMore failed")
                    reportException(it)
                }
            } finally {
                inFlightRequests.remove(requestKey)
            }
        }''',
)

print("Batch 3 hardening applied")
