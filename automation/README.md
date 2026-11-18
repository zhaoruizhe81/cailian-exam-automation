# 财连考试自动化

| 脚本 | 任务 | 说明 |
|---|---|---|
| `task11.py` | 任务1.1 大数据税务预警 | 在线表格 4 个子页面（数据导入/行业指标/风险预警/风险分析） |
| `task12.py` | 任务1.2 纳税自查 | examHome 分屏表格，10 个业务的是/否 + 5 个税种影响金额 |
| `task20.py` | 【任务2.0】数据提供 | 审计数据上传系统，4 类数据各勾选对应 xls |
| `task211.py` | 【2.1.1】数据校验、科目映射 | 科目类型/12月凭证平衡/核算项目/借贷校验 + 本年利润结转 + 坏账准备/实收资本映射 + 未审报表校验 |
| `task212.py` | 【2.1.2】审计重要性确定 | AE 重要性确定表 11 个单元格 |
| `task22.py` | 【2.2】风险评估 | 风险评估底稿（AF1 等） |
| `task23.py` | 【2.3】销售与收款循环实质性程序 | 应收账款/营业收入及成本/销售费用 3 个底稿 + 2 组审计调整 |
| `task3.py` | 任务3 财务大数据分析 | ExcelOS 在线表格 任务3.1/3.2/3.3 全量回填 |
| `task4.py` | 任务4 绩效管理 | PMS：组织/部门/人员、方案、评分、评价 |
| `submit_paper.py` | 交卷 | 点「交卷」并确认弹窗（不可撤销，`--dry-run` 只检查按钮） |

## 第二套（10 个任务点，`*b.py`）

题型不同（零售业 FSTZG / 动力电池 FSTZK），数据全部外置成 json，脚本逻辑与第一套同类任务一致：

| 脚本 | 任务 | 说明 |
|---|---|---|
| `task11b.py` | 任务1.1 大数据税务预警 | 26 个零售业行业指标 + 偏离度 + 26 组风险事项（`task11b_data.json`） |
| `task12b.py` | 任务1.2 纳税自查 | 10 个业务的是/否 + 税种影响金额（`task12b_answers.json`） |
| `task20b.py` | 【任务2.0】数据提供 | 上传系统账号取环境变量 `CAILIAN_UPLOAD_USER/PASS`（默认 `SJ101261002`），类别：财务数据/库存商品及产成品/管理费用/应付职工薪酬 |
| `task211b.py` | 【2.1.1】数据校验、科目映射 | 与第二套配置一致，薄封装复用 `task211.py` |
| `task212b.py` | 【2.1.2】审计重要性确定 | `task212b_data.json` |
| `task22b.py` | 【2.2】风险评估 | `task22b_af1.json` |
| `task23b.py` | 【2.3】人力资源与工薪业务循环 | F8 应付职工薪酬 + S4 管理费用底稿（`task23b_data.json`） |
| `task24b.py` | 【2.4】生产与存货业务循环 | Z9E 库存商品底稿 + 截止性测试 + 调整（`task24b_data.json`） |
| `task3b.py` | 任务3 财务大数据分析 | `task3b_cells.json` |
| `task4b.py` | 任务4 绩效管理 | PMS（`task4b_data.json`，FSTZK 有限公司） |

```bash
python3 task4b.py --user 1111111111111 --exam-url "https://cp.cailian.net/#/examHome?q=..." \
  --stage all|plan|score|eval|submit [--dry-run]
```

第二套额外踩过的坑：

- **1.2 答案行序**：每个业务块是「是否存在问题 → 1 行『存在涉税疑点的税种』表头 → 5 个税种」，
  金额要写在**税种标签所在行**（块首 +3..+7）。第一次跑错位了一行（CIT 落到地方教育附加行），
  已用 `task12b_answers.json` 的显式坐标修正并重新提交；业务7 的第 5 行是个人所得税。
- **1.1 行数**：第二套 26 个指标（行 4..29），第一套 23 个（4..26）；分析页 `base=3+5*(i-1)`。
- **附件下载**：任务材料附件没有下载图标，点文件名会跳 `#/error` 且 oauth token 接口 500。
  正确做法是读 examHome 的 Vue 状态 `testQuestionData.paper...attachList`（`window.__q4` 里的
  `questionId/attachName/url1`），直接 curl 下载 `https://zledu-oss-sx.cailian.net/chaosOffice/...xlsx`。
