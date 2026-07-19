from __future__ import annotations

from typing import Any, cast

from modules.agent.mcp_manager import MCPManager, MCPServerConfig
from modules.agent.plugin_bridge import _infer_plugin_contribution_categories
from modules.agent.tool_registry import ToolRegistry
from modules.agent.capability_registry import CapabilityRegistry
from modules.agent_plugins.manager import PluginManager


def test_infer_plugin_contribution_categories_from_manifest_shape():
    plugin = {
        'toolCapabilities': [{'id': 'cap-1'}],
        'routes': [{'id': 'route-1'}],
        'permissions': {'routes': ['route-1'], 'toolScopes': ['cap-1'], 'modelScopes': []},
    }
    categories = _infer_plugin_contribution_categories(plugin)
    assert categories == ['capability', 'event', 'policy']


def test_agent_plugin_manager_snapshot_includes_contribution_summary():
    manager = PluginManager()
    manager._states = {
        'demo': {'id': 'demo', 'name': 'Demo', 'version': '1.2.3', 'enabled': True, 'loaded': True, 'error': None, 'config': {'mode': 'strict'}, 'config_schema': {'type': 'object'}},
    }
    manager._plugin_tools = {'demo': ['plugin.demo.tool']}
    manager._trace = [
        {'timestamp': 'now', 'plugin_id': 'demo', 'hook': 'before_tool', 'status': 'ok', 'detail': 'plugin.demo.tool'},
        {'timestamp': 'now', 'plugin_id': 'demo', 'hook': 'proactive_dispatch', 'status': 'ok', 'detail': 'plugin'},
    ]
    snapshot = manager.snapshot()
    assert snapshot['plugins'][0]['version'] == '1.2.3'
    summary = {item['category']: item['count'] for item in snapshot['contributionSummary']}
    assert summary['capability'] == 1
    assert summary['event'] >= 1
    assert summary['policy'] == 1


def test_mcp_snapshot_includes_contribution_summary():
    manager = MCPManager()
    manager.servers = {
        'playwright': MCPServerConfig(name='playwright', base_url='http://127.0.0.1:7777', transport='http', enabled=True),
    }
    manager.status = {'playwright': {'enabled': True, 'ok': True}}
    snapshot = manager.snapshot()
    summary = {item['category']: item['count'] for item in snapshot['contributionSummary']}
    assert summary['capability'] == 1
    assert summary['policy'] == 1


def test_capability_registry_preserves_contribution_category_tags():
    registry = ToolRegistry()
    from modules.agent.tool_registry import ToolDefinition
    from modules.agent.tool_result import ToolResultEnvelope

    registry.register(ToolDefinition(
        name='plugin.demo.tool',
        description='Demo tool',
        source='plugin',
        parameters={'type': 'object', 'properties': {}},
        handler=lambda args: ToolResultEnvelope(success=True, content='ok', source='plugin', tool_name='plugin.demo.tool'),
        tags=['plugin', 'demo', 'contrib:capability', 'contrib:policy'],
    ))
    snapshot = CapabilityRegistry(registry).snapshot()
    capabilities = cast(list[dict[str, Any]], snapshot['capabilities'])
    capability = next(item for item in capabilities if item['id'] == 'plugin.demo.tool')
    assert capability['contributionCategories'] == ['capability', 'policy']
