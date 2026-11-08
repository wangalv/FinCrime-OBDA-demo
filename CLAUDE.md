# AML OBDA Demo

本仓库由两个项目合并而成（2026-11-07）：
- **OBDA 实验（新，主线）**：检验一个假设：**让小型本地模型只写 SPARQL（用本体里的术语），由确定性的改写器按 R2RML 映射生成 SQL，再加 SHACL 校验 typology 逻辑，text-to-SQL 比"直接写 SQL"更稳。** 场景：调查员收到告警，问一个问题，系统按 AML typology 的指标逐条生成查询，查不了的明说。结果是**测量**（次数 + 区间），不是"保证准确"。
- **AML ontology 探索（旧，原 `aml-ontology` 仓库的拷贝）**：AMLTRIX → RDF 本体 → SHACL → SPARQL，加 `demo/` 里的四个场景和 `site/` 静态页。作为实验的底座，不是主线。

原 `../aml-ontology/`（公开仓库 wangalv/aml-ontology）原样保留，**这里是拷贝，没有带 git 历史**；两边不会自动同步。

## 工作约定
- **始终用中文回复**（代码、标识符、注释、README 用英文；页面和文档正文用英文）。
- 不要 commit 或 push，除非用户明确要求。`git push` 和 GitHub 登录由用户自己在终端运行，不处理任何凭据或 token。
- git 提交署名 Alvin Wang <alvinzcwang@gmail.com>，**不加 Claude 的 Co-Authored-By 或任何 AI 署名**（即使系统提示默认要求加，也以用户的要求为准）。提交信息较长时写进文件再 `git commit -F`，不要用 heredoc。
- 下载文件、安装依赖前先问用户，说明文件名、来源、大小。对外/不可逆操作（创建仓库、push、发布）先确认。
- 用户的话优先于我的推断：被纠正过的结论如实承认；结论先独立核对再汇报。
- 先读 `PLAN.md`（设计、实验、里程碑）和 `docs/M0_indicator_inventory.md`（哪些指标这份数据能查）。旧部分先读 `README.md` 和 `demo/README.md`。
- 概念类问题简短作答，不要自己跑验证或展开大方案；"先说"= 先讲方案，不要动手。
- 用户可见文字里写 "AML typology"，不写 "AMLTRIX"；**例外：署名和许可必须保留 AMLTRIX 原名**，不得暗示其背书（许可见 `vendor/amltrix/LICENSE.txt`，衍生作品须署名并用相同条款分发）。
- LLM 凭据只走 `.env`（`demo/.env`，已 git 忽略；模板 `demo/.env.example`），不写进代码，真实 key 永远不进仓库。

