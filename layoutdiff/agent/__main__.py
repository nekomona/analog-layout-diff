"""Optional Bridge SSH-runner entry point for file-only remote operations."""
import argparse
import json
import os
from pathlib import Path
import uuid

from layoutdiff.agent import OPERATIONS
from layoutdiff.agent.service import AgentService, identifier
from layoutdiff.data.storage import strict_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, help='Dedicated agent state directory outside the project tree')
    parser.add_argument('--request-id', required=True)
    parser.add_argument('--operation', choices=OPERATIONS, required=True)
    parser.add_argument('--payload', required=True, help='JSON request file on this host')
    args = parser.parse_args()
    ident = identifier(args.request_id)
    payload = strict_json(Path(args.payload).read_bytes())
    raw = args.operation + '\n' + json.dumps(payload, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    service = AgentService(args.root, publish_capabilities=False)
    try:
        path = service.requests / (ident + '.request')
        if path.exists():
            if path.read_text(encoding='utf-8') != raw:
                raise ValueError('Request ID already has a different payload')
        else:
            # Complete file first, then create the immutable request atomically.
            temp = path.with_name(path.name + '.' + uuid.uuid4().hex)
            temp.write_text(raw, encoding='utf-8')
            try:
                os.link(temp, path)
            finally:
                temp.unlink()
        service.poll(request_id=ident)
        result = service.requests / (ident + '.result.json')
        print(result.read_text() if result.exists() else json.dumps({'request_id': ident, 'status': 'pending'}))
    finally:
        service.close()


if __name__ == '__main__':
    main()
