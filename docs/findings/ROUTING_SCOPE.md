# Routing scope

## Approved design decision: exclude routes, markers and Steiners

Routes, markers and Steiners can persist in OA and carry topology, connectivity,
routing or verification state. GDS does not certify those semantics. The codec
deliberately excludes them, including links from retained groups. Independent
member shapes/vias and supported scalar connectivity remain captured.

This is a format scope policy, not a claim that the objects are temporary.
Replay cannot restore the excluded topology or annotations. Future support would
need explicit identities, typed relationships, native creation rules and exact
readback tests. `dbWriteSkill` has documented attribute omissions and is not a
lossless fallback. Consult the installed database references before extending
capture, and test with independent synthetic native objects.
