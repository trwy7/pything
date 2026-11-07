"""Discovering apps on disk and resolving which ones are enabled."""

from __future__ import annotations

import json
import os
from typing import Any

from . import state


def app_manifest(app_dir: str) -> dict[str, Any]:
    with open(
        os.path.join(app_dir, "manifest.json"), encoding="utf-8"
    ) as manifest_file:
        manifest = json.load(manifest_file)
    if not isinstance(manifest, dict):
        raise TypeError(f"Manifest for app directory '{app_dir}' must be an object")
    dependencies = manifest.get("dependencies", {})
    if not isinstance(dependencies, dict):
        raise RuntimeError(  # noqa: TRY004
            f"Manifest for app directory '{app_dir}' has invalid dependencies"
        )
    for dependency_type in ("required", "optional"):
        values = dependencies.setdefault(dependency_type, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise RuntimeError(
                f"Manifest for app directory '{app_dir}' has invalid {dependency_type} dependencies"
            )
    manifest["dependencies"] = dependencies
    return manifest


def discover_apps() -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for app_root in ("apps", "customapps"):
        if not os.path.isdir(app_root):
            continue
        for app_name in sorted(os.listdir(app_root)):
            app_dir = os.path.join(app_root, app_name)
            if not os.path.isdir(app_dir) or not os.path.isfile(
                os.path.join(app_dir, "manifest.json")
            ):
                continue
            manifest = app_manifest(app_dir)
            app_id = manifest.get("id")
            if not isinstance(app_id, str):
                raise TypeError(
                    f"Manifest for app directory '{app_dir}' has invalid id"
                )
            if app_id in discovered:
                raise RuntimeError(
                    f"App id '{app_id}' is defined more than once"
                )  # TODO: disable duplicate apps when we allow custom apps
            discovered[app_id] = {
                "id": app_id,
                "name": manifest.get("name", app_id),
                "description": manifest.get("description", ""),
                "core": manifest.get("core", False),
                "default": manifest.get("default", False),
                "category": manifest.get("category", "uncategorized"),
                "dependencies": manifest["dependencies"],
                "directory": app_dir,
            }
    return discovered


def required_dependency_closure(
    selected: set[str], manifests: dict[str, dict[str, Any]]
) -> set[str]:
    enabled = selected & set(manifests)
    changed = True
    while changed:
        changed = False
        for app_id in tuple(enabled):
            for dependency in manifests[app_id]["dependencies"]["required"]:
                if dependency not in manifests:
                    enabled.remove(app_id)
                    changed = True
                    break
                if dependency not in enabled:
                    enabled.add(dependency)
                    changed = True
    return enabled


def enabled_apps(manifests: dict[str, dict[str, Any]]) -> set[str]:
    # Apply manifest defaults on first start and only to newly discovered apps later.
    default_apps = {
        app_id
        for app_id, manifest in manifests.items()
        if manifest.get("default") is True or manifest["core"]
    }

    # Save the initial selection and installed IDs for future update checks.
    if state.APP_CONFIG_ID not in state.config:
        initially_enabled = required_dependency_closure(default_apps, manifests)
        state.config[state.APP_CONFIG_ID] = {
            "disabled": sorted(set(manifests) - initially_enabled),
            "known": sorted(manifests),
        }
        state.save_config()
    else:
        app_config = state.config[state.APP_CONFIG_ID]
        if "known" not in app_config:
            # Preserve existing choices when upgrading from configs created before
            # app IDs were tracked.
            app_config["known"] = sorted(manifests)
            state.save_config()
        else:
            known_apps = set(app_config["known"])
            # Apply defaults only to apps added since the last saved selection.
            new_apps = set(manifests) - known_apps
            if new_apps:
                disabled = set(app_config.get("disabled", []))
                disabled.update(new_apps - default_apps)
                disabled.difference_update(new_apps & default_apps)
                app_config["disabled"] = sorted(disabled)
            if known_apps != set(manifests):
                app_config["known"] = sorted(manifests)
                state.save_config()

    disabled = set(state.config.get(state.APP_CONFIG_ID, {}).get("disabled", []))
    core_apps = {app_id for app_id, manifest in manifests.items() if manifest["core"]}
    return required_dependency_closure(set(manifests) - disabled | core_apps, manifests)


def app_dependency_view(manifests: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    enabled = enabled_apps(manifests)
    app_names = {app_id: manifest["name"] for app_id, manifest in manifests.items()}
    required_by: dict[str, set[str]] = {app_id: set() for app_id in manifests}
    for app_id, manifest in manifests.items():
        for dependency in manifest["dependencies"]["required"]:
            if dependency in required_by and app_id in enabled:
                required_by[dependency].add(app_id)
    result = []
    for app_id in sorted(
        manifests,
        key=lambda item: (manifests[item]["core"], manifests[item]["name"].casefold()),
    ):
        manifest = manifests[app_id]
        missing_required = [
            dependency
            for dependency in manifest["dependencies"]["required"]
            if dependency not in manifests
        ]
        result.append(
            {
                **manifest,
                "enabled": app_id in enabled,
                "required_names": [
                    app_names.get(dependency, dependency)
                    for dependency in manifest["dependencies"]["required"]
                ],
                "optional_names": [
                    app_names.get(dependency, dependency)
                    for dependency in manifest["dependencies"]["optional"]
                ],
                "required_by_names": [
                    app_names.get(dependency, dependency)
                    for dependency in sorted(required_by[app_id])
                ],
                "missing_required": missing_required,
                "missing_required_names": [
                    app_names.get(dependency, dependency)
                    for dependency in missing_required
                ],
            }
        )
    return result
