---
name: signal-monitor
description: 通用量化信号监控模板。一个 skill 管理 N 个独立监控 job（每个 job 有自己的资产池/公式/冷静期/推送/定时），用一句自然语言就能：新增/修改/暂停/恢复/删除监控、改资产池或来源、改公式、立即跑一遍、推测试到企微群、查看监控列表、看上次结果、重置冷静期、诊断"今天为什么没提醒"。覆盖 A 股/港股/美股/指数/ETF/期货。当用户说到：信号监控、定时监控、监控任务、加一个监控、改下监控时间、暂停监控、恢复监控、删掉监控、监控列表、为什么没提醒、推个测试到群里、立即跑一遍、重置冷静期、改成 X σ 下轨、加 MACD 监控、抄底监控、突破监控、signal monitor、scheduled scan，都触发本 skill。
metadata:
  requires: "quant-buddy-skill"
---

# signal-monitor — 通用量化信号监控模板

把"扫资产 → 算信号 → 冷静期去重 → 出报告 → 推企微 → 定时跑"这套骨架抽象成一个**多 job** 的模板 skill。每个 job 是 `jobs/<id>/job.json` 里一段声明式配置，由统一的 [scripts/cli.py](scripts/cli.py) 驱动。

**核心数据源**：quant-buddy-skill（统一 A/港/美股/指数/ETF/期货）
**调度**：Windows schtasks（每 job 独立任务名 `SignalMonitor_<id>`）
**通知**：内置企微 webhook（每 job 可独立 webhook + @ 列表）

---

## Step 0 — 依赖挂载（硬前置）

执行任何命令前确认 quant-buddy-skill 已安装；CLI 启动会自动按下列顺序找它，找不到立即停并提示：
```
{SKILL_ROOT}/../quant-buddy-skill/
~/.claude/skills/quant-buddy-skill/
~/.openclaw/skills/quant-buddy-skill/
~/.codex/skills/quant-buddy-skill/
{cwd}/.{claude|openclaw|codex|github}/skills/quant-buddy-skill/
```

> **路径约定**：`{SKILL_ROOT}` = 当前 SKILL.md 所在目录。

---

## 决策树（LLM 用这个判断走哪条路）

```
用户一句话
   │
   ├─ 看/查询类 → cli list / show / history / diagnose
   ├─ 立即跑   → cli run <id> [--dry-run]
   ├─ 推送测试 → cli test-push <id>
   ├─ 改字段   → cli set <id> <jsonpath> <value>   （写入前自动备份）
   ├─ 加资产   → cli set <id> asset_source.assets += {...}  或改 Excel
   ├─ 停用资产 → cli disable-asset <id> <ticker>
   ├─ 加 job   → cli add <id> --from preset:<name|file.json>
   ├─ 删 job   → cli delete <id>
   ├─ 暂停/恢复 → cli pause <id> / resume <id>
   ├─ 改公式后 → cli validate <id>   （强烈建议跑一次确认无语法错）
   └─ 改时间   → cli set schedule.cron OR schedule.time → cli apply-schedule <id>
```

所有命令的统一调用入口：
```bash
python {SKILL_ROOT}/scripts/cli.py <command> [...args]
```
**所有 stdout 都是 JSON**（便于 LLM 解析）；人类可读消息走 stderr。

---

## CLI 速查（覆盖 15 类自然语言场景）

