"""Validate local documentation links and Markdown heading anchors."""
from pathlib import Path
import collections
import re
from urllib.parse import unquote

root=Path(__file__).resolve().parents[1]
docs=root/'docs'

def text(path): return path.read_text(encoding='utf-8')
def unfenced(value):
    output=[]; fence=None
    for line in value.splitlines():
        m=re.match(r'^\s*(`{3,}|~{3,})',line)
        if m:
            marker=m.group(1)[0]
            if fence is None: fence=marker
            elif fence==marker: fence=None
            continue
        if fence is None: output.append(line)
    return '\n'.join(output)
def slug(value):
    value=re.sub(r'<[^>]+>','',value)
    return re.sub(r'[^\w\- ]','',value.lower()).replace(' ','-')
def anchors(value):
    found=set();counts=collections.Counter()
    for line in unfenced(value).splitlines():
        match=re.match(r'^#{1,6} (.+)',line)
        if match:
            key=slug(match.group(1));number=counts[key];counts[key]+=1
            found.add(key+(f'-{number}' if number else ''))
    found.update(re.findall(r'<a\s+(?:name|id)=[\'"]([^\'"]+)',value))
    return found

files=[root/'README.md',root/'klayout_plugin/README.md',*sorted(docs.rglob('*.md'))]
errors=[];checked=0
for path in files:
    for match in re.finditer(r'\]\(([^)\n]+)\)',unfenced(text(path))):
        raw=match.group(1)
        if re.match(r'\w+://|mailto:',raw): continue
        target,_,fragment=unquote(raw).partition('#')
        dest=(path.parent/target).resolve() if target else path
        checked+=1
        if not dest.exists(): errors.append((str(path.relative_to(root)),raw,'missing file'))
        elif fragment and dest.suffix=='.md' and fragment not in anchors(text(dest)):
            errors.append((str(path.relative_to(root)),raw,'missing anchor'))
        if not dest.is_relative_to(root): errors.append((str(path.relative_to(root)),raw,'outside repository'))
print('Checked local Markdown links:',checked)
for error in errors: print('ERROR',*error)

assert not errors, errors
