# Persistent layout annotations

Supported records include layer/area blockages, snap boundaries, technology-site
transforms and local attribute/parameter/property text displays. Capture retains
geometry, supported flags, typed properties and explicit owner/associate/parent
links. Site definitions remain external technology data.

The resolver replaces database handles before hashing, creates prerequisites
before dependent annotations and attaches groups last. `textDisplays` and
`assocTextDisplays` are relationship indexes, not additional object collections.

Native behavior requires care: omit an absent blockage owner instead of writing
nil; spacing and effective width are mutually exclusive; routing blockage
density may be readable but not writable. Property displays omit attribute-name
arguments. Nested properties retain root/container paths, and capture records
actual ownership after creation. Text displays may have zero height.

Cross-cellview associates, override masks, missing or ambiguous targets and
cycles remain coverage errors. Native mask colors require compatible technology.
GDS XOR cannot verify these constraints or relationships. See
[category coverage](../CATEGORIES.md).
