# Multipart paths and anonymous geometry matching

## ROD multipart paths and anonymous geometry correspondence

MPP masters and generated subshapes are ordinary cellview figures. Reading only
those figures preserves geometry but loses the ROD recipe and editing behavior.
Capture records an `mpp` recipe on the master and `mppOwner` on members, including
choppability, chop holes, subpart roles, dimensions, spacing and connectivity.
Replay uses native `rodCreatePath`, then matches/reuses generated members by
exact integer-DBU geometry within their owner. Missing/extra geometry fails.

ROD objects require their own accessors. Chop-hole representation can include
cached aggregates in database units; validate it and convert units only once.
Unsupported alignment, custom handles, subpart pins/terminals, custom names or
members can cause atomic omission of the entire MPP after explicit consent.

A recipe may name a net absent from the actual OA net set. Preserve that string
without treating it as a mandatory missing record. Actual member connections
still require real nets. Replay removes only recipe-created, unused dangling
nets absent from the checkpoint. Existing rejected nets propagate omissions.

Replay orders equal-priority records by canonical content and key. Restore MPP
properties after figure connectivity, masters before members, and before
property-linked displays, because native callbacks can alter earlier properties.
Full property readback stays strict.

Native comparison has narrow exceptions: generated subpart numbers may differ
when role/parameters match; a uniform member net can populate an otherwise empty
rectangle recipe; a held review may expose an effective offset-path net instead
of an absent recipe-only name. The latter requires unique identical members,
no pins/terminals, compatible real nets and otherwise exact recipes. Ambiguous
or live-net changes fail. Accepted aliases are logged; Git keeps captured data.
Only generated review cells may be saved to settle deferred ROD callbacks.

Historical flattened snapshots remain flattened; replay does not invent a
recipe from a current PDK or live source.

## Via position matching

Exact keys hash full records, so moved anonymous figures produce delete/add.
Presentation derives conservative correspondence without changing patch identity.
It uses MPP names, identical geometry, unique/common translations and reciprocal
geometric candidates. Ambiguity remains add/delete.

Vias have origins and parameter overrides without a saved footprint. The point
pass groups compatible definition/purpose/net and nondimensional overrides,
prefers identical geometry, then considers size/orientation edits. Reciprocal
nearest choices require a sufficiently separated runner-up; ties are refused.
Large groups use bounded spatial queries. Both review implementations share
this matcher. Synthetic fixtures exercise movement, resizing and rotation.
