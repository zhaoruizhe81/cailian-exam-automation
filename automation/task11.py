#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务1.1「大数据税务预警」全自动脚本（财连 cp.cailian.net / 金税师税务服务）

用法:
  python3 task11.py --user 1111111111111 --password 123456Lin \
      --student-url "https://cp.cailian.net/#/studentDetail?q=..." [--dry-run] [--headless]

流程:
  登录 -> 进入练习 -> 业务处理 -> 数据导入(检查) -> 大数据行业指标(填写D5:D27并保存)
  -> 税务风险预警(读取企业值/行业值, 计算偏离度G5:G27并保存)
  -> 税务风险分析(按偏离度勾选 是否存在/风险事项, 逐项保存)
  -> 返回任务页 -> 提交结果

行业指标值来自 task11_industry.json（同一套试卷通用）。若换试卷请替换该文件。
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
SX_HOME = "https://sx.cailian.net/"

# 从 sx 平台进入竞赛平台时用的上下文参数（业财税融合大数据应用）
def planhome_q(token: str) -> str:
    q = {
        "patternLx": 0, "token": token, "professionId": 38, "provinceId": "10",
        "tag": "ycsrhjncp", "cpName": "业财税融合大数据应用技能竞赛平台",
        "subjectId": 0, "notifyUrl": "https://sx.cailian.net/#/Home",
    }
    return urllib.parse.quote(
        base64.b64encode(json.dumps(q, separators=(",", ":"), ensure_ascii=False).encode()).decode()
    )

