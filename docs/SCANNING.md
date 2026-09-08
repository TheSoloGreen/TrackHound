# Scan behavior

Each scan takes a snapshot of the user's saved audio preferences, file extensions,
and anime detection settings. Extensions are case insensitive and normalized to
values such as `.mkv`. Invalid or empty extension lists are rejected. An empty
folder keyword list disables folder-based anime detection.

Incremental scans skip a file only when both size and modification time match its
stored values. Choose a full scan to reanalyze unchanged files after changing
preferences, detection settings, or analyzer versions. Manual anime changes
immediately reevaluate the cached audio tracks and issue counts.

## Classification

Manual anime marking or unmarking takes precedence over detection and scan-time
automatic audio edits. Otherwise an Anime scan location forces anime, followed
by matching folder keywords and enabled Plex genre detection. Other location
types provide the underlying movie or TV category. The deepest enabled configured
location wins when roots overlap, even if only its parent is selected for scanning.
Files discovered through overlapping roots are processed once.

`media_type` is the displayed/filterable category. `base_media_type` remembers
movie or TV so unmarking anime restores that category. `is_anime` and
`anime_source` are kept consistent with this choice. For historical anime rows
without an identifiable original category, the migration uses TV. Historical
negative manual choices are preserved where the prior flag/source reveals them.

Plex enrichment is optional. A failed lookup disables enrichment for the rest of
that scan and reports one warning; local path parsing and media analysis continue.
An existing Plex genre classification is retained during an outage unless another
classification rule overrides it. Unreadable stored tokens also allow local scans;
sign in again or restore the matching encryption key before retrying Plex access.

## Missing files and partial scans

A scan removes database records for genuinely missing paths only after every
selected root was fully enumerated, every discovered file was processed, and no
cancellation was requested. Failed probes, permission errors, partial directory
enumeration, and changed/unmounted roots prevent reconciliation. Existing files
excluded by the current extension filter stay indexed.

Cleanup is scoped to the scanning user and selected directories, including proper
directory boundaries. Dependent audio rows and empty seasons/shows are removed.
This cleanup never deletes a media file from disk. Location counts reflect saved
rows; the successful-scan timestamp advances only after reconciliation commits.
Moving a file is represented by removing its old missing row and indexing its new
path. Successful per-file results remain available after an interrupted scan.

The latest outcome, counts, and up to 50 errors and 50 warnings remain in scan
status until the next scan or application restart. Native analysis, Plex calls,
and directory discovery run outside the request event loop, allowing cancellation
and status requests while those operations wait. Cancellation takes effect between
operations; a native operation already running completes or reaches its timeout.

Continue to use one application worker/container per media library. Job state and
edit coordination are in-process; multiple workers and restart-resumable jobs need
a shared job store and shared edit locks before they can be supported.
