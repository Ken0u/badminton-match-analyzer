# Upload and YouTube import verification

Verified October 17, 2026. This report concerns importing and decoding media; it does not claim that the video has been automatically or correctly annotated.

The real-source smoke test imported BWF TV's [HSBC Play of the Day: Arif/Yap and Kim/Seo](https://www.youtube.com/watch?v=5BJxZYe-S-I) through `POST /api/import/youtube` into an isolated catalog. No browser cookies or account credentials were supplied to the downloader.

| Evidence | Observed result |
| --- | --- |
| Downloaded media | 21,600,568 bytes, MP4/H.264 |
| Source frames | 1,488 frames, 1920x1080, 25 fps |
| Decoded duration | 59.52 seconds |
| Content ID | `b7f3d39660df13fb`, derived from the SHA-256 of downloaded bytes |
| Publisher provenance | YouTube ID `5BJxZYe-S-I`, canonical watch URL, title, BWF TV channel ID, and upload date retained under `source` |
| Exact source image | Source frame 10 returned JPEG, HTTP 200 |
| Playback transport | HTTP range request bytes 0-31 returned 206 |

The source's YouTube ID never replaces the local content ID. The smoke test also verified the completed import job and catalog entry. Detailed local evidence is in `.cache/youtube-api-smoke-result.json`; media and local catalogs remain excluded from Git. YouTube may deliver different encoded bytes on a later run, so a content ID is not a permanent publisher identifier.

Generated-video regression tests cover upload decoding, frame timestamps, unsupported/empty/mislabeled files, size bounds including chunked requests, failure/conflict cleanup, duplicate source reuse, preservation of reviewed annotations and provenance, invalid YouTube URL rejection, downloader errors, authentication, and cross-site mutation rejection. Stubbed downloader tests exercise metadata and file failure cases without network access; they complement the actual public-video smoke test.

Rotated phone footage is normalized consistently for court dimensions, posters, exact-frame review, and both CV stages, while retaining the original uploaded bytes and source timestamps. Tests use genuine MP4 display matrices at 0, 90, 180, and 270 degrees. Chromium playback was compared against normalized images for all four orientations; dimensions and rotation agree, with the same small browser/decoder color difference at each angle. Unsupported mirrored, scaled, skewed, or noncardinal display transforms produce an explicit import error. Incremental download progress is tested with hundreds of small updates so a long download cannot appear stuck at zero merely because each update is below the display threshold.

The app accepts ordinary MP4, MOV, MKV, AVI, and WebM containers. Successful PyAV decoding does not prove a browser supports every codec/container. Exact-frame review is available when playback is unsupported; a browser-compatible proxy/transcoding stage remains a product requirement. The current downloader chooses one available video stream, with video-only fallback. Public completed YouTube URLs are the current input contract; playlists, active streams, and videos requiring sign-in are rejected. Imported video content still needs the analysis pipeline and review.
