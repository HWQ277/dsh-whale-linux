"""Command-line entry point for the whale widget."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from . import __version__
from .config import Config


def assets_dir() -> Path:
    """Locate the bundled image assets (works from a checkout or /usr/share)."""
    env = os.environ.get("DSH_WHALE_ASSETS")
    if env and (Path(env) / "DSniang1.png").is_file():
        return Path(env)
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "assets",  # source checkout
        Path("/usr/share/dsh-whale/assets"),
        Path.home() / ".local/share/dsh-whale/assets",
        Path(__file__).resolve().parent / "assets",
    ]
    for path in candidates:
        if (path / "DSniang1.png").is_file():
            return path
    tried = "\n".join(f"  - {p}" for p in candidates)
    raise SystemExit(
        "找不到挂件素材（assets/DSniang1.png）。已尝试：\n"
        f"{tried}\n"
        "请设置环境变量 DSH_WHALE_ASSETS 指向素材目录，或重新运行 ./install.sh。"
    )


def _acquire_single_instance():
    """Refuse a second widget instance.

    Launching twice (easy to do from a desktop icon) stacked identical widgets
    on the same spot, which looked like a rendering bug and made clicks land on
    the wrong window. Returns the open lock file, or None when another instance
    already holds it.
    """
    import fcntl

    config = Config()
    lock_path = config.path.parent / "widget.lock"
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "w")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.write(str(os.getpid()))
        handle.flush()
        return handle
    except (OSError, BlockingIOError):
        return None


def cmd_run(args: argparse.Namespace) -> int:
    from .widget import WhaleWidget

    config = Config()

    lock = _acquire_single_instance()
    if lock is None:
        print("小鲸鱼已经在运行了（只允许一个实例）。", file=sys.stderr)
        print("如需重启：先退出旧的，或运行  pkill -f dshwhale", file=sys.stderr)
        return 0
    if args.scale is not None:
        config.set("scale", args.scale)
        config.save()
    if args.no_mask:
        config.set("maskEnabled", False)
        config.save()

    if not config.api_key:
        # First run: guide the user to the settings window.
        print("未检测到 DeepSeek API Key。", file=sys.stderr)
        print("请运行: dsh-whale settings   （或右键鲸鱼 → 设置）", file=sys.stderr)

    widget = WhaleWidget(config, assets_dir())

    def handle_signal(_signum, _frame):
        try:
            widget.root.after(0, widget.quit)
        except Exception:
            pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handle_signal)
        except (ValueError, OSError):
            pass

    widget.run()
    return 0


def cmd_settings(_args: argparse.Namespace) -> int:
    """Open the settings window on its own (no whale)."""
    import tkinter as tk

    from .settings import StandaloneSettings

    config = Config()
    StandaloneSettings(config, assets_dir())
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    from .balance import BalanceError, fetch_balance
    from .ledger import Ledger

    config = Config()
    if not config.api_key:
        print("API Key: 未配置")
        print(f"配置文件: {config.path}")
        return 2
    source = "环境变量 DEEPSEEK_API_KEY" if config.key_from_env else "配置文件"
    print(f"API Key: 已配置（来源: {source}）")
    result = fetch_balance(config.api_key)
    if isinstance(result, BalanceError):
        print(f"余额获取失败 [{result.code}]: {result.message}")
        return 1
    print(f"余额: {result.fmt()}  ({result.currency})")
    if result.topped_up is not None:
        print(f"  充值: {result.topped_up:.2f}   赠金: {result.granted or 0:.2f}")
    ledger = Ledger(config.usage)
    print(f"今日已用（观测）: {ledger.today_usage:.2f}")
    print(f"统计日期（北京时间）: {ledger.usage.get('date')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dsh-whale",
        description="DeepSeek 余额小鲸鱼 — Arch Linux 桌面挂件",
    )
    parser.add_argument("--version", action="version", version=f"dsh-whale {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="启动小鲸鱼挂件（默认）")
    run.add_argument("--scale", type=float, default=None, help="挂件缩放 0.6–2.5")
    run.add_argument("--no-mask", action="store_true", help="禁用 X11 异形窗口（实体卡片回退）")
    run.set_defaults(func=cmd_run)

    settings = sub.add_parser("settings", help="打开设置窗口")
    settings.set_defaults(func=cmd_settings)

    status = sub.add_parser("status", help="在终端查看余额与今日已用")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if not getattr(args, "func", None):
        args = parser.parse_args(["run"])
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
