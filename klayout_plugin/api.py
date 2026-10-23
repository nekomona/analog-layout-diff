"""Select one KLayout binding family; never mix embedded pya and pip objects."""
import sys

_embedded = sys.modules.get("pya")
if _embedded is not None and hasattr(_embedded, "Application"):
    db = _embedded
else:
    try:
        import klayout.db as db
    except ImportError:
        import pya as db


def view_api():
    if _embedded is not None and hasattr(_embedded, "Application"):
        return _embedded
    try:
        import klayout.lay as lay
    except ImportError:
        import pya as lay
    return lay
