# Phase 1 Code Modifications & Workarounds Log

This document records all modifications, workarounds, or localized script copies created under `freqid/research/` during Phase 1. In accordance with Hard Rule 1, **no existing TFace file has been modified in place**.

## Log of Changes

| Component / Original File | Local Copy / Location | Reason for Copy / Modification | Description of Diff |
| :--- | :--- | :--- | :--- |
| `dareblopy` dependency in `.venv` | `.venv/lib/python3.12/site-packages/dareblopy.py` | `dareblopy` (v0.0.5) lacks Python 3.12 wheels on PyPI and is only used for legacy TFRecord reading. | Implemented lightweight shim class `RecordReader` in `.venv` to allow imports of `torchkit.data.parser` without modifying original source code. |
| Protobuf v3 runtime descriptor compatibility | `.venv/lib/python3.12/site-packages/protobuf_env.pth` | Generated `_pb2.py` files in `torchkit/data/` were compiled with protoc < 3.19. Modern protobuf requires pure-Python runtime parsing. | Injected `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` via `.pth` site-packages configuration hook. |
| Git ignore isolation | `.git/info/exclude` | Prevent local virtualenv and research outputs from dirtying `.gitignore` (which is a tracked TFace file). | Added `.venv/`, `data/`, and `freqid/research/outputs/` to local git exclude rules. |
