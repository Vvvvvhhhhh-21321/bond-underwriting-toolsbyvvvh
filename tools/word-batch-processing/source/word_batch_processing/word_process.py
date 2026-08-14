from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
import zipfile
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from .models import OperationName
from .ports import OperationCancelled


class _WorkerCrashed(RuntimeError):
    pass


def _word_session_is_unavailable(response: dict[str, Any]) -> bool:
    message = str(response.get("error", ""))
    return response.get("hresult") == -2147023174 or (
        "-2147023174" in message or "RPC 服务器不可用" in message
    )


def _validate_word_process_ownership(
    word_pid: int,
    existing_word_pids: set[int],
    created_at: float,
    dispatch_started: float,
) -> None:
    if word_pid in existing_word_pids or created_at < dispatch_started - 2:
        raise RuntimeError(
            "无法确认 Word 实例由本软件独占，任务已停止且不会接管现有 Word"
        )


class IsolatedWordProcessAdapter:
    """在独立进程中独占 Word 实例的生产适配器。"""

    def __init__(self, timeout: float = 120.0):
        self.timeout = timeout
        self._process: Any = None
        self._connection: Any = None
        self.word_pid: int | None = None
        self.word_created_at: float | None = None
        self.worker_pid: int | None = None
        self._cancel_requested = threading.Event()

    def begin_task(self) -> None:
        self._cancel_requested.clear()

    def cancel_current(self) -> None:
        self._cancel_requested.set()

    def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        self._discard_dead_worker()
        context = mp.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=_serve_word, args=(child,), daemon=True)
        process.start()
        child.close()
        if not parent.poll(self.timeout):
            process.terminate()
            process.join(5)
            raise TimeoutError("无法在规定时间内启动隔离 Word 实例")
        message = parent.recv()
        if not message.get("ok"):
            process.join(5)
            raise RuntimeError(message.get("error", "无法启动隔离 Word 实例"))
        self._process = process
        self._connection = parent
        self.word_pid = int(message["word_pid"])
        self.word_created_at = float(message["word_created_at"])
        self.worker_pid = int(message["worker_pid"])

    def _discard_dead_worker(self) -> None:
        process, connection = self._process, self._connection
        if process is None or process.is_alive():
            return
        self._process = None
        self._connection = None
        self._terminate_owned_word()
        if connection is not None:
            connection.close()

    def close(self) -> None:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        graceful = False
        if process is None:
            return
        if process.is_alive() and connection is not None:
            try:
                connection.send({"operation": "close"})
                if connection.poll(10):
                    connection.recv()
                    graceful = True
            except (BrokenPipeError, EOFError, OSError):
                pass
        if graceful:
            process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(10)
        # Word 偶尔会在 COM 工作进程正常退出后继续驻留。无论关闭路径如何，
        # 都按 PID 与创建时间复核并清理本软件拥有的实例。
        self._terminate_owned_word()
        if connection is not None:
            connection.close()

    def _force_stop_worker(self) -> None:
        process, connection = self._process, self._connection
        self._process = None
        self._connection = None
        if process is not None and process.is_alive():
            process.terminate()
            process.join(10)
        self._terminate_owned_word()
        if connection is not None:
            connection.close()

    def _terminate_owned_word(self) -> None:
        pid, created_at = self.word_pid, self.word_created_at
        self.word_pid = None
        self.word_created_at = None
        if pid is None or created_at is None:
            return
        try:
            import psutil

            process = psutil.Process(pid)
            if abs(process.create_time() - created_at) > 0.01:
                return
            try:
                process.wait(5)
                return
            except psutil.TimeoutExpired:
                pass
            process.terminate()
            process.wait(5)
        except (psutil.Error, OSError):
            pass

    def search(self, path: Path, text: str) -> bool:
        return bool(self._call(OperationName.SEARCH, path, text))

    def replace_text(
        self,
        path: Path,
        find_text: str,
        replace_text: str,
        track_changes: bool,
    ) -> bool:
        return bool(
            self._call(OperationName.REPLACE, path, find_text, replace_text, track_changes)
        )

    def count_revisions(self, path: Path) -> int:
        return int(self._call(OperationName.ACCEPT_REVISIONS, path, preview=True))

    def accept_all_revisions(self, path: Path) -> bool:
        return bool(self._call(OperationName.ACCEPT_REVISIONS, path))

    def count_comments(self, path: Path) -> int:
        return int(self._call(OperationName.DELETE_COMMENTS, path, preview=True))

    def delete_all_comments(self, path: Path) -> bool:
        return bool(self._call(OperationName.DELETE_COMMENTS, path))

    def update_toc_page_numbers(self, path: Path) -> bool:
        return bool(self._call(OperationName.UPDATE_TOC, path))

    def _call(self, operation: OperationName, path: Path, *args: object, preview: bool = False) -> Any:
        for attempt in range(2):
            try:
                return self._call_once(operation, path, *args, preview=preview)
            except _WorkerCrashed as exc:
                self.close()
                if attempt == 1:
                    raise RuntimeError("隔离 Word 工作进程连续两次意外退出") from exc
        raise AssertionError("不可达")

    def _call_once(
        self,
        operation: OperationName,
        path: Path,
        *args: object,
        preview: bool = False,
    ) -> Any:
        self.start()
        assert self._connection is not None
        assert self._process is not None
        try:
            self._connection.send(
                {
                    "operation": operation.value,
                    "path": str(path.resolve()),
                    "args": args,
                    "preview": preview,
                }
            )
            deadline = time.monotonic() + self.timeout
            while not self._connection.poll(0.1):
                if self._cancel_requested.is_set():
                    self._force_stop_worker()
                    raise OperationCancelled(f"已取消：{path.name}")
                if time.monotonic() >= deadline:
                    self._force_stop_worker()
                    raise _WorkerCrashed(f"Word 处理超时：{path.name}")
            response = self._connection.recv()
        except (BrokenPipeError, EOFError, OSError) as exc:
            raise _WorkerCrashed("隔离 Word 工作进程意外退出") from exc
        if not response.get("ok"):
            error_type = response.get("type")
            message = response.get("error", "Word 处理失败")
            if error_type == "PermissionError":
                raise PermissionError(message)
            if _word_session_is_unavailable(response):
                raise _WorkerCrashed("隔离 Word 实例已失联")
            raise RuntimeError(message)
        return response.get("value")

    def __enter__(self) -> "IsolatedWordProcessAdapter":
        self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _serve_word(connection: Connection) -> None:
    word = None
    normal_template = None
    owns_word = False
    previous_security = None
    try:
        import pythoncom
        import psutil
        import win32com.client
        import win32process

        pythoncom.CoInitialize()
        existing_word_pids = {
            process.info["pid"]
            for process in psutil.process_iter(["pid", "name"])
            if str(process.info.get("name") or "").casefold() == "winword.exe"
        }
        dispatch_started = time.time()
        word = win32com.client.DispatchEx("Word.Application")
        previous_security = word.AutomationSecurity
        word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
        ownership_document = word.Documents.Add()
        try:
            ownership_window = int(ownership_document.ActiveWindow.Hwnd)
            _, word_pid = win32process.GetWindowThreadProcessId(ownership_window)
        finally:
            ownership_document.Close(False)
        word_process = psutil.Process(word_pid)
        try:
            _validate_word_process_ownership(
                word_pid,
                existing_word_pids,
                word_process.create_time(),
                dispatch_started,
            )
        except RuntimeError:
            word.AutomationSecurity = previous_security
            raise
        owns_word = True
        word.Visible = False
        word.DisplayAlerts = 0
        normal_template = word.NormalTemplate

        connection.send(
            {
                "ok": True,
                "word_pid": word_pid,
                "word_created_at": word_process.create_time(),
                "worker_pid": os.getpid(),
            }
        )

        while True:
            request = connection.recv()
            operation = request["operation"]
            if operation == "close":
                connection.send({"ok": True})
                break
            try:
                value = _execute(
                    word,
                    OperationName(operation),
                    Path(request["path"]),
                    request.get("args", ()),
                    preview=bool(request.get("preview", False)),
                )
                connection.send({"ok": True, "value": value})
            except PermissionError as exc:
                connection.send({"ok": False, "type": "PermissionError", "error": str(exc)})
            except Exception as exc:
                connection.send(
                    {
                        "ok": False,
                        "type": type(exc).__name__,
                        "error": str(exc),
                        "hresult": getattr(exc, "hresult", None),
                    }
                )
    except Exception as exc:
        try:
            connection.send({"ok": False, "error": str(exc)})
        except Exception:
            pass
    finally:
        if word is not None and owns_word:
            try:
                if normal_template is not None:
                    normal_template.Saved = True
                word.Quit(0)
            except Exception:
                pass
        elif word is not None and previous_security is not None:
            try:
                word.AutomationSecurity = previous_security
            except Exception:
                pass
        try:
            import pythoncom

            pythoncom.CoUninitialize()
        except Exception:
            pass
        connection.close()


