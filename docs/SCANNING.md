# Scan behavior

Each scan takes a snapshot of the user's saved audio preferences, file extensions,
and anime detection settings. Extensions are case insensitive and normalized to
values such as `.mkv`. Invalid or empty extension lists are rejected. An empty
folder keyword list disables folder-based anime detection.

Incremental scans skip a file only when size and modification time match and its
saved analysis version is current. Missing/untrusted historical analysis is probed
again. Choose a full scan to reanalyze otherwise unchanged files after changing
detection settings or when refreshing metadata. Changed audio-evaluation rules
queue cached reevaluation in 0.5.0; that job never probes or edits media and uses
the saved title classification. Manual anime changes immediately reevaluate the
cached audio tracks and issue counts.

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

Plex enrichment is optional. A connection/inventory failure disables enrichment
for the rest of that scan and reports one warning; a simply unmatched title does
not disable Plex. Local path parsing and media analysis continue.
An existing Plex genre classification is retained during an outage unless another
classification rule overrides it. Unreadable stored tokens also allow local scans;
sign in again or restore the matching encryption key before retrying Plex access.

### Plex TV identity and review

An unambiguous exact path takes precedence over titles. Across different mount
roots, a relative path must include the show folder and, where present, the season
folder as well as the filename, and identify only one Plex title. A generic
`Season 01/E01.mkv` suffix cannot choose between unrelated shows. Flat show folders,
specials, backslash paths, original titles, and title variants are supported as
matching evidence. This is not configurable prefix mapping or server/library
selection; those remain [#82](https://github.com/TheSoloGreen/TrackHound/issues/82).

Colliding aliases are retained. A title/year hint can distinguish remakes; a
fuzzy fallback is accepted only when a single Plex identity clears the matching
threshold, not simply because it ranks first. Ambiguous stronger evidence is not
overridden by a weaker title guess. An incomplete Plex episode inventory is not
used to establish uniqueness.

Ambiguous TV matches are left unresolved and reported with the local file path,
matching strategy, and number of candidate titles in Dashboard/Jobs warnings.
Local audio analysis continues and other files can still receive Plex metadata.
Existing identity/artwork are not replaced, and existing Plex-based anime
classification is retained unless another classification rule overrides it.
Automatic media edits are skipped for an ambiguous file, including when automatic
default fixing is enabled. Review the paths/title/year and rescan once identity
is clear; full scans refresh unchanged records. There is no automatic unmerge or
repair of previously misidentified records when the new lookup remains ambiguous.

Episode matching also checks all media parts and refuses multiple matching episode
identities. Episode ranges, absolute anime numbering, and reliable episode-metadata
import remain [#68](https://github.com/TheSoloGreen/TrackHound/issues/68).

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

## Durable execution and retained results

Scans, file/title rescans, and individual edits acknowledge a queued database-backed
job with HTTP 202. One FIFO worker owns execution; requests return without waiting
for the operation. Jobs retains active work and the latest 200 finished jobs per
account, with a 100-active-job limit. Results include up to 50 errors and 50 warnings
with complete message counts. The latest saved scan remains available after restart;
per-file change history is separate work in [#78](https://github.com/TheSoloGreen/TrackHound/issues/78).

Queued jobs resume after restart. Work that was running is marked interrupted and
is not automatically replayed. A second app process against the same catalog is
rejected by a lifetime database/file lock; use one worker/container per catalog.

Native analysis, Plex calls, and discovery run outside the request event loop.
MediaInfo uses a disposable process with a 60-second deadline; scan cancellation
can stop/reap that process and is checked between operations. Native default edits
and remuxes have bounded deadlines (60 and 3600 seconds respectively; native
inspection uses 30 seconds). Running physical edits cannot be cancelled mid-write;
queued edits can be cancelled. Catalog resets/location changes are blocked during
that account's active work. Scan and job times are UTC and displayed consistently
in the browser's local timezone.

Remuxes retain an original `.bak` and refuse to overwrite it. Default edits do not
have an undo journal. Capacity preflight, full non-audio stream verification, and
reviewed crash-recovery controls remain [#66](https://github.com/TheSoloGreen/TrackHound/issues/66).
Do not test writes or forced-restart recovery against irreplaceable media.
