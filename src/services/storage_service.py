import os
import shutil

from src.app.config import build_data_storage_paths, get_configured_data_root, load_config, save_config
from src.storage.config_store import get_effective_model_dir
from src.app.logging_utils import get_logger
from src.storage.asset_store import load_metadata
from src.storage.config_store import get_config_schema_version, get_model_profile_storage_paths

logger = get_logger("storage_service")
STORAGE_DIR_NAME = "data"
STAGING_DIR_NAME = ".videoseek-migrate-staging"
MODELS_DIR_NAME = "models"


def _copy_tree(src_dir, dst_dir):
    if not os.path.exists(src_dir):
        return
    for current_root, _dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(current_root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            src_file = os.path.join(current_root, name)
            dst_file = os.path.join(target_root, name)
            shutil.copy2(src_file, dst_file)


def _copy_path(src_path, dst_path):
    if not src_path or not os.path.exists(src_path):
        return
    if os.path.isdir(src_path):
        _copy_tree(src_path, dst_path)
        return
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    shutil.copy2(src_path, dst_path)


def _remove_tree_if_exists(path):
    if not path or not os.path.exists(path):
        return
    shutil.rmtree(path, ignore_errors=True)


def _ensure_target_available(target_source_dir):
    if not os.path.exists(target_source_dir):
        return
    if os.path.isdir(target_source_dir) and not os.listdir(target_source_dir):
        return
    raise ValueError("Target data directory already exists and is not empty")


def _assert_not_nested_path(current_root, target_root):
    normalized_current = os.path.normcase(os.path.normpath(current_root))
    normalized_target = os.path.normcase(os.path.normpath(target_root))
    try:
        common_path = os.path.commonpath([normalized_current, normalized_target])
    except ValueError:
        return
    if common_path in {normalized_current, normalized_target} and normalized_current != normalized_target:
        raise ValueError("Target data directory cannot be nested inside the current data directory or vice versa")


def _validate_target_metadata(target_meta_file):
    if not os.path.exists(target_meta_file):
        return
    load_metadata(target_meta_file)


def _resolve_expected_meta_file(config, target_root):
    schema_version = get_config_schema_version(config=config)
    if schema_version >= 2:
        target_config = dict(config)
        target_config["data_root"] = target_root
        return get_model_profile_storage_paths(config=target_config)["meta_file"]
    target_paths = build_data_storage_paths(target_root)
    return target_paths["meta_file"]


def _normalize_existing_path(value):
    path = str(value or "").strip()
    if not path:
        return ""
    return os.path.normpath(os.path.abspath(os.fspath(path)))


def _path_is_strict_descendant(ancestor, descendant):
    """True if descendant is a proper subpath of ancestor (same normalized root)."""
    a = _normalize_existing_path(ancestor)
    d = _normalize_existing_path(descendant)
    if not a or not d or os.path.normcase(a) == os.path.normcase(d):
        return False
    try:
        common = os.path.commonpath([a, d])
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(a)


def _collect_storage_copy_tasks(config, current_data_root, target_root):
    target_paths = build_data_storage_paths(target_root)
    current_storage_dir = ""
    meta_file = _normalize_existing_path(config.get("meta_file", ""))
    if meta_file:
        current_storage_dir = os.path.dirname(meta_file)
    if not current_storage_dir:
        current_storage_dir = os.path.join(current_data_root, STORAGE_DIR_NAME)

    copy_tasks = []
    seen_pairs = set()

    source_pair = (
        _normalize_existing_path(current_storage_dir),
        _normalize_existing_path(os.path.dirname(target_paths["meta_file"])),
    )
    if source_pair[0]:
        copy_tasks.append(source_pair)
        seen_pairs.add(source_pair)

    for key, target_path in target_paths.items():
        current_path = _normalize_existing_path(config.get(key, ""))
        if not current_path:
            continue
        pair = (current_path, _normalize_existing_path(target_path))
        if pair in seen_pairs:
            continue
        if pair[0] == source_pair[0]:
            continue
        copy_tasks.append(pair)
        seen_pairs.add(pair)

    return current_storage_dir, target_paths, copy_tasks


def migrate_app_data_root(target_root):
    normalized_target_root = os.path.normpath(os.path.abspath(os.fspath(target_root)))
    if not normalized_target_root:
        raise ValueError("Target data directory is required")

    config = load_config()
    current_data_root = get_configured_data_root(config)
    if os.path.normcase(normalized_target_root) == os.path.normcase(current_data_root):
        return {
            "migrated": False,
            "reason": "same_path",
            "data_root": current_data_root,
        }

    staging_root = os.path.join(normalized_target_root, STAGING_DIR_NAME)
    current_storage_dir, staging_paths, copy_tasks = _collect_storage_copy_tasks(
        config,
        current_data_root,
        staging_root,
    )
    target_paths = build_data_storage_paths(normalized_target_root)
    target_storage_dir = os.path.dirname(target_paths["meta_file"])
    staging_storage_dir = os.path.dirname(staging_paths["meta_file"])

    _assert_not_nested_path(current_data_root, normalized_target_root)
    for current_path, _target_path in copy_tasks:
        _assert_not_nested_path(current_path, normalized_target_root)
    _ensure_target_available(target_storage_dir)
    os.makedirs(normalized_target_root, exist_ok=True)
    _remove_tree_if_exists(staging_root)

    logger.info("Migrating application data root from %s to %s", current_data_root, normalized_target_root)
    try:
        for current_path, target_path in copy_tasks:
            _copy_path(current_path, target_path)
        expected_meta_file = _resolve_expected_meta_file(config, staging_root)
        if not os.path.exists(expected_meta_file):
            raise RuntimeError("Data migration failed: metadata file was not copied successfully")
        _validate_target_metadata(expected_meta_file)
        if os.path.exists(staging_storage_dir):
            shutil.move(staging_storage_dir, target_storage_dir)
    except Exception:
        _remove_tree_if_exists(staging_root)
        raise
    finally:
        if os.path.isdir(staging_root) and not os.listdir(staging_root):
            _remove_tree_if_exists(staging_root)

    updated_config = dict(config)
    updated_config["data_root"] = normalized_target_root
    save_config(updated_config)
    return {
        "migrated": True,
        "reason": "",
        "old_data_root": current_data_root,
        "new_data_root": normalized_target_root,
        "old_data_dir": current_storage_dir,
        "new_data_dir": target_storage_dir,
    }


def migrate_model_root(target_root):
    """Copy the active profile's model tree to a new root and point matching profiles at it."""
    normalized_target = _normalize_existing_path(target_root)
    if not normalized_target:
        raise ValueError("Target model directory is required")

    config = load_config()
    source = _normalize_existing_path(get_effective_model_dir(config=config))
    if not source:
        raise ValueError("Active profile has no runtime.model_dir")

    if os.path.normcase(source) == os.path.normcase(normalized_target):
        return {
            "migrated": False,
            "reason": "same_path",
            "old_model_dir": source,
            "new_model_dir": normalized_target,
        }

    if not os.path.isdir(source):
        raise ValueError("Current model directory does not exist or is not a folder")

    _assert_not_nested_path(source, normalized_target)
    _assert_not_nested_path(normalized_target, source)

    if os.path.exists(normalized_target):
        try:
            entries = os.listdir(normalized_target)
        except OSError as exc:
            raise ValueError("Cannot read target model directory") from exc
        if entries:
            raise ValueError("Target model directory must be empty or not exist yet")

    os.makedirs(normalized_target, exist_ok=True)
    _copy_tree(source, normalized_target)

    old_normcase = os.path.normcase(source)
    updated_config = dict(config)
    top = _normalize_existing_path(updated_config.get("model_dir", ""))
    if top and os.path.normcase(top) == old_normcase:
        updated_config["model_dir"] = normalized_target

    models = updated_config.get("models")
    if isinstance(models, dict):
        profiles = models.get("profiles")
        if isinstance(profiles, list):
            for idx, item in enumerate(profiles):
                if not isinstance(item, dict):
                    continue
                runtime = item.get("runtime")
                if not isinstance(runtime, dict):
                    continue
                md = _normalize_existing_path(runtime.get("model_dir", ""))
                if not md or os.path.normcase(md) != old_normcase:
                    continue
                new_runtime = dict(runtime)
                new_runtime["model_dir"] = normalized_target
                new_item = dict(item)
                new_item["runtime"] = new_runtime
                profiles[idx] = new_item

    updated_config["pending_cleanup_model_dir"] = source
    save_config(updated_config)
    return {
        "migrated": True,
        "reason": "",
        "old_model_dir": source,
        "new_model_dir": normalized_target,
    }


def cleanup_old_model_dir(pending_root, active_model_dir=None):
    """Remove a former model root directory tree left after migrate_model_root. Refuses if still in use."""
    pending = _normalize_existing_path(pending_root)
    if not pending:
        raise ValueError("Path to clean up is required")

    config = load_config()
    active = _normalize_existing_path(active_model_dir or get_effective_model_dir(config=config))
    if not active:
        raise ValueError("Active model directory is unknown")

    if os.path.normcase(pending) == os.path.normcase(active):
        raise ValueError("Cannot remove the active model directory")

    if _path_is_strict_descendant(pending, active):
        raise ValueError("Current model directory is under the path to remove")

    if _path_is_strict_descendant(active, pending):
        raise ValueError("Refusing to remove a folder inside the active model directory")

    if not os.path.exists(pending):
        return {
            "cleaned": False,
            "reason": "missing",
            "old_model_dir": pending,
        }

    shutil.rmtree(pending)
    return {
        "cleaned": True,
        "reason": "",
        "old_model_dir": pending,
    }


def cleanup_old_data_root(target_root, active_data_root=None):
    normalized_target_root = os.path.normpath(os.path.abspath(os.fspath(target_root)))
    if not normalized_target_root:
        raise ValueError("Target data directory is required")

    current_root = os.path.normpath(active_data_root or get_configured_data_root())
    if os.path.normcase(normalized_target_root) == os.path.normcase(current_root):
        raise ValueError("Cannot clean the active data directory")

    target_paths = build_data_storage_paths(normalized_target_root)
    target_data_dir = os.path.dirname(target_paths["meta_file"])
    target_models_dir = os.path.join(normalized_target_root, MODELS_DIR_NAME)
    staging_dir = os.path.join(normalized_target_root, STAGING_DIR_NAME)
    configured_model_dir = _normalize_existing_path(load_config().get("model_dir", ""))

    removed_any = False
    if os.path.exists(target_data_dir):
        shutil.rmtree(target_data_dir)
        removed_any = True
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir, ignore_errors=True)
        removed_any = True
    can_remove_models_dir = True
    if configured_model_dir and os.path.exists(target_models_dir):
        try:
            common_model_root = os.path.commonpath([configured_model_dir, _normalize_existing_path(target_models_dir)])
        except ValueError:
            common_model_root = ""
        if common_model_root == _normalize_existing_path(target_models_dir):
            can_remove_models_dir = False
    if can_remove_models_dir and os.path.exists(target_models_dir):
        shutil.rmtree(target_models_dir, ignore_errors=True)
        removed_any = True

    return {
        "cleaned": removed_any,
        "reason": "" if removed_any else "missing",
        "old_data_root": normalized_target_root,
        "old_data_dir": target_data_dir,
    }