- **PMS 指标表单**：「最高等级」下拉只有 `10`/`5` 两档，填完权重后可能被带成 10，最后要显式选 `5`；
  「评分规则-编辑」在量化指标下会打开「量化指标等级」抽屉（评分/量化最小值/量化最大值），
  填完抽屉「确定」后再点表单「确定」，若又弹抽屉则再填一遍（`task4b.py` 里最多重试 3 次）。
- **考评人**是 el-select 多选，同一 form-item 内有隐藏/可见两个 select，要取可见的那个。
- **绩效实施**列表操作按钮文本是「提交」，不是「提交评分」。
- 量化值口径与第一套一致：百分比指标直接用百分点数值（100.05），绝对数指标用原值（716.81）。

## 第三套（planId 5000508920，`*c.py`）

第三套是「会计核算 + 个税优化」题型，共 11 个任务点（14 题拆成 11 个 task-item）。
`cailian3.py` 是公共库（登录注入、任务导航、财天下侧边栏、票据采集、新增凭证、在线表格），
其余脚本只放数据：

| 脚本 | 任务点 | 说明 |
|---|---|---|
| `task1c.py` | 1. 全面预算管理 | 经营目标 3 表 + 预算编制 6 簿 21 表 + 预算执行 2 表 + 预算分析 1 表；数据在 `task1c_data.json`（0-based 坐标） |
| `task2c.py` | 2. 投资决策 | 答题板 `spreadComEXCEL_TYDTB`：两方案现金流/NPV/EAA |
| `task3c.py` | 3. 融资决策 | 同答题板：销售百分比法 + 每股收益无差别点 |
| `task4c.py` | 4. 支付借款利息 | 采集 3 张 → 银行回单调整至其他票据 → 凭证 借 660302 财务费用-利息支出、贷 100201（普票不抵进项） |
| `task5c.py` | 5. 缴纳税费 | 6 行凭证（增值税/城建税/教育费附加/地方教育附加/个税 + 100201 贷），2022-12-08 |
| `task6c.py` | 6. 缴纳住房公积金 | 借 221104 / 贷 100201 各 10,800.00，2022-12-08 |
| `task7c.py` | 7. 发放工资 | 借 221101 / 贷 100201 各 115,810.00，2022-12-15 |
| `task8c.py` | 8. 银行结息 | 借 100201 / 贷 660301 各 3,750.15，2022-12-21 |
| `task9c.py` | 9. 税务优化① | 赡养老人每月扣除 1000 元（B） |
| `task10c.py` | 10. 税务优化② | 黄某 100% 扣除住房租金（D） |
| `task11c.py` | 11. 税务优化③ | 在线表格「税务优化方案计算表」回填 + 保存 |

任务 1–3 最初是人工交互完成，后来已固化为 `task1c.py`/`task2c.py`/`task3c.py`。

预算管理页（`onlineexcel` 的 `预算管理` 菜单）踩坑：

- **「保存」只提交当前活动 sheet 的改动**：`setValue` 后直接点保存，非活动 sheet 的单元格
  不会进 `buryPointList`。正解是把整本工作簿要写的单元格写进页面组件的
  `$parent.GLKJ_user_answer_list`（`{sheetName,rowNo,colNo,value}`，`value` 用
  `getCurExalVal(sheetName,row,col,'text')` 取显示文本），再调 `$parent.answerSave()`；
  它和点保存是同一条链路（POST `/api-manageaccount-cost/manageaccount/cost/answer/save/<GLKJ_*>`），
  一次能提交整本工作簿。`handleSaveClick()` 只是 `answerSave()` 的壳。
- 保存把**显示文本**存回服务端（“2,682”“2.38%”“-”），所以单元格格式决定落库值；
  数据坐标要与模板完全一致。
- `t1_*.json` 快照坐标是 **0-based**（与 SpreadJS `setValue` 一致），不要再减 1。
- 多工作簿页面按 `el-tabs__item` 切（采购预算…财务预算 / 预算分解·预算控制）；
  切页后先写再保存。答题板（任务 2/3）用 `__vue__.$data.spread`，`GC.Spread.Sheets.findControl`
  在这个构建里返回 null。

```bash
python3 task1c.py --user 1111111111111 --exam-url "..." [--stage all|ysmb,bianzhi,zhixing,fenxi]
```

```bash
python3 task5c.py --user 1111111111111 --exam-url "https://cp.cailian.net/#/examHome?q=..." \
  [--dry-run] [--headless]
```

第三套踩坑记录：

