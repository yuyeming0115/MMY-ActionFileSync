"""应用元信息：版本号的单一来源，供窗口标题与打包脚本读取。

发布新版本时只需修改 APP_VERSION，打包脚本会自动以
releases/v{版本号}_{时间戳} 目录名归档每次构建。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings

APP_VERSION = "0.2.5"
APP_ORG = "MMY-Tools"
APP_NAME = "MMY-ActionFileSync"


def create_app_settings() -> QSettings:
    """创建与主窗口共享的持久化配置实例。"""
    from PySide6.QtCore import QSettings

    return QSettings(QSettings.defaultFormat(), QSettings.UserScope, APP_ORG, APP_NAME)
