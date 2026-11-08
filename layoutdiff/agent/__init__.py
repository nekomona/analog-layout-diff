"""Remote agent access to the existing layout analysis and Git snapshots."""

PROTOCOL = "layoutdiff-agent/1"
OPERATIONS = ("diff", "merge_plan", "merge_explain", "merge_apply", "export")
