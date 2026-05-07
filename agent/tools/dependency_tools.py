from __future__ import annotations

"""依赖申请工具：允许 Agent 记录缺包请求，但不允许它直接安装。"""

from langchain_core.tools import tool

from agent.config import Settings
from agent.db.local_database import LocalDatabase


def build_dependency_tools(settings: Settings, session_id: str):
    """构造当前记忆窗口专属的依赖申请工具。"""

    @tool
    def request_dependency_install(module_name: str, package_name: str = "") -> str:
        """Record a dependency install request for user approval. package_name must be the pip/PyPI package name."""
        module_name = module_name.strip()
        package = package_name.strip()
        if not package:
            return (
                "Dependency request was not recorded because package_name is empty. "
                "Infer the correct pip/PyPI package name for this import module and call this tool again "
                "with both module_name and package_name."
            )
        database = LocalDatabase(settings.local_db_path)
        database.initialize()
        database.add_dependency_request(session_id, module_name, package, "Requested by Agent")
        return (
            f"Recorded dependency request: module={module_name}, package={package}. "
            "Ask the user to approve it with deps-list and deps-install."
        )

    return [request_dependency_install]
