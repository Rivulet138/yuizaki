from __future__ import annotations


class ActiveWorkspaceState:
    def __init__(self, initial_workspace_id: str = "default") -> None:
        self._workspace_id = str(initial_workspace_id or "default").strip() or "default"

    def get(self) -> str:
        workspace_id = str(self._workspace_id or "default").strip() or "default"
        self._workspace_id = workspace_id
        return workspace_id

    def set(self, workspace_id: str | None) -> str:
        self._workspace_id = str(workspace_id or "default").strip() or "default"
        return self._workspace_id
