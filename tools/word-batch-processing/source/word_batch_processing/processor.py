from __future__ import annotations

import json
import os
import stat
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .models import OperationName, OperationPreview, OperationResult, OperationStatus
from .ports import OperationCancelled, WordAdapter


SUPPORTED_SUFFIXES = {".doc", ".docx"}
UNSUPPORTED_WORD_SUFFIXES = {".docm", ".dot", ".dotm", ".dotx"}


def collect_word_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not path.name.startswith("~$")
        and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


@dataclass(frozen=True)
class _LastOperation:
    name: OperationName
    args: tuple[object, ...]
    failed_paths: tuple[str, ...] = ()


class DocumentBatchProcessor:
    """通过单一高层接口处理当前文档批次。"""

    def __init__(
        self,
        workspace: str | Path,
        word: WordAdapter,
        *,
        checkpoint_root: str | Path | None = None,
        batch_id: str | None = None,
        progress: Callable[[str, int, int, OperationResult], None] | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.word = word
        default_root = Path(os.getenv("LOCALAPPDATA", tempfile.gettempdir()))
        self.checkpoint_root = Path(checkpoint_root or default_root / "WordBatchProcessing" / "checkpoint")
        self.batch_id = batch_id or os.path.normcase(str(self.workspace))
        self.progress = progress
        self._last_operation: _LastOperation | None = None
        self._retry_checkpoint: Path | None = None
        self._cancelled = False
        self._retrying = False

    def cancel(self) -> None:
        self._cancelled = True
        self.word.cancel_current()

    @property
    def can_undo(self) -> bool:
        return self._checkpoint_data() is not None

    def reset_undo_history(self) -> None:
        for checkpoint in (
            self.checkpoint_root,
            self._pending_checkpoint(),
            self._previous_checkpoint(),
        ):
            if checkpoint.exists():
                shutil.rmtree(checkpoint)

    def search(self, text: str, *, only_paths: Iterable[str] | None = None) -> OperationResult:
        return self._run_read(
            OperationName.SEARCH,
            lambda path: self.word.search(path, text),
            (text,),
            only_paths,
        )

    def replace_text(
        self,
        find_text: str,
        replace_text: str,
        track_changes: bool = True,
        *,
        only_paths: Iterable[str] | None = None,
    ) -> OperationResult:
        return self._run_mutation(
            OperationName.REPLACE,
            lambda path: self.word.replace_text(path, find_text, replace_text, track_changes),
            (find_text, replace_text, track_changes),
            only_paths,
        )

    def preview_accept_revisions(self) -> OperationPreview:
        return self._preview(self.word.count_revisions)

    def accept_all_revisions(
        self, *, only_paths: Iterable[str] | None = None
    ) -> OperationResult:
        return self._run_mutation(
            OperationName.ACCEPT_REVISIONS,
            self.word.accept_all_revisions,
            (),
            only_paths,
        )

    def preview_delete_comments(self) -> OperationPreview:
        return self._preview(self.word.count_comments)

    def delete_all_comments(
        self, *, only_paths: Iterable[str] | None = None
    ) -> OperationResult:
        return self._run_mutation(
            OperationName.DELETE_COMMENTS,
            self.word.delete_all_comments,
            (),
            only_paths,
        )

    def update_toc_page_numbers(
        self, *, only_paths: Iterable[str] | None = None
    ) -> OperationResult:
        return self._run_mutation(
            OperationName.UPDATE_TOC,
            self.word.update_toc_page_numbers,
            (),
            only_paths,
        )

    def rename_files(
        self,
        find_text: str,
        replace_text: str,
        *,
        only_paths: Iterable[str] | None = None,
    ) -> OperationResult:
        self._begin_task()
        plans, result = self._rename_plans(find_text, replace_text, only_paths)
        if only_paths is None:
            self._add_unsupported_skips(result)
        if not plans:
            failed = self._retryable_paths(result)
            self._last_operation = _LastOperation(
                OperationName.RENAME, (find_text, replace_text), failed
            )
            return self._finalize_result(result, failed)
        checkpoint = (
            self._retry_checkpoint or self.checkpoint_root
            if self._retrying
            else self._pending_checkpoint()
        )
        if not self._retrying:
            self._create_checkpoint(checkpoint)
        changes: list[dict[str, str]] = []
        total = len(plans)
        processed = 0
        for component in self._rename_components(plans):
            if self._cancelled:
                result.status = OperationStatus.CANCELLED
                break
            staged: list[tuple[Path, Path, Path]] = []
            stage_error: tuple[Path, str] | None = None
            for component_index, (source, target) in enumerate(component):
                staging = source.with_name(
                    f".__word_batch_rename_{processed + component_index}__{source.suffix}"
                )
                try:
                    source.rename(staging)
                    staged.append((source, staging, target))
                except Exception as exc:
                    stage_error = (source, str(exc))
                    break
            if self._cancelled:
                try:
                    self._rollback_rename_component(staged, [])
                except Exception as exc:
                    result.add_failure("", str(exc))
                result.status = OperationStatus.CANCELLED
                break
            if stage_error is not None:
                failed_source, error_message = stage_error
                result.add_failure(self._relative(failed_source), error_message)
                try:
                    self._rollback_rename_component(staged, [])
                except Exception as rollback_exc:
                    result.add_failure("", str(rollback_exc))
                for source, _target in component:
                    if source != failed_source:
                        result.add_skip(
                            self._relative(source), "关联改名未执行，可在解除占用后重试"
                        )
                for source, _target in component:
                    processed += 1
                    self._emit_progress(self._relative(source), processed, total, result)
                continue

            committed: list[tuple[Path, Path, Path]] = []
            commit_error: tuple[Path, str] | None = None
            for source, staging, target in staged:
                try:
                    staging.rename(target)
                    committed.append((source, staging, target))
                except Exception as exc:
                    commit_error = (source, str(exc))
                    break
            if commit_error is not None:
                failed_source, error_message = commit_error
                result.add_failure(self._relative(failed_source), error_message)
                try:
                    self._rollback_rename_component(staged, committed)
                except Exception as rollback_exc:
                    result.add_failure("", str(rollback_exc))
                for source, _target in component:
                    if source != failed_source:
                        result.add_skip(
                            self._relative(source), "关联改名已回滚，可在解除冲突后重试"
                        )
            else:
                for source, _staging, target in committed:
                    result.succeeded += 1
                    changes.append(
                        {"before": self._relative(source), "after": self._relative(target)}
                    )
            for source, _target in component:
                processed += 1
                self._emit_progress(self._relative(source), processed, total, result)

        if result.status is not OperationStatus.CANCELLED:
            result._refresh_status()
        failed = self._retryable_paths(result)
        self._last_operation = _LastOperation(
            OperationName.RENAME, (find_text, replace_text), failed
        )
        self._finish_checkpoint(checkpoint, changes, keep_for_retry=bool(failed))
        return self._finalize_result(result, failed)

    def retry_last(self) -> OperationResult:
        operation = self._last_operation
        if operation is None or not operation.failed_paths:
            return OperationResult(can_undo=self.can_undo)
        self._retrying = True
        try:
            if operation.name is OperationName.REPLACE:
                return self.replace_text(
                    str(operation.args[0]),
                    str(operation.args[1]),
                    bool(operation.args[2]),
                    only_paths=operation.failed_paths,
                )
            if operation.name is OperationName.ACCEPT_REVISIONS:
                return self.accept_all_revisions(only_paths=operation.failed_paths)
            if operation.name is OperationName.DELETE_COMMENTS:
                return self.delete_all_comments(only_paths=operation.failed_paths)
            if operation.name is OperationName.UPDATE_TOC:
                return self.update_toc_page_numbers(only_paths=operation.failed_paths)
            if operation.name is OperationName.SEARCH:
                return self.search(str(operation.args[0]), only_paths=operation.failed_paths)
            return self.rename_files(
                str(operation.args[0]),
                str(operation.args[1]),
                only_paths=operation.failed_paths,
            )
        finally:
            self._retrying = False

    def undo_last(self) -> OperationResult:
        data = self._checkpoint_data()
        files_root = self.checkpoint_root / "files"
        if data is None:
            result = OperationResult(status=OperationStatus.FAILED)
            result.add_failure("", "没有属于当前文档批次的可撤销操作")
            return result
        result = OperationResult()
        changes = data.get("changes", [])
        for change in reversed(changes):
            before = str(change["before"])
            after = str(change["after"])
            source = files_root / before
            before_path = self.workspace / before
            after_path = self.workspace / after
            try:
                before_path.parent.mkdir(parents=True, exist_ok=True)
                if not source.is_file() or source.stat().st_size == 0:
                    raise OSError("撤销检查点文件缺失或为空")
                if after != before and before_path.exists():
                    raise FileExistsError(f"原文件名已被占用：{before_path.name}")
                with tempfile.TemporaryDirectory(
                    prefix="word-batch-undo-", dir=before_path.parent
                ) as temp_dir:
                    temporary = Path(temp_dir) / before_path.name
                    shutil.copy2(source, temporary)
                    if not temporary.is_file() or temporary.stat().st_size == 0:
                        raise OSError("撤销临时文件验证失败")
                    os.replace(temporary, before_path)
                if after != before and after_path.exists():
                    try:
                        after_path.unlink()
                    except Exception:
                        raise OSError(
                            f"已恢复 {before_path.name}，但无法删除 {after_path.name}；"
                            "两个文件均已保留"
                        )
                result.succeeded += 1
            except Exception as exc:
                result.add_failure(before, str(exc))
        if not result.failed:
            shutil.rmtree(self.checkpoint_root)
            self._last_operation = None
        else:
            result._refresh_status()
        result.can_undo = self.can_undo
        return result

    def _run_read(
        self,
        name: OperationName,
        action: Callable[[Path], bool],
        args: tuple[object, ...],
        only_paths: Iterable[str] | None,
    ) -> OperationResult:
        result = OperationResult()
        if only_paths is None:
            self._add_unsupported_skips(result)
        paths = self._paths(only_paths)
        self._begin_task()
        for index, path in enumerate(paths, 1):
            relative = self._relative(path)
            if self._cancelled:
                result.status = OperationStatus.CANCELLED
                break
            try:
                found = action(path)
                if self._cancelled:
                    result.status = OperationStatus.CANCELLED
                    break
                if found:
                    result.hits.append(relative)
                result.succeeded += 1
            except OperationCancelled:
                result.status = OperationStatus.CANCELLED
                break
            except PermissionError as exc:
                result.add_skip(relative, str(exc) or "文件正在使用或没有读取权限")
            except Exception as exc:
                result.add_failure(relative, str(exc))
            self._emit_progress(relative, index, len(paths), result)
        if result.status is not OperationStatus.CANCELLED:
            result._refresh_status()
        failed = self._retryable_paths(result)
        self._last_operation = _LastOperation(name, args, failed)
        return self._finalize_result(result, failed)

    def _run_mutation(
        self,
        name: OperationName,
        action: Callable[[Path], object],
        args: tuple[object, ...],
        only_paths: Iterable[str] | None,
    ) -> OperationResult:
        paths = self._paths(only_paths)
        result = OperationResult()
        if only_paths is None:
            self._add_unsupported_skips(result)
        checkpoint = (
            self._retry_checkpoint or self.checkpoint_root
            if self._retrying
            else self._pending_checkpoint()
        )
        if not self._retrying:
            self._create_checkpoint(checkpoint)
        changes: list[dict[str, str]] = []
        self._begin_task()
        for index, path in enumerate(paths, 1):
            relative = self._relative(path)
            if self._cancelled:
                result.status = OperationStatus.CANCELLED
                break
            try:
                committed = self._mutate_safely(path, action)
                if self._cancelled:
                    result.status = OperationStatus.CANCELLED
                    break
                result.succeeded += 1
                if committed:
                    changes.append({"before": relative, "after": relative})
            except OperationCancelled:
                result.status = OperationStatus.CANCELLED
                break
            except PermissionError as exc:
                result.add_skip(relative, str(exc) or "文件正在使用或没有写入权限")
            except Exception as exc:
                result.add_failure(relative, str(exc))
            self._emit_progress(relative, index, len(paths), result)
        if result.status is not OperationStatus.CANCELLED:
            result._refresh_status()
        failed = self._retryable_paths(result)
        self._last_operation = _LastOperation(name, args, failed)
        self._finish_checkpoint(checkpoint, changes, keep_for_retry=bool(failed))
        return self._finalize_result(result, failed)

    def _mutate_safely(self, path: Path, action: Callable[[Path], object]) -> bool:
        with tempfile.TemporaryDirectory(prefix="word-batch-", dir=path.parent) as temp_dir:
            temporary = Path(temp_dir) / path.name
            shutil.copy2(path, temporary)
            temporary.chmod(temporary.stat().st_mode | stat.S_IWRITE)
            changed = action(temporary)
            if self._cancelled:
                raise OperationCancelled("任务已取消")
            if changed == 0:
                return False
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise OSError("处理结果无法通过基本可读性验证")
            path.chmod(path.stat().st_mode | stat.S_IWRITE)
            os.replace(temporary, path)
            return True

    def _begin_task(self) -> None:
        self._cancelled = False
        self.word.begin_task()

    def _finalize_result(
        self, result: OperationResult, retryable_paths: tuple[str, ...]
    ) -> OperationResult:
        result.can_retry = bool(retryable_paths)
        result.can_undo = self.can_undo
        return result

    def _preview(self, counter: Callable[[Path], int]) -> OperationPreview:
        self._begin_task()
        files = 0
        items = 0
        for path in collect_word_files(self.workspace):
            try:
                count = counter(path)
            except Exception:
                continue
            if count:
                files += 1
                items += count
        return OperationPreview(files, items)

    def _paths(self, only_paths: Iterable[str] | None) -> list[Path]:
        if only_paths is None:
            return collect_word_files(self.workspace)
        return [self.workspace / relative for relative in only_paths if (self.workspace / relative).is_file()]

    def _unsupported_word_files(self) -> list[Path]:
        return sorted(
            path
            for path in self.workspace.rglob("*")
            if path.is_file()
            and not path.name.startswith("~$")
            and path.suffix.lower() in UNSUPPORTED_WORD_SUFFIXES
        )

    def _add_unsupported_skips(self, result: OperationResult) -> None:
        for path in self._unsupported_word_files():
            result.add_skip(
                self._relative(path),
                f"不支持 {path.suffix.lower()} 格式；仅处理 .doc 和 .docx",
            )

    def _retryable_paths(self, result: OperationResult) -> tuple[str, ...]:
        return tuple(
            item.path
            for item in result.items
            if Path(item.path).suffix.lower() in SUPPORTED_SUFFIXES
        )

    def _pending_checkpoint(self) -> Path:
        return self.checkpoint_root.with_name(self.checkpoint_root.name + ".pending")

    def _previous_checkpoint(self) -> Path:
        return self.checkpoint_root.with_name(self.checkpoint_root.name + ".previous")

    def _checkpoint_data(self) -> dict[str, Any] | None:
        manifest = self.checkpoint_root / "manifest.json"
        files_root = self.checkpoint_root / "files"
        if not manifest.is_file() or not files_root.is_dir():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        if data.get("batch_id") != self.batch_id:
            return None
        manifest_workspace = os.path.normcase(str(data.get("workspace", "")))
        if manifest_workspace != os.path.normcase(str(self.workspace)):
            return None
        return data

    def _create_checkpoint(self, checkpoint: Path) -> None:
        if checkpoint.exists():
            shutil.rmtree(checkpoint)
        files_root = checkpoint / "files"
        for path in collect_word_files(self.workspace):
            relative = path.relative_to(self.workspace)
            target = files_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        self._write_checkpoint_metadata(checkpoint, [])

    def _write_checkpoint_metadata(
        self, checkpoint: Path, changes: list[dict[str, str]]
    ) -> None:
        files_root = checkpoint / "files"
        if not files_root.exists():
            return
        files = [str(path.relative_to(files_root)) for path in collect_word_files(files_root)]
        manifest = checkpoint / "manifest.json"
        temporary = checkpoint / "manifest.tmp"
        temporary.write_text(
            json.dumps(
                {
                    "batch_id": self.batch_id,
                    "workspace": str(self.workspace),
                    "files": files,
                    "changes": changes,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, manifest)

    def _finish_checkpoint(
        self,
        checkpoint: Path,
        new_changes: list[dict[str, str]],
        *,
        keep_for_retry: bool,
    ) -> None:
        if not new_changes:
            if keep_for_retry:
                self._retry_checkpoint = checkpoint
            elif checkpoint != self.checkpoint_root:
                shutil.rmtree(checkpoint, ignore_errors=True)
            return
        manifest = checkpoint / "manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        changes = list(data.get("changes", []))
        changes.extend(new_changes)
        self._write_checkpoint_metadata(checkpoint, changes)
        if checkpoint != self.checkpoint_root:
            previous = self._previous_checkpoint()
            if previous.exists():
                shutil.rmtree(previous)
            if self.checkpoint_root.exists():
                os.replace(self.checkpoint_root, previous)
            try:
                os.replace(checkpoint, self.checkpoint_root)
            except Exception:
                if previous.exists() and not self.checkpoint_root.exists():
                    os.replace(previous, self.checkpoint_root)
                raise
            if previous.exists():
                shutil.rmtree(previous)
        self._retry_checkpoint = None

    def _rename_plans(
        self,
        find_text: str,
        replace_text: str,
        only_paths: Iterable[str] | None = None,
    ) -> tuple[list[tuple[Path, Path]], OperationResult]:
        result = OperationResult()
        all_files = collect_word_files(self.workspace)
        files = all_files if only_paths is None else self._paths(only_paths)
        proposals: list[tuple[Path, Path]] = []
        for source in files:
            new_stem = source.stem.replace(find_text, replace_text)
            if not new_stem.strip():
                result.add_failure(self._relative(source), "替换后文件名为空")
                return [], result
            target = source.with_name(new_stem + source.suffix)
            if os.path.normcase(str(target)) == os.path.normcase(str(source)):
                continue
            proposals.append((source, target))

        target_groups: dict[str, list[tuple[Path, Path]]] = {}
        for proposal in proposals:
            target_groups.setdefault(os.path.normcase(str(proposal[1])), []).append(
                proposal
            )
        conflicts = {
            os.path.normcase(str(source))
            for group in target_groups.values()
            if len(group) > 1
            for source, _target in group
        }
        for group in target_groups.values():
            if len(group) > 1:
                for source, _target in group:
                    result.add_skip(
                        self._relative(source), "多个文件将改为同一名称"
                    )

        plans = [
            proposal
            for proposal in proposals
            if os.path.normcase(str(proposal[0])) not in conflicts
        ]
        while True:
            moving_sources = {
                os.path.normcase(str(source)) for source, _target in plans
            }
            blocked = [
                (source, target)
                for source, target in plans
                if target.exists()
                and os.path.normcase(str(target)) not in moving_sources
            ]
            if not blocked:
                break
            blocked_sources = {
                os.path.normcase(str(source)) for source, _target in blocked
            }
            for source, _target in blocked:
                result.add_skip(self._relative(source), "目标名称已存在且不会被移走")
            plans = [
                proposal
                for proposal in plans
                if os.path.normcase(str(proposal[0])) not in blocked_sources
            ]
        return plans, result

    def _rename_components(
        self, plans: list[tuple[Path, Path]]
    ) -> list[list[tuple[Path, Path]]]:
        parent = list(range(len(plans)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        source_indexes = {
            os.path.normcase(str(source)): index
            for index, (source, _target) in enumerate(plans)
        }
        for index, (_source, target) in enumerate(plans):
            target_source = source_indexes.get(os.path.normcase(str(target)))
            if target_source is not None:
                union(index, target_source)

        grouped: dict[int, list[tuple[int, tuple[Path, Path]]]] = {}
        for index, plan in enumerate(plans):
            grouped.setdefault(find(index), []).append((index, plan))
        return [
            [plan for _index, plan in sorted(group)]
            for _root, group in sorted(
                grouped.items(), key=lambda item: min(index for index, _plan in item[1])
            )
        ]

    def _rollback_rename_component(
        self,
        staged: list[tuple[Path, Path, Path]],
        committed: list[tuple[Path, Path, Path]],
    ) -> None:
        errors: list[str] = []
        for _source, staging, target in reversed(committed):
            try:
                if target.exists():
                    target.rename(staging)
            except Exception as exc:
                errors.append(str(exc))
        for source, staging, _target in reversed(staged):
            try:
                if staging.exists():
                    staging.rename(source)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise OSError("改名回滚未完全成功：" + "；".join(errors))

    def _emit_progress(
        self, path: str, current: int, total: int, result: OperationResult
    ) -> None:
        if self.progress:
            self.progress(path, current, total, result)

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.workspace))
