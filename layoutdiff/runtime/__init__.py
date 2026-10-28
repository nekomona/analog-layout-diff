"""Background runtime ownership and temporary-resource lifecycle."""
from .supervisor import process_identity, supervise

__all__ = ["process_identity", "supervise"]