def _execute(
    word: Any,
    operation: OperationName | str,
    path: Path,
    args: tuple[object, ...],
    *,
    preview: bool = False,
) -> Any:
    operation = OperationName(operation)
    if path.suffix.lower() == ".docx" and not zipfile.is_zipfile(path):
        raise PermissionError("文档可能已加密或不是有效的 DOCX，已在打开前跳过")
    read_only = operation is OperationName.SEARCH or preview
    word.AutomationSecurity = 3
    try:
        document = word.Documents.Open(
            str(path),
            ConfirmConversions=False,
            ReadOnly=read_only,
            AddToRecentFiles=False,
            Revert=False,
            NoEncodingDialog=True,
            PasswordDocument="",
            WritePasswordDocument="",
            OpenAndRepair=False,
        )
    except Exception as exc:
        raise PermissionError(
            "文档无法安全打开（可能需要密码、正在使用或受到保护），已跳过"
        ) from exc
    save = False
    try:
        try:
            if int(document.Signatures.Count):
                raise PermissionError("文档包含数字签名；修改会使签名失效，已跳过")
        except PermissionError:
            raise
        except Exception:
            pass
        try:
            if bool(document.Permission.Enabled):
                raise PermissionError("文档受信息权限管理保护，已跳过")
        except PermissionError:
            raise
        except Exception:
            pass
        protection = int(document.ProtectionType)
        if protection != -1:  # wdNoProtection
            raise PermissionError("文档受到编辑保护，已跳过")

        if operation is OperationName.SEARCH:
            return _search_document(document, str(args[0]))
        if operation is OperationName.REPLACE:
            document.UpdateStylesOnOpen = False
            document.TrackRevisions = bool(args[2])
            changed = False
            for text_range in _text_ranges(document):
                changed = _replace_range(text_range, str(args[0]), str(args[1])) or changed
            save = changed
            return changed
        if operation is OperationName.ACCEPT_REVISIONS and preview:
            return _count_revisions(document)
        if operation is OperationName.ACCEPT_REVISIONS:
            count = _count_revisions(document)
            track_revisions = bool(document.TrackRevisions)
            if count:
                _accept_all_revisions(document)
            document.TrackRevisions = False
            save = bool(count or track_revisions)
            return save
        if operation is OperationName.DELETE_COMMENTS and preview:
            return int(document.Comments.Count)
        if operation is OperationName.DELETE_COMMENTS:
            count = int(document.Comments.Count)
            for index in range(count, 0, -1):
                comment = document.Comments(index)
                try:
                    comment.DeleteRecursively()
                except Exception:
                    comment.Delete()
            save = True
            return count > 0
        if operation is OperationName.UPDATE_TOC:
            count = int(document.TablesOfContents.Count)
            for index in range(1, count + 1):
                document.TablesOfContents(index).UpdatePageNumbers()
            save = count > 0
            return count > 0
        raise ValueError(f"未知 Word 操作：{operation}")
    finally:
        try:
            if save:
                document.Save()
        finally:
            document.Close(False)