- **财天下有两个同名 `invoice-collect` frame**：`ctxdslxpro/#/invoice/invoice-collect`（只有菜单外壳）
  和 `ptxinvoicedslxpro/#/invoice-collect/...`（真正内容）。取 frame 必须用 `ptxinvoicedslxpro`。
- 票据采集「教学票据采集」弹窗的确定按钮文字是 `确 定`（中间有空格）；上传结果提示也要再点一次确认。
- 银行回单改方向（收款↔付款）后要切到对应子页签（收款/付款）才能看到；表格里必须点
  `.el-checkbox` 才能勾选，`div.click()` 不会选中。
- **银行回单在票据制单里制单会失败**：审核报「缺少必要参数」，ctx 查询提示「业务类型不存在」。
  本套推荐不依赖票据制单，直接用「新增凭证」手工填制（金额/科目与票据一致），
  附件用凭证右上角「附件管理器」的 `.z-upload__input` 上传票据截图即可。
- **调整类型弹窗**：`原发票类型` 是只读的，只需在第二个 select（红色星号「调整发票类型至」）
  选目标类型再点确定；选之前不要点「收款/付款」子页签，否则图片列表会重置为占位图、弹窗拿不到单据。
  调整成功后分类计数应变成 银行回单（0）/其他票据（+1）。
- **新增凭证的会计科目是 autocomplete**：先点单元格，再在输入框里 `type` 科目代码过滤，
  点可见的 `.el-select-dropdown__item`（`li` 的 `offsetWidth>0`），不要取 `.el-select-dropdown` 容器，
  科目多时容器宽度为 0、目标项也不在首屏。
- **凭证表格上常驻 `.mack` 遮罩**（选科目后出现，永远不消失），会拦截 td 点击；
  `cailian3.clear_mack()` 直接把它 `display:none` 后再点。
- 任务 4 的利息发票是**增值税普票**，进项税不得抵扣：借 660302 财务费用-利息支出 116,400，
  贷 100201 银行存款 116,400（不是 640101，也不是 3 行拆税）。
- Element UI 日期选择器输入框是 readonly，必须点开面板点具体日期格。
- 任务 9/10 是 cp 页面内嵌单选，选中即自动记为 `task-success`；任务 11 才需要打开在线表格。
- 任务 11 的口径：租金 1500/月×12=18,000 优于房贷利息 12,000，二者不可同时享受；
  赡养老人自父亲 2021-04 满 60 当月算 9 个月；全部扣除给边际税率 10% 的黄某税负最低。

所有脚本共用 `sx_token.txt` 和 `profile/`，参数一致：

```bash
python3 taskXX.py --user 1111111111111 \
  --exam-url "https://cp.cailian.net/#/examHome?q=..." \
  [--dry-run] [--headless]
```

## 复用第一套脚本的试卷（业绩评价-第1套（2-4班），planId 5000508928）

同一套题的另一个考生/计划：9 个任务点与第一套完全相同，直接跑 `task11/12/20/211/212/22/23/3/4.py`，
数据文件通用。`playerId` / `teamId` 随账号与计划变化，脚本从 `q=` 解析，无需手填。

- **`task11.py` 新增 `--exam-url` 模式**：先从 examHome 进任务再点「业务处理」；不再需要
  `--student-url`。导入「会计报表.xlsx」后平台只预填 D（行业值）/ F，**E（企业指标值）是空的**，
  脚本用 `compute_indicators()` 从三表 + 申报数据算出来再写入，最后算 G 偏离率。
  报表读取在风险预警页会卡住，已改为用本地快照 `task11_statements.json`（财务数据 8547713.94 /
  11835870.58 / 308845.57，与 2.1.1 实跑一致）。
- 风险预警页**不能直接从菜单跳**：必须先打开「大数据行业指标」，否则 `findControl` 拿到空工作簿；
  `spreadCom\d+` 的 id 在页面间会复用，必须按 sheet 名找。
- 第一套构建**没有 `__vue__`**，SpreadJS 一律用 `GC.Spread.Sheets.findControl(document.getElementById(id))`。
- `task20.py` / `task212.py` / `task4.py` 的 `goto_task()` 不能用「再次提交」判断是否已在任务页
  （考试首页也会显示它，导致误判跳过导航）：改为比对 `.title-text` 或统一走任务导航。
- `task4.py` 曾丢失两处历史修改：`js()` 包装器必须是 `async (arg) => {...}`（内部有 `await`），
  年度选择器在 PMS iframe 里，要用 `self.pms.locator(...)` 而不是 `self.page.locator(...)`。
