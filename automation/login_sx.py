#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打开有头浏览器停在 sx 登录页，人工登录后自动把 Authorization 存进 sx_token.txt。

练习计划只能从 sx 平台进入，换账号时先跑这个：

  python3 login_sx.py            # 打开 sx，登录后保存 token，浏览器保持打开
  python3 login_sx.py --exit-after-token   # 保存后直接关浏览器

旧 token 会备份到 sx_token.prev.txt（本机凭证，不要外传）。
"""
import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SX_HOME = "https://sx.cailian.net/"
TOKEN_FILE = HERE / "sx_token.txt"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--timeout", type=int, default=1800, help="等待登录的秒数")
    ap.add_argument("--exit-after-token", action="store_true")
    args = ap.parse_args()

    p = sync_playwright().start()
    ctx = p.chromium.launch_persistent_context(
        args.profile, channel="chrome", headless=False,
        viewport={"width": 1440, "height": 820},
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(SX_HOME, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.evaluate("()=>{localStorage.removeItem('Authorization');}")
    page.reload(wait_until="domcontentloaded")
    log("已打开 sx 登录页（已清除旧登录态），请在浏览器里登录 ...")

    end = time.time() + args.timeout
    got = ""
    while time.time() < end:
        try:
            got = page.evaluate("()=>localStorage.getItem('Authorization')||''")
        except Exception:
            pass
        if got:
            break
        page.wait_for_timeout(2000)

    if not got:
        log("超时未获取到 sx token，浏览器保持打开，可继续登录")
        return

    if TOKEN_FILE.exists():
        old = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if old and old != got:
            (HERE / "sx_token.prev.txt").write_text(old + "\n", encoding="utf-8")
            log(f"旧 token 已备份到 sx_token.prev.txt ({old[:8]}...)")
    TOKEN_FILE.write_text(got, encoding="utf-8")
    log(f"已获取 sx token: {got[:8]}...（已保存到 {TOKEN_FILE.name}）")
    try:
        log(f"当前页面: {page.url}")
    except Exception:
        pass

    if args.exit_after_token:
        ctx.close()
        p.stop()
        return

    log("浏览器保持打开，登录态已就绪；Ctrl-C 结束本进程")
    try:
        while True:
            page.wait_for_timeout(5000)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            ctx.close()
            p.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
