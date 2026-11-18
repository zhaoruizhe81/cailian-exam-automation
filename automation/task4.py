#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务4「绩效管理」全自动脚本（财连 cp.cailian.net + 绩效管理系统 zledupmspro）

用法:
  python3 task4.py --user 1111111111111 \
      --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run]

流程（对应题目 4.1 / 4.2 / 4.3）:
  4.1.1 系统管理-组织管理: 新建组织 KMBRE有限公司
        系统管理-基础数据: 按表1新建 7 个部门 + 7 个部门负责人
  4.1.2 绩效计划: 新建年度方案（100 分、A~E 五级、四个考核维度、16 个 BSC 指标）
        指标含目标量化值、权重、最高等级 5、最低等级 3、评分规则（量化区间）、考评人
  4.2   发起考核 -> 四位考评人分别录入实际量化值 -> 保存 -> 提交评分
  4.3   绩效评价（自动汇总 91 分、B 级）-> 查看绩效分析
  最后回到任务页点「提交结果」

说明:
  * 绩效系统的下拉框/多选框是 Element UI，脚本统一用 mousedown/click 打开、按 li 文本选择。
  * 评分规则里「量化指标等级」对正向指标行序为 100/80/60，反向指标为 60/80/100，
    脚本按只读的“评分”列数值匹配，避免行序问题。
  * 目标量化值/实际量化值都是“量化值”：百分比类指标 = 实际百分比 * 100。
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
TASK_NAME = "任务4 绩效管理"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------------
# 注入到页面执行的通用 JS
# ----------------------------------------------------------------------------
JS_HELPERS = r"""
const sleep = ms => new Promise(r => setTimeout(r, ms));
const vis = el => el && el.getBoundingClientRect().width > 0 &&
                 getComputedStyle(el).visibility !== 'hidden';
const setVal = (inp, v) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(inp, v);
  inp.dispatchEvent(new Event('input', {bubbles:true}));
  inp.dispatchEvent(new Event('change', {bubbles:true}));
  inp.dispatchEvent(new Event('blur', {bubbles:true}));
};
const openSel = async (sel) => {
  const ti = sel.querySelector('.el-input');
  ti.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
  ti.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
  ti.dispatchEvent(new MouseEvent('click', {bubbles:true}));
  await sleep(800);
  return [...document.querySelectorAll('.el-select-dropdown')].filter(vis);
};
const pickSel = async (sel, text) => {
  const drops = await openSel(sel);
  const drop = drops.find(d => [...d.querySelectorAll('li')].some(l => l.textContent.trim() === text));
  if (!drop) return false;
  [...drop.querySelectorAll('li')].find(l => l.textContent.trim() === text)
    .dispatchEvent(new MouseEvent('click', {bubbles:true}));
  await sleep(500);
  return true;
};
const clickText = (text, opts) => {
  opts = opts || {};
  const els = [...document.querySelectorAll(opts.sel || '*')].filter(e =>
    vis(e) && e.textContent.trim() === text &&
    (!opts.leaf || e.children.length === 0));
  const el = opts.last ? els[els.length-1] : els[0];
  if (!el) return false;
  el.click();
  return true;
};
const pickVisible = async (sel, text) => {
  const drops = await openSel(sel);
  for (const d of drops) {
    const li = [...d.querySelectorAll('li')].find(l => l.textContent.trim() === text);
    if (li) { li.dispatchEvent(new MouseEvent('click', {bubbles:true})); await sleep(700); return true; }
  }
  return false;
};
const findBlock = (name) => [...document.querySelectorAll('.content-info')].find(b => {
  const s = b.querySelector('strong.describe');
  return s && s.textContent.trim() === name;
});
const lastDrawer = () => [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
"""