def _story_ranges(document: Any):
    for story_type in range(1, 18):
        try:
            current = document.StoryRanges(story_type)
        except Exception:
            continue
        while current is not None:
            yield current
            try:
                current = current.NextStoryRange
            except Exception:
                current = None


def _text_ranges(document: Any):
    yield from _story_ranges(document)


def _count_revisions(document: Any) -> int:
    return sum(int(text_range.Revisions.Count) for text_range in _story_ranges(document))


def _accept_all_revisions(document: Any) -> None:
    document.AcceptAllRevisions()
    for text_range in _story_ranges(document):
        while int(text_range.Revisions.Count):
            text_range.Revisions(1).Accept()


def _search_document(document: Any, text: str) -> bool:
    for text_range in _text_ranges(document):
        search_range = text_range.Duplicate
        if _find(search_range, text):
            return True
    return False


def _find(text_range: Any, text: str) -> bool:
    text_range.Find.Execute(
        text, False, False, False, False, False, True, 0, False, "", 0,
        False, False, False, False,
    )
    return bool(text_range.Find.Found)


def _replace_range(text_range: Any, find_text: str, replace_text: str) -> bool:
    return bool(text_range.Find.Execute(
        find_text, False, False, False, False, False, True, 1, False,
        replace_text, 2, False, False, False, False,
    ))
