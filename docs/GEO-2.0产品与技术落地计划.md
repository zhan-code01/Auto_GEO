# GEO 2.0 产品与技术落地计划

> 版本：v1.4<br>
> 日期：2026-09-04<br>
> 适用项目：AutoGEO<br>
> 目标：将 AutoGEO 从“自动生成与发布内容的平台”升级为“有证据、有实验、有归因的 AI 搜索可见度平台”。

## 1. 背景与判断

GEO（Generative Engine Optimization）关注品牌和内容是否被 ChatGPT、Perplexity、Google AI Overviews、豆包、通义千问等生成式搜索系统理解、提及、推荐和引用。

当前行业尚未形成统一的 GEO 开源标准。开源项目主要分为四类：

1. 学术研究与基准：GEO-Bench、AutoGEO；
2. AI 可见度监测：GeoLook、GEORank 等工具；
3. 网站审计与内容优化：GEORank、geo-optimizer-skill；
4. 可组合基础设施：LlamaIndex、LangGraph、Playwright、Ragas、DeepEval。

### 1.1 开源项目选型矩阵

以下项目的定位不能混为“GEO 生产框架”。正式接入前必须重新核对仓库活跃度、版本、License、依赖安全和最近一次可运行验证；论文代码或个人工具不因名称相似而直接进入生产链路。

| 项目 | 实际定位 | 可复用部分 | 本项目决策 |
|---|---|---|---|
| GEO-Bench | GEO 研究论文中的公开评测基准 / 查询集 | 固定问题分类、离线对照和指标设计 | 仅用于研究和离线校准，不作为生产运行时依赖 |
| AutoGEO | GEO 研究与协作优化参考实现 | 问题、内容、评测协作思路 | 借鉴方法，暂不作为核心运行时依赖 |
| GEO-optim/GEO | GEO 研究基线 / 实验代码 | 基准问题和实验设计 | 用于对照实验，先做隔离验证 |
| GeoLook、GEORank | 可见度监测或审计工具参考 | 指标展示、报告和审计思路 | 评估可复用模块，不直接替换现有系统 |
| geo-optimizer-skill | 内容优化检查清单 / Agent 工具 | 内容结构和检查项 | 作为可选内容规则，不作为测评事实来源 |
| LlamaIndex | RAG、数据连接和检索基础设施 | 事实库检索、文档切分和引用上下文 | 仅在事实库需要时采用，不作为 GEO 指标框架 |
| Playwright | Browser 自动化基础设施 | 页面操作、网络事件和快照 | 采用，受平台合规和本地浏览器约束 |
| LangGraph | 有状态工作流编排 | 评测任务、重试和人工介入状态机 | 按现有架构需要采用，不为使用而使用 |
| Ragas、DeepEval | LLM 应用评测组件 | 事实性、检索和回答质量评测 | 先与自定义 Judge 对照，不能替代人工校准 |

对有代码仓库的候选项目至少记录 `repository_url`、`license`、`last_verified_at`、`version_or_commit`、`security_status`、`integration_cost` 和 `decision`；GEO-Bench 作为论文基准单独记录 `paper_url`、数据来源和数据许可。以下是截至 2026-09-04 的初步核验快照，不把“能运行”误当成“适合长期生产”：

