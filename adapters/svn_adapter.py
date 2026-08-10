from __future__ import annotations

from adapters.base_source_adapter import BaseSourceAdapter
from models.tree_node import TreeNode


class SVNAdapter(BaseSourceAdapter):
    source_type = "svn"

    def scan(self, root_path: str) -> TreeNode:
        # TODO: 接入真实 SVN 工作副本扫描、状态识别与提交更新能力。
        raise NotImplementedError("MVP 阶段 SVNAdapter 仅作扩展占位。")
