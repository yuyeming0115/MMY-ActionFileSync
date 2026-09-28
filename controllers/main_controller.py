from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QDialog, QMessageBox

from models.app_state import AppState
from models.preview_item import PreviewItem
from services.action_diff_service import ActionDiffService
from services.transfer_service import TransferService
from utils.cancel_token import CancellationToken
from utils.hash_utils import HashCache
from utils.path_matcher import find_same_name_folder, normalize_path
from views.main_window import MainWindow
from views.redundancy_dialog import RedundancyDialog
from views.transfer_preview_dialog import TransferPreviewDialog
from workers.preview_worker import PreviewWorker
from workers.scan_worker import ScanWorker
from workers.transfer_worker import TransferWorker


class MainController(MainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.state = AppState()
        self._hash_cache = HashCache()
        self.action_diff_service = ActionDiffService(hash_cache=self._hash_cache)
        self.transfer_service = TransferService()
        self._active_threads: list[QThread] = []
        self._active_workers: list[object] = []
        self._total_files = 0
        self._success = 0
        self._failed = 0
        self._skipped = 0
        self._scan_in_progress = False
        self._transfer_in_progress = False
        self._scan_cancel_token: CancellationToken | None = None
        self._transfer_cancel_token: CancellationToken | None = None

        self.source_target_bar.path_changed.connect(self.on_paths_changed)
        self.source_target_bar.refresh_requested.connect(self.refresh_compare)
        self.source_target_bar.cancel_requested.connect(self.cancel_scan)
        self.source_target_bar.clear_requested.connect(self.clear_all_lists)
        self.source_target_bar.redundancy_scan_requested.connect(self.open_redundancy_scan)
        self.action_diff_panel.action_selected.connect(self.on_action_selected)
        self.action_diff_panel.selection_changed.connect(self.on_selection_changed)
        self.transfer_panel.transfer_requested.connect(self.show_transfer_preview)
        self.transfer_panel.cancel_requested.connect(self.cancel_transfer)
        self.transfer_panel.clear_selection_requested.connect(self.action_diff_panel.clear_selection)
        self.preview_panel.path_dropped.connect(self._on_preview_path_dropped)

        self._restore_recent_paths()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._active_threads:
            reply = QMessageBox.question(
                self,
                "任务进行中",
                "当前有正在运行的扫描或传输任务，是否取消并退出？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            # 请求取消所有任务
            if self._scan_cancel_token:
                self._scan_cancel_token.cancel()
            if self._transfer_cancel_token:
                self._transfer_cancel_token.cancel()
            # 给线程一点时间退出，但不阻塞 UI——由 Qt 退出时清理
            super().closeEvent(event)
            return
        super().closeEvent(event)

    def on_paths_changed(self, source_path: str, target_path: str) -> None:
        # 入口统一归一化，保证拖放/对话框/设置恢复等来源的路径可正确比较
        source_path = normalize_path(source_path)
        target_path = normalize_path(target_path)
        source_changed = source_path != self.state.left_root_path
        target_changed = target_path != self.state.right_root_path
        final_target = target_path

        # 来源变化（拖入/选择）时，自动在目标侧寻找同名文件夹并填入
        if source_changed and not target_changed and source_path:
            final_target = self._auto_match_target(source_path, target_path)

        # 用户手动更换目标时，记住其父目录作为目标根，供后续自动匹配递归兜底
        if target_changed and final_target and Path(final_target).parent.is_dir():
            self._save_target_root(normalize_path(str(Path(final_target).parent)))

        self.state.left_root_path = source_path
        self.state.right_root_path = final_target
        self.settings.setValue("paths/source", source_path)
        self.settings.setValue("paths/target", final_target)
        self.settings.sync()
        if final_target != target_path:
            self.source_target_bar.set_paths(source_path, final_target)
        self.source_target_bar.refresh_button.setEnabled(bool(source_path and final_target))
        self._append_recent("source", source_path)
        self._append_recent("target", final_target)
        self._refresh_recent_menus()
        if source_path and final_target:
            self.refresh_compare()

    def _auto_match_target(self, source_path: str, current_target: str) -> str:
        """在目标侧寻找与来源末级目录同名的文件夹；找不到则保留原目标。"""
        name = Path(source_path).name
        if not name:
            return current_target
        roots: list[str] = []
        if current_target:
            roots.append(normalize_path(str(Path(current_target).parent)))
        remembered_root = self._target_root()
        if remembered_root and remembered_root not in roots:
            roots.append(remembered_root)
        matched = find_same_name_folder(name, *roots)
        if matched:
            normalized = normalize_path(matched)
            if normalized != current_target:
                self.transfer_panel.append_log(f"已自动匹配目标文件夹: {normalized}", "info")
            return normalized
        if roots:
            self.transfer_panel.append_log(
                f"目标目录下未找到同名文件夹“{name}”，已保留原目标。",
                "warning",
            )
        else:
            self.transfer_panel.append_log(
                "目标为空，无法自动匹配同名文件夹；请先手动选择一次目标目录。",
                "warning",
            )
        return current_target

    def _target_root(self) -> str:
        return str(self.settings.value("paths/target_root", "") or "")

    def _save_target_root(self, root: str) -> None:
        self.settings.setValue("paths/target_root", root)

    def _on_preview_path_dropped(self, role: str, path: str) -> None:
        """预览画布拖入目录：按 role 更新对应来源/目标目录并触发对比。"""
        source = path if role == "source" else (self.state.left_root_path or "")
        target = path if role == "target" else (self.state.right_root_path or "")
        self.source_target_bar.set_paths(source, target)
        self.on_paths_changed(source, target)

    def _append_recent(self, role: str, path: str) -> None:
        """把目录追加到对应角色的最近列表（去重、最多保留 10 条、最新在前）。"""
        if not path:
            return
        key = f"paths/recent_{role}"
        recent = self.settings.value(key, []) or []
        if isinstance(recent, str):
            recent = [recent]
        recent = [p for p in recent if p != path]
        recent.insert(0, path)
        self.settings.setValue(key, recent[:10])

    def _refresh_recent_menus(self) -> None:
        """从持久化读取最近目录列表并刷新来源/目标下拉菜单。"""
        self.source_target_bar.set_recent_paths(
            self.settings.value("paths/recent_source", []) or [],
            self.settings.value("paths/recent_target", []) or [],
        )

    def open_redundancy_scan(self) -> None:
        """打开冗余帧扫描工具；若在工具里移动了来源目录下的文件，回来后刷新对比。"""
        dialog = RedundancyDialog(default_root=self.state.left_root_path or "", parent=self)
        dialog.exec()
        scanned_root = normalize_path(dialog.scanned_root())
        if dialog.moved_anything and scanned_root and scanned_root == normalize_path(self.state.left_root_path):
            self.refresh_compare()

    def refresh_compare(self) -> None:
        if not self.state.left_root_path or not self.state.right_root_path:
            self.source_target_bar.set_scan_status("请选择来源和目标目录", "idle")
            return
        if self._scan_in_progress or self._transfer_in_progress:
            return
        self._scan_in_progress = True
        self._scan_cancel_token = CancellationToken()
        self.source_target_bar.set_scan_status("正在扫描并对比目录…", "busy")
        self.source_target_bar.set_busy(True)
        self.action_diff_panel.set_controls_enabled(False)
        self.transfer_panel.set_transfer_enabled(False)
        worker = ScanWorker(
            self.state.left_root_path,
            self.state.right_root_path,
            hash_cache=self._hash_cache,
            cancel_token=self._scan_cancel_token,
        )
        self._run_worker(worker, self._on_compare_finished, self._on_worker_failed)

    def cancel_scan(self) -> None:
        """请求取消当前扫描。"""
        if self._scan_cancel_token:
            self._scan_cancel_token.cancel()
            self.source_target_bar.set_scan_status("正在取消…", "busy")

    def _on_compare_finished(self, compare_result) -> None:
        self._scan_in_progress = False
        self._scan_cancel_token = None
        self.state.compare_result = compare_result
        self.state.action_items = self.action_diff_service.build_actions(compare_result)
        eligible = {
            file_item.relative_path
            for action in self.state.action_items
            for file_item in action.transferable_files
        }
        self.state.selected_file_paths.intersection_update(eligible)
        self.action_diff_panel.populate(self.state.action_items, self.state.selected_file_paths)
        update_count = sum(action.transfer_file_count > 0 for action in self.state.action_items)
        file_count = sum(action.transfer_file_count for action in self.state.action_items)
        self.source_target_bar.set_scan_status(
            f"扫描完成 · {update_count} 个动作待更新 · {file_count} 个文件",
            "ready",
        )
        self.source_target_bar.set_busy(False)
        self.action_diff_panel.set_controls_enabled(True)
        self.transfer_panel.set_transfer_enabled(True)

    def _on_worker_failed(self, message: str) -> None:
        self._scan_in_progress = False
        self._scan_cancel_token = None
        self.source_target_bar.set_busy(False)
        self.action_diff_panel.set_controls_enabled(True)
        self.transfer_panel.set_transfer_enabled(True)
        if "取消" in message:
            self.source_target_bar.set_scan_status("扫描已取消", "idle")
            self.transfer_panel.append_log(message, "warning")
        else:
            self.source_target_bar.set_scan_status("扫描失败", "error")
            self.transfer_panel.append_log(message, "error")
            QMessageBox.critical(self, "扫描失败", message)

    def on_action_selected(self, relative_path: str) -> None:
        self.state.selected_relative_path = relative_path
        self.preview_panel.clear_all()
        self.load_previews(relative_path)

    def on_selection_changed(self, selected_paths: set[str]) -> None:
        self.state.selected_file_paths = set(selected_paths)
        summary = self.action_diff_service.selected_summary(
            self.state.action_items,
            self.state.selected_file_paths,
        )
        self.transfer_panel.set_selection_summary(*summary)

    def load_previews(self, relative_path: str) -> None:
        if not self.state.compare_result:
            return
        pair = self.state.compare_result.node_map.get(relative_path.casefold())
        if not pair:
            return
        self._start_preview_worker("left", relative_path, pair.left)
        self._start_preview_worker("right", relative_path, pair.right)

    def _start_preview_worker(self, side: str, relative_path: str, node) -> None:
        worker = PreviewWorker(side, relative_path, node)
        self._run_worker(worker, self._on_preview_finished, self._on_preview_failed)

    def _on_preview_finished(self, item: PreviewItem) -> None:
        if item.relative_path != self.state.selected_relative_path:
            return
        self.preview_panel.set_preview(item.side, item)

    def _on_preview_failed(self, side: str, message: str) -> None:
        item = PreviewItem(
            side=side,
            relative_path=self.state.selected_relative_path,
            source_path=None,
            cache_path=None,
            status="error",
            message=message,
        )
        self.preview_panel.set_preview(side, item)
        role = "来源" if side == "left" else "目标"
        self.transfer_panel.append_log(f"{role}预览失败: {message}", "error")

    def show_transfer_preview(self) -> None:
        paths = sorted(self.state.selected_file_paths)
        if not paths:
            QMessageBox.information(self, "提示", "请先勾选要传输的动作或文件。")
            return
        dialog = TransferPreviewDialog(
            self.state.left_root_path,
            self.state.right_root_path,
            paths,
            self.action_diff_service.file_to_action(self.state.action_items),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        final_paths = dialog.selected_paths()
        if not final_paths:
            return
        self.action_diff_panel.set_selected_paths(set(final_paths))
        self._start_transfer(final_paths)

    def _start_transfer(self, relative_paths: list[str]) -> None:
        job = self.transfer_service.build_job_for_files(
            self.state.left_root_path,
            self.state.right_root_path,
            relative_paths,
        )
        if job.total_files == 0:
            QMessageBox.information(self, "提示", "选中范围内没有可复制文件。")
            return
        self.transfer_panel.reset_progress()
        self._transfer_in_progress = True
        self._transfer_cancel_token = CancellationToken()
        self.transfer_panel.set_busy(True)
        self.source_target_bar.set_busy(True)
        self.action_diff_panel.set_controls_enabled(False)
        self._success = 0
        self._failed = 0
        self._skipped = 0
        self.transfer_panel.append_log(f"开始传输，共 {job.total_files} 个文件。", "info")
        self._run_transfer_worker(TransferWorker(job, cancel_token=self._transfer_cancel_token))

    def cancel_transfer(self) -> None:
        """请求取消当前传输。"""
        if self._transfer_cancel_token:
            self._transfer_cancel_token.cancel()
            self.transfer_panel.append_log("正在取消传输…", "warning")

    def _run_transfer_worker(self, worker: TransferWorker) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.job_started.connect(self._on_job_started)
        worker.file_started.connect(self._on_file_started)
        worker.progress_changed.connect(self._on_progress_changed)
        worker.file_finished.connect(self._on_file_finished)
        worker.job_completed.connect(self._on_job_completed)
        worker.job_failed.connect(self._on_transfer_error)
        worker.job_completed.connect(thread.quit)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._release_worker(worker, thread))
        self._active_threads.append(thread)
        self._active_workers.append(worker)
        thread.start()

    def _on_job_started(self, total_files: int) -> None:
        self._total_files = total_files
        self.transfer_panel.set_progress(0, total_files)

    def _on_file_started(self, index: int, relative_path: str, total_bytes: int) -> None:
        self.transfer_panel.set_file_started(relative_path)
        self.transfer_panel.append_log(
            f"[{index}/{self._total_files}] 开始复制: {relative_path} ({self._format_size(total_bytes)})",
            "info",
        )

    def _on_progress_changed(self, copied: int, total: int) -> None:
        # 只更新进度条，不改动 status_label（避免反复冲掉文件名/统计）
        if total:
            percent = copied * 100 // total
            self.transfer_panel.set_file_progress(percent)

    def _on_file_finished(self, index: int, relative_path: str, success: bool) -> None:
        if success:
            self._success += 1
        else:
            self._failed += 1
        self.transfer_panel.set_progress(index, self._total_files)
        self.transfer_panel.set_stats(self._success, self._failed, self._skipped)
        self.transfer_panel.append_log(
            f"[{index}/{self._total_files}] {'完成' if success else '失败'}: {relative_path}",
            "success" if success else "error",
        )

    def _on_transfer_error(self, message: str) -> None:
        self.transfer_panel.append_log(message, "error")

    def _on_job_completed(self, success: int, failed: int, skipped: int) -> None:
        self._transfer_in_progress = False
        self._transfer_cancel_token = None
        self.transfer_panel.set_stats(success, failed, skipped)
        was_cancelled = skipped > 0
        if was_cancelled:
            self.transfer_panel.append_log(
                f"传输已取消（成功 {success} · 失败 {failed} · 跳过 {skipped}）。",
                "warning",
            )
        else:
            self.transfer_panel.append_log(
                "传输完成，正在重新扫描。",
                "success" if failed == 0 else "warning",
            )
        self.transfer_panel.set_busy(False)
        self.source_target_bar.set_busy(False)
        self.action_diff_panel.set_controls_enabled(True)
        # 取消后不复扫，避免用户等待
        if not was_cancelled:
            QTimer.singleShot(0, self.refresh_compare)

    def clear_all_lists(self) -> None:
        if self._scan_in_progress or self._transfer_in_progress:
            return
        self.state = AppState()
        self.source_target_bar.set_paths("", "")
        self.source_target_bar.set_scan_status("请选择来源和目标目录", "idle")
        self.action_diff_panel.reset()
        self.preview_panel.clear_all()
        self.transfer_panel.reset_progress()
        self.transfer_panel.reset_actions()

    def _restore_recent_paths(self) -> None:
        source = normalize_path(str(self.settings.value("paths/source", "") or ""))
        target = normalize_path(str(self.settings.value("paths/target", "") or ""))
        self.state.left_root_path = source
        self.state.right_root_path = target
        self.source_target_bar.set_paths(source, target)
        self.source_target_bar.refresh_button.setEnabled(bool(source and target))
        self._refresh_recent_menus()
        if source and target:
            self.source_target_bar.set_scan_status("已恢复上次目录，点击“刷新对比”开始扫描", "idle")

    def _run_worker(self, worker, finished, failed) -> None:
        thread = QThread(self)
        worker.moveToThread(thread)
        worker.finished.connect(finished)
        worker.failed.connect(failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._release_worker(worker, thread))
        thread.started.connect(worker.run)
        self._active_threads.append(thread)
        self._active_workers.append(worker)
        thread.start()

    def _release_worker(self, worker: object, thread: QThread) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)
        if thread in self._active_threads:
            self._active_threads.remove(thread)

    @staticmethod
    def _format_size(size: int) -> str:
        if size >= 1024 ** 2:
            return f"{size / 1024 ** 2:.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size} B"