| 用户说                             | 命令                                                                                                                                       |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| "现在有哪些监控"                       | `cli.py list`                                                                                                                            |
| "看下 core-asset-dip 上次跑出什么"      | `cli.py show core-asset-dip`                                                                                                             |
| "立即跑一遍 core-asset-dip"          | `cli.py run core-asset-dip --dry-run`（不写 state、不推送）                                                                                      |
| "正式跑一次"                         | `cli.py run core-asset-dip`                                                                                                              |
| "推个测试到群里"                       | `cli.py test-push core-asset-dip`                                                                                                        |
| "把腾讯港股加进去"                      | `cli.py set core-asset-dip asset_source.assets+ '{"ticker":"00700.HK","company":"腾讯控股"}'`                                                |
| "改用 D:/foo.xlsx"                | `cli.py set core-asset-dip asset_source.path D:/foo.xlsx` 然后 `cli.py run core-asset-dip --dry-run` 触发快照同步                                |
| "暂停茅台不监控"                       | `cli.py disable-asset core-asset-dip 600519.SH`                                                                                          |
| "恢复茅台"                          | `cli.py enable-asset core-asset-dip 600519.SH`                                                                                           |
| "下轨改成 1.5σ"                     | `cli.py set core-asset-dip 'signal.formulas[name=下轨].expression' '"MA20" - 1.5 * 标准差("资产池收盘价", 20)'` 然后 `cli.py validate core-asset-dip` |
| "加一个 MACD 金叉的 job 叫 macd-watch" | `cli.py add macd-watch --from preset:macd_cross` 然后 `cli.py set macd-watch asset_source.assets ...`                                      |
| "改成早 7:30 跑"                    | `cli.py set core-asset-dip schedule.time 07:30` 然后 `cli.py apply-schedule core-asset-dip`                                                |
| "改成每个工作日 9 点"                   | `cli.py set core-asset-dip schedule.cron "0 9 * * 1-5"` 然后 `cli.py apply-schedule core-asset-dip`                                        |
| "暂停定时"                          | `cli.py pause core-asset-dip`                                                                                                            |
| "恢复定时"                          | `cli.py resume core-asset-dip`                                                                                                           |
| "彻底删掉"                          | `cli.py delete core-asset-dip --yes`                                                                                                     |
| "改成无论是否触发都推"                    | `cli.py set core-asset-dip notification.push_when always`                                                                                |
| "重置茅台冷静期"                       | `cli.py reset-cooldown core-asset-dip --ticker 600519.SH`                                                                                |
| "重置全部冷静期"                       | `cli.py reset-cooldown core-asset-dip --all`                                                                                             |
| "今天怎么没提醒？"                      | `cli.py diagnose core-asset-dip`                                                                                                         |
| "刚才那次改撤销下"                      | `cli.py history core-asset-dip` 然后 `cli.py rollback core-asset-dip`                                                                      |

---

## job.json 结构（LLM 写公式时直接编辑这一份）

```json
{
  "id": "core-asset-dip",
  "name": "核心资产抄底跟踪",
  "enabled": true,
  "asset_source": {
    "type": "excel",
    "path": "assets.xlsx",
    "disabled_tickers": []
  },
  "signal": {
    "category": {"direction": "buy", "label": "抄底", "description": "MA20 - 2σ 跌破"},
    "formulas": [
      {"name": "资产池收盘价", "expression": "资产池构造({ASSETS}) * \"全市场每日收盘价（分钟刷新）\""},
      {"name": "MA20",         "expression": "平均(\"资产池收盘价\", 20)"},
      {"name": "下轨",         "expression": "\"MA20\" - 2 * 标准差(\"资产池收盘价\", 20)"},
      {"name": "信号",         "expression": "\"资产池收盘价\" < \"下轨\""}
    ],
    "trigger_formula": "信号",
    "display_fields": ["资产池收盘价", "MA20", "下轨"],
    "lookback_days": 60
  },
  "cooldown_days": 7,
  "analysis_hook": {
    "enabled": true,
    "framework_doc": "references/抄底判断框架.md",
    "websearch_template": {
      "A": "{company} 近期下跌 原因",
      "HK": "{company} 下跌",
      "US": "{ticker} selloff reasons"
    },
    "output_sections": ["下跌归因", "框架分类", "抄底结论"]
  },
  "notification": {
    "wecom": {
      "enabled": true,
      "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...",
      "mentioned_list": [],
      "mentioned_mobile_list": []
    },
    "push_when": "triggered_only"
  },
  "schedule": {
    "enabled": true,
    "time": "08:30",
    "cron": null,
    "task_name": "SignalMonitor_core-asset-dip"
  },
  "report": {
    "template_path": "../../templates/default_report.md",
    "output_dir": "output/reports"
  }
}
```

**关键字段**：
- `asset_source.type`：`excel | csv | inline`
  - `excel/csv` → `path` 指向文件（相对 job 目录或绝对路径）
  - `inline` → `assets: [{ticker, company}]`
  - `disabled_tickers[]` → 始终被排除，不删数据，方便恢复
