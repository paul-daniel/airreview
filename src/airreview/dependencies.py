from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import tomllib


def scan_dependency_context(repo: Path) -> dict[str, Any]:
    context: dict[str, Any] = {
        "package_manifests": [],
        "dependencies": {},
        "dev_dependencies": {},
        "notes": [],
    }
    package_json = repo / "package.json"
    if package_json.exists():
        data = json.loads(package_json.read_text(encoding="utf-8"))
        context["package_manifests"].append("package.json")
        context["dependencies"].update(data.get("dependencies", {}))
        context["dev_dependencies"].update(data.get("devDependencies", {}))
        context["package_manager"] = detect_package_manager(repo)
        react_version = context["dependencies"].get("react") or context["dev_dependencies"].get("react")
        if react_version:
            context["notes"].append(f"React detected at version constraint {react_version}; review React API usage against that major version.")
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        context["package_manifests"].append("pyproject.toml")
        project = data.get("project", {})
        for dependency in project.get("dependencies", []):
            name = str(dependency).split("=", 1)[0].split("<", 1)[0].split(">", 1)[0].strip()
            context["dependencies"][name] = dependency
    requirements = repo / "requirements.txt"
    if requirements.exists():
        context["package_manifests"].append("requirements.txt")
        for line in requirements.read_text(encoding="utf-8").splitlines():
            cleaned = line.strip()
            if cleaned and not cleaned.startswith("#"):
                name = cleaned.split("=", 1)[0].split("<", 1)[0].split(">", 1)[0].strip()
                context["dependencies"][name] = cleaned
    return context


def detect_package_manager(repo: Path) -> str:
    if (repo / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo / "yarn.lock").exists():
        return "yarn"
    if (repo / "package-lock.json").exists():
        return "npm"
    return "unknown"
