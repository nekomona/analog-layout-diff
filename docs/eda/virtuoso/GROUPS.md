# Logical groups and session definitions

OA permits duplicate group names, so logical-group identity uses canonical
content rather than name alone. Capture preserves set/collection flags,
ordering, multiplicity, deletion policy, registered definition names, properties
and member-link properties. Nested groups and supported pin/instance-terminal
links use explicit references.

Registered group definitions belong to a Virtuoso session. Replay can load them
by opening a designated source read-only; definitions must be available before
construction. Cycles and ambiguous references to identical anonymous objects
remain coverage errors. Duplicate names alone are supported. Group changes can
produce delete/add records for dependent parents; they are not standalone
highlighted geometry. See [the format](../../data/LOGICAL_FORMAT.md#logical-groups).