- `signal.category` ← **每个 job 必填**，用于推送/报告标注信号类型
  - `direction`: `buy`（🟢 买入信号）/ `sell`（🔴 卖出信号）/ `watch`（🟡 观察信号）
  - `label`: 自由文本子类型，如 `抄底` / `突破` / `金叉` / `乖离超跌` / `止损`
  - `description`: 一句话解释，仅进 markdown 报告，不进推送
  - 用户说"加一个 R4C 乖离超跌的买入信号"→ direction=buy, label=乖离超跌
- `signal.formulas` ← LLM 直接写中文公式，原文喂 quant-buddy `runMultiFormula`
  - 第一条**必须**包含 `{ASSETS}` 占位符，CLI 会替换成 `资产池构造(资产1, 资产2, ...)`
  - 其它公式互引用通过 `"前一条名字"` 字符串引用（quant-buddy 约定）
- `signal.trigger_formula` ← 哪条公式的布尔/数值结果决定"触发"（默认 ≥ 0.5 视为触发）
- `signal.display_fields` ← 报告展示用，与 trigger_formula 合并请求一次 read_data
- `analysis_hook.enabled` 为 true 时，scanner 会把 `pending_analysis: true` 标进 stdout JSON，**LLM 在外层完成 WebSearch + 框架分析 + 写回报告**（cli.py 不调 LLM）
- `schedule.cron` 优先于 `schedule.time`；支持的 cron 子集：5 字段 `分 时 日 月 周`，仅支持 `* / 数字 / 逗号分隔 / 简单范围`，覆盖每日/每周几/每月几号；不支持的表达式 `apply-schedule` 会报错

---

## 工作流（LLM 收到自然语言后的标准动作）

### A. 用户问"现状"类（看不到 job_id）
1. 跑 `cli.py list`，把 enabled / schedule / last_run / triggered_today 列给用户
2. 让用户选具体哪个 job 后再走 B/C/D

### B. 用户要"改字段"
1. 必要时先 `cli.py show <id>` 拿当前值
2. 跑 `cli.py set <id> <jsonpath> <value>`（CLI 自动备份到 `jobs/<id>/.history/job-YYYYMMDD-HHMMSS.json`，保留最近 20 份）
3. 如果改的是 `signal.formulas` → **务必接着** `cli.py validate <id>`，把 errors[] 报回用户
4. 如果改的是 `schedule.*` → 接着 `cli.py apply-schedule <id>` 同步到 schtasks
5. 一句话回报：改了什么 / 备份在哪 / 是否需要 rollback

### C. 用户要"立即跑一遍"
1. 跑 `cli.py run <id> --dry-run` 拿到结构化 JSON
2. 解读 `triggered[]` / `cooled_down[]` / `all_stocks[]` / `anomalies[]`
3. **若 `pending_analysis=true` 且有触发** → 按 `analysis_hook.framework_doc` 做 WebSearch + 套框架，把每只触发股票的"下跌归因 / 框架分类 / 抄底结论"写进报告（追加到 `report.output_dir`）
4. 一句话总结回报，**dry-run 不推企微**

### D. 用户要"加 job"
1. 跑 `cli.py add <new_id> --from preset:<dip_2sigma|breakout_20d|macd_cross>`（或 `--from /path/to/job.json`）
2. 用 `set` 命令补 `asset_source.assets`、`notification.wecom.webhook`
3. `cli.py validate <new_id>` 确认公式可跑通
4. `cli.py run <new_id> --dry-run` 试一遍
5. `cli.py apply-schedule <new_id>` 注册到 schtasks（若 `schedule.enabled=true`）

### E. 用户问"今天怎么没提醒"
1. `cli.py diagnose <id>` 输出结构化 JSON：
   - `enabled`、`schedule.last_run_time`、`scheduler_status`（schtasks 查到的状态）
   - `cooldown_hits[]`（命中冷静期的股票 + 距冷静期结束日期）
   - `last_result_summary`（上次 triggered 数量 / fatal）
   - `quant_buddy_reachable`（小连通性测试）
2. 用一两句话翻译给用户："今天没提醒是因为 X"

---

## 资产池一致性（仅 type=excel/csv 时生效）

CLI `run` 启动会比对 `asset_source.path` 文件 与 `state/<id>/assets_snapshot.json`：
- 首次运行 → 生成 snapshot
- 无差异 → 直接扫
- 有差异 → **自动同步**（默认），stderr 提示 `资产池已自动同步：新增 N / 移除 M / 改名 K`，差异同时进 stdout JSON 的 `asset_pool_change`
- `inline` 类型不走快照（assets 直接写在 job.json 里，已是权威）