- `task4.py` 的「首个绩效目标」在本套是**内联表单**（没有 `+新增` 抽屉），`add_target` 需要
  先试抽屉、再退回到 `form` 里的输入框 + 「确定」（已按 `task4b.py` 的写法补齐）。
- `task4.py` 的 `add_indicator` 已换成 `task4b.py` 的稳健版（`findBlock`/`pickVisible`、
  评分规则抽屉可能重复弹出最多重试 3 次），旧的按 `items[4]/items[7]` 序号取控件在本套会错位。
- 方案存在性检查会被**残留草稿**误判：平台在向导「下一步」时就把方案落库（状态「新建」），
  中途失败会留下空方案，重跑时 `create_scheme` 直接跳过 → 发起考核后评分页打不开。
  失败后先在绩效计划列表点「删除」清掉，再重跑。
- `all` 阶段必须 **plan → score → eval 全串起来**（曾用 `if/elif` 漏掉 4.3）。
  `do_evaluation` 里的「评价成功」判断用的是 `self.page`（CP 外壳），会误报未成功；
  实际结果以绩效评价列表为准（本套：绩效总分 91.00 / 等级 B / 已评价）。
- `task4.py` 可重复执行：组织/部门/人员/方案已存在时会自动跳过。

---

## 任务1.2 纳税自查（task12.py）

```bash
python3 task12.py --user 1111111111111 \
  --exam-url "https://cp.cailian.net/#/examHome?q=..." \
  --dry-run        # 只保存，不提交
```

答题数据在 `task12_answers.json`：`cells` 键为 `"行,列"`（0-based，与平台 `answer/save` 的 rowNo/colNo 一致），值 `是`/`否` 或金额。

### 和 1.1 不同的关键点（踩过的坑）

1. **examHome 白屏**：只注入 localStorage 不够，必须同时满足
   - `sessionStorage.queryData` = 从 sx 进入的上下文 JSON（含 `professionId:38`、`token`）
   - `localStorage.playerInfo` / `resultVal`（同一份 JSON）/ `matchPlanId`
   - `sessionStorage.stationId` / `planIdShow`
   脚本从 `--exam-url` 的 `q=` 解出 planId/orgId/userId，再调
   `/api-match-practise/practise/js/playerDetail` 拿 playerInfo，全部自动完成。
2. **答案在分屏里**：不是独立练习页，要点任务页底部「业务处理」，找 url 含 `onlineexcel` 的 frame。
3. **保存接口**：`/api-tax/manageaccount/tax/answer/save/SWFWYDSJYY_SWZC_V2`（纳税自查的 manuscriptIdentify）。
4. **已提交后再点**：按钮会变成「再次提交」，脚本自动识别。
5. 「任务1.2」需先完成 1.1（前置题），批量时先跑 `task11.py`。

### 答案结构

每个业务 10 行一块：第 1 行 `是否存在问题`（B 列），第 2 行表头，第 3–7 行是增值税/城建税/教育费附加/地方教育费附加/企业所得税，金额在 C 列（0-based 第 2 列）。

**注意**：第 3 块（业务3）比前两块多 1 行偏移（标签在第 22 行、判断在第 23 行），后面第 4 块又回到 10 行间隔。所以 `task12_answers.json` 用**显式 `行,列` 坐标**而不是按公式推算，换行/改模板时直接改坐标即可。

---

# 任务1.1 大数据税务预警（task11.py）

用 Playwright 驱动 SpreadJS 工作簿，自动完成并提交**任务1.1**的 4 个子任务：

1. 数据导入（检查报表数据，系统判定）
2. 大数据行业指标：写入 `大数据行业均值计算!D5:D27`（23 个指标）
3. 税务风险预警：读取系统带出的企业指标值/行业指标值，计算并写入偏离度 `G5:G27`
4. 税务风险分析：按偏离度勾选「是否存在」和 115 个风险事项（是/否）
5. 返回任务页点「提交结果」

## 环境

- Python 3 + `playwright`（本机已安装）
- 本机 Chrome

## 关键前提：sx 平台的 token

该练习计划**只能从 sx 平台（实训教学综合服务平台）进入**。直接用 cp.cailian.net 的账号密码登录得到的 token 会报「当前计划已经失效」，这是踩过的坑。

所以脚本用 `sx_token.txt` 里的 token 注入 cp：