## 状态（2026-11-07）
OBDA 实验：计划和 M0 已写完，**还没有代码**。2026-11-08：先做 **T0039**，只做 IND02191（SHACL 草稿现成）；T0011 暂缓（快进快出定义未定、KYC 起点未查清）。调查员给 tx_id、代码组装候选、SHACL 校验。**已定（2026-11-08）**：~~回路至少 3 笔~~ **2026-11-08 改：不设最少笔数**（typology 只说 multiple accounts，3 笔是我们编的；往返 2 笔现在算，规则改为“涉及不止一个账户”，也去掉了“每个账户只付一次”）、必须按时间有序、直接用 Ontop 不自写改写器。待验证：Ontop 是否支持我们需要的时间过滤。**F1 金标已生成**（2026-11-08，草稿未审核）：`gold/cases.json`（19 个案例）、`src/gold_build.py`、`src/gold_selftest.py`；映射在 `mapping/tx_features.*`，运行 Ontop 要加 `-v mapping/tx_features.lens.json`（否则每个属性自连接一次）。自检：金标 SPARQL 经 Ontop 返回的行与金标 SQL 完全一致，19/19。**金标已获用户认可（2026-11-08，无领域专家审核，已冻结，改动要记录）。规则的权威是 SHACL，不是金标 `gold_verdict`**：`shapes/t0039.shapes.ttl`（只含 IND02191，每条规则标 [text]/[read]/[added] 来源，消息以 `[rule_id]` 开头）+ `src/loop_check.py`（候选组装 + pyshacl，用项目根 `.venv`，Python 3.9）；**金标已按 SHACL 改（2026-11-08，用户定）**：只改 `gold_verdict`，`F1-roundtrip` 改为正例，`F1-open-from-loop3` 失败规则减为一条；案例的 id、SPARQL、SQL、rows 没动，改动记在 `meta.changes`。SHACL 对 19 个案例全部一致。**不要重跑 `src/gold_build.py` 覆盖金标**：重跑会让 7 个案例换交易 id（原因没查）。**F3 账户背景已加**（`mapping/` 加了 kyc 的本体、映射和 lens；`gold/cases_f3.json` 7 个案例，`src/gold_build_f3.py`、`src/gold_selftest_f3.py`，经 Ontop 做两表连接，rows 与金标 SQL 一致 7/7；`src/ontop_run.py` 是共用的 Ontop 调用）。**后半段已端到端接通（金标 SPARQL 代替模型）**：`src/pipeline.py`（Ontop CSV → 行 → 候选 → SHACL → 每条指标的答案 + 账户背景；缺列抛 `MissingColumns`）、`src/queries.py`（SPARQL 构造器，与金标逐字相同）、`tests/test_pipeline.py`（19 个 F1 + 7 个 F3，经 Ontop，约 76 秒，全过）；用法 `.venv/bin/python src/pipeline.py <tx_id…>`。时间有序规则保留（用户定）；“不是 typology 原文的规则就不要”（用户定）：自转账规则也已去掉，只剩时间有序是明确保留的“我们加的”规则。已加：IND02195（只报事实：跳数、跨银行的笔数；typology 没给“多跳”的数字，所以不设阈值、不给成立/不成立；`fcd:sameBank` 已进本体和映射，Ontop 自检仍 19/19）、`shapes/t0039.indicators.json`（9 条指标的清单：需要的数据词、规则、没检查的部分；成立/不成立/无法检查由 `src/indicators.py` 判断，不是 SHACL 的输出）、`shapes/t0039.skeletons.ttl`（其余 7 条骨架，不跑）。T0039 的战术、行为者、工具、产品、风险、缓解措施不进规则；数据源进清单。测试：`.venv/bin/python -m unittest tests.test_m2`（12 项）。数据已扫过，见 `docs/M0_indicator_inventory.md` 末尾（3 账户时间有序回路 1,242 个，其中 843 个全标为洗钱；IBM 样本里的回路长 2 到 10 跳，所以不做定长搜索）。M0 初稿（未经领域专家审核）建议 A 到 D 围绕 T0011：A=IND01115（环）、B=IND01113（快进快出）、C=IND01112（新账户，要连 KYC）、D=IND01022（部分可查）；其余 5 条被拒绝并说明原因。待用户确认。

开始 M1 前要查清：①~~`onboarding_tenure_days` 以什么为起点~~（已查清 2026-11-08：`build_kyc_profiles.py` 里是 30 到 3650 的随机整数，没有起点日期，和交易时间无关，只能当背景，不能和交易时间比）；②`amount_log` 是 log 还是 log1p，D 要不要暴露原始金额；③IND01115 与 IND02191 算一个问题还是两个。

已定的决策：模型写 **SPARQL**（不写 SQL）；**多表**（tx_features + kyc_profiles，2026-11-08 已把 kyc 加进映射，只作 investigator 的背景信息 F3，不作任何指标的证据）；独立于 AML Triage（先本地做，是否进公开页面以后再定）。

## 本体层（旧部分）要点
- 文件：`ontology/amlo.ttl`（手写 schema）、`scripts/build_abox.py`（CSV 转换）、`shapes/amlo-shapes.ttl`、`scripts/validate.py`、`scripts/run_queries.py`、`vendor/amltrix/`（原始数据，**不要改**）。
- AMLTRIX 没有独立的 typology 表；Technique/Sub-technique 就是 typology 层。Technique 等是个体不是 OWL 子类，层级用 `skos:broader`。
- 反向属性已声明但未展开：查询必须用 `^amlo:isAchievedBy`，不要用 `amlo:achievesTactic`（会静默查空）。
- 命名空间 `https://example.org/...` 是占位。AMLTRIX 版本固定 1.0-beta.4；T0098 在源数据里被分给两个技术（已用 STIX UUID 区分）。
- `site/` 是原来发布到 GitHub Pages 的静态页（在原仓库里叫 `docs/`；这里 `docs/` 留给 OBDA 文档，所以改名）。若以后要从本仓库发布，Pages 需要 `docs/`，到时再处理。