# 每个指标下 5 个风险事项对指标的"作用方向": +1 使指标升高, -1 使指标降低, 0 无影响
ITEM_EFFECT = {
    1:  [+1, -1, +1, -1, -1],
    2:  [-1, -1, +1, +1, -1],
    3:  [-1, -1,  0, +1, +1],
    4:  [+1, -1,  0, -1, +1],
    5:  [+1, -1,  0, -1, +1],
    6:  [-1, +1,  0, +1, -1],
    7:  [ 0,  0,  0,  0,  0],
    8:  [+1, +1, +1, +1, -1],
    9:  [-1, -1,  0, +1, +1],
    10: [+1, +1, -1, -1, +1],
    11: [-1, +1, -1, +1, +1],
    12: [+1, -1, +1, +1, -1],
    13: [-1, +1, -1, -1, +1],
    14: [+1, -1, -1, +1, -1],
    15: [+1, -1, +1, -1, +1],
    16: [-1, -1, +1, +1, -1],
    17: [ 0,  0,  0,  0,  0],
    18: [-1,  0, +1, +1, -1],
    19: [+1, -1, +1, +1, -1],
    20: [+1, -1,  0, +1, -1],
    21: [-1, -1, +1, -1, +1],
    22: [-1, +1, -1, -1, +1],
    23: [ 0,  0,  0,  0,  0],
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def pct(text):
    """'12.34%' -> 12.34 ; '' -> None"""
    if text is None:
        return None
    s = str(text).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _num(s):
    s = str(s).replace(",", "").replace("　", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def compute_indicators(sheets):
    """用导入的财务报表计算 23 个企业指标值（返回 {0-based行: 小数}，统一保留 2 位百分数）。"""
    def val(sheet, key, idx=0, last=False):
        hit = None
        for row in sheets.get(sheet, []):
            if len(row) < 5:
                continue
            lab = str(row[2]).replace("　", "").strip()
            if key in lab:
                hit = row
                if not last:
                    break
        return _num(hit[3 + idx]) if hit else None

    pl, bs, cf = "利润表", "资产负债表", "现金流量表"
    r20, r19 = val(pl, "营业收入", 0), val(pl, "营业收入", 1)
    c20, c19 = val(pl, "营业成本", 0), val(pl, "营业成本", 1)
    s20, s19 = val(pl, "销售费用", 0), val(pl, "销售费用", 1)
    m20 = val(pl, "管理费用", 0)
    f20 = val(pl, "财务费用", 0)
    p20, p19 = val(pl, "利润总额", 0), val(pl, "利润总额", 1)
    it20 = val(pl, "所得税费用", 0)
    ni20 = val(pl, "净利润（净亏损", 0)

    inv20, inv19 = val(bs, "存货", 0), val(bs, "存货", 1)
    ar20, ar19 = val(bs, "应收账款", 0), val(bs, "应收账款", 1)
    ta20, ta19 = val(bs, "资产总计", 0), val(bs, "资产总计", 1)
    cl20 = val(bs, "合同负债", 0)
    ap20, ap19 = val(bs, "应付账款", 0), val(bs, "应付账款", 1)
    dta20, dta19 = val(bs, "递延所得税资产", 0), val(bs, "递延所得税资产", 1)
    dtl20, dtl19 = val(bs, "递延所得税负债", 0), val(bs, "递延所得税负债", 1)
    eq20, eq19 = val(bs, "所有者权益合计", 0), val(bs, "所有者权益合计", 1)

    taxes = val(cf, "支付的各项税费", 0)
    ocf = val(cf, "经营活动现金流出小计", 0)

    # 增值税取「2018-2020年度增值税、企业所得税申报数据表」（表内靠后的那一块，单位万元）
    vat20 = val("增值税、所得税申报数据", "增值税", 0, last=True)
    vat19 = val("增值税、所得税申报数据", "增值税", 1, last=True)

    cit = it20 + (dta20 - dta19) - (dtl20 - dtl19)      # 应纳所得税税额
    v20 = vat20 / r20
    v19 = vat19 / r19
    gm20 = (r20 - c20) / r20
    gm19 = (r19 - c19) / r19
    avg_inv = (inv20 + inv19) / 2
    avg_ar = (ar20 + ar19) / 2
    avg_eq = (eq20 + eq19) / 2
    avg_ta = (ta20 + ta19) / 2

    raw = {
        4:  v20,
        5:  (v20 - v19) / v19,
        6:  cit / r20,
        7:  gm20,
        8:  (gm20 - gm19) / gm19,
        9:  cit / p20,
        10: m20 / r20,
        11: s20 / r20,
        12: (r20 - r19) / r19,
        13: (c20 - c19) / c19,
        14: (p20 - p19) / p19,
        15: (inv20 - inv19) / inv19,
        16: c20 / avg_inv,
        17: (ar20 - ar19) / ar19,
        18: r20 / avg_ar,
        19: ni20 / avg_eq,
        20: taxes / p20,
        21: taxes / ocf,
        22: taxes / r20,
        23: cl20 / r20,
        24: (ap20 - ap19) / ap19,
        25: (p20 + f20) / avg_ta,
        26: r20 / avg_ta,
    }
    return {r: round(v * 100.0, 2) / 100.0 for r, v in raw.items()}


class Bot:
    def __init__(self, page, outdir: Path):
        self.page = page
        self.outdir = outdir
        self.outdir.mkdir(parents=True, exist_ok=True)

    # ---------- 基础 ----------
    def shot(self, name):
        try:
            self.page.screenshot(path=str(self.outdir / f"{name}.png"), full_page=False)
        except Exception:
            pass

    def iframe(self, timeout=120):
        end = time.time() + timeout
        while time.time() < end:
            for f in self.page.frames:
                if f.name == "iframeContainer":
                    return f
            self.page.wait_for_timeout(1000)
        raise RuntimeError("找不到 iframeContainer（在线表格未加载）")

    def wait_text(self, text, timeout=60, page=None):
        pg = page or self.page
        end = time.time() + timeout
        while time.time() < end:
            try:
                if pg.get_by_text(text, exact=True).count():
                    return True
            except Exception:
                pass
            self.page.wait_for_timeout(1000)
        return False

    def click_text(self, text, timeout=60):
        """优先点当前页；若弹出新标签页，自动切到最新页再点。"""
        if not self.wait_text(text, timeout):
            self.shot("fail_" + text)
            raise RuntimeError(f"页面上找不到按钮/文本: {text}（可能未登录或页面加载失败）")
        pages_before = len(self.page.context.pages)
        self.page.get_by_text(text, exact=True).first.click()
        time.sleep(1.5)
        pages = self.page.context.pages
        if len(pages) > pages_before:
            self.page = pages[-1]
            log(f"检测到新标签页，已切换: {self.page.url[:60]}")
        return True

    def js(self, frame, expr, arg=None):
        return frame.evaluate(expr, arg) if arg is not None else frame.evaluate(expr)

    def wait_js(self, frame, expr, timeout=120, interval=1.5, arg=None):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            try:
                last = self.js(frame, expr, arg)
                if last:
                    return last
            except Exception:
                pass
            self.page.wait_for_timeout(int(interval * 1000))
        return last

    def click_menu(self, frame, text):
        ok = frame.evaluate(
            """(t)=>{const el=[...document.querySelectorAll('div.item')]
                 .find(e=>e.textContent.trim()===t); if(!el) return false; el.click(); return true;}""",
            text,
        )
        if not ok:
            raise RuntimeError(f"左侧菜单点不到: {text}")
        log(f"已切换页面: {text}")
        self.page.wait_for_timeout(1500)
        return ok

    def find_spread(self, frame, sheet_name):
        """返回 sheet_name 所在的 spread 容器 id（如 spreadCom2/3/6）"""
        js = """(name)=>{
            const ids=[]; const re=/^spreadCom\\d+$/;
            document.querySelectorAll('[id]').forEach(e=>{ if(re.test(e.id)) ids.push(e.id); });
            for(const id of ids){
                try{
                    const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
                    if(!sp || sp.getSheetCount()===0) continue;
                    if(sp.getSheet(0).name()===name) return id;
                }catch(e){}
            }
            return null;
        }"""
        return self.wait_js(frame, js, timeout=180, arg=sheet_name)

    def save_page(self, frame, tag):
        log(f"保存 [{tag}] ...")
        try:
            with self.page.expect_response(
                lambda r: "/api-tax/manageaccount/tax/answer/save/" in r.url, timeout=30000
            ) as info:
                frame.locator("button:has-text('保存')").first.click()
            resp = info.value
            body = resp.text()
            log(f"保存 [{tag}] 返回: {body[:80]}")
            if '"code":0' not in body.replace(" ", ""):
                raise RuntimeError(f"保存失败: {body[:200]}")
        except PWTimeout:
            raise RuntimeError(f"保存 [{tag}] 超时（未捕获到 answer/save 请求）")
        self.page.wait_for_timeout(1500)

    def read_sheets(self, frame, sid):
        """把整本工作簿所有 sheet 的显示文本读成 {sheetName: [[...]]}。"""
        js = """(id)=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const out={};
            for(let i=0;i<sp.getSheetCount();i++){
              const s=sp.getSheet(i), rows=[];
              for(let r=0;r<s.getRowCount();r++){
                const row=[];
                for(let c=0;c<s.getColumnCount();c++) row.push(s.getText(r,c)||"");
                rows.push(row);
              }
              out[s.name()]=rows;
            }
            return out;
        }"""
        return frame.evaluate(js, sid)

    # ---------- 各页面 ----------
    def do_import(self, frame):
        """数据导入：未导入时点「导入」勾选平台预置的 会计报表.xlsx 并确定。"""
        def imported():
            return frame.evaluate("""()=>{
                const ids=[...document.querySelectorAll('[id^=spreadCom]')].map(e=>e.id);
                return ids.some(id=>{
                    try{
                        const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
                        if(!sp) return false;
                        for(let i=0;i<sp.getSheetCount();i++)
                            if(String(sp.getSheet(i).name()).indexOf('资产负债表')>=0) return true;
                    }catch(e){}
                    return false;
                });
            }""")
        if imported():
            log("数据导入: 已导入，跳过")
            return
        log("数据导入: 导入 会计报表.xlsx ...")
        frame.locator("button:has-text('导入')").first.click()
        self.page.wait_for_timeout(2500)
        ok = frame.evaluate("""()=>{
            const d=[...document.querySelectorAll('.el-dialog,.z-dialog')].filter(x=>x.offsetWidth>0)[0];
            if(!d) return 'no-dialog';
            const r=d.querySelector('.el-radio,.el-checkbox,input[type=radio],input[type=checkbox]');
            if(r) (r.querySelector('input')||r).click();
            return 'checked';
        }""")
        self.page.wait_for_timeout(600)
        frame.evaluate("""()=>{
            const d=[...document.querySelectorAll('.el-dialog,.z-dialog')].filter(x=>x.offsetWidth>0)[0];
            if(!d) return 'no-dialog';
            const b=[...d.querySelectorAll('button')].find(x=>x.innerText.replace(/\\s/g,'')==='确定');
            if(b) b.click();
            return 'ok';
        }""")
        self.page.wait_for_timeout(6000)
        log(f"数据导入: {ok} / 导入结果 {'成功' if imported() else '未确认'}")
        self.shot("00_import")

    def do_industry(self, frame, values):
        self.click_menu(frame, "大数据行业指标")
        sid = self.find_spread(frame, "大数据行业均值计算")
        if not sid:
            raise RuntimeError("大数据行业指标页未加载")
        self.industry_sid = sid
        log(f"行业指标工作簿: {sid}")
        # 填 D5:D27（0-based 行 4..26，列 3）
        # 模板已预填（非空/非 0）的行保持原值，不覆盖
        js = """([id, vals])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            const kept=[];
            for(const [r,v] of Object.entries(vals)){
              const cur=String(s.getText(Number(r),3)||'').trim();
              if(cur && cur!=='0' && cur!=='0.00%' && cur!=='-'){ kept.push([Number(r),cur]); continue; }
              s.setValue(Number(r),3,v);
            }
            sp.repaint();
            return {first:s.getText(4,3), last:s.getText(26,3), kept};
        }"""
        check = frame.evaluate(js, [sid, values])
        log(f"已写入行业指标值（保留预填 {check.get('kept')}），首/末显示: {check.get('first')} / {check.get('last')}")
        self.save_page(frame, "大数据行业指标")
        self.shot("01_industry")

    def do_risk(self, frame):
        self.click_menu(frame, "税务风险预警")
        log("等待'税务风险预警'大表加载（首次约 30-60 秒，最多 3 分钟）...")
        sid = self.find_spread(frame, "税务风险预警指标计算及风险评价表")
        if not sid:
            raise RuntimeError("税务风险预警页未加载（超时）")
        log(f"风险预警工作簿: {sid}")
        # 读取系统带出的 企业指标值(E) / 行业指标值(F)
        read_js = """(id)=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0); const out=[];
            for(let r=4;r<27;r++) out.push({row:r+1, name:s.getText(r,2), e:s.getText(r,4), f:s.getText(r,5)});
            return out;
        }"""
        rows = frame.evaluate(read_js, sid)
        # 等待 F 列全部就绪
        end = time.time() + 60
        while time.time() < end and any(not pct(x["f"]) for x in rows):
            self.page.wait_for_timeout(2000)
            rows = frame.evaluate(read_js, sid)

        # 企业指标值(E)若为空，用导入的财务报表自行计算并写入
        if all(pct(x["e"]) is None for x in rows):
            log("E 列企业指标值为空，按导入报表计算 ...")
            sid_ind = getattr(self, "industry_sid", None)
            stmt = HERE / "task11_statements.json"
            if stmt.exists():
                sheets = json.loads(stmt.read_text(encoding="utf-8"))
                log(f"  使用本地报表快照 {stmt.name}")
            elif sid_ind:
                sheets = self.read_sheets(frame, sid_ind)
            else:
                raise RuntimeError("没有报表数据，无法计算企业指标值")
            vals = compute_indicators(sheets)
            for r, v in sorted(vals.items()):
                log(f"  第{r + 1:>2}行 {rows[r - 4]['name']:<12} 企业值 {v * 100:>9.2f}%")
            fill_e = """([id, vals])=>{
                const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
                const s=sp.getSheet(0);
                for(const [r,v] of Object.entries(vals)) s.setValue(Number(r),4,v);
                sp.repaint();
                return [s.getText(4,4), s.getText(26,4)];
            }"""
            self.page.wait_for_timeout(500)
            check_e = frame.evaluate(fill_e, [sid, {str(k): v for k, v in vals.items()}])
            log(f"已写入 23 个企业指标值，首/末显示: {check_e}")
            self.page.wait_for_timeout(800)
            rows = frame.evaluate(read_js, sid)
        missing = [x for x in rows if pct(x["e"]) is None or pct(x["f"]) is None]
        for x in missing:
            log(f"  注意: 第{x['row']}行 {x['name']} 企业值/行业值缺失 -> {x['e']} / {x['f']}")

        devs = {}
        for x in rows:
            e, fv = pct(x["e"]), pct(x["f"])
            if e is None or fv in (None, 0):
                continue
            dev = (e - fv) / fv * 100.0          # 百分点
            devs[str(x["row"])] = round(dev / 100.0, 6)  # 存小数，单元格 0.00% 显示
            log(f"  第{x['row']:>2}行 {x['name']:<12} 企业 {x['e']:>9} 行业 {x['f']:>9} 偏离 {dev:>10.2f}%")
        fill_js = """([id, devs])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            for(const [r,v] of Object.entries(devs)) s.setValue(Number(r)-1,6,v);
            sp.repaint();
            return [s.getText(4,6), s.getText(26,6)];
        }"""
        check = frame.evaluate(fill_js, [sid, devs])
        log(f"已写入偏离度 G5:G27，首/末显示: {check}")
        self.save_page(frame, "税务风险预警")
        self.shot("02_risk")
        return rows

    def do_analysis(self, frame, risk_rows):
        self.click_menu(frame, "税务风险分析")
        sid = self.find_spread(frame, "税务风险预警分析")
        if not sid:
            raise RuntimeError("税务风险分析页未加载")
        log(f"风险分析工作簿: {sid}")
        read_js = """(id)=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0); const out=[];
            for(let i=0;i<23;i++){
                const r=3+5*i;
                out.push({i:i+1, name:s.getText(r,2), e:s.getText(r,3), f:s.getText(r,4), dev:s.getText(r,5)});
            }
            return out;
        }"""
        rows = frame.evaluate(read_js, sid)
        end = time.time() + 60
        while time.time() < end and any(pct(x["f"]) is None for x in rows):
            self.page.wait_for_timeout(2000)
            rows = frame.evaluate(read_js, sid)
        if any(pct(x["f"]) is None for x in rows):
            log("  警告: 仍有指标行业值为空，相关行按'否'处理")

        result = []
        for x in rows:
            e, fv, dv = pct(x["e"]), pct(x["f"]), pct(x["dev"])
            if e is None or fv is None:
                result.append((x["i"], "否", ["否"] * 5, None))
                continue
            abnormal = dv is not None and abs(dv) > 30.0
            if not abnormal:
                result.append((x["i"], "否", ["否"] * 5, dv))
                continue
            direction = 1 if e > fv else (-1 if e < fv else 0)
            picks = []
            for eff in ITEM_EFFECT[x["i"]]:
                picks.append("是" if direction != 0 and eff == direction else "否")
            result.append((x["i"], "是", picks, dv))
            log(f"  指标{x['i']:>2} {x['name']:<12} 偏离 {dv:>10.2f}% -> 是, 事项 {''.join('是' if p=='是' else '·' for p in picks)}")

        fill_js = """([id, data])=>{
            const sp=GC.Spread.Sheets.findControl(document.getElementById(id));
            const s=sp.getSheet(0);
            for(const [i,g,items] of data){
                const base=3+5*(i-1);
                s.setValue(base,6,g);
                items.forEach((v,j)=>s.setValue(base+j,8,v));
            }
            sp.repaint();
            return [s.getValue(3,6), s.getValue(113,6)];
        }"""
        check = frame.evaluate(fill_js, [sid, [[i, g, items] for (i, g, items, _) in result]])
        log(f"已写入 23 个是否判断 + 115 个事项选择，首/末: {check}")
        self.save_page(frame, "税务风险分析")
        self.shot("03_analysis")

    # ---------- 提交 ----------
    def submit(self):
        log("返回任务页 ...")
        if getattr(self, "exam_mode", False):
            # examHome：先关分屏回到任务页；提交按钮取可见的那个
            btn = self.page.get_by_text("关闭分屏", exact=True)
            if btn.count():
                btn.first.click()
                self.page.wait_for_timeout(2500)
            if self.wait_text("再次提交", 3):
                log("任务已是'已提交'状态，无需再次提交")
                return True
            self.page.evaluate(
                """(t)=>{const e=[...document.querySelectorAll('.button-div-width-auto')]
                     .find(x=>x.innerText.trim()===t&&x.offsetParent!==null);
                     if(e)e.click();}""", "提交结果")
            self.page.wait_for_timeout(2000)
            self.page.evaluate(
                """()=>{const bs=[...document.querySelectorAll('button')]
                     .filter(x=>x.offsetWidth>0&&x.innerText.replace(/\\s+/g,'')==='确定');
                     if(bs.length){bs[bs.length-1].click(); return true} return false;}""")
            self.page.wait_for_timeout(3000)
            ok = self.wait_text("再次提交", 15)
            log("提交结果: " + ("成功" if ok else "未确认到状态变化，请人工检查"))
            self.shot("04_submitted")
            return ok
        self.page.locator("text=返回").first.click()
        self.page.wait_for_timeout(3000)
        self.click_text("进入练习", timeout=60)
        self.page.wait_for_timeout(3000)
        if self.wait_text("再次提交", 5):
            log("任务已是'已提交'状态，无需再次提交")
            return True
        self.click_text("提交结果", timeout=30)
        self.page.wait_for_timeout(1000)
        self.click_text("确定", timeout=20)
        self.page.wait_for_timeout(3000)
        ok = self.wait_text("再次提交", 15)
        log("提交结果: " + ("成功" if ok else "未确认到状态变化，请人工检查"))
        self.shot("04_submitted")
        return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--sx-token", default="", help="sx 平台登录后的 Authorization（localStorage），不填则读 sx_token.txt")
    ap.add_argument("--login-sx", action="store_true", help="先打开 sx 登录页，人工登录后自动保存 token")
    ap.add_argument("--student-url", default="", help="cp 的 studentDetail 链接（...#/studentDetail?q=...）")
    ap.add_argument("--exam-url", default="", help="cp 的 examHome 链接（与 --student-url 二选一，推荐）")
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--industry-json", default=str(HERE / "task11_industry.json"))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="只做到保存，不点提交结果")
    args = ap.parse_args()
    token_file = HERE / "sx_token.txt"
    if args.sx_token:
        sx_token = args.sx_token.strip()
    elif token_file.exists():
        sx_token = token_file.read_text(encoding="utf-8").strip()
    else:
        sx_token = ""

    industry = json.loads(Path(args.industry_json).read_text(encoding="utf-8"))["industry_values"]
    outdir = HERE / "out"
    outdir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile,
            channel="chrome",
            headless=args.headless,
            viewport={"width": 1440, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        bot = Bot(page, outdir)
        bot.exam_mode = bool(args.exam_url)
        bot.exam_url = args.exam_url

        # 0) 拿 sx token（该计划只能从 sx 平台的 ssotoken 进入，cp 直接登录的 token 会报"计划已失效"）
        if args.login_sx:
            log("打开 sx 登录页，请在浏览器里完成登录 ...")
            page.goto(SX_HOME, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)
            page.evaluate("localStorage.removeItem('Authorization')")
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        if not sx_token or args.login_sx:
            if not page.url.startswith(SX_HOME):
                page.goto(SX_HOME, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
            end = time.time() + 300
            got = ""
            while time.time() < end:
                got = page.evaluate("localStorage.getItem('Authorization') || ''")
                if got:
                    break
                page.wait_for_timeout(2000)
            if not got:
                bot.shot("fail_sx_login")
                raise RuntimeError("未获取到 sx token（请先在 sx 登录，或检查账号是否可用）")
            sx_token = got
            token_file.write_text(sx_token, encoding="utf-8")
            log(f"已获取 sx token: {sx_token[:8]}...（已保存到 {token_file.name}）")
        else:
            log(f"使用已保存的 sx token: {sx_token[:8]}...")

        if not args.student_url and not args.exam_url:
            raise SystemExit("需要 --exam-url 或 --student-url 之一")

        if args.exam_url:
            # examHome 直接进入：与 task12/task20 等相同的登录态注入（不经过 planHome/studentDetail）
            log("注入登录态并打开考试页 ...")
            page.goto(CP_HOME, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
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
            page.goto(args.exam_url, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            if not bot.wait_text("任务导航", 60):
                bot.shot("fail_exam_home")
                raise RuntimeError("考试页未加载（token 失效或链接不对）")
            # 点第一个任务点（任务1.1）
            page.evaluate(
                "()=>{const t=document.querySelectorAll('.task-item')[0]; if(t) t.click();}")
            page.wait_for_timeout(3000)
            bot.click_text("业务处理", timeout=90)
            bot.page.wait_for_timeout(4000)
        else:
            # 1) 用 sx token 进入竞赛平台（走 planHome 上下文，再进练习详情）
            log("进入竞赛平台 ...")
            page.goto(CP_HOME, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            page.evaluate(
                "([u,t])=>{localStorage.setItem('username',u);localStorage.setItem('jsToken',t);localStorage.setItem('pattern_lx','1');}",
                [args.user, sx_token],
            )
            page.goto("https://cp.cailian.net/#/planHome?q=" + planhome_q(sx_token), wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # 2) 进入练习 -> 任务页 -> 业务处理
            log("打开练习详情 ...")
            page.goto(args.student_url, wait_until="domcontentloaded")
            bot.click_text("进入练习", timeout=60)
            bot.page.wait_for_timeout(3000)
            if bot.page is not page:
                page = bot.page
            bot.click_text("业务处理", timeout=90)
            bot.page.wait_for_timeout(4000)

        frame = bot.iframe()
        log("在线表格已加载")

        # 3) 四个子页面
        bot.do_import(frame)
        bot.do_industry(frame, industry)
        bot.do_risk(frame)
        bot.do_analysis(frame, None)

        # 4) 回到任务页提交
        if args.dry_run:
            log("dry-run：已保存全部答案，跳过提交结果")
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