```bash
# 首次 / token 过期时：打开 sx 登录页，人工登录（有验证码）
python3 task11.py --user 1111111111111 --login-sx \
  --student-url "https://cp.cailian.net/#/studentDetail?q=..." --dry-run
# 登录成功后脚本会自动把 Authorization 存到 sx_token.txt
```

已有 token 时直接跑：

```bash
python3 task11.py \
  --user 1111111111111 \
  --student-url "https://cp.cailian.net/#/studentDetail?q=eyJpZCI6NTAwMDUwODkyOCw..." \
  --dry-run        # 只填到保存，不提交
```

去掉 `--dry-run` 即包含「提交结果」。

## 参数

| 参数 | 说明 |
|---|---|
| `--user` | 账号（写入 cp localStorage） |
| `--sx-token` | sx 的 Authorization；不填则读 `sx_token.txt` |
| `--login-sx` | 打开 sx 登录页，人工登录后自动保存 token |
| `--student-url` | cp 的 `studentDetail` 链接（带 `q=`，每人不同） |
| `--industry-json` | 行业指标值文件，默认 `task11_industry.json` |
| `--dry-run` | 只保存，不点「提交结果」 |
| `--headless` | 无头模式（不推荐，个别弹窗/加载更慢） |

## 行业指标值

`task11_industry.json` 是同一套试卷通用的 23 个行业指标值（医药制造业 265 家 A股公司 2020/2019 报表聚合：分子合计÷分母合计）。

- 前 2 项（增值税税负率、变动率）**没有直接数据源**，用的是「应交税费÷营业收入」代理口径：2.07%、+25.55%。如果答案库用别的口径（支付的各项税费 / 税金及附加），替换 json 中对应两行即可（键 `4`、`5`，0-based 行号）。
- 换试卷/换年份需要重新生成该 json。

## 风险事项勾选规则

脚本按题目说明自动判断：

- `|偏离度| ≤ 30%` → 该指标「否」，其下 5 个事项全「否」；
- 异常 → 「是」，且仅勾选**会把指标往同一方向推**的事项（`ITEM_EFFECT` 表，+1 升高 / -1 降低 / 0 不影响），方向取 `企业值 - 行业值` 的符号。

## 产物

- 截图：`out/01_industry.png`、`02_risk.png`、`03_analysis.png`、`04_submitted.png`
- 日志：控制台输出每个指标的 企业值 / 行业值 / 偏离度
- 失败截图：`out/fail_*.png`

## 已知限制

- sx 登录有验证码，首次需人工登录一次；token 失效后重复该步骤。
- `studentDetail` 链接每人不同，批量时需要每人一条（从 sx 课程/练习入口获取）。
- 平台会话约半小时失效，建议拿到 token 后尽快跑。

---

# 任务2.0 数据提供（task20.py）

```bash
python3 task20.py --user 1111111111111 --exam-url "https://cp.cailian.net/#/examHome?q=..."
```

- 业务处理打开 `answer.cailian.net`「审计数据上传系统」，账号固定 `SJ101261001 / 123456`。
- 四个类别逐一「上传」，对话框会列出平台预置的 4 个 xls，只勾选自己那一类：
  `财务数据.xls` / `应收账款.xls` / `营业收入及成本.xls` / `销售费用.xls`；最后点「保存」。
- 已显示「上传成功」的类别自动跳过，可重复执行。

# 任务2.1.1 数据校验、科目映射（task211.py）

```bash
python3 task211.py --user 1111111111111 --exam-url "https://cp.cailian.net/#/examHome?q=..." [--dry-run]
```

进入项目 XM0044 后依次完成：

1. **科目信息校验**：设置科目类型 `1=资产 2=负债 4=权益 5=成本 6=损益` → 点「应用数据」→
   弹框「是否确认应用新的科目类型?」点「确定」→ 提示「保存成功」。
2. **凭证平衡校验**：月份下拉选「十二月」。注意要同时 `$emit('input')` 和 `$emit('change')`，
   否则只是显示值变了、不会重新查询；12 月 61 张凭证差额应全为 0（每页 20 条）。
3. **核算项目与科目校验**、**借贷发生额校验**：点页签内的运行按钮，检查差额列全为 0
   （按 `td` 列下标判断，不要按文本拆分，科目编号会被当成数字）。
