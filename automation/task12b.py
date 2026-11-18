#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务1.2「纳税自查」全自动脚本 · 第二套（财连 cp.cailian.net / 金税师税务服务）

用法:
  python3 task12.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run] [--headless]

流程:
  注入 sx token -> 打开 examHome -> 任务导航选「任务1.2 纳税自查」
  -> 点「业务处理」打开在线表格分屏 -> 按 task12_answers.json 写入 10 个任务的
     是/否 与 5 个税种影响金额 -> 保存 -> 关闭分屏 -> 提交结果

答案数据在 task12b_answers.json（cells 键为 "行,列"，0-based，与平台保存接口一致）。
注意：第二个业务块之后每个税种行是「是否存在问题 +1 行表头 + 5 个税种」，
因此金额行相对块首是 +3..+7（业务3/4 等标题行有偏移，数据文件里是显式坐标）。
同一套试卷通用；换试卷请替换该文件。
"""
import argparse
import base64
import json
import sys
import time
import urllib.parse
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

HERE = Path(__file__).resolve().parent
CP_HOME = "https://cp.cailian.net/"
TASK_NAME = "任务1.2 纳税自查"


def planhome_q(token: str) -> str:
    """从 sx 平台进入竞赛平台的上下文参数（与 task11 相同）"""
    q = {
        "patternLx": 0, "token": token, "professionId": 38, "provinceId": "10",
        "tag": "ycsrhjncp", "cpName": "业财税融合大数据应用技能竞赛平台",
        "subjectId": 0, "notifyUrl": "https://sx.cailian.net/#/Home",
    }
    return urllib.parse.quote(
        base64.b64encode(json.dumps(q, separators=(",", ":"), ensure_ascii=False).encode()).decode()
    )


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

    # ---------- 页面基础 ----------
    def wait_text(self, text, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.page.get_by_text(text, exact=True).count():
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(1000)
        return False

    def click_text(self, text, timeout=60):
        if not self.wait_text(text, timeout):
            self.shot("fail_" + text)
            raise RuntimeError(f"找不到文本: {text}")
        self.page.get_by_text(text, exact=True).first.click()
        self.page.wait_for_timeout(1500)

    def goto_task(self, name):
        """用右上角「任务导航」弹窗切到指定任务"""
        if TASK_NAME_SHORT in self.page.inner_text("body"):
            title = self.page.locator(".title-text").first.inner_text() if self.page.locator(".title-text").count() else ""
            if name in title:
                log(f"当前已在「{name}」")
                return
        self.click_text("任务导航", timeout=30)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(name, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        title = self.page.locator(".title-text").first.inner_text()
        if name not in title:
            raise RuntimeError(f"切换任务失败，当前标题: {title}")
        log(f"已切换到「{title}」")

    def open_business(self):
        """点底部「业务处理」打开在线表格分屏，返回 frame"""
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if "onlineexcel" in f.url:
                    try:
                        if f.evaluate("typeof GC !== 'undefined'"):
                            return f
                    except Exception:
                        pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("在线表格（onlineexcel）未加载")

    def find_spread(self, frame, timeout=120):
        js = """()=>{
            const ids=[]; const re=/^spreadCom\\d+$/;
            document.querySelectorAll('[id]').forEach(e=>{ if(re.test(e.id)) ids.push(e.id); });
            for(const id of ids){
                try{
                    const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
                    if(!sp || sp.getSheetCount()===0) continue;
                    if(sp.getSheet(0).name().toLowerCase()==='sheet1') return id;
                }catch(e){}
            }
            return null;
        }"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                sid = frame.evaluate(js)
                if sid:
                    return sid
            except Exception:
                pass
            self.page.wait_for_timeout(1500)
        raise RuntimeError("找不到答题工作簿（Sheet1）")

    # ---------- 作答 ----------
    def fill(self, frame, sid, cells):
        js = """([id, cells])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            for(const [rc,v] of Object.entries(cells)){
                const [r,c]=rc.split(',').map(Number);
                s.setValue(r,c, (/^-?\\d+(\\.\\d+)?$/.test(v) && v!=='是' && v!=='否') ? Number(v) : v);
            }
            sp.repaint();
            const out={};
            for(const rc of Object.keys(cells)){
                const [r,c]=rc.split(',').map(Number);
                out[rc]=String(s.getText(r,c)).trim();
            }
            return out;
        }"""
        got = frame.evaluate(js, [sid, cells])
        bad = [(k, cells[k], got.get(k)) for k in cells if got.get(k) != str(cells[k]).strip()]
        if bad:
            log(f"  警告: {len(bad)} 个单元格显示值与预期不同（多为格式补零）: {bad[:5]}")
        else:
            log(f"已写入 {len(cells)} 个答题单元格，显示值全部一致")
        return got

    def save(self, frame):
        log("保存 ...")
        try:
            with self.page.expect_response(
                lambda r: "/answer/save/" in r.url, timeout=60000
            ) as info:
                frame.locator("text=保存").first.click()
            body = info.value.text()
            log(f"保存返回: {body[:80]}")
            if '"code":0' not in body.replace(" ", ""):
                raise RuntimeError(f"保存失败: {body[:200]}")
        except PWTimeout:
            raise RuntimeError("保存超时（未捕获到 answer/save 请求）")
        self.page.wait_for_timeout(1500)

    def close_split(self):
        try:
            self.page.get_by_text("关闭分屏", exact=False).first.click()
            self.page.wait_for_timeout(2000)
        except Exception:
            pass

    def submit(self):
        log("提交结果 ...")
        btn = "再次提交" if self.wait_text("再次提交", 5) else "提交结果"
        log(f"当前按钮: {btn}")
        self.click_text(btn, timeout=30)
        if self.wait_text("确定", 6):
            self.click_text("确定", timeout=20)
        self.page.wait_for_timeout(3000)
        ok = self.wait_text("再次提交", 20)
        log("提交结果: " + ("成功（已变为再次提交）" if ok else "未确认到状态变化，请人工检查"))
        self.shot("12_submitted")
        return ok


