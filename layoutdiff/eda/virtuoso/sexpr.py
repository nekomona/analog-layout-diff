"""Strict data-only reader for SKILL %L output (never evaluates source)."""
import re

TOKEN = re.compile(r'\s*("(?:\\.|[^"\\])*"|[()]|[^\s()]+)', re.S)


def loads(text):
    tokens = TOKEN.findall(text)
    pos = 0

    def read():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("Truncated SKILL data")
        token = tokens[pos]
        pos += 1
        if token == "(":
            result = []
            while pos < len(tokens) and tokens[pos] != ")":
                result.append(read())
            if pos >= len(tokens):
                raise ValueError("Unterminated SKILL list")
            pos += 1
            return result
        if token == ")":
            raise ValueError("Unexpected closing parenthesis")
        if token.startswith('"'):
            chars, i = [], 1
            while i < len(token) - 1:
                c = token[i]
                if c == "\\":
                    i += 1
                    c = {"n": "\n", "t": "\t", "r": "\r"}.get(token[i], token[i])
                chars.append(c)
                i += 1
            return "".join(chars)
        if token == "nil":
            return None
        if token == "t":
            return True
        if re.fullmatch(r'[+-]?\d+', token):
            return int(token)
        if re.fullmatch(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?', token):
            return float(token)
        # Symbols are distinct from strings, notably in ILList properties.
        return {"symbol": token}

    result = read()
    if pos != len(tokens):
        raise ValueError("Trailing SKILL data")
    return result


def dumps(value):
    if value is None or value is False:
        return "nil"
    if value is True:
        return "t"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"'
    if isinstance(value, (float, int)):
        import math
        if not math.isfinite(value):
            raise ValueError("Nonfinite number")
        return repr(value)
    if isinstance(value, list):
        return "list(" + " ".join(dumps(x) for x in value) + ")"
    if isinstance(value, dict) and set(value) == {"symbol"} and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', value["symbol"]):
        return "'" + value["symbol"]
    raise ValueError("Unsupported SKILL value: " + repr(value))
