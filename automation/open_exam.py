#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打开考试页（有头浏览器，注入 sx 登录态后留在考试首页，供人工检查）

用法:
  python3 open_exam.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--minutes 120]

浏览器会一直保持打开，直到脚本被结束（Ctrl+C / kill）或到时。
"""
import argparse
import base64
import json
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--minutes", type=int, default=120)
    args = ap.parse_args()

    token = args.sx_token.strip() or (HERE / "sx_token.txt").read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("缺少 sx token")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=False,
            viewport={"width": 1440, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        log("注入登录态 ...")
        page.goto(CP_HOME, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        q = json.loads(base64.b64decode(urllib.parse.unquote(args.exam_url.split("q=", 1)[1])))
        pq = {"token": token, "patternLx": 0, "professionId": 38, "provinceId": "10",
              "tag": "ycsrhjncp", "cpName": "业财税融合大数据应用技能竞赛平台",
              "subjectId": 0, "notifyUrl": "https://sx.cailian.net/#/Home"}
        page.evaluate(
            "([u,t,pq])=>{localStorage.setItem('username',u);localStorage.setItem('jsToken',t);"
            "localStorage.setItem('pattern_lx','1');sessionStorage.setItem('token',t);"
            "sessionStorage.setItem('queryData',JSON.stringify(pq));}",
            [args.user, token, pq])
        body = dict(q); body["dev"] = True
        resp = page.evaluate(
            """async ([tok,body,user])=>{
                const r=await fetch('https://zledusxapi.cailian.net/api-match-practise/practise/js/playerDetail',
                  {method:'POST',headers:{'content-type':'application/json','authorization':'bearer '+tok,
                   'x-user-header':user,'prodtag':'ycsrhjncp'},body:JSON.stringify(body)});
                return await r.text();}""", [token, body, args.user])
        pd = json.loads(resp).get("data") or {}
        if not pd.get("playerId"):
            raise RuntimeError(f"playerDetail 获取失败: {resp[:200]}")
        page.evaluate(
            "([p,pid,sid])=>{localStorage.setItem('playerInfo',p);localStorage.setItem('resultVal',p);"
            "localStorage.setItem('matchPlanId',pid);sessionStorage.setItem('stationId',sid);"
            "sessionStorage.setItem('planIdShow',pid);}",
            [json.dumps(pd, ensure_ascii=False), str(pd.get("planId")),
             str((pd.get("stationIdList") or [""])[0])])

        log("打开考试页 ...")
        page.goto(args.exam_url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        btns = page.evaluate("""
            () => [...document.querySelectorAll('button, .el-button, .button-div-width-auto')]
              .filter(e => e.offsetParent !== null && e.innerText.trim())
              .map(e => e.innerText.replace(/\\s+/g, '').trim())
        """)
        log(f"当前可见按钮: {btns}")
        log(f"浏览器已打开，保持 {args.minutes} 分钟（关闭浏览器或 Ctrl+C 结束）")
        try:
            page.wait_for_timeout(args.minutes * 60 * 1000)
        except Exception:
            pass
        ctx.close()


if __name__ == "__main__":
    main()