| 项目 / 仓库 | License / 数据许可 | 核验到的版本或提交 | 核验日期 | 选型结论 |
|---|---|---|---|---|
| [AutoGEO](https://github.com/cxcscmu/AutoGEO) | MIT | `49456df`（2026-06-14） | 2026-09-04 | 方法参考，暂不作为核心运行时 |
| [GEO-optim/GEO](https://github.com/GEO-optim/GEO) | Apache-2.0 | `c9e985f`（2025-10-30） | 2026-09-04 | 隔离对照实验 |
| [GeoLook](https://github.com/aigclink/geolook) | MIT | `9492cb3`（2026-08-10） | 2026-09-04 | 评估可复用模块 |
| [GEORank](https://github.com/yaojingang/GEORank) | Apache-2.0（代码）；数据另见 `DATA_LICENSE.md` | `424a0cf`（2026-08-12） | 2026-09-04 | 评估指标和审计思路，数据许可单独核对 |
| [geo-optimizer-skill](https://github.com/Auriti-Labs/geo-optimizer-skill) | MIT | `v4.17.1`（2026-09-03） | 2026-09-04 | 可选内容规则 |
| [LlamaIndex](https://github.com/run-llama/llama_index) | MIT | `949f2b8`（2026-09-02） | 2026-09-04 | 事实库需要时采用 |
| [Playwright](https://github.com/microsoft/playwright) | Apache-2.0 | `34d2302`（2026-09-03） | 2026-09-04 | 采用，受本地浏览器和平台规则约束 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT | `81bf17b`（HEAD，2026-09-04 拉取） | 2026-09-04 | 仅按工作流复杂度决定 |
| [Ragas](https://github.com/explodinggradients/ragas) | Apache-2.0 | `298b682`（HEAD，2026-09-04 拉取） | 2026-09-04 | 与自定义 Judge 对照 |
| [DeepEval](https://github.com/confident-ai/deepeval) | Apache-2.0 | `077c81b`（HEAD，2026-09-04 拉取） | 2026-09-04 | 与自定义 Judge 对照 |
| GEO-Bench | 论文基准；数据许可和分发方式按原始来源重核 | 见 GEO 论文附录 | 2026-09-04 | 仅用于研究和离线校准 |

这些版本和 License 是时间点快照；正式接入前仍要重新执行安全、依赖、数据许可和可运行性验证。GitHub API 限流或页面缓存时，不得把“无法读取元数据”解释为仓库不存在或 License 缺失。

Google 官方说明，AI Overviews 和 AI Mode 没有额外的专用技术要求，传统 SEO 基础仍然有效。OpenAI 和 Perplexity 则强调搜索爬虫、robots.txt、WAF/CDN 放行和页面可抓取性。

因此，AutoGEO 的技术重点应该从“生成更多文章”转为：

```text
可发现 -> 可理解 -> 可引用 -> 可验证 -> 可优化 -> 可归因
```

## 2. 总体目标

### 2.1 产品目标

建立以下业务闭环：

```text
用户问题采集
  -> 问题意图分类
  -> 多 AI 引擎测评
  -> 保存原始回答与引用证据
  -> GEO 指标计算
  -> 竞品与来源分析
  -> 生成优化建议
  -> 内容版本改写
  -> 人工审核发布
  -> 复测验证
  -> AI 流量与线索归因
```

### 2.2 12 周交付目标

| 目标 | 验收标准 |
|---|---|
| 测评可信 | 每条回答具备平台、模型、时间、问题版本、采集方式等元数据 |
| 引用可追踪 | 保存 URL、域名、标题、引用位置、来源类型和解析置信度 |
| 指标可解释 | 每个分数都能回溯到原始回答和证据 |
| 内容可优化 | 每条建议关联具体问题、页面、事实和内容版本 |
| 效果可验证 | 支持 baseline、recheck 和 A/B 内容实验 |
| 业务可归因 | 能追踪 AI 引用到访问、留资和转化 |

### 2.3 北极星指标与业务结果目标

本项目不能只用“数据可回溯”“接口可验证”作为成功标准。建议将以下指标作为试点期的北极星指标：

```text
Qualified Citation Rate (QCR)
= 有效问题回答中，品牌被可靠来源引用，且该引用能够支持回答结论的回答数
  / 有效问题回答总数
```

其中“可靠来源”采用两阶段判定，不能把 `source_quality` 和 `citation_support` 都交给 Judge：

1. **确定性来源资格**：先根据版本化的域名等级表 / 白名单、URL 是否可访问、URL 是否可规范化、页面正文是否可公开读取计算 `source_quality_rule_score`。首版规则建议使用以下固定权重：

   ```text
   source_quality_rule_score
   = 0.5 * domain_tier_score
   + 0.2 * url_access_score
   + 0.2 * canonicalization_score
   + 0.1 * content_access_score
   ```

   只有 `source_quality_rule_score >= 0.7` 且 `domain_tier_score >= 0.6` 才具备 Qualified Citation 的来源资格。这样一般 UGC / 聚合站即使页面可访问，也不会仅靠可访问性进入 QCR；域名等级、各项分值、白名单内容和 `source_quality_policy_version` 必须落库。未知域名可以保留在来源分析中，但默认不进入 QCR 分子。
2. **结论支持判断**：只有“引用内容是否支持回答结论”交给 Judge。Judge 必须记录模型、Prompt、版本和缓存键；输出不确定时进入人工复核，不能静默按支持处理。

因此，QCR 只有在“确定性来源资格通过”且与 `primary_claim` 关联的 `claim_citation_link.citation_support = supported` 时才计入。仅出现品牌名、出现无效链接、来源质量低于阈值或无法判断引用内容时，不计入 Qualified Citation。

回答可能同时包含多个事实和建议，不能因为某个次要句子被引用就把整条回答计入 QCR。Judge 先抽取 `primary_claim`（回答对用户问题的核心结论）和 `material_claims`（会影响决策的事实 / 条件），再把引用与主张建立关联。首版 Qualified Citation 判定为：至少一个通过来源资格的引用对应的 `claim_citation_link` 支持 `primary_claim`，且所有已识别的、通过来源资格并关联 `primary_claim` 的引用中没有明确反驳主结论的终态结果；只关联次要主张的引用不能计入。主结论无法确定，或 `primary_claim` 关联仍有 `pending / uncertain` 关系时，标记 `uncertain`，进入人工复核。额外报告 `material_claim_support_rate`，但它不替代按回答计算的 QCR。

QCR 的统计口径也必须固定：统计单位是一次 `prompt_id + platform + measurement_type + round_no + replicate_no` 的有效回答，而不是单条引用。有效回答定义为回答采集成功且正文非空；同一回答有多个合格来源时，QCR 分子仍只加 1。一次采样内部的失败重试不增加 `replicate_no`，只累加 `retry_count`。

```text
automatically_observable_valid_answers =
  valid answers where citation_observation_status in {extracted, no_citation}

review_resolved_valid_answers =
  valid answers where citation_observation_status in {unavailable, failed}
  and citation_review_status in {confirmed_citation, confirmed_no_citation}

observable_valid_answers = automatically_observable_valid_answers
  or review_resolved_valid_answers

unresolved_valid_answers =
  valid answers where citation observation is unavailable/failed and review is pending
  or primary_claim is missing
  or a source-qualified citation linked to primary_claim has citation_support in {pending, uncertain}

resolved_valid_answers = valid_answers - unresolved_valid_answers

automated_citation_observability_rate = automatically_observable_valid_answers / valid_answers
citation_review_resolution_rate = review_resolved_valid_answers / valid_answers
QCR_observed = qualified_citation_answers / resolved_valid_answers
QCR_lower_bound = qualified_citation_answers / valid_answers
QCR_upper_bound = (qualified_citation_answers + unresolved_valid_answers) / valid_answers
```

`no_citation` 必须表示采集器已经确认回答没有引用；引用不可见时先记录 `citation_observation_status=unavailable|failed`、`citation_review_status=pending`，人工确认后转为 `confirmed_citation` 或 `confirmed_no_citation`。人工确认有引用时必须补写至少一条 `fallback_level=manual` 的引用证据记录。`automated_citation_observability_rate` 只统计自动采集已经判定的回答，`citation_review_resolution_rate` 单独统计由人工复核解决的回答，不能用后者掩盖主链路不可观测。`resolved_valid_answers` 需要排除 `primary_claim` 缺失或其来源合格引用关系仍为 `pending` / `uncertain` 的回答；仅 material claim 的未决关系不影响回答级 QCR，但必须单独报告未决率。已确认无合格来源、`contradicted` 或 `insufficient` 的回答属于已判定的非 Qualified 回答，不进入未决分子。这样 `QCR_observed` 只反映已判定样本，`QCR_lower_bound` / `QCR_upper_bound` 才覆盖所有有效回答的不确定区间。当 `valid_answers = 0` 或 `resolved_valid_answers = 0` 时相应指标为 `null`，不能展示为 0。

正式宣称 QCR 提升前，各平台 `automated_citation_observability_rate` 暂以 80% 为最低门槛，并同时报告 `citation_review_resolution_rate`、`QCR_observed`、上下界、已判定样本数和不可观测率；该门槛需在 baseline 前冻结，不能根据结果事后调整。平台等权的 macro QCR 只对通过该门槛且有可比较 baseline / recheck 的平台计算；被排除的平台仍单独报告，不得从分母中静默删除。总体结果同时展示按回答数加权的 micro QCR。baseline / recheck 只比较相同 `prompt_id + platform + round_no + replicate_no` 的配对样本，置信区间按问题聚类 bootstrap 计算，避免把同一个问题在多个平台的回答当作完全独立样本。

来源资格分的首版规则必须可复算。建议将 `domain_tier_score` 固定为：官方 / 监管 / 原始机构 `1.0`，权威媒体 / 学术机构 `0.8`，专业社区 / 行业组织 `0.6`，一般 UGC / 聚合站 `0.4`，未知或无法判定 `0.0`；`url_access_score`、`canonicalization_score`、`content_access_score` 采用 `1 / 0.5 / 0` 三档，并将每项命中规则落库。Qualified Citation 同时要求总分 `>= 0.7` 和域名等级 `>= 0.6`。该分数表示“来源是否具备进入 QCR 的资格”，不等于来源内容本身一定真实；页面内容与回答结论的支持关系仍由 Judge 判断。

第 1～2 周完成协议、采集和归因可行性验证；第 4 周冻结采集协议、来源规则和测量口径后采集试点客户 baseline 原始回答，第 5 周冻结 Judge 版本并回放 baseline 生成基线结果；第 11 周采集 recheck 后沿用同一 Judge 和规则版本，避免两轮使用不同判定器。以下只能作为 12 周试点的暂定目标，不能在完成 baseline 和样本量登记前对客户承诺：

| 结果指标 | 暂定目标 | 约束 |
|---|---:|---|
| Qualified Citation Rate | 相对 baseline 提升 20% | 问题集、平台和采集规则保持可比 |
| AI 归因有效访问 | 相对 baseline 提升 15% | 只统计确定性或高置信度归因 |
| AI 归因有效线索成本 | 相对 baseline 下降 10% | 需要有足够转化样本，否则只报告趋势 |
| Utility / Factuality | 不低于 baseline | 作为护栏指标，不能用可见度换取事实错误 |

报告必须同时展示 QCR、Recommendation Rate、Own Source Citation Rate、AI-attributed Qualified Lead Rate、Cost per Qualified AI Lead、Answer Utility 和 Factuality，避免为了提高单一引用率而牺牲回答质量。

## 3. 产品边界

### 3.1 本阶段必须做

- AI 可见度监测；
- 品牌提及、推荐、排名、引用和情感分析；
- 竞品引用来源差距分析；
- 企业品牌事实库；
- 内容版本管理；
- 多 AI 引擎适配；
- baseline / recheck 测评；
- AI 流量归因；
- 人工审核和合规控制。

### 3.2 本阶段不做

- 自动破解验证码、滑块或登录保护；
- 承诺“保证被 AI 推荐”；
- 制造虚假第三方背书、评价或案例；
- 恢复服务器端浏览器作为主要测评入口；
- 把 `llms.txt` 当作核心排名因素；
- 无差异地复制文章到所有平台；
- 用单次成功回答证明长期 GEO 效果。

## 4. 总体技术架构

现有 FastAPI、PostgreSQL、Vue、Electron、Playwright、RAGFlow、LangGraph 继续保留，新增 GEO 领域服务层。

```text
frontend
  ├─ GEO Dashboard
  ├─ Citation Evidence
  ├─ Query Bank
  ├─ Content Experiments
  └─ Attribution

backend
  ├─ GEO Engine Registry
  ├─ Query Intelligence
  ├─ Citation Evidence
  ├─ Metrics V2
  ├─ Content Facts
  ├─ Experiment Service
  └─ Attribution Service

execution
  ├─ API Adapter
  ├─ Browser Adapter
  └─ Manual Sampling Adapter

storage
  ├─ PostgreSQL
  ├─ Raw Answer
  ├─ Citation JSON
  ├─ Page Snapshot
  └─ Metric Version
```

建议新增目录：

```text
backend/services/geo_engine/
backend/services/geo_metrics/
backend/services/geo_experiments/
backend/services/geo_attribution/
backend/services/geo_facts/
```

## 5. 阶段一：修复测评证据链

**周期：第 1～3 周，优先级：P0**

### 5.1 当前问题

Electron Worker 提交结果时将引用固定为空数组：

```python
"citations": [],
```

但平台适配器已经存在引用提取逻辑，导致当前链路变成：

```text
AI 页面有引用
  -> Worker 获取回答
  -> Worker 丢弃引用
  -> 后端收到 citations=[]
  -> Judge 判断无引用
```

### 5.2 涉及文件

```text
backend/workers/geo_evaluation_worker.py
backend/services/playwright/ai_platforms/base.py
backend/services/playwright/ai_platforms/doubao.py
backend/services/playwright/ai_platforms/qianwen.py
backend/services/playwright/ai_platforms/deepseek.py
backend/services/geo_evaluation_run_service.py
backend/services/geo_response_judge_service.py
backend/services/geo_evaluation_analytics_service.py
backend/api/client_geo_evaluation.py
backend/database/models.py（新增 GeoAnswerClaim、GeoCitationEvidence、GeoClaimCitationLink、GeoEvaluationMetricSnapshot 模型）
backend/migrations/versions/0037_geo_citation_evidence.py（计划新建；当前迁移 head 为 0036）
```

仓库实际迁移序列是 `0028 -> 0031 -> 0032 -> 0033 -> 0034 -> 0035 -> 0036`，不存在 `0029` 和 `0030`。实施前应运行 `alembic heads` 确认当前 head；如果 head 仍为 `0036_client_devices_multi_account`，新迁移使用 `0037_geo_citation_evidence.py` 和对应的真实 `down_revision`。这里的文件名是实施计划，不代表该文件当前已经存在。

当前实现还存在三个必须一起修复的语义问题：Electron Worker 将 `citations` 固定为空数组；服务端 Browser 流程只在引用列表为真值时保存引用，空列表和未观察到引用无法区分；现有 Judge 的 `citation_supported` 主要表示“存在可解析链接”，并不表示“引用内容支持回答结论”。Analytics 当前也仍是旧的四指标聚合。现有 Judge 输出还没有 claim-level 支持标签、事实性和回答实用性字段。阶段一不能只改 Worker，必须同时改 Worker、运行服务、Judge、Analytics 和接口 / 模型层，并为旧字段保留兼容读取规则。

### 5.3 实施内容

回答完成后执行：

```text
等待回答稳定
  -> 提取回答正文
  -> 对已通过能力确认的 API 读取结构化 citation / source 字段
  -> 对未确认或不提供 citation 字段的平台，Browser 模式读取网络响应和流式事件
  -> Browser 模式读取平台专用引用卡片
  -> 通用 DOM 规则作为最后的自动提取兜底
  -> 无法确认时记录 citation_observation_status=unavailable 或 failed
  -> 需要人工判断时记录 citation_review_status=pending，而不是伪造空引用
  -> 规范化 URL、过滤平台内部链接、去重
  -> 保存回答、原始证据和提取状态
  -> 异步调用 Judge，判断引用是否支持回答结论
```

引用提取不能统一假设为 DOM 问题。豆包、通义千问、DeepSeek 的引用可能出现在搜索结果卡片、引用角标、悬浮层或流式接口响应中；Browser 页面 DOM 看不到引用时，不能用“DOM 没有链接”推断“回答没有引用”。采集器必须区分观察状态和复核状态：`citation_observation_status` 使用 `extracted`（已提取引用）、`no_citation`（确认没有引用）、`unavailable`（当前采集方式无法判断）和 `failed`（提取器异常）；`citation_review_status` 使用 `not_required`、`pending`、`confirmed_citation` 和 `confirmed_no_citation`。`manual_required` / `manual_resolved` 继续保留给任务级平台人工验证，不能直接作为引用结论。

自动提取按“能力确认优先”实现，不是对所有平台默认 API-first：

1. **API / 结构化响应（条件路径）**：只有正式 API 的真实响应已经确认包含 `citations`、`sources`、`references` 等字段时，才直接读取字段并保存原始响应片段和字段路径。仅能返回纯文本回答的 API 不承担引用采集职责。
2. **网络响应 / 流式事件（国内平台默认主链路）**：对豆包、通义千问、DeepSeek，先在第 1 周逐一验证对应开放 API 是否真实返回引用字段；在验证结果为“不支持”或“未知”前，统一以 Browser 模式监听已授权页面产生的网络响应和流式事件作为主链路，只解析公开返回的结构化数据，不绕过登录、验证码或访问控制。
3. **平台专用解析器**：针对引用卡片、角标、展开面板和悬浮层实现 `doubao_*`、`qianwen_*`、`deepseek_*` 解析器；需要记录页面状态和展开动作。
4. **通用 DOM 解析器**：仅作为最后兜底，使用 `[class*="citation"]`、`[class*="source"]` 等规则，并保存命中的 selector、元素文本和快照，便于排查误判。
5. **人工 / 不可用**：上述路径都无法确认时保留回答正文和截图，设置 `citation_observation_status=unavailable` 或 `failed`，并按需设置 `citation_review_status=pending`；人工确认后转为 `confirmed_citation` 或 `confirmed_no_citation`，不把 `citations=[]` 当作事实结论。

第一周必须形成 API capability matrix，逐一记录豆包对应开放 API、通义对应 DashScope API、DeepSeek API 的真实响应是否包含 citation 字段、字段路径、是否受模型 / 地区 / 账号影响及样本证据。若某个平台没有字段或结果为未知，不得为“API 引用提取”单独开工期，该平台直接走 Browser 网络 / 流式事件解析；API 仍可用于回答内容或健康检查，但不能冒充引用数据源。

引用证据结构（回答级状态字段不重复写入每条引用；`citation_support` 属于主张-引用关系，不放在引用实体本身）：

```json
{
  "url": "https://example.com/article",
  "canonical_url": "https://example.com/article",
  "domain": "example.com",
  "title": "页面标题",
  "anchor_text": "引用文本",
  "position": 2,
  "source_type": "media",
  "is_own_domain": true,
  "source_quality_rule_score": 0.9,
  "source_quality_components": {
    "domain_tier_score": 0.8,
    "url_access_score": 1.0,
    "canonicalization_score": 1.0,
    "content_access_score": 1.0
  },
  "source_quality_rule_hits": [
    "domain_tier:authoritative_media",
    "url_access:http_2xx",
    "canonicalization:stable",
    "content_access:public_text"
  ],
  "source_quality_policy_version": "v1",
  "citation_extractor_version": "doubao_dom_v1",
  "fallback_level": "platform_dom",
  "raw_locator": {"selector": ".citation-card", "event_path": null},
  "snapshot_id": "object://geo-evidence/answer-snapshot-001",
  "confidence": 0.92
}
```

0037 迁移必须创建可索引的 `geo_answer_claims`、`geo_citation_evidence`、`geo_claim_citation_links` 和 `geo_evaluation_metric_snapshots` 表，而不是只继续堆叠 JSON 字段。`geo_evaluation_records` 保存回答级字段：`citation_observation_status`、`citation_review_status`、`capture_id`、`replicate_no`、`retry_count`、`measurement_type`、`raw_response_ref`、`answer_capture_method`、`capture_environment`、`answer_snapshot_id`、`evidence_schema_version` 和 Judge 版本；`geo_answer_claims` 保存回答主张：`id`、`answer_id`（外键指向 `geo_evaluation_records.id`）、`claim_key`、`claim_role`（`primary|material`）、`claim_text`、`claim_order`、`created_at`、`updated_at`，对 `(answer_id, claim_key)` 建立唯一约束，并保证每个回答最多一个 `primary` claim；`geo_citation_evidence` 保存引用观测级字段：`id`、`answer_id`（外键指向 `geo_evaluation_records.id`）、`canonical_url`、`domain`、`title`、`anchor_text`、`position`、`source_type`、`is_own_domain`、`source_quality_rule_score`、`source_quality_components`、`source_quality_rule_hits`、`source_quality_policy_version`、`citation_extractor_version`、`fallback_level`、`raw_locator`、`snapshot_id`、`created_at`、`updated_at`。对 `(answer_id, canonical_url, position)` 建立唯一约束，并对 `canonical_url`、`domain`、`source_quality_rule_score` 建立查询索引；原始网络事件和截图只保存对象存储引用，不直接塞进业务表。

`geo_claim_citation_links` 保存主张-引用关系，最小字段为：`id`、`answer_id`（外键指向 `geo_evaluation_records.id`）、`citation_id`、`claim_id`（外键指向 `geo_answer_claims.id`）、`claim_role`（冗余保存并由事务校验）、`citation_support`（`supported|contradicted|insufficient|uncertain|pending`）、`citation_support_reason`、`evidence_span`、`judge_model`、`judge_prompt_version`、`citation_support_judge_version`、`review_status`、`reviewed_by`、`reviewed_at`、`created_at`、`updated_at`。`citation_id` 外键指向 `geo_citation_evidence.id`；同一 `answer_id + citation_id + claim_id` 唯一，且三者必须属于同一回答。这样同一来源支持 `primary_claim` 但不足以支持某个 material claim 时，可以分别保存关系，不能把一个引用级布尔值覆盖成单一结论。

`geo_evaluation_metric_snapshots` 保存报表级可复算结果，最小字段为：`id`、`client_id`、`project_id`、`run_id`、`prompt_set_id`、`metric_name`、`metric_version`、`aggregation_level`、`dimension_key`、`filter_spec`、`window_start`、`window_end`、`value`、`numerator`、`denominator`、`interval_low`、`interval_high`、`confidence_level`、`input_data_version`、`evidence_schema_version`、`judge_prompt_version`、`citation_support_judge_version`、`source_quality_policy_version`、`data_quality_status`、`calculation_key`、`computed_at`、`created_at`。`dimension_key` 必须是稳定的规范化字符串，`filter_spec` 保存完整筛选条件；`input_data_version` 必须在回答证据或人工复核结果变化时递增。以 `calculation_key`（由指标名、版本、粒度、维度、窗口、筛选条件、输入数据版本和判定规则版本规范化后哈希得到）做唯一键，重复计算返回同一快照而不是产生重复报表；输入数据或判定规则变化时生成新快照。QCR 的上下界、observability、macro / micro 聚合都必须作为独立快照保存，不能只保存最终展示分数。

初期复用已有 `raw_citations`、`cited_urls`、`cited_domains` JSON 字段，并增加：

```text
citation_observation_status
citation_review_status
citation_extractor_version
capture_id
replicate_no
retry_count
measurement_type
raw_response_ref
answer_capture_method
capture_environment
answer_snapshot_id
evidence_schema_version
judge_prompt_version
citation_support_judge_version
judge_cache_key
```

`answer_id` 是现有 `geo_evaluation_records.id` 的业务别名，不再额外增加一个同名主键列；`raw_citations` 等旧 JSON 字段只作为兼容镜像，V2 查询以 `geo_citation_evidence` 和 `geo_claim_citation_links` 为准。`citation_support` 只属于主张-引用关系，`citation_observation_status` / `citation_review_status` 是回答级的采集状态，不能互相替代。传输层的 `capture_method` 映射到回答表的 `answer_capture_method`；`extractor_version` 统一映射为 `citation_extractor_version`，避免同一语义出现两套字段名。

### 5.4 验收标准

- 三个平台各准备至少 20 个固定 fixture，覆盖 API 字段、引用卡片、角标、悬浮层、流式响应、无引用和提取不可见等情况；
- fixture 仅作为冒烟和回归样本，不作为准确率结论；300 条人工标注子集按平台至少各 100 条分层，引用存在、确认无引用、不可观测 / 争议样本均须覆盖；每个平台和采集模式样本不足时只报告趋势；
- 第 1 周完成三平台 API capability matrix；每个平台明确标记 `supported`、`unsupported` 或 `unknown`，并保存真实响应证据；
- 不再使用一个笼统的“90% 准确率”作为整体承诺；按平台、采集模式和提取器版本分别报告 precision、recall、F1、unavailable rate 和 manual review rate；
- API / 结构化响应路径在该能力被 capability matrix 确认存在且有人工真值时，以 precision >= 0.95、recall >= 0.90 为首期门槛；Browser 路径先以 precision >= 0.85、recall >= 0.70 作为试点准入门槛，正式 baseline 后用真实分层标注重新估计并版本化，不达标时默认进入人工复核；来源资格规则另受 `source_quality_rule_score >= 0.7` 和 `domain_tier_score >= 0.6` 双门槛约束；
- URL 规范化和去重结果稳定；
- 引用提取失败不影响回答保存；
- Worker 和后端旧兼容路径的引用格式统一；
- 重复提交不会产生重复记录；
- 不增加新的服务器端浏览器测评入口。

平台集成闸门建议固定为：回答成功率 >= 90%，主链路 `automated_citation_observability_rate >= 80%`，引用存在性判断的人工对照 macro-F1 >= 0.80；人工复核解决率单独报告，不能替代主链路门槛。未达到时继续保存原始回答，但该平台不进入 QCR 提升汇总。

Browser 可行性必须有时间盒和降级条件：第 1 周每个平台使用至少 10 个真实问题完成一次网络响应 / 流式事件、平台专用 DOM、通用 DOM 的探测；成功标准是能把回答、引用事件、采集时间和临时 `capture_id` 稳定关联，并在回答落库后绑定到 `answer_id`，同时区分 `no_citation` 与 `unavailable`。单个平台连续 2 个工作日无法获得稳定结构化引用，立即降级为 Manual / unavailable，不再阻塞其他平台和指标开发。

Worker 必须传递 `result.get("citations")` 和提取状态，不能继续硬编码 `"citations": []`。每条引用记录至少保存 `citation_extractor_version`、`fallback_level`、`confidence`、`raw_locator` 和 `snapshot_id`，以便知道引用来自 API、网络响应、平台 DOM、通用 DOM 还是人工确认。

### 5.5 数据契约与幂等规则

回答和引用必须有稳定的关联标识，不能只依赖一组可变 JSON 字段：

```text
capture_id：客户端在发起提问前生成的单次采集关联 ID，用于先关联网络事件 / DOM 快照，回答落库后再绑定 `answer_id`
answer_id：当前 MVP 直接复用 geo_evaluation_records.id（自增整数）；只有跨系统传输时另加 answer_ref UUID，不为已有主表强行替换主键
replicate_no：同一问题 / 平台 / 轮次的独立重复采样编号，默认从 1 开始
retry_count：同一采样内部的失败重试次数，不参与样本唯一键
evaluation_key：run_id + prompt_id + platform + measurement_type + round_no + replicate_no
citation_key：`(answer_id, canonical_url, position)` 规范化元组，不使用无分隔符的字符串拼接
snapshot_id：原始回答、网络事件或页面快照的对象存储标识
```

数据库约束建议如下：

- 对新记录建立数据库唯一索引 `run_id + prompt_id + platform + measurement_type + round_no + replicate_no`，应用层重复检查只是用户体验优化；由于历史 `prompt_id` 允许为空，新 V2 记录必须要求 `prompt_id` 非空，或使用 `WHERE prompt_id IS NOT NULL` 的部分唯一索引；并捕获并发写入产生的唯一约束异常，返回幂等成功；baseline / recheck 在同一 run 下也因此不会互相碰撞；
- 同一 `answer_id` 下，`canonical_url + position` 唯一；同一 URL 在回答中出现多次时保留不同位置；
- `replicate_no` 与 `retry_count` 必须在请求、模型、接口和统计层使用同一语义；现有请求字段 `attempt_count` 只能兼容映射为 `retry_count`，不能直接作为独立样本编号；
- 新客户端请求显式传递 `replicate_no` 和 `retry_count`；旧客户端只传 `attempt_count` 时按 `replicate_no=1`、`retry_count=attempt_count` 兼容处理，并在记录中标记 `client_schema_version`；
- 现有 `phase` 的数据库语义是 `baseline / ongoing`，`recheck` 是产品层业务名称，不能直接写入旧 `phase` 或与 `round_no` 混用；V2 增加 `measurement_type=baseline|recheck|exploratory_repeat`，主报告只比较 `baseline` 与 `recheck`；同一测量类型的独立重复使用 `replicate_no`，不把 `repeat` 既当测量类型又当重复编号；旧 `phase=ongoing` 仅在兼容层映射为非基线测量；
- `round_no` 表示同一测量任务内的轮次，`replicate_no` 表示同一问题 / 平台 / 轮次的独立重复采样，`retry_count` 表示一次采样内部的失败重试，三者必须独立保存；
- 引用状态、人工确认结果和 Judge 结果必须可更新且保留更新时间、操作者和版本；
- `raw_citations` 可以作为旧接口兼容字段，但新查询和统计优先使用独立的引用记录或可索引结构；
- 迁移采用当前 head 之后的新 revision，执行前再次校验单一 head 和回滚脚本。

引用载荷必须保持三态：`citations=null` 表示未观察到或提取失败，`citations=[]` 只允许在 `citation_observation_status=no_citation` 时使用，非空列表表示已提取至少一条可规范化引用；如果原始响应有引用结构但全部 URL 无法解析，记录 `failed` 或 `unavailable`，不能伪装成“确认无引用”。任何接口适配不得用 `if citations` 把 `null`、空列表和非空列表压成同一结果。状态组合必须经过校验：`extracted/no_citation` 只能配 `not_required`（后续 Judge 支持关系仍可为 `pending`），`unavailable/failed` 必须配 `pending` 或已完成的人工确认状态。

原始回答、截图、网络事件和引用页面快照可能含有用户问题、个人信息、账号标识或敏感请求头。默认不保存 Cookie、Token、Authorization 和完整请求头；入库前对请求头、响应体、URL 参数和截图做脱敏，原始证据加密并按租户隔离，访问写审计日志。建议默认保留：原始网络事件、截图和引用页面快照 30 天，规范化回答与引用证据 12 个月；客户或合规要求更严格时以更短期限为准，并提供删除和撤回机制。

迁移采用“新增、双写、回放、切换”顺序：先新增 V2 字段、`geo_citation_evidence`、`geo_claim_citation_links`、`geo_evaluation_metric_snapshots` 表和兼容索引，再由 Worker、运行服务和 Judge 双写旧字段与 V2 字段；用固定回归集回放新旧结果，确认差异可解释后切换 Analytics 和前端 feature flag；历史记录不根据旧 `citation_supported` 反推 `citation_support`，只能标记为 `legacy_v1 / unknown`。

## 6. 阶段二：建立 GEO 指标 V2

**周期：第 3～5 周，优先级：P0**

### 6.1 指标分层

#### 出现层

```text
mention_rate       品牌提及率
coverage_rate      问题覆盖率
```

#### 推荐层

```text
recommendation_rate  被推荐比例
top1_rate             首选比例
ranking_score         推荐位置分
```

#### 引用层

```text
citation_rate       回答出现引用的比例
own_source_rate     自有域名引用比例
citation_share      所有引用中我方占比
source_quality_rule_score  确定性来源资格分
citation_support       单条主张-引用关系的支持标签（supported/contradicted/insufficient/uncertain/pending）
citation_support_rate  可审计主张-引用关系的支持比例
automated_citation_observability_rate 自动采集可观测引用状态覆盖率
citation_review_resolution_rate 人工复核解决覆盖率
qcr_observed        已判定样本中的 Qualified Citation Rate
qcr_lower_bound     全部有效回答的 QCR 下界
qcr_upper_bound     全部有效回答的 QCR 上界
```

#### 质量与业务层

```text
answer_utility      回答是否有用
factuality          事实准确性
sentiment_score     品牌情感
negative_risk       负面或错误推荐风险
confidence          评测置信度
conversion_rate     AI 流量转化率
ai_attributed_sessions       可审计 AI 来源带来的去重访问会话数
ai_attributed_qualified_lead_rate  AI 来源合格线索占全部合格线索比例
cost_per_qualified_ai_lead  每个合格 AI 线索的归因成本
```

### 6.2 Metrics Dictionary

V2 的每个指标必须固定数据粒度、公式、分母、来源和空值行为。以下为首版口径；除非新增 `metric_version`，不得在报表层临时改公式。

| 指标 | 计算公式 | 数据来源 | 口径约束 |
|---|---|---|---|
| `coverage_rate` | `valid_answers / attempted_answers` | 采集记录 | 表示回答采集覆盖，不再复用旧版“品牌被提及率”含义 |
| `mention_rate` | `brand_mentioned_answers / valid_discovery_answers` | Judge + 问题标签 | 直问品牌问题单独展示，不纳入 discovery 主指标 |
| `recommendation_rate` | `recommended_answers / valid_discovery_answers` | Judge | 未提及或仅背景提及不算推荐 |
| `top1_rate` | `top1_recommended_answers / valid_discovery_answers` | Judge | 表示所有有效发现型问题中被列为首选的比例；有效发现型回答数为 0 时为 `null` |
| `ranking_score` | `mean(ranking_score)` over valid discovery answers | Judge | 未推荐按 0 计入；同时展示样本数 |
| `citation_rate` | `citation_observed_answers / observable_valid_answers` | 引用状态 | 只在可观测回答中计算，不把 `unavailable` 当无引用 |
| `automated_citation_observability_rate` | `automatically_observable_valid_answers / valid_answers` | 自动采集状态 | 主链路能力指标；不含人工复核补齐；分母为 0 时为 `null` |
| `citation_review_resolution_rate` | `review_resolved_valid_answers / valid_answers` | 人工复核状态 | 只报告人工解决了多少不可观测样本；不作为主链路通过条件；分母为 0 时为 `null` |
| `qcr_observed` | `qualified_citation_answers / resolved_valid_answers` | 来源规则 + claim-citation link | 只统计已判定回答；分母为 0 时为 `null` |
| `qcr_lower_bound` | `qualified_citation_answers / valid_answers` | 来源规则 + claim-citation link | 未决回答按非 Qualified 计入分母；分母为 0 时为 `null` |
| `qcr_upper_bound` | `(qualified_citation_answers + unresolved_valid_answers) / valid_answers` | 来源规则 + 状态机 | 未决回答按可能 Qualified 计入分子；分母为 0 时为 `null` |
| `own_source_rate` | `answers_with_own_source_qualified / answers_with_any_source_qualified` | 规则 + 引用记录 | “source-qualified”只表示确定性来源资格通过，不要求 claim 支持终态；分母为 0 时为 `null` |
| `citation_share` | `own_source_qualified_citation_count / all_source_qualified_citation_count` | 规范化引用记录 | 按来源资格通过的引用条数计算，与 QCR 的按回答、按支持关系计算分开；分母为 0 时为 `null` |
| `source_quality_rule_score` | 每条引用按来源规则计算的分数 | 确定性规则 | 同时保存四个分项和命中规则；仅用于来源资格，不代表页面事实已被验证 |
| `citation_support_rate` | `supported_claim_citation_links / support_evaluable_claim_citation_links` | Judge + 人工复核 | 分母只包含有可审计证据片段、来源资格通过且支持标签已终态（`supported` / `contradicted` / `insufficient`）的主张-引用关系；`uncertain` / `pending` 排除出分母并单独报告未决率；不与按回答计算的 QCR 混用；单条关系的枚举字段仍叫 `citation_support` |
| `material_claim_support_rate` | `supported_material_claim_links / evaluable_material_claim_links` | Judge + 人工复核 | 仅用于诊断材料主张，不替代 QCR；`uncertain` / `pending` 单独报告 |
| `answer_utility` | `mean(utility_score)` | Judge / 人工校准 | 只在 Judge 成功且回答有效时计算 |
| `factuality` | `mean(factuality_score)` | Judge / 事实库核验 | 高风险事实错误单独计入 `negative_risk` |
| `sentiment_score` | `mean(sentiment_score)` over brand-mentioned answers | Judge | 未提及不进入情感分母 |
| `negative_risk` | `negative_or_fact_risk_answers / valid_answers` | 规则 + Judge | 作为质量护栏，不因 QCR 提升而放宽 |
| `confidence` | 按评测结果和采集可观测性输出区间 / 等级 | 统计层 | 不能把 Judge 自报 confidence 直接当统计置信度 |
| `conversion_rate` | `qualified_leads / attributed_sessions` | 归因与转化事件 | 主报告的 `attributed_sessions` 和 `qualified_leads` 只纳入确定性 / 高置信度归因；必须附归因等级、转化窗口和去重规则，`assisted` / `unknown` 单独展示 |
| `ai_attributed_sessions` | 确定性或高置信度 AI 来源带来的去重 `session_id` 数 | 归因日志 | 排除已识别爬虫和预取请求；作为计数而非比例 |
| `ai_attributed_qualified_lead_rate` | `deterministic_or_high_confidence_ai_qualified_leads / all_qualified_leads` | 归因与转化事件 | 对应北极星配套业务指标；分母为 0 时为 `null` |
| `cost_per_qualified_ai_lead` | `attributable_ai_spend / deterministic_or_high_confidence_ai_qualified_leads` | 发布、测评和转化成本 | 成本范围、币种、窗口和归因等级必须预先登记；分子或分母缺失时为 `null` |

所有比例指标（包括 `*_rate`、QCR、`qcr_observed`、`qcr_lower_bound`、`qcr_upper_bound`、`citation_share`、`negative_risk` 和 `ai_attributed_qualified_lead_rate`）统一使用 `[0, 1]` 存储，前端按百分比展示；`ranking_score`、`sentiment_score`、`factuality`、`answer_utility`、`Visibility Score` 和 `Utility Score` 使用 `[0, 100]`；`ai_attributed_sessions` 使用非负整数，`cost_per_qualified_ai_lead` 使用项目登记的货币单位。`citation_observed_answers` 定义为 `citation_observation_status=extracted` 或 `citation_review_status=confirmed_citation` 的有效回答；`observable_valid_answers` 还包括确认无引用的有效回答。旧版 `coverage_rate`、`citation_supported` 和 `visibility_score` 保留其历史单位，通过兼容层标记为 `legacy_v1`，不能直接代入 V2 公式。所有比例指标在分母为 0 时返回 `null`；`null` 表示未测量，`0` 表示已测量且没有命中。每条指标结果保存 `metric_version`、`aggregation_level`、分子、分母、过滤条件、时间窗口和数据质量状态。

V2 综合分先采用以下可复算的初始公式，完成 300 条人工标注校准后才允许调整，并递增 `metric_version`：

```text
Visibility Score V2
= 100 * (0.35 * mention_rate
       + 0.30 * recommendation_rate
       + 0.20 * top1_rate
       + 0.15 * citation_rate)

Utility Score V2
= 0.45 * factuality
 + 0.35 * answer_utility
 + 0.20 * (100 * (1 - negative_risk))
```

综合分的输入分母不足或为 `null` 时，综合分返回 `null`，不对剩余项自动重新加权；报告必须同时展示组成指标、分子、分母和缺失原因。当前代码中的旧 `visibility_score` 公式只用于 `legacy_v1` 回放，不能覆盖 V2 结果。

### 6.3 数据版本兼容

不覆盖历史数据，新增：

```text
metric_version = v1 | v2
judge_model
judge_prompt_version
evidence_schema_version
source_quality_policy_version
citation_support_judge_version
measurement_type = baseline | recheck | exploratory_repeat
aggregation_level = answer | prompt | platform | client
```

`schema_version` 是已有评估记录的整体协议版本：历史记录保持 `1.0.0`；V2 新记录使用 `2.0.0`，同时双写旧字段以支持过渡读取。`metric_version` 表示指标公式版本，`evidence_schema_version` 表示引用证据结构版本，三者不能互相替代。历史记录按 V1 展示，新测评默认使用 V2；切换期间由 feature flag 明确选择 V1 或 V2 查询，不能让旧 Analytics 因为只过滤 `schema_version=1.0.0` 而误读新结果。

### 6.4 分数校准

不要直接拍脑袋确定新权重，按以下流程校准：

1. 采集 300 条真实回答；
2. 人工标注提及、推荐、引用、事实性和实用性；
3. 对比 LLM Judge 与人工结果；
4. 调整 Judge Prompt、规则和权重；
5. 固化指标版本并建立回归数据集。

引用支持标签固定为 `supported`、`contradicted`、`insufficient`、`uncertain`、`pending`。Judge 的输入必须同时包含回答中的具体结论和引用页面的可审计片段；只看到 URL 不能判定为 `supported`。`supported` 才进入 QCR，`contradicted` 进入事实风险，`insufficient` 和 `uncertain` 进入人工复核。旧字段 `citation_supported` 只表示历史的“存在可解析链接”，不得直接映射为 V2 的 `citation_support`。

Judge 输出至少新增 `primary_claim`、`material_claims`、`claim_citation_links` 和 `material_claim_support_rate`；`primary_claim` / `material_claims` 写入 `geo_answer_claims`，每个 claim-citation link 写入 `geo_claim_citation_links`，记录 `citation_id`、判断标签（即 `citation_support`）和证据片段。没有可审计证据时不得由 Judge 凭常识补全来源。`citation_support_rate` 的分子 / 分母按这些 link 统计，QCR 仍按“回答是否至少有一条合格引用支持 `primary_claim`”统计，两者必须在报表中分开命名。

Judge 校准至少在 300 条人工标注子集中按平台和状态分层，包含引用存在、确认无引用、引用不可见 / 需人工判断和支持关系有争议的样本；从其中提取的引用回答中再至少标注 100 个 claim-citation link，用于校准 `citation_support`，不足时只报告趋势。由两名标注者独立标注至少 20% 样本，先计算一致性，再由第三方或负责人裁决冲突；首版闸门建议分别报告 citation presence 的 macro-F1 和 claim-support 标签（五类枚举）的 macro-F1，按预先登记的标签集各自达到 >= 0.80；任一关键标签低于门槛时不发布 QCR 业务提升结论。

最终显示两个分数：

```text
Visibility Score   被看见、被推荐和被引用的程度
Utility Score      对用户是否准确、有用和可信
```

### 6.5 前端改造

```text
frontend/src/views/geo/Monitor.vue
frontend/src/components/business/geo/GeoEvidenceTable.vue
frontend/src/components/business/geo/GeoFiveMetrics.vue
frontend/src/components/business/geo/GeoMetricComparisonChart.vue
frontend/src/services/api/index.ts
```

新增能力：

- 指标定义说明；
- 每个分数对应的证据；
- 引用域名排行榜；
- 我方与竞品引用占比；
- 按平台、问题类型、地区和时间筛选；
- 样本数和置信度展示；
- “未测量”和“数据为 0”严格区分。

## 7. 阶段三：问题池和 Query Intelligence

**周期：第 4～6 周，优先级：P1**

现有问题池是项目优势，需要从“生成问题”升级为“管理测评样本”。

### 7.1 默认问题结构

| 类型 | 数量 | 用途 |
|---|---:|---|
| 类目发现 | 25 | 用户寻找解决方案 |
| 产品比较 | 20 | 品牌与竞品对比 |
| 推荐型问题 | 20 | 测量推荐率和排名 |
| 问题解决 | 15 | 测量专业能力 |
| 教程 / 方法 | 10 | 测量知识覆盖 |
| 品牌直问 | 10 | 诊断品牌认知 |

品牌直问单独展示，不直接纳入整体可见度分数。

### 7.2 问题来源

```text
LLM 生成
用户手工输入
搜索联想词
客服问题导入
销售咨询记录导入
Search Console 数据
竞品问题反推
历史高转化问题
```

### 7.3 问题字段

```text
intent_type
funnel_stage
business_value
brand_entry_reason
competitor_entities
query_source
query_version
is_holdout
is_direct_brand_question
```

### 7.4 核心规则

- baseline 和 recheck 使用同一问题版本；
- 保留 holdout 集，防止内容过拟合；
- 只比较共同成功的问题；
- 记录地区、语言、平台和采集时间；
- 同时做词法去重和语义去重；
- 不能通过删除低分问题来人为提高结果。

## 8. 阶段四：品牌事实库和内容优化

**周期：第 5～8 周，优先级：P1**

### 8.1 新增模块

```text
backend/services/geo_facts/
backend/services/geo_facts/fact_extractor.py
backend/services/geo_facts/fact_validator.py
backend/services/geo_facts/fact_repository.py
```

事实对象：

```json
{
  "claim_id": "claim_001",
  "subject": "产品名称",
  "predicate": "支持能力",
  "object": "功能描述",
  "evidence_url": "https://example.com",
  "evidence_text": "原始证据",
  "valid_from": "2026-01-01",
  "valid_until": null,
  "status": "approved",
  "risk_level": "low",
  "approved_by": 1
}
```

### 8.2 内容流程

```text
问题
  -> 匹配相关事实
  -> 匹配已有页面
  -> 分析竞品引用来源
  -> 生成 Content Brief
  -> 生成 2～3 个内容版本
  -> 事实检查
  -> 引用检查
  -> 人工审核
  -> 发布
```

### 8.3 推荐内容结构

- 结论前置；
- 清晰定义；
- 客观数据；
- 对比表；
- 适用条件；
- 限制说明；
- 可靠来源；
- 作者和更新时间；
- FAQ 作为补充；
- 可独立被引用的段落。

### 8.4 内容质量禁止项

- 关键词堆砌；
- 大量同质化文章；
- 伪造案例、评价或第三方引用；
- 只改标题、不改事实；
- 15 个平台无差异复制同一文章；
- 生成无法核验的价格、资质和效果承诺。

## 9. 阶段五：AI 引擎适配层

**周期：第 7～10 周，优先级：P1**

### 9.1 统一接口

```text
backend/services/geo_engine/contracts.py
backend/services/geo_engine/registry.py
backend/services/geo_engine/capabilities.py
backend/services/geo_engine/citation_normalizer.py
```

建议接口：

```python
class GeoEngineAdapter(Protocol):
    name: str
    mode: Literal["api", "browser", "manual"]

    async def ask(self, query: str, context: EngineContext) -> EngineAnswer:
        ...

    async def health_check(self) -> EngineHealth:
        ...

    async def extract_citations(self, answer: EngineAnswer) -> list[CitationEvidence]:
        ...
```

`EngineAnswer` 还应携带 `capture_id`、`capture_method`、`citation_observation_status`、`citation_review_status`、`raw_response_ref`、`answer_snapshot_id` 和 `citation_extractor_version`。接口层必须允许“有回答但引用不可见”，不能用空数组丢失这一状态。旧接口中的 `citation_extraction_status` 只做读取兼容，写入统一使用上述两个字段。

### 9.2 采集模式

1. API 模式：仅对 capability matrix 已确认提供 citation 字段的官方 API 或正式商业接口启用；没有字段的 API 只负责回答内容，不负责引用采集；
2. Browser 模式：对第一批国内平台默认作为引用采集主路径，使用 Electron 本地浏览器、网络响应 / 流式事件和 Python 平台适配器；
3. Manual 模式：没有稳定 API 或自动化风险较高的平台，使用插件辅助人工采集。

引用提取策略固定为“已确认 API 字段（如有）-> Browser 网络 / 流式事件 -> 平台专用解析 -> 通用 DOM -> 人工 / unavailable”。对豆包、通义千问、DeepSeek，默认从 Browser 网络 / 流式事件开始；DOM 只能作为 Browser 模式的采集手段，不能作为 API 模式的唯一来源。平台接入验收必须包含至少一条引用不可见或引用延迟出现的失败样本，并验证回答仍然可保存。

### 9.3 平台优先级

第一批保持：

```text
豆包、通义千问、DeepSeek
```

第二批：

```text
Kimi、腾讯元宝、智谱清言、百度 AI
```

第三批：

```text
ChatGPT Search、Perplexity、Gemini、Google AI Overviews
```

每个平台单独记录：

```text
platform
model
model_version
region
language
capture_mode
login_state
search_mode
conversation_reset
asked_at
response_version
citation_parser_version
```

第一批平台的引用采集决策：

| 平台 | 开放 API citation 字段 | 第 1 主链路 | 备用链路 |
|---|---|---|---|
| 豆包 | 第 1 周实测；未确认前按 unsupported / unknown 处理 | Browser 网络响应 / 流式事件 | 平台专用 DOM -> 通用 DOM -> Manual |
| 通义千问 | 第 1 周实测；未确认前按 unsupported / unknown 处理 | Browser 网络响应 / 流式事件 | 平台专用 DOM -> 通用 DOM -> Manual |
| DeepSeek | 第 1 周实测；未确认前按 unsupported / unknown 处理 | Browser 网络响应 / 流式事件 | 平台专用 DOM -> 通用 DOM -> Manual |

API capability 的结论必须带测试时间、API / 模型版本、请求样本和响应证据；不能因为文档或 SDK 类型中出现 `source` 字样，就推断实际返回了引用。

## 10. 阶段六：内容实验系统

**周期：第 8～10 周，优先级：P1**

### 10.1 实验版本

```text
A：原始版本
B：结论前置版本
C：数据和引用增强版本
D：对比和适用条件增强版本
```

### 10.2 实验流程

```text
选择问题集
  -> 生成内容变体
  -> 离线事实与质量检查
  -> 人工审核
  -> 指定渠道发布
  -> 固定时间窗口复测
  -> 对比 mention / recommendation / citation
  -> 判断是否保留版本
```

### 10.3 实验约束

- 每个实验必须保留原始版本；
- baseline / recheck 使用相同问题集；
- baseline / recheck 各默认采样 1 次；需要估计回答随机性的实验，再对同一问题做至少 2 次独立重复；
- 内容变化和平台变化不能同时发生；
- baseline / recheck 固定平台、模型 / 模型版本、地区、语言、登录账户类型、搜索开关、上下文清理方式、提示词版本、采集器版本、来源规则版本和 Judge 版本；任一项改变都重新建立 baseline 或只做观察性比较；
- 报告置信区间和样本数；
- 低样本结果只能标记为“趋势”。

### 10.4 统计与决策口径

每个实验开始前登记问题集版本、平台、内容版本、观察窗口、主指标、最小可检测差异（MDE）、显著性水平和目标检验功效。`Qualified Citation Rate` 的“相对提升 20%”只是业务目标，不是自动通过条件；最终是否达标以预先登记的绝对差异、置信区间和样本量要求为准。

默认使用双侧检验、显著性水平 `alpha = 0.05`、目标功效 `0.80`，但实际样本量由 baseline QCR、MDE、平台数和问题聚类结构计算。不能因为收集到 600 条回答就直接认为样本充足；如果样本不足，结果只能标记为趋势，不得宣称因果提升。

实验报告至少包含：每个平台的分子 / 分母、observability、QCR observed 和上下界、绝对变化、相对变化、95% 置信区间、失败与重试数、采集版本、Judge 版本和成本。实验期间不得根据中途结果反复停止或扩大样本，除非预先登记了停止规则。

## 11. 阶段七：发布和渠道质量

**周期：第 8～10 周，优先级：P2**

现有 15+ 平台发布能力继续保留，但发布策略从“覆盖数量”改为“渠道质量”。

### 11.1 渠道分层

```text
Owned：官网、知识库、产品文档
Earned：行业媒体、真实新闻报道、第三方评测
Community：知乎、论坛、专业社区
Social：公众号、小红书、头条等
```

### 11.2 发布记录新增字段

```text
content_version
channel_type
canonical_url
source_article_id
duplicate_hash
approved_by
published_url
citation_priority
```

### 11.3 新闻稿方向

当前新闻渠道方案可以作为 P2，但必须先确认真实供应商 API，再做小额单篇实验。不得直接采用未经验证的“媒体权重更高”“引用提升数倍”等结论。

新闻稿流程：

```text
内容适配
  -> 人工审批
  -> 提交供应商
  -> 查询订单
  -> 保存发布 URL
  -> 进入 AI 引用测评
  -> 比较投入和引用增量
```

“新闻稿媒体权重更高”只能作为待验证假设。采用小额匹配实验验证：选择意图、难度、平台和问题量级相近的问题集，Treatment 增加新闻稿 / 权威媒体渠道，Control 保持现有渠道；两组使用相同 baseline / recheck 规则，固定 2～4 周观察窗口，并记录每个发布 URL、发布时间、渠道成本和内容版本。主要比较：

```text
incremental_citation_rate
incremental_own_source_rate
recommendation_rate_delta
cost_per_incremental_citation
```

实验期间不能同时更换问题集、平台、内容主张和发布节奏；若无法做页面或问题级随机化，至少使用匹配对照并明确标记为“观察性结果”，不得写成新闻稿导致了引用增量。

新闻稿实验进一步拆为两类，禁止混合：

- `channel-only`：Treatment 和 Control 使用同一内容版本，仅增加或不增加新闻稿 / 权威媒体渠道，用于估计渠道增量；
- `content-only`：两组使用同一渠道，仅改变内容版本，用于估计内容增量。

如果供应商必须改写稿件才能发布，则该实验标记为混合干预，只能报告关联结果，不能归因于媒体渠道本身；同时记录搜索引擎 / AI 平台可能存在的索引延迟，不得在内容尚未完成索引时提前判定失败。

## 12. 阶段八：AI 流量和转化归因

**周期：第 1～2 周完成可行性验证；第 9～12 周完成产品化，优先级：P1**

### 12.1 归因链路

```text
AI 回答提及
  -> 引用链接
  -> 用户点击
  -> 官网访问
  -> 页面行为
  -> 留资 / 注册 / 咨询
  -> 成交
```

归因分为四级，不能把无 referrer 的访问全部归为豆包、通义或 DeepSeek：

```text
确定性：服务端命中已登记的短链 / 重定向 token 或唯一落地页参数并有点击日志，或明确 UTM 被保留且有服务端访问日志；点击已排除已识别的爬虫和预取请求
高置信度：referrer 或平台显式来源存在，并与引用页面、时间窗口和访问路径一致
辅助性：无 referrer，但有已发布引用、页面路径、时间窗口和匿名行为特征的聚合匹配
未知：只有普通直达访问或行为相似，无法证明来自某个 AI 平台
```

无 referrer 时的兜底方案：

1. 为实验内容生成按“平台 + 内容版本 + 发布 URL”隔离的唯一落地页路径或短链，例如 `/r/{token}`，由服务端记录 token、平台、发布时间和目标页面后再重定向；token 不包含用户身份信息，避免多个平台共用一个 token 后只能归因到活动而无法归因到平台；服务端点击日志必须区分终端用户、AI 爬虫和预取请求，后两者不能创建 AI 用户会话或直接计入转化分母；
2. 在取得必要的隐私告知 / 同意并符合客户合规要求的前提下记录 first-party cookie、服务端访问日志、页面进入路径、停留和转化事件；不采集不必要的个人信息，并提供拒绝、撤回和删除机制；
3. 对 URL 参数、短链是否会被 AI 平台保留和点击进行小规模可行性实验，不能默认 AI 引用会保留 query 参数；
4. 没有 token、referrer 或可审计来源时，只计入“AI-like / 未知来源”观察池，不计入确定性 AI 转化；
5. 行为特征只能做匿名聚合的辅助归因，不能据此在用户级别断言“来自某个平台”。

### 12.2 新增模块

```text
backend/services/geo_attribution/
backend/services/geo_attribution/referrer_classifier.py
backend/services/geo_attribution/utm_service.py
backend/services/geo_attribution/landing_token_service.py
backend/services/geo_attribution/redirect_log_service.py
backend/services/geo_attribution/conversion_service.py
```

采集内容：

```text
AI 来源域名
引用页面
进入页面
问题类型
平台
访问时间
UTM 参数
转化事件
归因等级（deterministic / high_confidence / assisted / unknown）
归因证据和证据版本
```

第 1～2 周的可行性验证至少包含三组链路：普通 UTM、唯一落地页参数 / 路径、短链重定向。对每组链路记录“链接是否被保留、是否被点击、是否能落到服务端日志、是否能排除爬虫 / 预取、是否能连接到转化事件”，并输出可归因率。验证失败时，12 周目标只能承诺渠道级趋势分析，不能承诺用户级 AI 平台归因。

### 12.3 归因验收边界

- 先支持自有域名和自有内容，不把第三方媒体站点的访问日志假设为可获得；
- 每个归因结论必须保存证据来源、时间窗口、匹配规则和置信等级；
- 确定性归因只接受可审计的 token、UTM、referrer 或服务端点击日志，并排除已识别的爬虫、预取和内部测试流量；单独的 referrer 只能进入高置信度，不得自动升级为确定性；
- 无 referrer 且无 token 的访问进入未知池，不进入 AI-attributed Qualified Lead Rate 分子；
- 转化链路必须支持撤回、去重和跨会话规则，避免一个用户多次访问重复计数。

### 12.4 转化指标口径

首版固定以下口径，项目启动后不得按结果临时切换：

```text
AI-attributed Qualified Lead Rate
= 确定性或高置信度 AI 来源带来的去重合格线索数
  / 全部去重合格线索数
```

默认将同一 first-party `session_id` 定义为 30 分钟无活动即结束的会话，MVP 不做跨设备拼接；转化窗口为访问后 7 天内计入有效访问，14 天内计入合格线索，30 天内计入注册 / 咨询；成交窗口由业务周期另行配置，但必须在实验开始前登记。合格线索必须按试点客户预先登记的业务状态定义，不能把所有表单提交直接视为合格线索。每个 `conversion_id` 只能归属一次，主报告使用 first-touch AI attribution，辅助报告同时展示 last-touch 结果；`assisted` 和 `unknown` 单独展示，不进入确定性主指标。

## 13. 风险、依赖与成本控制

### 13.1 风险清单

| 风险 | 影响 | 触发信号 | 缓解措施 | 责任人 |
|---|---|---|---|---|
| 平台 UI 或引用结构改版 | 引用解析失效、指标断崖 | fixture 通过率下降、unavailable rate 上升 | 平台专用解析器、版本化 fixture、人工 fallback、改版告警 | 后端 / 测试 |
| API / 网络协议变化 | citation 字段消失或结构变化 | schema 校验失败 | 保存原始响应、字段路径监控、适配器 capability 检查 | 后端 |
| 登录状态、验证码、账号风控 | 采集样本不足或账号封禁 | 登录失败率、人工介入率上升 | 限速、账号隔离、人工模式、停止绕过风控 | 测试 / 运营 |
| 引用存在但 DOM 不可见 | citation 被误判为不存在 | API 有引用而 DOM 为空 | API / 网络响应优先，状态区分 unavailable 与 no_citation | 后端 |
| AI 回答随机性 | baseline / recheck 不可比 | 同题多次回答差异大 | 固定提示词和环境、至少 2 次重复、报告区间和样本数 | 产品 / 研究 |
| Judge token 成本超预算 | 评测规模无法持续 | 单次评测成本、队列积压 | 规则预筛、缓存、低成本模型优先、按争议样本升级 Judge | 产品 / 后端 |
| URL 规范化失败 | own source / citation share 失真 | 同页多 URL、重定向失败 | canonical 规则、重定向解析、域名白名单、人工抽样 | 后端 |
| 国内 App 缺少 referrer | AI 转化不可直接归因 | direct / empty referrer 占比高 | token / 短链实验、归因等级、未知池、只报可审计结果 | 数据 / 产品 |
| 新闻稿供应商不稳定 | 发布和效果实验中断 | API 超时、发布 URL 缺失 | 供应商适配层、人工补录、单篇小额验证 | 发布 / 产品 |
| 内容重复或低质量 | 平台降权、品牌风险 | 内容相似度高、负面反馈上升 | 事实库、人工审核、渠道差异化、停止批量复制 | 内容 / 合规 |
| 原始回答或网络证据含敏感数据 | 隐私泄露、跨租户暴露 | 脱敏扫描失败、异常下载或访问 | 请求头脱敏、加密存储、租户隔离、RBAC、保留期限和删除审计 | 后端 / 合规 |
| ToS、版权和隐私边界 | 项目被叫停或产生合规风险 | 平台规则变化、投诉 | 只使用授权访问和公开响应，保留人工模式，做法务审查 | 产品 / 合规 |

### 13.2 依赖清单

| 依赖 | 最晚确认时间 | 阻塞后的替代方案 |
|---|---|---|
| 三个平台可用账号、登录设备和人工介入 | 第 1 周 | 降为 Manual Sampling，减少平台或问题数 |
| API / 网络响应可观测性和平台字段样本 | 第 1 周 | 先交付 Browser 专用解析和 unavailable 统计 |
| 当前 Alembic head 与数据库权限 | 第 1 周 | 先复用 JSON 字段，迁移单独排队 |
| 试点客户自有域名、访问日志和转化事件 | 第 2 周 | 只做渠道级趋势，暂停用户级归因 |
| 新闻稿供应商真实 API、发布 URL 和成本 | 第 8 周 | 只做人工单篇实验，不接自动发布 |
| Judge 模型额度和预算 | 第 4 周 | 规则 + 小样本人工标注，延后全量 Judge |

### 13.3 评测规模与成本模型

固定验收集按 `100 个问题 × 3 个平台 × baseline/recheck 2 轮 = 600 条回答采集` 估算。若每条有效回答执行 1 次 Judge，基础 Judge 调用约 600 次；按“15% 记录需要 1 次额外调用”的预算假设计，常规预算约 690 次。该 15% 只是第 1 周前的容量假设，需用小样本实测替换并记录版本；当前 Judge 实现最多允许 2 次额外重试，因此容量上限按 `600 + 600 × 15% × 2 = 780` 次预留。回答采集重试与 Judge 重试分开计数，回答采集重试还必须单独记录预算。若每题做 2 次独立重复采样，则回答和 Judge 规模约翻倍，常规预算约 1,380 次、容量上限约 1,560 次，不含人工复核。以上只估算 Judge 调用，不含 AI 平台账号 / API、Browser 设备、对象存储、网络流量和人工标注成本；这些成本必须单独纳入 `attributable_ai_spend` 或项目预算表，不能默认为 0。

上线前必须记录：回答数、成功率、回答采集重试率、Judge 重试率、Judge 调用数、平均输入 / 输出 token、单条回答成本、每次测评成本和每个 Qualified Citation 的成本；当 Qualified Citation 数为 0 时，单位成本返回 `null`，不能展示为无穷大或 0。成本控制按以下顺序执行：规则预筛 -> answer hash 缓存 -> Judge prompt / model 版本缓存 -> 争议样本升级模型 -> 定期抽样人工复核。没有预算和额度确认，不把“全量每次都 Judge”作为默认排期承诺。

第 4 周开始 baseline 前必须登记成本预算表：`budget_per_run`、`budget_per_answer`、`judge_token_budget`、`retry_budget` 和超预算处理人。单次测评达到预算的 80% 时触发预警，达到 100% 时停止新增 Judge，改用缓存、规则预筛或人工抽样；预算调整必须记录版本，不能在实验结束后补填。

### 13.4 生产发布闸门

每周发布前执行一次数据质量闸门，未通过时暂停业务效果比较，但保留原始采集和故障诊断：

| 闸门 | 暂定通过条件 | 未通过处理 |
|---|---|---|
| 采集可用性 | 各主平台回答成功率和引用可观测率达到预设门槛 | 标记 unavailable，停止 QCR 提升宣称 |
| 证据可追溯 | 回答、引用、快照和解析版本可相互关联 | 阻止进入 Judge 和业务报表 |
| Judge 一致性 | 与人工标注的关键标签达到预设一致性，争议样本可复核 | 降级规则或人工复核 |
| 事实与合规 | 高风险事实无未审核发布，敏感数据无泄漏 | 阻止发布并回滚内容版本 |
| 成本与容量 | 评测成本、队列积压、失败重试在预算内 | 降低 Judge 频率或缩小样本 |

上述“预设门槛”必须在 baseline 前登记具体数值。任何解析器、来源规则、Judge Prompt 或归因规则变更都要递增版本，并至少保留一轮旧版本回放结果，防止规则变更制造假增长。

## 14. 测试方案

### 14.1 后端单元测试

```text
tests/unit/test_geo_citation_normalizer.py
tests/unit/test_geo_metrics_v2.py
tests/unit/test_geo_query_quality.py
tests/unit/test_geo_fact_validator.py
tests/unit/test_geo_attribution.py
tests/unit/test_geo_data_contract.py
tests/unit/test_geo_observability.py
tests/unit/test_geo_claim_support.py
```

覆盖：

- URL 规范化和去重；
- 自有域名识别；
- 引用质量分；
- 确定性 `source_quality_rule_score`、域名等级和 `>= 0.7` 阈值；
- 指标计算；
- QCR 的来源资格与 Judge `citation_support` 分离；
- `citation_observation_status` 与 `citation_review_status` 的状态迁移和 QCR 上下界；
- `capture_id` 到 `answer_id` 的绑定、证据表外键和引用唯一约束；
- 指标快照的 `calculation_key` 幂等、分母 / 分子和版本字段完整保存；
- QCR 的 macro / micro 聚合和按问题聚类的置信区间；
- `primary_claim`、`material_claims` 和 `claim_citation_links` 的解析与支持标签；
- 低样本处理；
- 置信度计算；
- baseline / recheck 共同问题集；
- 幂等提交和失败重试。

### 14.2 平台集成测试

每个平台覆盖：

```text
登录有效
登录失效
正常回答
回答超时
引用存在
引用不存在
人工验证
回答重复
浏览器退出
网络中断恢复
网络事件无法关联回答
引用延迟出现
引用不可观测但回答成功
任务级人工验证与引用级人工复核同时发生
```

### 14.3 前端 E2E

```text
创建问题集
建立 baseline
启动 recheck
查看引用证据
查看竞品来源
查看指标解释
筛选平台和问题类型
查看内容实验结果
查看转化归因
```

### 14.4 固定验收数据集

```text
3 个平台
100 个问题
2 轮（1 次 baseline + 1 次 recheck）
600 条回答采集
其中至少 300 条人工标注子集（用于 Judge 校准，不是额外样本）
每个平台至少 20 个 fixture（合计至少 60 个，覆盖引用、无引用、不可观测、网络 / 流式事件和 DOM 状态）
```

这里的“2 轮”对应 `measurement_type=baseline` 和 `measurement_type=recheck`，不是 `round_no=1/2`；同一轮如需重复采样，再增加 `replicate_no`，不改变测量类型。

每个 fixture 不只指 HTML 页面，还必须覆盖网络 / 流式事件样本、DOM 快照、引用角标或悬浮层状态、无引用回答和不可观测回答；每个 fixture 标记期望状态和来源证据，避免把“页面样本”误解为真实引用的完整真值。fixture 数量与 600 条真实回答采集相互独立，不计入回答样本量；若某平台未达到每个平台 20 个 fixture，只能报告该平台的冒烟结果。

## 15. 12 周排期

| 周期 | 任务 | 交付物 |
|---|---|---|
| 第 1 周 | 指标定义、数据盘点、迁移 head 核对、三平台 API capability matrix、Browser 可行性 spike、归因可行性验证启动 | 测评协议、指标字典、0037 迁移草案、API 能力结论、Browser 决策、归因实验设计 |
| 第 2 周 | Worker 引用提取；以 Browser 网络 / 流式事件为国内平台主链路，补平台专用 DOM 和通用 DOM 兜底；执行平台降级决策 | 引用证据进入后端；Browser spike 报告；归因可行性初测 |
| 第 3 周 | 引用规范化、数据契约、幂等、状态字段和 fixture 回归 | Citation Evidence V1；数据契约和脱敏检查 |
| 第 4 周 | Metrics V2 数据结构；冻结采集协议、来源质量规则、QCR 口径和实验统计方案；采集 100 问题 baseline 原始回答 | 新指标接口；版本化协议；baseline 原始数据 |
| 第 5 周 | Judge 校准并冻结版本；统一回放 baseline；指标前端和成本测算 | Visibility / Utility / QCR 基线结果、成本报告和统计方案 |
| 第 6 周 | Query Intelligence | 意图分类、holdout 集 |
| 第 7 周 | 品牌事实库 | 事实审核和版本机制 |
| 第 8 周 | 内容优化工作台 | 内容变体、引用检查 |
| 第 9 周 | AI 引擎注册中心 | API / Browser / Manual 统一接口 |
| 第 10 周 | 新平台接入、内容实验和新闻稿匹配实验准备 | 第一批实验报告；渠道对照组 |
| 第 11 周 | AI 流量归因产品化；完成 recheck 和转化链路 | UTM、token、日志、归因等级和转化链路 |
| 第 12 周 | 压测、回归、试点复盘和业务结果评估 | 试点交付包；QCR / 访问 / 线索成本报告 |

## 16. 团队和工作量

最低配置：

```text
后端工程师：2 人
前端工程师：1 人
测试 / 自动化：1 人
产品 / GEO 研究：1 人
内容与行业专家：兼职
```

如果只有 1～2 名开发，优先完成：

```text
引用证据
指标 V2
问题池和事实库
```

暂缓更多平台、新闻稿 API、复杂归因和多租户商业化。

### 16.1 交付分层与砍项线

以最低配置执行时，且第 3 周 P0 闸门通过，12 周必须交付范围包含：三平台可比较测评、引用证据与状态机、Metrics V2、QCR / Utility 报表、固定问题集、事实库最小版本和人工审核。以下内容也只有在闸门通过后才继续：内容多版本实验、AI 引擎注册中心的第二批平台、自动化归因和新闻稿渠道实验；闸门未通过时按下一段的降级目标执行。

第 3 周的 P0 闸门只检查各主平台回答成功率 >= 90%、`automated_citation_observability_rate >= 80%` 和回答 / 引用证据能否稳定关联；任一未达到，则自动砍掉第二批平台、新闻稿 API、复杂内容实验和用户级归因，12 周目标降为“可审计测评 + 规则型建议 + 渠道级趋势”。`macro-F1 >= 0.80` 属于第 5 周 Judge 校准闸门：若校准不达标，不发布 QCR 业务提升结论，改用规则和人工复核。不得通过压缩测试、删除低分样本或放宽指标定义来维持原排期。

## 17. 最终优先级

```text
P0：修复引用证据链
P0：升级可解释指标
P0：建立稳定测评协议
P1：问题池意图化和事实库
P1：内容版本实验
P1：AI 流量和转化归因
P1：AI 引擎适配层
P2：新闻稿和权威媒体渠道
P2：开放 SDK / MCP / 插件生态
P2：行业版本：医疗、金融、教育、SaaS
```

## 18. 关键决策

1. **先修数据可信度，再扩大平台数量。**
2. **可见度和回答质量分开统计。**
3. **引用证据必须能够回溯到原始回答。**
4. **内容优化必须建立在企业事实库之上。**
5. **所有效果都通过固定问题集和重复采样验证。**
6. **发布渠道按引用价值和转化价值评估，而不是按数量评估。**
7. **不绕过平台风控，不制造虚假内容，不承诺固定排名。**
8. **QCR 是北极星指标，Utility / Factuality 是不可突破的质量护栏。**
9. **无 referrer 且无可审计 token 时只能报告未知或辅助归因，不做平台级确定性结论。**

## 19. 参考资料

- [Google：Optimizing your website for generative AI features](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide)
- [OpenAI：Overview of OpenAI Crawlers](https://platform.openai.com/docs/bots)
- [Perplexity：Perplexity Crawlers](https://docs.perplexity.ai/guides/bots)
- [GEO: Generative Engine Optimization](https://arxiv.org/abs/2311.09735)
- [GEO-Bench：GEO 论文中的评测基准说明](https://arxiv.org/html/2311.09735v3#A2.SS2)
- [C-SEO Bench: Does Conversational SEO Work?](https://arxiv.org/abs/2506.11097)
- [AutoGEO：What Generative Search Engines Like and How to Optimize Web Content Cooperatively](https://proceedings.iclr.cc/paper_files/paper/2026/hash/dd5dfba659a7ec010414de1c1debdeb4-Abstract-Conference.html)
- [GEO-optim/GEO](https://github.com/GEO-optim/GEO)
- [AutoGEO](https://github.com/cxcscmu/AutoGEO)
- [GeoLook](https://github.com/aigclink/geolook)
- [GEORank](https://github.com/yaojingang/GEORank)
- [GEO Optimizer Skill](https://github.com/Auriti-Labs/geo-optimizer-skill)
