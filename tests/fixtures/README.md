# Synthetic compatibility fixtures

`legacy_history/` contains a synthetic three-commit v1 operation chain and its
expected final snapshot. Its hashes and parent links exercise legacy replay.
`moved_vias.json` contains independently generated via translations, cut-array
resizing and an orientation change. It checks matching in both review paths.
Neither fixture contains captured layout data or a foundry device recipe.
