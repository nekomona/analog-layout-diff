# Standard-via default readback

Native creation can omit explicit row/column overrides equal to technology
defaults. The installed `dbCreateVia` reference advises against specifying
defaults in the parameter list. Query defaults through the destination via
definition; never assume a particular foundry value.

Only native reconstruction comparison removes proven redundant integer row or
column overrides. Stored snapshots and generic diff/apply remain exact. The
comparison updates logical-group reference keys, preserves duplicate counts,
and rejects ambiguous referenced duplicates. All other geometry, parameters,
properties and connectivity remain checked. Raw readback and accepted
normalizations are retained in local artifacts.
