# 会话整理 - 2026-03-07

## 本次需求

用户要求完成三件事：

1. 编写或重写项目 `README.md`。
2. 将本次对话内容整理成 Markdown 文件，放到 `docs/`。
3. 编写一个适合提交仓库的 `.gitignore`，并补一份需要上传/备份的核心文件清单。

## 本次处理结果

- 重写了根目录 `README.md`，内容基于当前仓库真实结构与代码行为。
- 新增本文件，用于记录本次会话目标与处理结论。
- 新增 `docs/core-files-backup.md`，列出建议保留与上传的核心文件范围。
- 新增 `.gitignore`，忽略虚拟环境、缓存、构建产物、发布目录与 Python 临时文件。

## 本次整理时参考的代码上下文

- `main.py`：应用入口，初始化 Qt 程序和主控制器。
- `controllers/main_controller.py`：目录扫描、树同步、预览加载、传输流程主编排。
- `services/preview_service.py`：当前预览策略，支持单图和序列帧。
- `requirements.txt`：依赖包括 `PySide6`、`Pillow`、`imageio`、`natsort`。

## 说明

- 本文件不是完整聊天逐字稿，而是按任务执行结果做的结构化归档。
- 如果后续要保留更细的开发日志，建议单独建立 `docs/changelog/` 或 `session-logs/` 目录管理。