TASK_NAME_SHORT = "纳税自查"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="cp 账号（写入 localStorage）")
    ap.add_argument("--exam-url", required=True, help="examHome 链接（...#/examHome?q=...）")
    ap.add_argument("--sx-token", default="", help="sx Authorization；不填读 sx_token.txt")
    ap.add_argument("--answers", default=str(HERE / "task12b_answers.json"))
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只保存，不提交结果")
    args = ap.parse_args()

    token_file = HERE / "sx_token.txt"
    sx_token = args.sx_token.strip() or (token_file.read_text(encoding="utf-8").strip()
                                         if token_file.exists() else "")
    if not sx_token:
        raise RuntimeError("缺少 sx token（--sx-token 或 sx_token.txt）")
    cells = json.loads(Path(args.answers).read_text(encoding="utf-8"))["cells"]
    outdir = HERE / "out"

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=args.headless,
            viewport={"width": 1440, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        bot = Bot(page, outdir)

        log("注入登录态 ...")
        page.goto(CP_HOME, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        # examHome 的 q 里含 planId/orgId/userId；页面还依赖 sessionStorage.queryData(professionId)
        # 和 localStorage.playerInfo，否则白屏
        q = json.loads(base64.b64decode(urllib.parse.unquote(args.exam_url.split("q=", 1)[1])))
        pq = {
            "token": sx_token, "patternLx": 0, "professionId": 38, "provinceId": "10",
            "tag": "ycsrhjncp", "cpName": "业财税融合大数据应用技能竞赛平台",
            "subjectId": 0, "notifyUrl": "https://sx.cailian.net/#/Home",
        }
        page.evaluate(
            "([u,t,pq])=>{localStorage.setItem('username',u);localStorage.setItem('jsToken',t);"
            "localStorage.setItem('pattern_lx','1');sessionStorage.setItem('token',t);"
            "sessionStorage.setItem('queryData',JSON.stringify(pq));}",
            [args.user, sx_token, pq],
        )

        log("获取考生练考信息 ...")
        body = dict(q)
        body["dev"] = True
        resp = page.evaluate(
            """async ([tok,body,user])=>{
                const r=await fetch('https://zledusxapi.cailian.net/api-match-practise/practise/js/playerDetail',
                  {method:'POST',headers:{'content-type':'application/json','authorization':'bearer '+tok,
                   'x-user-header':user,'prodtag':'ycsrhjncp'},body:JSON.stringify(body)});
                return await r.text();
            }""",
            [sx_token, body, args.user],
        )
        pdata = json.loads(resp).get("data") or {}
        if not pdata.get("playerId"):
            raise RuntimeError(f"playerDetail 获取失败: {resp[:200]}")
        player_json = json.dumps(pdata, ensure_ascii=False)
        station = str((pdata.get("stationIdList") or [""])[0])
        page.evaluate(
            "([p,pid,sid])=>{localStorage.setItem('playerInfo',p);localStorage.setItem('resultVal',p);"
            "localStorage.setItem('matchPlanId',pid);sessionStorage.setItem('stationId',sid);"
            "sessionStorage.setItem('planIdShow',pid);}",
            [player_json, str(pdata.get("planId")), station],
        )

        log("打开考试页 ...")
        page.goto(args.exam_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        if not bot.wait_text("任务导航", 60):
            bot.shot("fail_exam_home")
            raise RuntimeError("考试页未加载（token 失效或链接不对）")

        bot.goto_task(TASK_NAME)
        frame = bot.open_business()
        log("在线表格已加载")
        sid = bot.find_spread(frame)
        log(f"答题工作簿: {sid}")

        bot.fill(frame, sid, cells)
        bot.save(frame)
        bot.close_split()

        if args.dry_run:
            log("dry-run：已保存，跳过提交结果")
        else:
            bot.submit()

        log("完成。截图目录: " + str(outdir))
        ctx.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
