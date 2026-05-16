import numpy as np


DEFAULT_SIMILARITY_MODE = "chunk"
SUPPORTED_SIMILARITY_MODES = {"chunk", "frame"}


def build_semantic_chunks(
    embeddings,
    timestamps,
    similarity_threshold=0.85,
    max_chunk_duration=5.0,
    min_chunk_size=2,
    similarity_mode=DEFAULT_SIMILARITY_MODE,
):
    vectors = np.asarray(embeddings, dtype=np.float32)
    times = np.asarray(timestamps, dtype=np.float32)

    if vectors.ndim != 2:
        raise ValueError("embeddings must be a 2D array")
    if len(vectors) != len(times):
        raise ValueError("embeddings and timestamps must have the same length")
    if similarity_mode not in SUPPORTED_SIMILARITY_MODES:
        raise ValueError(f"Unsupported similarity_mode: {similarity_mode}")
    if len(vectors) == 0:
        return []

    threshold = float(similarity_threshold)
    max_duration = float(max_chunk_duration)
    min_size = max(1, int(min_chunk_size))

    chunks = []
    current_vectors = [vectors[0]]
    current_times = [float(times[0])]

    for index in range(1, len(vectors)):
        current_vector = vectors[index]
        current_time = float(times[index])

        similarity = _similarity_to_reference(
            current_vector,
            current_vectors,
            similarity_mode=similarity_mode,
        )
        duration = current_time - current_times[0]
        should_split = similarity < threshold or duration > max_duration

        if should_split and len(current_vectors) >= min_size:
            chunks.append(_finalize_chunk(current_vectors, current_times))
            current_vectors = [current_vector]
            current_times = [current_time]
            continue

        current_vectors.append(current_vector)
        current_times.append(current_time)

    if current_vectors:
        chunks.append(_finalize_chunk(current_vectors, current_times))

    return chunks


class SemanticChunkStreamBuilder:
    """Incremental ``build_semantic_chunks`` for long videos (same rules, batch by batch)."""

    def __init__(
        self,
        similarity_threshold=0.85,
        max_chunk_duration=5.0,
        min_chunk_size=2,
        similarity_mode=DEFAULT_SIMILARITY_MODE,
    ):
        if similarity_mode not in SUPPORTED_SIMILARITY_MODES:
            raise ValueError(f"Unsupported similarity_mode: {similarity_mode}")
        self.threshold = float(similarity_threshold)
        self.max_duration = float(max_chunk_duration)
        self.min_size = max(1, int(min_chunk_size))
        self.similarity_mode = similarity_mode
        self.chunks = []
        self._current_vectors = []
        self._current_times = []

    def extend(self, embeddings, timestamps):
        vectors = np.asarray(embeddings, dtype=np.float32)
        if vectors.size == 0:
            return
        if vectors.ndim == 1:
            vectors = vectors.reshape(1, -1)
        if vectors.ndim != 2:
            raise ValueError("embeddings must be a 2D array")
        times = np.asarray(timestamps, dtype=np.float32).reshape(-1)
        if len(vectors) != len(times):
            raise ValueError("embeddings and timestamps must have the same length")
        for index in range(len(vectors)):
            self._append_frame(vectors[index], float(times[index]))

    def finish(self):
        if self._current_vectors:
            self.chunks.append(_finalize_chunk(self._current_vectors, self._current_times))
            self._current_vectors = []
            self._current_times = []
        return list(self.chunks)

    def _append_frame(self, vector, timestamp):
        if not self._current_vectors:
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            return

        similarity = _similarity_to_reference(
            vector,
            self._current_vectors,
            similarity_mode=self.similarity_mode,
        )
        duration = timestamp - self._current_times[0]
        should_split = similarity < self.threshold or duration > self.max_duration

        if should_split and len(self._current_vectors) >= self.min_size:
            self.chunks.append(_finalize_chunk(self._current_vectors, self._current_times))
            self._current_vectors = [vector]
            self._current_times = [timestamp]
            return

        self._current_vectors.append(vector)
        self._current_times.append(timestamp)


def build_semantic_chunks_streaming(vector_batches, timestamps, **kwargs):
    """Build chunks from per-batch frame vectors without materializing a full matrix first."""
    builder = SemanticChunkStreamBuilder(**kwargs)
    if not vector_batches:
        return builder.finish()
    times = np.asarray(timestamps, dtype=np.float32).reshape(-1)
    offset = 0
    for batch in vector_batches:
        batch_vectors = np.asarray(batch, dtype=np.float32)
        if batch_vectors.size == 0:
            continue
        if batch_vectors.ndim == 1:
            batch_vectors = batch_vectors.reshape(1, -1)
        end = offset + batch_vectors.shape[0]
        if end > len(times):
            raise ValueError("streaming chunk timestamps shorter than vector batches")
        builder.extend(batch_vectors, times[offset:end])
        offset = end
    if offset != len(times):
        raise ValueError("streaming chunk timestamps longer than vector batches")
    return builder.finish()


def chunk_config_payload(
    similarity_threshold=0.85,
    max_chunk_duration=5.0,
    min_chunk_size=2,
    similarity_mode=DEFAULT_SIMILARITY_MODE,
):
    return {
        "similarity_threshold": float(similarity_threshold),
        "max_chunk_duration": float(max_chunk_duration),
        "min_chunk_size": int(min_chunk_size),
        "similarity_mode": str(similarity_mode),
    }


def _similarity_to_reference(vector, current_vectors, similarity_mode):
    if similarity_mode == "frame":
        reference = current_vectors[-1]
    else:
        reference = np.mean(np.asarray(current_vectors, dtype=np.float32), axis=0)
    return cosine_similarity(vector, reference)


def _finalize_chunk(vectors, timestamps):
    embedding = np.mean(np.asarray(vectors, dtype=np.float32), axis=0)
    embedding = _normalize_vector(embedding)
    return {
        "start": float(timestamps[0]),
        "end": float(timestamps[-1]),
        "embedding": embedding,
    }


def cosine_similarity(left, right):
    left_vector = _normalize_vector(np.asarray(left, dtype=np.float32))
    right_vector = _normalize_vector(np.asarray(right, dtype=np.float32))
    return float(np.dot(left_vector, right_vector))


def pack_chunks(chunks):
    if not chunks:
        return None

    return {
        "start": np.asarray([chunk["start"] for chunk in chunks], dtype=np.float32),
        "end": np.asarray([chunk["end"] for chunk in chunks], dtype=np.float32),
        "embedding": np.asarray([chunk["embedding"] for chunk in chunks], dtype=np.float32),
    }


def unpack_chunks(payload):
    if not isinstance(payload, dict):
        return []

    starts = np.asarray(payload.get("start", []), dtype=np.float32)
    ends = np.asarray(payload.get("end", []), dtype=np.float32)
    embeddings = np.asarray(payload.get("embedding", []), dtype=np.float32)
    if len(starts) != len(ends) or len(starts) != len(embeddings):
        return []

    return [
        {
            "start": float(starts[index]),
            "end": float(ends[index]),
            "embedding": embeddings[index],
        }
        for index in range(len(starts))
    ]


def _normalize_vector(vector):
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        return vector.astype(np.float32, copy=False)
    return (vector / norm).astype(np.float32, copy=False)
