from __future__ import annotations
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Protocol


# 子进程默认超时(秒)。防止 DB 不可达时 dump 永久挂起、记录卡 running。
DEFAULT_TIMEOUT = 3600


class BackupCancelled(Exception):
    """取消信号在子进程执行期间触发(由 run_subprocess 抛出)。"""


def _kill(proc: subprocess.Popen) -> None:
    """先 terminate 再 kill,尽力收尾子进程。"""
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass


def run_subprocess(
    argv: list[str],
    *,
    env: dict | None = None,
    stdin=None,
    stdout=None,
    timeout: int | None = DEFAULT_TIMEOUT,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """统一执行 dump/restore 子进程:

    - 以 Popen + 轮询运行,使 *执行期间* 的取消能即时 terminate 子进程;
    - 强制 timeout,避免 DB 不可达时永久挂起;
    - 捕获 stderr 并附入失败信息(便于运维定位"密码错误/库不存在"等真实原因);
    - 取消 → 抛 BackupCancelled;超时/非零退出 → 抛 RuntimeError。"""
    proc = subprocess.Popen(argv, env=env, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE)
    start = time.monotonic()
    while True:
        try:
            proc.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            pass
        if is_cancelled is not None and is_cancelled():
            _kill(proc)
            raise BackupCancelled()
        if timeout and time.monotonic() - start > timeout:
            _kill(proc)
            raise RuntimeError(f"命令超时({timeout}s): {argv[0]}")
    if proc.returncode != 0:
        err = b""
        if proc.stderr is not None:
            try:
                err = proc.stderr.read() or b""
            except Exception:
                pass
        detail = err.decode("utf-8", "replace").strip()
        raise RuntimeError(f"命令失败(退出码 {proc.returncode}): {argv[0]}\n{detail}")


def run_subprocess_capture(
    argv: list[str],
    *,
    env: dict | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
    is_cancelled: Callable[[], bool] | None = None,
) -> str:
    """同 run_subprocess,但捕获并返回 stdout 的解码文本(用于 list_databases 等需读取输出的场景)。
    取消 → BackupCancelled;超时/非零退出 → RuntimeError(含 stderr)。"""
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    start = time.monotonic()
    while True:
        try:
            proc.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            pass
        if is_cancelled is not None and is_cancelled():
            _kill(proc)
            raise BackupCancelled()
        if timeout and time.monotonic() - start > timeout:
            _kill(proc)
            raise RuntimeError(f"命令超时({timeout}s): {argv[0]}")
    if proc.returncode != 0:
        err = b""
        if proc.stderr is not None:
            try:
                err = proc.stderr.read() or b""
            except Exception:
                pass
        detail = err.decode("utf-8", "replace").strip()
        raise RuntimeError(f"命令失败(退出码 {proc.returncode}): {argv[0]}\n{detail}")
    out = b""
    if proc.stdout is not None:
        try:
            out = proc.stdout.read() or b""
        except Exception:
            pass
    return out.decode("utf-8", "replace")


@dataclass
class ConnectionInfo:
    """已解密的连接信息(传给适配器执行 dump)。"""
    type: str
    host: str | None = None
    port: int | None = None
    db_name: str | None = None
    username: str | None = None
    password: str | None = None  # 明文(已用 Fernet 解出)


class BackupAdapter(Protocol):
    type: str

    def dump(self, info: ConnectionInfo, dest_path: str, *,
             is_cancelled: Callable[[], bool] | None = None) -> None:
        """执行 dump,把原始(未压缩)字节写入 dest_path。失败抛异常。"""
        ...

    def restore(self, info: ConnectionInfo, src_path: str, *,
                is_cancelled: Callable[[], bool] | None = None) -> None:
        """从 src_path(未压缩的原始 dump)执行还原。失败抛异常。"""
        ...


_REGISTRY: dict[str, BackupAdapter] = {}


def register_adapter(adapter: BackupAdapter) -> None:
    _REGISTRY[adapter.type] = adapter


def get_adapter(db_type: str) -> BackupAdapter:
    try:
        return _REGISTRY[db_type]
    except KeyError:
        raise ValueError(f"不支持的数据库类型: {db_type}")