---

## 关键约束 & 心智模型

- **stdout 永远是 JSON** —— LLM 解析直接 `json.loads`，stderr 给人看
- **set 永远先备份** —— 任何 set 都自动 snapshot 到 `.history/`，可 `rollback`
- **dry-run 是默认安全档** —— 用户说"试一下/看看"统统加 `--dry-run`
- **触发判定** —— `signal.trigger_formula` 公式末日值 `>= 0.5` 视为 true
- **冷静期** —— `state/<id>/triggered.json` 按 ticker 记 `last_triggered`；`reset-cooldown` 可清单只或全部
- **analysis_hook 由 LLM 完成** —— scanner 只产数据并标 `pending_analysis`，避免 cli.py 强耦合 LLM
- **任务名前缀** —— `SignalMonitor_<id>`（与原 `CoreAssetDipTracker` 不冲突，可并存迁移）

---

## 目录结构

```
{SKILL_ROOT}/
├── SKILL.md                         本文件
├── scripts/
│   └── cli.py                       唯一 agent 入口
├── lib/                             被 cli.py 调用的实现模块
│   ├── job_schema.py                load/save/set/backup/rollback
│   ├── asset_source.py              excel/csv/inline 三类 loader
│   ├── scanner.py                   runMultiFormula + 触发判定 + 冷静期
│   ├── cooldown.py                  triggered.json 读写
│   ├── wecom.py                     企微 markdown 推送
│   ├── scheduler_win.py             schtasks 包装 + cron→schtasks 转换
│   ├── validator.py                 公式语法校验
│   ├── reporter.py                  报告渲染
│   └── quant_buddy.py               动态发现 quant-buddy-skill 并 import QuantAPI
├── jobs/
│   ├── registry.json                所有 job 的全局索引（cli list 的数据源）
│   ├── _presets/                    job.json 模板
│   │   ├── dip_2sigma.json
│   │   ├── breakout_20d.json
│   │   └── macd_cross.json
│   └── <job_id>/
│       ├── job.json                 该 job 的完整声明
│       ├── assets.xlsx              资产源（type=excel 时）
│       ├── .history/                set 命令的自动备份
│       ├── state/
│       │   ├── triggered.json       冷静期状态
│       │   ├── assets_snapshot.json 资产快照（excel/csv 模式）
│       │   ├── last_result.json     最近一次 run 的完整 JSON
│       │   └── logs/YYYY-MM-DD.log
│       └── output/reports/YYYY-MM-DD_<id>.md
└── templates/
    └── default_report.md
```

---

## 可扩展的信号类型示例

每个 job 的公式完全自定义，以下是几类典型信号的公式写法，直接用 `cli.py add <id> --from preset:<name>` 或手动填 `signal.formulas` 即可。

| 信号名 | preset 名 | 触发条件 | 适用场景 |
|--------|-----------|----------|----------|
| R4A（短线抄底） | `dip_2sigma` | 收盘价 < MA20 − 2×STD20 | 20 日布林下轨，捕捉短线超卖 |
| R4B（中线稳健） | `dip_2sigma_60d` | 收盘价 < MA60 − 2×STD60 | 60 日布林下轨，假信号更少，适合中线底部埋伏 |
| 20 日突破 | `breakout_20d` | 收盘价 > 近 20 日最高价 | 动量突破买入 |
| MACD 金叉 | `macd_cross` | DIF 上穿 DEA | 趋势确认买入 |

**R4B 公式示例**（替换 `signal.formulas`）：

```json
[
  {"name": "资产池收盘价", "expression": "资产池构造({ASSETS}) * \"全市场每日收盘价（分钟刷新）\""},
  {"name": "MA60",         "expression": "平均(\"资产池收盘价\", 60)"},
  {"name": "下轨60",       "expression": "\"MA60\" - 2 * 标准差(\"资产池收盘价\", 60)"},
  {"name": "信号",         "expression": "\"资产池收盘价\" < \"下轨60\""}
]
```

切换方法：`cli.py set <id> signal.formulas '<上方 JSON 数组>'` → `cli.py validate <id>`
