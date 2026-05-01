import numpy as np

from src.storage.config_store import get_model_profile_storage_paths
from src.utils import load_meta, save_meta


def load_metadata(meta_file):
    return load_meta(meta_file)


def save_metadata(meta, meta_file):
    save_meta(meta, meta_file)


def load_model_metadata(config=None):
    paths = get_model_profile_storage_paths(config=config)
    return load_metadata(paths["meta_file"])


def save_model_metadata(meta, config=None):
    paths = get_model_profile_storage_paths(config=config)
    save_metadata(meta, paths["meta_file"])


def load_vector_payload(vector_file):
    from src.core.faiss_index import load_vectors

    return load_vectors(vector_file)


def save_vector_payload(vectors, timestamps, vector_file, chunks=None, chunk_config=None, embedding_spec=None):
    from src.core.faiss_index import save_vectors

    return save_vectors(
        vectors,
        timestamps,
        vector_file,
        chunks=chunks,
        chunk_config=chunk_config,
        embedding_spec=embedding_spec,
    )


def save_remote_vector_payload(vector_file, payload):
    from src.core.faiss_index import atomic_save_numpy

    atomic_save_numpy(vector_file, payload)


def load_remote_vector_payload(vector_file):
    data = np.load(vector_file, allow_pickle=True).item()
    return {
        "vector": np.asarray(data.get("vector", np.empty((0, 0), dtype=np.float32)), dtype=np.float32),
        "timestamps": [float(value) for value in data.get("timestamps", [])],
        "paths": [str(value) for value in data.get("paths", [])],
        "source_links": [str(value) for value in data.get("source_links", [])],
        "titles": [str(value) for value in data.get("titles", [])],
    }


def load_numpy_payload(npy_file):
    return np.load(npy_file, allow_pickle=True).item()


def save_numpy_payload(npy_file, payload):
    from src.core.faiss_index import atomic_save_numpy

    atomic_save_numpy(npy_file, payload)
