# Python Tests Execution Notes

当前仓库的 Python 测试依赖定义在：

- `python/requirements-dev.txt`

如果系统全局没有安装 `pytest`，请优先使用仓库内虚拟环境执行：

## Windows PowerShell

```powershell
".venv\Scripts\python.exe" -m pytest "tests/test_workspace_companion_integrity.py"
```

## 通用建议

- 在 `E:\yuizaki\python` 目录下运行测试。
- 若首次执行失败，请先安装开发依赖：

```powershell
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
```

## 当前重点测试

- `tests/test_workspace_companion_integrity.py`
- `tests/test_migration_bootstrap.py`
- `test_heartbeat.py`

这些测试分别覆盖：

- Workspace ↔ Companion 完整性
- migration bootstrap 对已知 schema 阶段的识别
- heartbeat / relationship runtime 行为
