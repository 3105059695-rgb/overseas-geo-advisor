"""Optional, offline multilingual dense retrieval. No inference API or auto-download.

Only ``setup`` accesses the network, downloading two pinned official model files
directly into one model directory. ``build`` and ``search`` are entirely local.
E5 recipe: query/passages prefixes, attention-mask mean pooling, L2 normalization.
Model: https://huggingface.co/intfloat/multilingual-e5-small
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import gzip
import importlib.metadata
import json
from pathlib import Path
import sys
import time
import urllib.request

RUNTIME = Path(__file__).resolve().parents[2] / ".runtime"
DEFAULT_MODEL_DIR = RUNTIME / "models" / "multilingual-e5-small-int8"
DEFAULT_INDEX_DIR = RUNTIME / "vector-index"
MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
ASSETS = {
    "model.onnx": {"remote": "onnx/model_qint8_avx512_vnni.onnx", "bytes": 118346824,
                   "sha256": "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"},
    "tokenizer.json": {"remote": "tokenizer.json", "bytes": 17082730,
                       "sha256": "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"},
}
MODEL_METADATA = {"model_id": MODEL_ID, "revision": REVISION, "dimensions": 384,
                  "onnx_sha256": ASSETS["model.onnx"]["sha256"],
                  "tokenizer_sha256": ASSETS["tokenizer.json"]["sha256"],
                  "pooling": "attention_mask_mean_then_l2", "max_tokens": 512,
                  "query_prefix": "query: ", "passage_prefix": "passage: ",
                  "passage_title_max_chars": 96, "body_window_tokens": 400,
                  "body_window_overlap_tokens": 48,
                  "quantization": "qint8", "runtime": "onnxruntime_cpu"}


def _json(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _numpy():
    try:
        import numpy
        return numpy
    except ImportError as exc:
        raise RuntimeError("Optional vector dependencies are absent; install requirements-vectors.txt into an existing compatible Python environment.") from exc


def setup(model_dir: Path = DEFAULT_MODEL_DIR) -> dict:
    """Explicit, bounded download. No Hugging Face home/cache or duplicate runtime."""
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    reused, downloaded = [], []
    for name, asset in ASSETS.items():
        path = model_dir / name
        if path.is_file() and path.stat().st_size == asset["bytes"] and _sha256(path) == asset["sha256"]:
            reused.append(name)
            continue
        if path.exists():
            raise ValueError(f"Unexpected existing model file; refusing to overwrite: {path}")
        temporary = model_dir / (name + ".partial")
        url = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{asset['remote']}"
        request = urllib.request.Request(url, headers={"User-Agent": "geo-local-vectors/0.5"})
        count, digest = 0, hashlib.sha256()
        print(f"Downloading {name}: {asset['bytes']} bytes", file=sys.stderr, flush=True)
        try:
            with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as target:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    count += len(block)
                    if count > asset["bytes"]:
                        raise ValueError(f"Download exceeded pinned size: {name}")
                    digest.update(block)
                    target.write(block)
            if count != asset["bytes"] or digest.hexdigest() != asset["sha256"]:
                raise ValueError(f"Pinned model size/hash verification failed: {name}")
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()  # only this command's incomplete download
        downloaded.append(name)
    report = {"model": MODEL_METADATA, "model_dir": str(model_dir.resolve()),
              "bytes": sum(a["bytes"] for a in ASSETS.values()), "downloaded": downloaded, "reused": reused,
              "source": f"https://huggingface.co/{MODEL_ID}/tree/{REVISION}", "license": "MIT"}
    _write_json(model_dir / "model-manifest.json", report)
    return report


class LocalEncoder:
    """Local quantized transformer. Constructing this never downloads anything."""
    metadata = MODEL_METADATA

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR, threads: int = 4):
        np = _numpy()
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise RuntimeError("Optional vector dependencies are absent; install requirements-vectors.txt into an existing compatible Python environment.") from exc
        model_dir = Path(model_dir)
        for name, asset in ASSETS.items():
            path = model_dir / name
            if not path.is_file():
                raise FileNotFoundError(f"Local model missing: {path}. Run geo_vectors.py setup explicitly first.")
            if path.stat().st_size != asset["bytes"] or _sha256(path) != asset["sha256"]:
                raise ValueError(f"Local model does not match pinned model hash: {path}")
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(int(threads), 16))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_dir / "model.onnx"), sess_options=options,
                                           providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        self.input_names = {item.name for item in self.session.get_inputs()}
        self.truncated_count = 0
        self.dependencies = {name: importlib.metadata.version(name) for name in ("numpy", "onnxruntime", "tokenizers")}

    def split_text(self, text: str, token_budget: int = 400, overlap: int = 48) -> list[dict]:
        """Cover full passage using overlapping token-offset windows, preserving text."""
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        try:
            offsets = self.tokenizer.encode(text, add_special_tokens=False).offsets
        finally:
            self.tokenizer.enable_truncation(max_length=512)
            self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>"), pad_token="<pad>")
        if len(offsets) <= token_budget:
            return [{"text": text, "char_start": 0, "char_end": len(text)}]
        windows = []
        for start in range(0, len(offsets), token_budget - overlap):
            end = min(start + token_budget, len(offsets))
            char_start = 0 if start == 0 else offsets[start][0]
            char_end = len(text) if end == len(offsets) else offsets[end - 1][1]
            windows.append({"text": text[char_start:char_end], "char_start": char_start, "char_end": char_end})
            if end == len(offsets):
                break
        return windows

    def encode(self, texts: list[str], *, query: bool = False):
        np = _numpy()
        if not texts:
            return np.empty((0, self.metadata["dimensions"]), dtype=np.float32)
        prefix = "query: " if query else "passage: "
        batch = self.tokenizer.encode_batch([prefix + text for text in texts])
        self.truncated_count += sum(bool(item.overflowing) for item in batch)
        ids = np.asarray([item.ids for item in batch], dtype=np.int64)
        mask = np.asarray([item.attention_mask for item in batch], dtype=np.int64)
        inputs = {"input_ids": ids, "attention_mask": mask,
                  "token_type_ids": np.asarray([item.type_ids for item in batch], dtype=np.int64)}
        hidden = self.session.run(None, {name: inputs[name] for name in self.input_names})[0]
        if hidden.ndim != 3:
            raise ValueError("Expected token hidden states for masked-mean E5 pooling")
        weights = mask[:, :, None].astype(np.float32)
        pooled = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1)
        pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
        if pooled.shape[1] != self.metadata["dimensions"] or not np.isfinite(pooled).all():
            raise ValueError("Invalid encoder dimensions or non-finite embeddings")
        return pooled.astype(np.float32)


def _records(chunks_jsonl: Path | None, data_root: Path | None) -> list[dict]:
    if chunks_jsonl:
        with Path(chunks_jsonl).open(encoding="utf-8-sig") as stream:
            records = [json.loads(line) for line in stream if line.strip()]
    elif data_root:
        root = Path(data_root).resolve()
        catalog = _json(root / "catalog.json")["documents"]
        documents, records = {}, []
        for chunk in _json(root / "chunks.json"):
            document_id, version = chunk["document_id"], chunk["source_version"]
            key = (document_id, version)
            if key not in documents:
                path = (root / "documents" / document_id / (version + ".json")).resolve()
                if not path.is_relative_to(root / "documents"):
                    raise ValueError("Document path escapes snapshot")
                document = _json(path)
                if document["document_id"] != document_id or document["source_version"] != version:
                    raise ValueError("Document version mismatch")
                documents[key] = document["text"].splitlines()
            start, end = chunk["line_start"], chunk["line_end"]
            if not 1 <= start <= end <= len(documents[key]):
                raise ValueError("Invalid chunk source line range")
            meta = catalog[document_id]
            records.append({"document_id": document_id, "source_version": version,
                            "chunk_id": chunk["id"], "line_start": start, "line_end": end,
                            "title": meta["title"], "work_id": meta.get("work_id"),
                            "section_path": chunk.get("heading", ""), "metadata": meta,
                            "text": "\n".join(documents[key][start - 1:end])})
    else:
        raise ValueError("Provide chunks_jsonl or data_root")
    if not records or len(records) > 100000:
        raise ValueError("Index must contain 1–100000 passages")
    for record in records:
        for name in ("document_id", "source_version", "line_start", "line_end", "text"):
            if name not in record:
                raise ValueError(f"Missing required chunk field: {name}")
        if not isinstance(record["text"], str) or not record["text"].strip():
            raise ValueError("Empty/non-string passage")
        if not 1 <= record["line_start"] <= record["line_end"]:
            raise ValueError("Invalid passage source line range")
    return records


def build_index(index_dir: Path = DEFAULT_INDEX_DIR, model_dir: Path = DEFAULT_MODEL_DIR,
                *, chunks_jsonl: Path | None = None, data_root: Path | None = None,
                batch_size: int = 8, encoder=None) -> dict:
    """Build from normalized ingestion JSONL, or explicitly from snapshot passages.

    The index stores compact vectors and provenance only. Original text is never
    rewritten. Input records beyond 512 model tokens are counted in the manifest.
    ``encoder`` injection is for deterministic fixture tests, not a hash fallback.
    """
    np = _numpy()
    if not 1 <= batch_size <= 64:
        raise ValueError("batch_size must be 1–64")
    source_records = _records(chunks_jsonl, data_root)
    encoder = encoder or LocalEncoder(model_dir)
    model = dict(encoder.metadata)
    records = []
    for record in source_records:
        windows = encoder.split_text(record["text"]) if hasattr(encoder, "split_text") else [{"text": record["text"], "char_start": 0, "char_end": len(record["text"])}]
        for window_index, window in enumerate(windows):
            records.append({**record, "text": window["text"], "vector_window": {
                "index": window_index, "count": len(windows), "char_start": window["char_start"],
                "char_end": window["char_end"], "token_budget": 400, "overlap_tokens": 48}})
    digest = hashlib.sha256(json.dumps(model, sort_keys=True).encode())
    for record in records:
        digest.update(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    fingerprint = digest.hexdigest()
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = index_dir / "index.json"
    if manifest_path.is_file():
        previous = _json(manifest_path)
        if previous.get("fingerprint") == fingerprint:
            if all((index_dir / previous[k]).is_file() and _sha256(index_dir / previous[k]) == previous[k + "_sha256"]
                   for k in ("vectors_file", "records_file")):
                return {**previous, "reused": True}
    started = time.monotonic()
    vectors = np.empty((len(records), model["dimensions"]), dtype=np.float16)
    for offset in range(0, len(records), batch_size):
        batch = records[offset:offset + batch_size]
        passages = [str(item.get("title", ""))[:96] + "\n" + item["text"] for item in batch]
        encoded = encoder.encode(passages, query=False)
        if encoded.shape != (len(batch), model["dimensions"]) or not np.isfinite(encoded).all():
            raise ValueError("Encoder returned invalid batch")
        vectors[offset:offset + len(batch)] = encoded
        if offset % (batch_size * 16) == 0 or offset + len(batch) == len(records):
            print(f"Encoded {offset + len(batch)}/{len(records)} passages ({time.monotonic() - started:.1f}s)", file=sys.stderr, flush=True)
    # A generation's files are immutable; switching index.json is the only live mutation.
    vectors_file, records_file = f"{fingerprint[:20]}.npy", f"{fingerprint[:20]}.json.gz"
    vector_path, record_path = index_dir / vectors_file, index_dir / records_file
    with (index_dir / (vectors_file + ".partial")).open("wb") as stream:
        np.save(stream, vectors, allow_pickle=False)
    (index_dir / (vectors_file + ".partial")).replace(vector_path)
    rows = []
    for record in records:
        rows.append({**{key: value for key, value in record.items() if key != "text"},
                     "original_url": record.get("original_url") or record.get("metadata", {}).get("original_url"),
                     "passage_sha256": hashlib.sha256(record["text"].encode()).hexdigest()})
    with gzip.open(index_dir / (records_file + ".partial"), "wt", encoding="utf-8", compresslevel=6) as stream:
        json.dump(rows, stream, ensure_ascii=False, separators=(",", ":"))
    (index_dir / (records_file + ".partial")).replace(record_path)
    manifest = {"schema_version": 1, "fingerprint": fingerprint, "model": model,
                "count": len(records), "source_chunk_count": len(source_records),
                "window_policy": "400-token body windows with 48-token overlap; return best window per source chunk",
                "dtype": "float16", "normalized": True,
                "vectors_file": vectors_file, "vectors_file_sha256": _sha256(vector_path),
                "records_file": records_file, "records_file_sha256": _sha256(record_path),
                "source": str(Path(chunks_jsonl or data_root).resolve()),
                "source_format": "normalized_ingest_jsonl" if chunks_jsonl else "snapshot_chunks",
                "truncated_passages": getattr(encoder, "truncated_count", 0),
                "dependencies": getattr(encoder, "dependencies", {}),
                "built_at": datetime.now(timezone.utc).isoformat(),
                "build_seconds": round(time.monotonic() - started, 2),
                "bytes": vector_path.stat().st_size + record_path.stat().st_size,
                "score_meaning": "cosine similarity; candidate relevance, not factual confidence"}
    _write_json(index_dir / "index.json.partial", manifest)
    (index_dir / "index.json.partial").replace(manifest_path)
    return manifest


class VectorRetriever:
    """Read an existing local index; never builds/downloads on a user query."""

    def __init__(self, index_dir: Path = DEFAULT_INDEX_DIR, model_dir: Path = DEFAULT_MODEL_DIR, *, encoder=None):
        np = _numpy()
        index_dir = Path(index_dir).resolve()
        self.manifest = _json(index_dir / "index.json")
        if self.manifest.get("schema_version") != 1:
            raise ValueError("Unsupported vector index schema")
        self.encoder = encoder or LocalEncoder(model_dir)
        if self.manifest["model"] != self.encoder.metadata:
            raise ValueError("Vector index was built by a different encoder; rebuild explicitly")
        paths = {}
        for key in ("vectors_file", "records_file"):
            path = (index_dir / self.manifest[key]).resolve()
            if not path.is_relative_to(index_dir):
                raise ValueError("Vector index file escapes its directory")
            if _sha256(path) != self.manifest[key + "_sha256"]:
                raise ValueError("Vector index integrity check failed")
            paths[key] = path
        self.rows = _json(paths["records_file"])
        self.vectors = np.load(paths["vectors_file"], mmap_mode="r", allow_pickle=False)
        if self.vectors.shape != (len(self.rows), self.encoder.metadata["dimensions"]):
            raise ValueError("Vector/provenance shape mismatch")
        if len(self.rows) != self.manifest["count"] or not np.isfinite(self.vectors).all():
            raise ValueError("Invalid vector index count/values")

    def search(self, query: str, limit: int = 20) -> list[dict]:
        np = _numpy()
        if not isinstance(query, str) or not query.strip() or limit < 1:
            return []
        if len(query) > 16000:
            raise ValueError("Query exceeds 16000 characters")
        vector = self.encoder.encode([query.strip()], query=True)[0]
        matrix = self.vectors.astype(np.float32)
        # Re-normalize after float16 storage for a real cosine score.
        scores = (matrix @ vector) / np.maximum(np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector), 1e-12)
        order = np.argsort(-scores, kind="stable")
        results, seen = [], set()
        for i in order:
            row = self.rows[int(i)]
            if row.get("metadata", {}).get("block_kind") == "heading":
                continue  # headings alone cannot supply evidence
            key = (row["document_id"], row["source_version"], row.get("chunk_id"), row["line_start"], row["line_end"])
            if key in seen:
                continue
            seen.add(key)
            results.append({**row, "score": float(scores[i]), "retrieval_type": "dense_embedding",
                            "index_model": self.manifest["model"], "index_fingerprint": self.manifest["fingerprint"]})
            if len(results) >= min(int(limit), 100):
                break
        return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup_parser = commands.add_parser("setup", help="Explicit download of pinned 135429554-byte model assets")
    setup_parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    build_parser = commands.add_parser("build", help="Encode local passages (offline)")
    build_parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    build_parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    source = build_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--chunks-jsonl", type=Path)
    source.add_argument("--data-root", type=Path)
    build_parser.add_argument("--batch-size", type=int, default=8)
    search_parser = commands.add_parser("search", help="Search existing vectors (offline)")
    search_parser.add_argument("query")
    search_parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    search_parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    search_parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            result = setup(args.model_dir)
        elif args.command == "build":
            result = build_index(args.index_dir, args.model_dir, chunks_jsonl=args.chunks_jsonl,
                                 data_root=args.data_root, batch_size=args.batch_size)
        else:
            result = VectorRetriever(args.index_dir, args.model_dir).search(args.query, args.limit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
