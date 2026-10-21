# Mac player/pose development diagnostic

Task [#176](https://github.com/Ken0u/badminton-match-analyzer/issues/176)
exercises actual automatic player/pose analysis on original development footage.
The [frozen manifest](../data/manifests/mac_player_runtime_v1.json) fixes the
source, native clock, annotation revision, both installed checkpoint hashes,
50 native frames and five overlay frames before inference. No held-out data,
downloads, threshold changes, training or model promotion are permitted.

Execution and source-overlay inspection are pending. This report will record
actual results before publication. Counts do not measure accuracy or identity.
