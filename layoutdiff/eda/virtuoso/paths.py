"""Session-owned scratch names for an embedded runtime, legacy /tmp otherwise."""
def scratch(client, name):
    allocator = getattr(client, "layoutdiff_scratch", None)
    return str(allocator(name)) if allocator else "/tmp/" + name
