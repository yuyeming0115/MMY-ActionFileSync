# 动画序列同步预览算法

## 概述

预览系统支持单帧图片、图片序列目录和目录内 GIF。数据构建在后台线程执行；界面使用一个共享时间轴驱动来源与目标预览，避免两侧独立计时器产生播放漂移。

## 1. 预览数据构建

`PreviewService.build_preview()` 接收角色、相对路径和 `TreeNode`，返回 `PreviewItem`。

处理顺序：

1. 节点不存在：返回 `missing`。
2. 节点不可预览：返回 `not_previewable`。
3. 单图节点：读取图片尺寸，使用一个 `frame_path`。
4. 图片序列目录：按扫描结果生成 `frame_paths`，读取第一帧尺寸。
5. 目录内 GIF：使用 `cache_path`，读取尺寸和帧数。
6. 没有可用素材：返回 `error`。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `side` | 内部角色：`left` / `right`；界面显示为“来源 / 目标” |
| `relative_path` | 当前动作相对路径 |
| `source_path` | 文件或动作目录 |
| `frame_paths` | 序列帧路径 |
| `cache_path` | GIF 或静态缓存路径 |
| `frame_interval_ms` | 建议播放间隔 |
| `frame_count` | 帧数 |
| `width` / `height` | 原始尺寸 |
| `status` | `ready`、`missing`、`not_previewable`、`error` |

## 2. 共享时间轴

`PreviewPanel` 持有唯一的播放 `QTimer`、帧滑杆和归一化进度：

```text
master_count = max(source_count, target_count, 1)
progress = master_index / (master_count - 1)

source_index = round(progress * (source_count - 1))
target_index = round(progress * (target_count - 1))
```

因此：

- 两侧帧数相同：按相同帧号播放。
- 两侧帧数不同：按 0%～100% 动画进度对齐。
- 单帧资源：始终显示第 1 帧。
- 缺失资源：保留画布并显示角色明确的空状态。

切换动作时，控制器会先清空旧预览，再启动两侧后台任务。完成事件还会核对 `relative_path`，过期任务不会覆盖当前动作。

## 3. 帧渲染

`SinglePreviewWidget` 保存有效 `QPixmap` 列表，根据共享进度取帧：

1. 根据缩放比例计算目标尺寸。
2. 使用 `Qt.KeepAspectRatio` 保持宽高比。
3. 创建与画布相同尺寸的透明帧。
4. 水平居中，并叠加共享 Y 轴位移。
5. 在画布尺寸变化、进度变化、缩放变化或位移变化时重新绘制。

缩放范围为 25%～300%，Y 轴位移范围为 -200～200 px。

## 4. 预览模式

### 并排

来源和目标画布同时显示，标题使用稳定的角色名称和不同强调色。两侧共享帧滑杆、播放状态、缩放和位移。

### 差异闪烁

在同一画布位置以 450 ms 间隔交替显示来源与目标当前进度帧。该模式适合观察轮廓、位置和像素边缘变化；角色标题同步切换，信息不只依赖颜色。

## 5. 组件职责

| 组件 | 职责 |
| --- | --- |
| `PreviewService` | 构建 `PreviewItem` |
| `PreviewWorker` | 后台读取预览元数据 |
| `PreviewPanel` | 共享时间轴、模式、缩放和位移 |
| `SinglePreviewWidget` | 单角色帧存储和绘制 |
| `BlinkPreviewWidget` | 同位置交替绘制来源/目标帧 |
| `PreviewItem` | 跨线程预览数据 |

## 6. 当前限制

- 图片序列会将有效帧加载为 `QPixmap`，超大序列仍可能占用较多内存。
- GIF 当前通过 `QPixmap` 显示静态帧；完整 GIF 解帧可作为后续优化。
- 对比是视觉同步，不执行逐像素差异计算。

## 变更记录

- 2026-08-10：改为单一共享时间轴，增加归一化帧映射和差异闪烁模式，并补充异步结果防串动作说明。
