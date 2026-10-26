"""Compare native diff/apply with Python for saved OA annotation checkpoints."""
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
from layoutdiff.core import diff
from layoutdiff.storage import from_snapshot
from layoutdiff.changeindex import ChangeIndex
from layoutdiff.streampatch import create, apply
from layoutdiff.acceleration import info

source = Path(sys.argv[1])
states = [json.loads((source/f'snapshot{i}.json').read_text()) for i in range(3)]
with tempfile.TemporaryDirectory(prefix='ald_oa_native_') as directory:
    root = Path(directory)
    for i,(before,after) in enumerate(zip(states,states[1:])):
        with closing(from_snapshot(before,root/f'a{i}')) as a, closing(from_snapshot(after,root/f'b{i}')) as b:
            with closing(ChangeIndex(a,b,backend='python')) as py, closing(ChangeIndex(a,b,backend='native')) as native:
                assert py.operations_path.read_bytes() == native.operations_path.read_bytes()
                assert native.rows == py.rows
                assert list(native.operations()) == diff(before,after)['operations']
            create(a,b,root/f'patch{i}',backend='native')
            with closing(apply(a,root/f'patch{i}',root/f'forward{i}',backend='native')) as result:
                assert result.materialize() == after
            with closing(apply(b,root/f'patch{i}',root/f'reverse{i}',backend='native',reverse=True)) as result:
                assert result.materialize() == before
print(json.dumps(dict(annotation_pairs=2, forward_reverse=4, exact_python_parity=True, backend=info())))
