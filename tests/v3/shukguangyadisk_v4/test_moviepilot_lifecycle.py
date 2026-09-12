"""在 MoviePilot V3 官方 pytest runtime 下验证光鸭 V4 插件生命周期。"""

from app.plugins.shukguangyadisk import ShukGuangYaDisk


def test_moviepilot_v3_plugin_lifecycle_contract():
    """实例化、禁用态初始化、API/module/service 枚举和停止均应成功。"""
    plugin = ShukGuangYaDisk()
    plugin.init_plugin({"enabled": False})

    api_paths = {
        (row.get("path"), tuple(row.get("methods") or []))
        for row in plugin.get_api()
    }
    assert ("/config", ("GET",)) in api_paths
    assert ("/organize/monitor/status", ("GET",)) in api_paths
    assert ("/organize/monitor/graceful-stop", ("POST",)) in api_paths

    modules = plugin.get_module()
    for name in (
        "list_files",
        "upload_file",
        "download_file",
        "storage_manage",
        "get_folder",
    ):
        assert callable(modules.get(name)), name

    services = plugin.get_service()
    assert {row["id"] for row in services} == {
        "ShukGuangYaDiskV4Bootstrap",
        "ShukGuangYaDiskV4Monitor",
    }

    plugin.stop_service()