class PmsBot:
    def __init__(self, page, data, outdir: Path):
        self.page = page
        self.data = data
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)
        self.pms = None

    # ---------------- 基础 ----------------
    def shot(self, name):
        try:
            self.page.screenshot(path=str(self.outdir / f"{name}.png"))
        except Exception:
            pass

    def js(self, code, arg=None, pms=True):
        f = self.pms if pms else self.page.main_frame
        return f.evaluate("async (arg) => { " + JS_HELPERS + code + " }", arg)

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

    # ---------------- 考试页 ----------------
    def goto_task(self):
        # 考试首页也会显示「再次提交」，不能用它判断是否已在任务页，统一走任务导航
        self.page.get_by_text("任务导航", exact=True).first.click()
        self.page.wait_for_timeout(1500)
        item = self.page.locator(".task-nav .el-dialog__body").get_by_text(TASK_NAME, exact=False).first
        item.wait_for(state="visible", timeout=15000)
        item.click()
        self.page.wait_for_timeout(2500)
        if self.wait_text("确定", 3):
            self.page.get_by_text("确定", exact=True).first.click()
            self.page.wait_for_timeout(3500)

    def open_business(self):
        if self.wait_text("关闭分屏", 2):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(1500)
        btn = self.page.locator(".button-box div", has_text="业务处理").first
        btn.click()
        end = time.time() + 90
        while time.time() < end:
            for f in self.page.frames:
                if "zledupmspro" in f.url:
                    self.pms = f
                    self.page.wait_for_timeout(2000)
                    return f
            self.page.wait_for_timeout(1500)
        raise RuntimeError("绩效管理系统 iframe 未加载")

    def click_text_exam(self, text):
        self.page.evaluate(
            """(t)=>{const e=[...document.querySelectorAll('span,div')]
                 .find(x=>x.textContent.trim()===t&&x.offsetParent!==null&&x.children.length===0);
                 if(e)e.click();}""", text)

    def submit_result(self):
        if self.wait_text("关闭分屏", 2):
            self.click_text_exam("关闭分屏")
            self.page.wait_for_timeout(2000)
        log("提交结果 ...")
        btn = "再次提交" if self.wait_text("再次提交", 3) else "提交结果"
        self.page.evaluate(
            """(t)=>{const e=[...document.querySelectorAll('.button-div-width-auto')]
                 .find(x=>x.innerText.trim()===t&&x.offsetParent!==null);
                 if(e)e.click();}""", btn)
        self.page.wait_for_timeout(1500)
        if self.wait_text("确定", 5):
            self.page.get_by_text("确定", exact=True).first.click()
        self.page.wait_for_timeout(3000)
        ok = self.wait_text("再次提交", 20)
        log("提交结果: " + ("成功" if ok else "未确认，请人工检查"))
        self.shot("t4_submitted")
        return ok

    # ---------------- 系统管理 ----------------
    def nav_top(self, name):
        """顶部菜单：绩效计划/绩效实施/绩效评价/绩效分析"""
        ok = self.js(f"""
            const li = [...document.querySelectorAll('li.el-menu-item')]
              .find(e => vis(e) && e.textContent.trim() === {json.dumps(name)});
            if (!li) return false;
            li.dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
            await sleep(2500);
            return true;
        """)
        if not ok:
            raise RuntimeError(f"找不到顶部菜单 {name}")
        log(f"进入 {name}: {self.pms.url.split('#')[-1]}")

    def nav_sys(self, name):
        """系统管理 -> 组织管理/基础数据"""
        self.js("""
            const li = [...document.querySelectorAll('li.el-submenu')]
              .find(e => e.textContent.includes('系统管理'));
            li.querySelector('.el-submenu__title')
              .dispatchEvent(new MouseEvent('mouseenter', {bubbles:true}));
            await sleep(1200);
        """)
        ok = self.js(f"""
            const els = [...document.querySelectorAll('li.el-menu-item')]
              .filter(e => vis(e) && e.textContent.trim() === {json.dumps(name)});
            if (!els.length) return false;
            els[0].dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
            await sleep(3000);
            return true;
        """)
        if not ok:
            raise RuntimeError(f"找不到系统管理子菜单 {name}")

    def click_btn(self, text, scope=None, last=False):
        return self.js(f"""
            const root = {json.dumps(scope)} ? document.querySelector({json.dumps(scope)}) : document;
            const btns = [...root.querySelectorAll('button')]
              .filter(e => vis(e) && e.textContent.trim() === {json.dumps(text)});
            const b = {'btns[btns.length-1]' if last else 'btns[0]'};
            if (!b) return false;
            b.click();
            return true;
        """)

    def fill_visible_drawer(self, values):
        """在当前可见抽屉里按顺序填 text input"""
        return self.js(f"""
            const d = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
            if (!d) return false;
            const ins = [...d.querySelectorAll('input')].filter(i => i.type === 'text' && !i.disabled);
            {json.dumps(values)}.forEach((v, i) => {{ if (ins[i]) setVal(ins[i], v); }});
            await sleep(400);
            return true;
        """)

    # ---------------- 4.1.1 组织 + 基础数据 ----------------
    def create_org(self):
        org = self.data["org"]
        self.nav_sys("组织管理")
        exists = self.js(f"return document.body.innerText.includes({json.dumps(org)});")
        if exists:
            log(f"组织已存在: {org}")
            return
        self.click_btn("新 建")
        self.page.wait_for_timeout(1200)
        self.js(f"""
            const d = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
            setVal(d.querySelector('input:not([disabled])'), {json.dumps(org)});
            await sleep(400);
        """)
        self.click_btn("保存", scope=".el-drawer__body", last=True)
        self.page.wait_for_timeout(2500)
        log(f"组织创建完成: {org}")

    def create_basic_data(self):
        depts = self.data["departments"]
        self.nav_sys("基础数据")

        # ---- 部门 ----
        self.click_tab("部门")
        existing = self.js("""
            return [...document.querySelectorAll('.el-table__body tbody tr')]
              .filter(r => vis(r))
              .map(r => r.innerText.replace(/\\s+/g, ' ').trim());
        """)
        have = " ".join(existing)
        for d in depts:
            if d["name"] in have:
                continue
            self.click_btn("新建")
            self.page.wait_for_timeout(1000)
            self.js(f"""
                const d = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
                setVal(d.querySelector('input:not([disabled])'), {json.dumps(d["name"])});
                await sleep(300);
            """)
            self.click_btn("保存", scope=".el-drawer__body", last=True)
            self.page.wait_for_timeout(2000)
            log(f"部门: {d['name']}")

        # ---- 人员 ----
        self.click_tab("人员")
        existing = self.js("""
            return [...document.querySelectorAll('.el-table__body tbody tr')]
              .filter(r => vis(r))
              .map(r => r.innerText.replace(/\\s+/g, ' ').trim());
        """)
        have = " ".join(existing)
        for p in depts:
            if p["manager"] in have:
                continue
            self.add_person(p["name"], p["manager"], p["phone"])
            log(f"人员: {p['manager']} / {p['name']}")
        # 校验负责人
        self.click_tab("部门")
        rows = self.js("""
            return [...document.querySelectorAll('.el-table__body tbody tr')]
              .filter(r => vis(r))
              .map(r => r.innerText.replace(/\\s+/g, ' ').trim());
        """)
        missing = [d["name"] for d in depts if d["name"] in " ".join(rows) and d["manager"] not in " ".join(rows)]
        if missing:
            log(f"警告: 以下部门负责人可能未设置: {missing}")
        else:
            log("7 个部门负责人校验通过")

    def click_tab(self, name):
        ok = self.js(f"""
            const tab = [...document.querySelectorAll('.el-tabs__item')]
              .find(e => e.textContent.trim() === {json.dumps(name)});
            if (!tab) return false;
            tab.dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
            await sleep(1800);
            return true;
        """)
        if not ok:
            raise RuntimeError(f"找不到页签 {name}")

    def add_person(self, dept, name, phone):
        self.click_btn("新建")
        self.page.wait_for_timeout(1200)
        ok = self.js(f"""
            const d = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
            if (!d) return false;
            const ins = [...d.querySelectorAll('input')];
            const textIns = ins.filter(i => i.type === 'text' && !i.disabled && !i.readOnly);
            setVal(textIns[0], {json.dumps(name)});
            setVal(textIns[1], {json.dumps(phone)});
            await sleep(300);
            const selInp = ins.find(i => i.readOnly);
            const sel = selInp.closest('.el-select');
            const drops = await openSel(sel);
            const drop = drops.find(x => [...x.querySelectorAll('li')]
                .some(l => l.textContent.trim() === {json.dumps(dept)}));
            if (!drop) return false;
            [...drop.querySelectorAll('li')]
              .find(l => l.textContent.trim() === {json.dumps(dept)})
              .dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
            await sleep(500);
            const d2 = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
            const cb = d2.querySelector('.el-checkbox__original');
            if (cb && !cb.checked) cb.click();
            await sleep(300);
            [...d2.querySelectorAll('button')].find(b => b.textContent.includes('保存')).click();
            await sleep(2200);
            return true;
        """)
        if not ok:
            raise RuntimeError(f"人员录入失败: {name}")

    # ---------------- 4.1.2 方案 ----------------
    def create_scheme(self):
        sd = self.data["scheme"]
        self.nav_top("绩效计划")
        if self.js(f"return document.body.innerText.includes({json.dumps(sd['name'])});"):
            log("绩效考核方案已存在，跳过新建")
            return False
        self.click_btn("新建")
        self.page.wait_for_timeout(2000)

        # 基础字段
        ok = self.js(f"""
            const m = document.querySelector('section.el-container');
            const inputs = [...m.querySelectorAll('input')];
            setVal(inputs[0], {json.dumps(sd['name'])});
            await sleep(300);
            const pick = async (inp, text) => {{
              const drops = await openSel(inp.closest('.el-select'));
              const drop = drops.find(d => [...d.querySelectorAll('li')].some(l => l.textContent.trim() === text));
              if (!drop) return false;
              [...drop.querySelectorAll('li')].find(l => l.textContent.trim() === text)
                .dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
              await sleep(800);
              return true;
            }};
            if (!await pick(inputs[1], '组织')) return false;
            if (!await pick(inputs[2], '年度')) return false;
            if (!await pick(inputs[3], {json.dumps(self.data['org'])})) return false;
            // 年度：必须点日期面板里的年份，直接写 input 不会写入 v-model
            null;
            return true;
        """)
        if not ok:
            raise RuntimeError("方案基础字段填写失败")

        # 年份选择器
        self.pms.locator('input[placeholder="选择考核年度"]').first.click(force=True)
        self.page.wait_for_timeout(1000)
        self.js(f"""
            const panel = [...document.querySelectorAll('.el-picker-panel')].filter(vis)[0];
            const cell = [...panel.querySelectorAll('a, td, span')]
              .find(e => e.children.length === 0 && e.textContent.trim() === {json.dumps(sd['year'])});
            cell.dispatchEvent(new MouseEvent('click', {{bubbles:true}}));
            await sleep(900);
        """)
        self.js("""
            const m = document.querySelector('section.el-container');
            const inputs = [...m.querySelectorAll('input')];
            const drops = await openSel(inputs[6].closest('.el-select'));
            const drop = drops.find(d => [...d.querySelectorAll('li')].some(l => l.textContent.trim() === '全年'));
            [...drop.querySelectorAll('li')].find(l => l.textContent.trim() === '全年')
              .dispatchEvent(new MouseEvent('click', {bubbles:true}));
            await sleep(800);
        """)
        log("方案基础信息已填写")

        # 绩效等级
        self.js("""
            const e = [...document.querySelectorAll('*')]
              .filter(x => x.children.length === 0 && x.textContent.trim() === '编辑' && vis(x)).pop();
            e.click();
            await sleep(1500);
        """)
        self.fill_grades(sd["grades"])
        self.page.wait_for_timeout(1500)

        # 下一步
        self.click_btn("下一步")
        self.page.wait_for_timeout(3000)
        if not self.js("return document.body.innerText.includes('绩效目标');"):
            raise RuntimeError("未进入绩效目标页")
        log("进入绩效目标设置")

        # 目标
        for t in sd["targets"]:
            self.add_target(t["name"], t["desc"], t["weight"])
        log(f"绩效目标: {len(sd['targets'])} 个")

        # 指标
        for t in sd["targets"]:
            for ind in t["indicators"]:
                self.add_indicator(t["name"], ind)
                log(f"指标: [{t['name']}] {ind['name']}")

        # 完成
        self.click_btn("完成")
        self.page.wait_for_timeout(3000)
        msg = self.page.inner_text("body")
        if "方案创建完成" in msg:
            log("绩效考核方案创建完成")
        else:
            log("警告: 未看到“方案创建完成”提示，请检查")
        return True

    def fill_grades(self, grades):
        """grades: [[等级, 最低分], ...] 从 A 到 E"""
        ok = self.js(f"""
            const d = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
            if (!d) return false;
            const grades = {json.dumps(grades)};
            for (let i = 0; i < grades.length; i++) {{
              d.querySelector('.add').click();
              await sleep(900);
              const rows = [...d.querySelectorAll('.el-table__body tbody tr')];
              const ins = [...rows[rows.length-1].querySelectorAll('input')];
              setVal(ins[0], grades[i][0]);
              await sleep(150);
              setVal(ins[1], grades[i][1]);
              await sleep(400);
            }}
            const rows = [...d.querySelectorAll('.el-table__body tbody tr')];
            const dump = rows.map(tr => [...tr.querySelectorAll('input')].map(i => i.value).join('|'));
            [...d.querySelectorAll('button')].find(b => b.textContent.includes('保存')).click();
            await sleep(2200);
            return dump;
        """)
        log(f"绩效等级: {ok}")

    def add_target(self, name, desc, weight):
        ok = self.js(f"""
            const spans = [...document.querySelectorAll('span')]
              .filter(e => vis(e) && e.textContent.trim() === '+新增');
            if (spans.length) {{
              spans[0].click();
              await sleep(1600);
              const d = [...document.querySelectorAll('.el-drawer__body')].filter(vis).pop();
              if (d) {{
                const ins = [...d.querySelectorAll('input')].filter(i => i.type === 'text');
                setVal(ins[0], {json.dumps(name)});
                setVal(ins[1], {json.dumps(desc)});
                setVal(ins[2], {json.dumps(str(weight))});
                await sleep(300);
                [...d.querySelectorAll('button')].find(b => b.textContent.includes('保存')).click();
                await sleep(2400);
                return true;
              }}
            }}
            // 首个目标：页面直接是内联表单，没有 +新增
            const form = [...document.querySelectorAll('form')].find(f => f.innerText.includes('目标任务'));
            if (!form) return false;
            const ins = [...form.querySelectorAll('input')].filter(i => !i.disabled);
            setVal(ins[0], {json.dumps(name)});
            setVal(ins[1], {json.dumps(desc)});
            setVal(ins[2], {json.dumps(str(weight))});
            await sleep(400);
            [...form.querySelectorAll('button')].find(b => b.textContent.trim() === '确定').click();
            await sleep(2400);
            return true;
        """)
        if not ok:
            raise RuntimeError(f"新增绩效目标失败: {name}")

    def select_target(self, name):
        ok = self.js(f"""
            const infos = [...document.querySelectorAll('.content-info')]
              .filter(e => vis(e) && e.querySelector('strong') &&
                           e.querySelector('strong').innerText.trim() === {json.dumps(name)});
            if (!infos.length) return false;
            infos[0].click();
            await sleep(900);
            const link = [...infos[0].querySelectorAll('span')]
              .find(e => e.textContent.trim() === '新增指标');
            if (!link) return false;
            link.click();
            await sleep(2000);
            return true;
        """)
        if not ok:
            raise RuntimeError(f"打开指标表单失败: {name}")

    def add_indicator(self, target, ind):
        ok = self.js(f"""
            const block = findBlock({json.dumps(target)});
            if (!block) return 'no-block';
            block.click();
            await sleep(900);
            const link = [...block.querySelectorAll('span')].find(s => s.textContent.trim() === '新增指标');
            if (!link) return 'no-link';
            link.click();
            await sleep(2200);

            let label = [...document.querySelectorAll('label')].find(l => l.innerText.includes('指标名称'));
            if (!label) return 'no-form';
            let form = label.closest('form') || label.closest('.el-form');
            let items = [...form.querySelectorAll('.el-form-item')];
            setVal(items[1].querySelector('input'), {json.dumps(ind['name'])});
            await sleep(200);
            const radios = [...form.querySelectorAll('.el-radio')];
            const cr = t => {{ const r = radios.find(x => x.innerText.trim() === t); if (r && !r.classList.contains('is-checked')) r.querySelector('input').click(); }};
            cr('量化'); await sleep(250);
            cr({json.dumps('反向' if ind.get('reverse') else '正向')}); await sleep(300);
            const objInp = [...items[2].querySelectorAll('input')].filter(i => i.type === 'text').pop();
            setVal(objInp, {json.dumps(str(ind['target']))});
            setVal(items[3].querySelector('input'), {json.dumps(str(ind['weight']))});
            setVal(items[5].querySelector('input'), '3');
            await sleep(500);

            // 最高等级显式选 5
            const lvItem = items.find(x => (x.querySelector('.el-form-item__label') || {{}}).innerText === '最高等级:');
            const lvSel = lvItem.querySelector('.el-select');
            if (!await pickVisible(lvSel, '5')) return 'no-level5';
            await sleep(500);

            // 考评人（可见的多选 select）
            const kp = items.find(x => x.innerText.includes('考评人'));
            const sels = [...kp.querySelectorAll('.el-select')].filter(vis);
            const sel = sels[sels.length - 1];
            if (!await pickVisible(sel, {json.dumps(ind['kpr'])})) return 'no-kpr';
            document.body.click();
            await sleep(500);

            // 评分规则 -> 量化指标等级
            label = [...document.querySelectorAll('label')].find(l => l.innerText.includes('指标名称'));
            form = label.closest('form') || label.closest('.el-form');
            const it = [...form.querySelectorAll('.el-form-item')].find(x => x.innerText.includes('评分规则'));
            const e = [...it.querySelectorAll('*')].find(x => x.children.length === 0 && x.textContent.trim() === '编辑' && vis(x));
            if (!e) return 'no-rule-edit';
            e.click();
            await sleep(1800);
            let dr = lastDrawer();
            if (!dr) return 'no-rule-drawer';
            const rules = {json.dumps(ind['rules'])};
            const fillRules = (d) => {{
              for (const tr of [...d.querySelectorAll('.el-table__body tbody tr')]) {{
                const ins = [...tr.querySelectorAll('input')];
                const rv = rules[ins[0].value];
                if (!rv) continue;
                setVal(ins[1], String(rv[0]));
                setVal(ins[2], String(rv[1]));
              }}
            }};
            fillRules(dr);
            await sleep(400);
            [...dr.querySelectorAll('button')].find(b => b.textContent.trim() === '确定').click();
            await sleep(1600);

            // 表单确定（可能再弹一次等级抽屉）
            for (let k = 0; k < 3; k++) {{
              label = [...document.querySelectorAll('label')].find(l => l.innerText.includes('指标名称'));
              if (!label) {{ await sleep(1500); continue; }}
              form = label.closest('form') || label.closest('.el-form');
              const okb = [...form.querySelectorAll('button')].find(b => b.textContent.trim() === '确定');
              if (okb) okb.click();
              await sleep(2200);
              const dr2 = lastDrawer();
              if (dr2) {{
                fillRules(dr2);
                await sleep(300);
                [...dr2.querySelectorAll('button')].find(b => b.textContent.trim() === '确定').click();
                await sleep(1800);
              }}
              if (![...document.querySelectorAll('label')].some(l => l.innerText.includes('指标名称'))) break;
            }}
            await sleep(1200);
            return 'ok';
        """)
        if ok != "ok":
            raise RuntimeError(f"指标保存失败 {ind['name']}: {ok}")

    # ---------------- 4.2 发起考核 + 评分 ----------------
    def start_assessment(self):
        self.nav_top("绩效计划")
        ok = self.js("""
            const row = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r))[0];
            if (!row) return false;
            const el = [...row.querySelectorAll('*')]
              .find(e => e.children.length === 0 && e.textContent.trim() === '发起考核');
            if (!el) return false;
            el.click();
            await sleep(2000);
            const dlg = [...document.querySelectorAll('.el-drawer__body, .el-dialog')]
              .filter(d => vis(d) && d.innerText.includes('发起考核')).pop();
            if (!dlg) return false;
            const btn = [...dlg.querySelectorAll('button')].find(b => b.textContent.trim() === '发起考核');
            if (!btn) return false;
            btn.click();
            await sleep(2800);
            return true;
        """)
        if not ok:
            raise RuntimeError("发起考核失败")
        log("已发起考核（生成 4 位考评人的评分任务）")

    def score_all(self):
        # 等待考核列表
        end = time.time() + 30
        while time.time() < end:
            rows = self.js("""
                return [...document.querySelectorAll('.el-table__body tbody tr')]
                  .filter(r => vis(r)).map(r => r.innerText.replace(/\\s+/g,' ').trim());
            """)
            if rows and any("考核方案" not in r and "评分" in r for r in rows):
                break
            self.page.wait_for_timeout(1500)

        values = {}
        for t in self.data["scheme"]["targets"]:
            for ind in t["indicators"]:
                values[ind["name"]] = str(ind["actual"])

        evaluators = self.data["evaluators"]
        for ev in evaluators:
            # 若已提交或已评分，跳过
            status = self.js(f"""
                const rows = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r));
                const row = rows.find(r => r.innerText.includes({json.dumps(ev)}));
                if (!row) return 'missing';
                const t = row.innerText;
                if (t.includes('已提交')) return 'done';
                return 'todo';
            """)
            if status == "done":
                log(f"考评人 {ev} 已提交，跳过")
                continue
            opened = self.js(f"""
                const rows = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r));
                const row = rows.find(r => r.innerText.includes({json.dumps(ev)}));
                if (!row) return false;
                const el = [...row.querySelectorAll('*')]
                  .find(e => e.children.length === 0 && e.textContent.trim() === '评分');
                if (!el) return false;
                el.click();
                await sleep(2600);
                return true;
            """)
            if not opened:
                raise RuntimeError(f"无法打开 {ev} 的评分页")
            self.fill_evaluator(values)
            # 保存
            self.click_btn("保存")
            self.page.wait_for_timeout(2600)
            log(f"考评人 {ev} 评分已保存")

        # 提交全部评分
        for _ in range(4):
            ok = self.js("""
                const rows = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r));
                const row = rows.find(r => r.innerText.includes('待提交'));
                if (!row) return false;
                const btn = [...row.querySelectorAll('button')].find(b => b.textContent.trim() === '提交');
                if (!btn) return false;
                btn.click();
                await sleep(2000);
                const box = [...document.querySelectorAll('.el-message-box')].filter(vis).pop();
                if (box) {
                  const ok = [...box.querySelectorAll('button')].find(b => /确定|确认/.test(b.textContent));
                  if (ok) ok.click();
                  await sleep(2200);
                }
                return true;
            """)
            if not ok:
                break
        log("评分提交完成")

    def fill_evaluator(self, values):
        """遍历左侧每个考核维度，按指标名称填实际量化值"""
        n = self.js("""
            return [...document.querySelectorAll('li.indicator')].filter(vis).length;
        """)
        for i in range(n):
            self.js(f"""
                const lis = [...document.querySelectorAll('li.indicator')].filter(vis);
                lis[{i}].click();
                await sleep(1200);
            """)
            self.js(f"""
                const vals = {json.dumps(values)};
                const rows = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r));
                for (const r of rows) {{
                  const name = r.querySelector('td .cell')?.innerText.trim();
                  if (vals[name] === undefined) continue;
                  const inp = r.querySelector('input');
                  if (!inp) continue;
                  setVal(inp, vals[name]);
                  await sleep(500);
                }}
                await sleep(700);
            """)

    # ---------------- 4.3 评价 + 分析 ----------------
    def do_evaluation(self):
        self.nav_top("绩效评价")
        state = self.js("""
            const rows = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r));
            if (!rows.length) return 'empty';
            return rows[0].innerText.includes('已评价') ? 'done' : 'todo';
        """)
        if state == "todo":
            self.js("""
                const row = [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r))[0];
                const el = [...row.querySelectorAll('*')]
                  .find(e => e.children.length === 0 && e.textContent.trim() === '评价');
                el.click();
                await sleep(2800);
            """)
            self.click_btn("保存")
            self.page.wait_for_timeout(2500)
            if "评价成功" in self.page.inner_text("body"):
                log("绩效评价完成")
            else:
                log("警告: 未看到“评价成功”")
        else:
            log("绩效评价已是“已评价”，跳过")

        # 绩效分析
        self.nav_top("绩效分析")
        rows = self.js("""
            return [...document.querySelectorAll('.el-table__body tbody tr')].filter(r => vis(r)).length;
        """)
        log(f"绩效分析已加载，共 {rows} 行指标数据")
        self.shot("t4_analysis")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--exam-url", required=True)
    ap.add_argument("--sx-token", default="")
    ap.add_argument("--data", default=str(HERE / "task4_data.json"))
    ap.add_argument("--profile", default=str(HERE / "profile"))
    ap.add_argument("--stage", default="all",
                    choices=["all", "plan", "score", "eval", "submit"],
                    help="all=全部；plan=只做4.1；score=4.2；eval=4.3；submit=只提交")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="保存但不点提交结果")
    args = ap.parse_args()

    token_file = HERE / "sx_token.txt"
    sx_token = args.sx_token.strip() or (token_file.read_text(encoding="utf-8").strip()
                                         if token_file.exists() else "")
    if not sx_token:
        raise RuntimeError("缺少 sx token（--sx-token 或 sx_token.txt）")
    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    outdir = HERE / "out"

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            args.profile, channel="chrome", headless=args.headless,
            viewport={"width": 1440, "height": 800},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        bot = PmsBot(page, data, outdir)

        log("注入登录态 ...")
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
        body = dict(q); body["dev"] = True
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

        bot.goto_task()
        bot.open_business()

        if args.stage in ("all", "plan"):
            bot.create_org()
            bot.create_basic_data()
            bot.create_scheme()
        if args.stage in ("all", "score"):
            bot.nav_top("绩效计划")
            bot.start_assessment()
            bot.score_all()
        if args.stage in ("all", "eval"):
            bot.do_evaluation()

        if args.dry_run:
            log("dry-run：跳过提交结果")
        else:
            bot.submit_result()

        log("完成。截图目录: " + str(outdir))
        ctx.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAILED] {type(e).__name__}: {e}", file=sys.stderr)
        raise
