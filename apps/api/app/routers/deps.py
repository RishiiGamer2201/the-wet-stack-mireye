"""Shared router dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from ..domain import Project
from ..store import C, Store, get_store


def store_dep() -> Store:
    return get_store()


def get_project(project_id: str, store: Store = Depends(store_dep)) -> Project:
    project = store.get(C.PROJECTS, project_id, Project)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"project {project_id} not found - seed the demo data with POST /api/admin/seed",
        )
    return project