4. **标记结转**：设置结转科目勾选 `4103 本年利润` → 确定 → 保存（提示「操作成功」）。
5. **科目映射**（已存在则跳过）：
   - `1231 坏账准备` → 报表项目「应收账款」
   - `4001 实收资本` → 报表项目「民营资本」
   做法：点左侧 `li.subject-li` 选中报表项目 → 勾选右侧科目行 → 点「对应」→ 提示「已建立对应关系」。
6. **报表 → 未审报表**：截止月份 `202212`，调用组件 `verify()` 校验，要求
   `finalVerifyLogic` 与 `openingVerifyLogic` 均为 `OK！`，再 `save()`。

**坑**：
- 数据校验页的「运行按钮」在已校验过的页签可能不再出现，脚本按「已加载」处理。
- 应用数据后会弹 `.el-message-box` 确认框，不点确定会一直卡住。
- 科目映射页数据在 Vue 组件 `subject-map-table` 的 `submaplist` 里，用它判断是否已映射最可靠。

# 任务2.1.2 审计重要性确定（task212.py）

```bash
python3 task212.py --user 1111111111111 --exam-url "..." [--dry-run]
```

数据在 `task212_data.json`（税前利润 308845.57、比率 8%/75%/5%、理由）。写入 AE 重要性确定表：
`D7/B14/C14/D14/D18/C28/F28/D30/C41/F41/D42`；`G14/G28/G41` 是模板公式，不要覆盖。

# 任务2.2 风险评估（task22.py）

```bash
python3 task22.py --user 1111111111111 --exam-url "..." [--dry-run]
```

按 `task22_af1.json` 回填 AF1 风险评估底稿并保存提交。

# 任务2.3 销售与收款循环实质性程序（task23.py）

```bash
python3 task23.py --user 1111111111111 --exam-url "..." [--dry-run] [--skip-adjust]
```

- 回填三个底稿（数据在 `task23_data.json`，只回填非公式单元格）：
  - `Z5 应收账款`（导引表/明细表/函证/坏账准备测试/凭证抽查等）
  - `S1 营业收入及成本`（导引表/明细表/销售分析/截止性/合同履行等）
  - `S3 销售费用`（导引表/明细表/截止性/凭证抽查等）
- 底稿保存按钮在直接 `setValue` 时不会激活（组件靠编辑事件判断 dirty），脚本直接调用
  组件 `handleSaveClick()`；保存前用 `changeCellsObjListByData()` 登记改动，并等状态栏「就绪」。
- 审计调整（调整 → 账项期末调整）自动确保两组分录：
  - `0001` 借 `6702 信用减值损失` 223043.07 / 贷 `123101 坏账准备-应收账款` 223043.07
  - `0002` 借 `122101 其他应收款-内部往来` 636.00 / 贷 `660104 销售费用-业务招待费` 636.00
  - 分录行通过点击「科目名称」单元格打开科目树选择，选择科目后报表项目会自动带出。
- 已存在且科目匹配时自动跳过，可重复执行。

# 任务3 财务大数据分析（task3.py）

```bash
python3 task3.py --user 1111111111111 --exam-url "..." [--dry-run]
```

- 数据在 `task3_cells.json`（0 基行列）：`任务3.1` 317 格、`任务3.2` 349 格、`任务3.3` 154 格，
  只回填非公式单元格；「（参考选项）」不回填。
- 定位 iframe 中 `id=spreadComEXCEL_TYDTB` 的 SpreadJS 工作簿，逐格 `setValue`。
- 保存按钮同样因「未检测到数据变化」而 disabled，脚本直接调用答题板组件
  （`khdsj-comp`）的 `answerSave()`，它会上传整份 sjs 并由服务端做差异比对。

# 任务4 绩效管理（task4.py）

```bash
python3 task4.py --user 1111111111111 --exam-url "..." \
  --stage all|plan|score|eval|submit [--dry-run]
```

数据在 `task4_data.json`（组织、7 个部门/负责人、4 位考评人、4 个维度 16 个指标及实际值/评分规则）。

- `plan`：建组织 → 部门/人员 → 绩效考核方案（等级 A–E、绩效目标/指标/权重/评分规则/考评人）。
- `score`：启动考核并对 4 位考评人逐项打分（按指标名称写入实际值），提交全部待提交绩效。
- `eval`：绩效评价 → 保存；绩效分析核对。
- 坑：Element UI 下拉要 `mousedown+mouseup+click`；年度选择必须点 `.el-picker-panel` 里的年份格子；
  最低等级选 3 才不会强制要求 5 行评分规则；反向指标规则行顺序是 60/80/100，要按分值列写。
