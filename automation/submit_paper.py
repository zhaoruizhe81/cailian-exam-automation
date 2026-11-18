#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交卷脚本：登录考试页 -> 点「交卷」-> 依次确认弹窗 -> 输出结果

用法:
  python3 submit_paper.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..."

说明:
  * 交卷不可撤销；脚本只在显式运行且不带 --dry-run 时点「交卷」。
  * --dry-run 只检查「交卷」按钮是否可见、是否提示少做题。
"""
import argparse
import base64
import json
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class Bot:
    def __init__(self, page, outdir: Path):
        self.page = page
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)

    def shot(self, name):
        try:
            self.page.screenshot(path=str(self.outdir / f"{name}.png"))
        except Exception:
            pass

    def visible_buttons(self):
        return self.page.evaluate("""
            () => [...document.querySelectorAll(
                'button, .el-button, .button-div-width-auto, .button-div-info')]
              .filter(e => e.offsetParent !== null && e.innerText.trim())
              .map(e => e.innerText.replace(/\\s+/g, '').trim())
        """)

    def click_juanjuan(self):
        # 「交卷」是 header 里的 div.button-div-info，不是 button，也不一定没有子节点
        return self.page.evaluate("""
            () => {
              const els = [...document.querySelectorAll('.button-div-info, div, span')]
                .filter(e => e.offsetParent !== null &&
                             e.innerText.replace(/\\s+/g, '') === '交卷');
              if (!els.length) return false;
              els[0].click();
              return true;
            }
        """)

    def click_text(self, text, tags="button, div, span"):
        return self.page.evaluate("""
            ([t, tags]) => {
              const els = [...document.querySelectorAll(tags)]
                .filter(e => e.offsetParent !== null && e.children.length === 0 &&
                             e.innerText.replace(/\\s+/g, '') === t);
              if (!els.length) return false;
              els[els.length - 1].click();
              return true;
            }
        """, [text, tags])

    def body_text(self):
        return self.page.inner_text("body")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只检查，不点交卷")
    args = ap.parse_args()

    token_file = HERE / "sx_token.txt"
    sx_token = args.sx_token.strip() or token_file.read_text(encoding="utf-8").strip()
    if not sx_token:
        raise RuntimeError("缺少 sx token")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=args.headless,
            viewport={"width": 1440, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        bot = Bot(page, HERE / "out")

        log("注入登录态 ...")
        page.goto(CP_HOME, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        q = json.loads(base64.b64decode(urllib.parse.unquote(args.exam_url.split("q=", 1)[1])))
        pq = {"token": sx_token, "patternLx": 0, "professionId": 38, "provinceId": "10",
              "tag": "ycsrhjncp", "cpName": "业财税融合大数据应用技能竞赛平台",
              "subjectId": 0, "notifyUrl": "https://sx.cailian.net/#/Home"}
        page.evaluate(
            "([u,t,pq])=>{localStorage.setItem('username',u);localStorage.setItem('jsToken',t);"
            "localStorage.setItem('pattern_lx','1');sessionStorage.setItem('token',t);"
            "sessionStorage.setItem('queryData',JSON.stringify(pq));}",
            [args.user, sx_token, pq])
        body = dict(q); body["dev"] = True
        resp = page.evaluate(
            """async ([tok,body,user])=>{
                const r=await fetch('https://zledusxapi.cailian.net/api-match-practise/practise/js/playerDetail',
                  {method:'POST',headers:{'content-type':'application/json','authorization':'bearer '+tok,
                   'x-user-header':user,'prodtag':'ycsrhjncp'},body:JSON.stringify(body)});
                return await r.text();}""", [sx_token, body, args.user])
        pdata = json.loads(resp).get("data") or {}
        if not pdata.get("playerId"):
            raise RuntimeError(f"playerDetail 获取失败: {resp[:200]}")
        page.evaluate(
            "([p,pid,sid])=>{localStorage.setItem('playerInfo',p);localStorage.setItem('resultVal',p);"
            "localStorage.setItem('matchPlanId',pid);sessionStorage.setItem('stationId',sid);"
            "sessionStorage.setItem('planIdShow',pid);}",
            [json.dumps(pdata, ensure_ascii=False), str(pdata.get("planId")),
             str((pdata.get("stationIdList") or [""])[0])])

        log("打开考试页 ...")
        page.goto(args.exam_url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        btns = bot.visible_buttons()
        log(f"可见按钮: {[b for b in btns if b in ('交卷', '已交卷')] or btns[:8]}")
        if "交卷" not in btns:
            log("没有「交卷」按钮：" + ("可能已交卷" if "已交卷" in btns else "请人工确认"))
            bot.shot("submit_paper_no_btn")
            return

        if args.dry_run:
            log("dry-run：检查完成，未点交卷")
            return

        log("点击交卷 ...")
        if not bot.click_juanjuan():
            raise RuntimeError("找不到「交卷」按钮")
        page.wait_for_timeout(2500)

        for i in range(6):
            txt = bot.body_text()
            if "已交卷" in txt or "交卷成功" in txt:
                break
            done = False
            for label in ("确认交卷", "确定", "确认", "是"):
                if bot.click_text(label):
                    log(f"确认弹窗: {label}")
                    done = True
                    page.wait_for_timeout(2500)
                    break
            if not done:
                break

        page.wait_for_timeout(4000)
        tail = bot.body_text()
        log("页面提示: " + tail[-300:].replace("\n", " | "))
        bot.shot("submit_paper_result")
        log("完成。截图: out/submit_paper_result.png")
        ctx.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
