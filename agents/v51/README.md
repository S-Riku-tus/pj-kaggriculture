# V51

V51 tests a capacity-matched Wheat logistics correction on V14. It lowers a
pickup to one Wheat only when distinct current/prospective carriers can each
reach a distinct unfed animal before the end of the day. Otherwise it preserves
V14's original batch exactly.

The experiment is disabled and rejected. In ten paired starter diagnostics it
reduced mean requested Wheat from 725.8 to 686.8 and preserved zero animal loss,
but mean reward fell from 129244.0 to 128131.8. Three of five distinct seeds
regressed and the worst paired reward delta was -24943. Reachability alone did
not guarantee stable mission execution or FEED coverage.

The rating-3000 goal remains aspirational and unverified.
