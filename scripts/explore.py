"""Read-only live discovery and installed-documentation capture."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("VB_CACHE_DIR", str(ROOT / ".cache"))
from virtuoso_bridge import VirtuosoClient


def save(name, data):
    path = ROOT / "evidence" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def main():
    client = VirtuosoClient.from_env()
    mode = sys.argv[1] if len(sys.argv) > 1 else "environment"
    if mode == "environment":
        data = {"quick_test": client.execute_skill("1+2").model_dump(),
                "ssh": client.run_shell_command("echo ok; pgrep -f '[v]irtuoso' | head -10").model_dump(),
                "docs": client.doc_info(), "libraries": client.library.list()}
        save("environment.json", data)
        print(json.dumps(data, indent=2, default=str))
    elif mode == "docs":
        for name in sys.argv[2:]:
            info = client.get_skill_more_info(name)
            save("docs/" + name + ".json", info)
            print(name, (info or {}).get("plain_text", "NOT FOUND")[:800], flush=True)
    elif mode == "search":
        for query in sys.argv[2:]:
            info = client.search_docs(query, limit=6)
            save("docs/search_" + query.replace(" ", "_") + ".json", info)
            print(json.dumps(info, indent=2, default=str), flush=True)
    elif mode == "pages":
        from virtuoso_bridge.virtuoso.skill_finder.more_info import html_to_plain_text
        for name in sys.argv[2:]:
            target = ROOT / "evidence/docs" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            client.download_file("/opt/cadence/IC231/doc/skdfref/" + name, str(target))
            plain = html_to_plain_text(target.read_text(encoding="utf-8"))
            target.with_suffix(".txt").write_text(plain, encoding="utf-8")
            print(name, plain[:150], flush=True)


if __name__ == "__main__":
    main()
