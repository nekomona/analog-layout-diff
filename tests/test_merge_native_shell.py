"""Check native source structure before loading disposable GUI testbenches."""
from pathlib import Path


def test_merge_shell_balanced_top_level_procedures():
    source = (Path(__file__).parents[1] / 'layoutdiff/eda/virtuoso/skill/merge.il').read_text()
    depth = 0
    quoted = escaped = comment = False
    for ch in source:
        if comment:
            if ch == '\n':
                comment = False
            continue
        if quoted:
            if ch == '"' and not escaped:
                quoted = False
            escaped = ch == '\\' and not escaped
        elif ch == ';':
            comment = True
        elif ch == '"':
            quoted = True
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            assert depth >= 0
    assert depth == 0 and not quoted