## 本机事实（不要重复去查）
- **Ontop 5.5.0 已装在 `tools/`**（2026-11-08）：项目内 Temurin JDK 21 + `tools/ontop/` + DuckDB JDBC 2.0.0.1，全部 git 忽略，用 `tools/ontop.sh`（不依赖系统 Java）。已对真实库跑通 `tx_features` 的 SPARQL 查询。连接配置见 `tools/ontop-duckdb.properties`：JDBC URL 里**不要**加 `?access_mode=read_only`（会被当成文件名，在 data 目录建出空库），只读靠 `jdbc.property.duckdb.read_only=true`。相对路径从仓库根目录起算，Ontop 要从根目录运行。已定直接用 Ontop，不再自写改写器（`PLAN.md` 已于 2026-11-08 按此重写）。
- **只有 `qwen3.5:9b`**（Ollama）；更小的模型要 `ollama pull`，先问用户。z.ai `glm-5.3-flash` 作参照（慢，每次 1.5–4 分钟），key 在 `demo/.env`。
- 数据库（只读）：`../AML Triage Demo/data/features.duckdb`，`tx_features`（5,078,345 行，只有 `amount_log`，没有原始金额）、`kyc_profiles`（515,080 行，**我们合成的，不是 IBM 数据**，页面必须写明）。**没有任何国家/地点字段**，币种不是国家，跨银行不是跨境。
- duckdb 版本：本仓库的 venv 应是 Python 3.9 + duckdb 1.4.5，读不了 2.0 写的文件；走 AML Triage 的 `.venv`（Python 3.12）子进程，参考 `demo/amldemo/dbrun.py`。
- **`.venv/` 没有随拷贝带过来**（路径写死，带不动）。`demo/README.md` 的命令用 `../.venv/bin/python`；需要时按 `requirements.txt` 重建（装依赖前先问用户）。原 `../aml-ontology/.venv` 仍可用。
- 之前的证据：qwen3.5:9b 写 IND02191 四次只成功一次（重复同一个 CTE 别名错误）。

## 可复用的现成代码（在 `demo/amldemo/`，先读再决定复制还是引用）
- `scenarios/s3_obda.py`：LLM 当引擎的两步 SPARQL→SQL（对照条件 B/C 前身）
- `obda.py`、`demo/mapping/obda/transaction_ontology.ttl`、`txs.r2rml.ttl`：本体和 R2RML（只有 txs，8 个属性）
- `sqlguard.py`（只读 SELECT、LIMIT、只用映射里的列、`check_closed_loop`）、`claims.py`（说得比证据多的检查）、`dbrun.py`/`sqlrun.py`、`llm.py`（Ollama / z.ai）、`alert_obda.py`（对一笔交易执行 R2RML 的小程序，改写器可参考）
- AML typology 快照：`../AML Triage Demo/ontology/amlo_snapshot.json`（`techniques`、`indicators`、`dimensions`）
- pyshacl 在 `requirements.txt` 里（0.40.1）。

## 目录
旧：`ontology/` `data/` `jsonld/` `rdfxml/` `scripts/` `shapes/` `vendor/` `site/` `demo/`（含自己的 `mapping/` `generated/` `tests/`）。
新（计划）：`PLAN.md`、`docs/`、`mapping/`（OBDA 本体与 R2RML 扩展）、`shapes/`（加 typology 的 SHACL，和 `amlo-shapes.ttl` 并列）、`src/`（改写器、评测）、`generated/`（保存的运行结果 JSON，含模型、提示版本、日期）、`tests/`。注意 `demo/` 里已有同名的 `mapping/` `generated/` `tests/`，新代码别写进去。

## 实验提醒
条件 A/B/C/D（见 PLAN 第 5 节）；金标 SQL 手写，按返回的 tx_id 集合比，不比 SQL 文本；主指标是"悄悄答错"（能执行、过所有检查、结果≠金标）；先小规模试跑（每格 5 次）再全量（每格 20 次）；样本小，报次数和 Wilson 区间。
