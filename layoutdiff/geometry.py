"""Independent hierarchy-expanded GDS checks using KLayout."""
from collections import Counter
from pathlib import Path


def compare_gds(left, right, *, left_top=None, right_top=None):
    import klayout.db as kdb
    layouts = []
    for path, top in ((left, left_top), (right, right_top)):
        layout = kdb.Layout()
        layout.read(str(path))
        cell = layout.cell(top) if top else layout.top_cell()
        if cell is None:
            raise ValueError("Missing or ambiguous GDS top cell")
        layouts.append((layout, cell))
    (a, ac), (b, bc) = layouts
    if a.dbu != b.dbu:
        raise ValueError("GDS database units differ")
    infos = sorted(set((x.layer, x.datatype) for ly in (a, b) for x in ly.layer_infos()))
    layers = []
    for layer, datatype in infos:
        regions, labels = [], []
        for ly, cell in layouts:
            index = ly.find_layer(layer, datatype)
            regions.append(kdb.Region(cell.begin_shapes_rec(index)) if index is not None else kdb.Region())
            texts = Counter()
            if index is not None:
                iterator = cell.begin_shapes_rec(index)
                while not iterator.at_end():
                    shape = iterator.shape()
                    if shape.is_text():
                        text = shape.text.transformed(iterator.trans())
                        texts[(text.string, str(text.trans))] += 1
                    iterator.next()
            labels.append(texts)
        xor = regions[0] ^ regions[1]
        layers.append({"layer": layer, "datatype": datatype, "xor_empty": xor.is_empty(),
                       "xor_area_dbu2": xor.area(), "labels_equal": labels[0] == labels[1],
                       "left_area_dbu2": regions[0].merged().area(),
                       "right_area_dbu2": regions[1].merged().area()})
    return {"equal": all(x["xor_empty"] and x["labels_equal"] for x in layers),
            "has_geometry": any(x["left_area_dbu2"] > 0 or x["right_area_dbu2"] > 0 for x in layers),
            "dbu_um": a.dbu, "layers": layers}


def export(client, lib, cell, destination, stream_map):
    """Use the supported XStream renderer, with portable SHA-256 publication.

    The host's bridge high-level publisher rejects its own Windows temp file
    identity. Keep this local adapter independent of that unrelated module.
    Each run has a fresh remote directory; poll terminal failures every time.
    """
    import hashlib
    import os
    import shlex
    import time
    import uuid
    from virtuoso_bridge.virtuoso.layout import XStreamExportRequest, xstream_export_gds_skill, parse_xstream_log
    from .virtuoso import checked
    run = "/tmp/ald_gds_" + uuid.uuid4().hex
    response = client.ssh_runner.run_command("mkdir -m 700 " + shlex.quote(run))
    if response.returncode:
        raise RuntimeError(response.stderr)
    # IC23.1's map parser rejects Windows CRLF records as XSTRM-25.
    normalized_map = Path(destination).with_suffix(".stream.map")
    normalized_map.write_bytes(Path(stream_map).read_bytes().replace(b"\r\n", b"\n"))
    client.upload_file(str(normalized_map), run + "/stream.map")
    request = XStreamExportRequest(library=lib, top_cell=cell, view="layout",
                                  stream_file=run+"/output.gds", layer_map=run+"/stream.map",
                                  log_file=run+"/xstream.log", run_dir=run)
    checked(client.execute_skill(xstream_export_gds_skill(request), timeout=30))
    deadline = time.monotonic() + 90
    destination = Path(destination)
    while time.monotonic() < deadline:
        observation = client.ssh_runner.run_command("tail -n 200 " + shlex.quote(run + "/xstream.log"))
        log = observation.stdout
        destination.with_suffix(".xstream.log").write_text(log, encoding="utf-8")
        result = parse_xstream_log(log)
        if result.terminal_failures or (result.completed and result.error_count):
            raise RuntimeError("XStream failure: " + log[-4000:])
        if result.completed and result.error_count == 0:
            # Poll the tail for speed, but classify the complete log before accepting
            # a result so early unmapped-layer warnings cannot fall out of the tail.
            client.download_file(run + "/xstream.log", str(destination.with_suffix(".xstream.log")))
            log = destination.with_suffix(".xstream.log").read_text(encoding="utf-8", errors="replace")
            result = parse_xstream_log(log)
            if not result.completed or result.error_count != 0 or result.terminal_failures or result.parse_errors:
                raise RuntimeError("Invalid final XStream log: " + str(destination.with_suffix('.xstream.log')))
            def remote_hash():
                r = client.ssh_runner.run_command("sha256sum " + shlex.quote(run + "/output.gds"))
                if r.returncode:
                    raise RuntimeError(r.stderr)
                return r.stdout.split()[0]
            before = remote_hash()
            temp = destination.with_suffix(".gds.part")
            client.download_file(run + "/output.gds", str(temp))
            if temp.stat().st_size == 0 or hashlib.sha256(temp.read_bytes()).hexdigest() != before or remote_hash() != before:
                raise RuntimeError("Unstable or corrupt GDS transfer")
            os.replace(temp, destination)
            # This installation displays a modal completion acknowledgement.
            # Touch only this exact dialog title; leave every design/editor alone.
            from virtuoso_bridge.virtuoso import x11
            runner = client.docs_runner
            for window in x11.list_windows(runner, runner.user, top_level=True):
                if window.get("title") == "Stream out translation complete":
                    x11.dismiss_window(runner, runner.user, window["dismiss_id"],
                                       display=window.get("display"), action="enter")
            if any(code in log for code in ("XSTRM-25)", "XSTRM-35)", "XSTRM-399)")):
                raise RuntimeError("Export dropped geometry or rejected its layer map; inspect " + str(destination.with_suffix('.xstream.log')))
            return {"remote_run": run, "sha256": before, "warnings": result.warning_count}
        time.sleep(0.5)
    raise TimeoutError("XStream did not complete: " + run)
