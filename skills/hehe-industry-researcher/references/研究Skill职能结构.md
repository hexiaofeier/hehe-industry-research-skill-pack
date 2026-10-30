# 研究Skill职能结构

公开组合由 `hehe-industry-researcher`、13 个研究专项及 2 个可选交付增强 Skill 组成。研究辅助能力按当前环境选用。

1. **研究辅助能力**  
负责搜索方向设计、公开信息采集、材料审核、报告整合和交付检查。使用宿主当前可用的搜索、浏览器、数据库、MCP/API、文件解析或已安装 Skill；没有专用 Skill 时，由 `hehe-industry-researcher` 按各流程中的后备规则自行完成。

2. **研究分析类 Skill** 
共 13 个专项 Skill，每个 Skill 负责一个核心分析任务，是行业研究技能包的核心能力。包含市场规模 `hehe-market-sizing`、产业链 `hehe-industry-chain-map`、商业模式 `hehe-business-model`、竞争格局 `hehe-competitive-landscape`、PEST 外部环境 `hehe-pest-analysis`、趋势分析 `hehe-trend-analysis`、驱动力分析 `hehe-industry-drivers`、行业痛点 `hehe-industry-pain-points`、公司画像 `hehe-company-profile`、公司财务分析 `hehe-financial-analysis`、治理与资本配置 `hehe-governance-capital-allocation`、估值分析 `hehe-valuation-analysis` 和投资逻辑 `hehe-investment-logic`，均由盒子原创。
用户可以单独安装和直接调用任一专项 Skill，直接调用时由该专项独立完成，不因 `hehe-industry-researcher` 已安装而重新路由。用户明确调用 `hehe-industry-researcher` 统筹时，才由它派发任务卡。完整公开组合提供总入口与 13 个专项，并可捆绑两个交付增强 Skill；两者不是运行前提。仅缺少交付增强 Skill 不影响报告完整性；应调用的研究专项缺失时，仍按实际覆盖交付单项或有限范围研究。

3. **报告交付 Skill**
`hehe-report-writing` 安装后默认润色专项及综合报告，未安装时由研究方按原流程定稿；其独立文本撰写模块不用于重写已成型研究报告。综合报告默认交付 HTML，有 `hehe-report-presentation` 则使用它并按最终交付流程提供形式选择，无则使用基础侧栏 HTML；单独专项在安装了呈现 Skill 时主动询问是否增加 HTML／PPT。两者均可独立使用，缺少任何一项不阻塞研究与交付。

## 研究辅助能力说明

- **搜索方向设计：** 有对应能力时调用；没有时根据研究问题自行设计关键词和需收集字段。
- **公开信息采集：** 使用当前可用的网页搜索、浏览器、数据库、MCP/API、文件提取或已安装的公开信息采集 Skill，不限定工具组合。
- **材料审核：** 有专用审核能力时调用；没有时完成原文、主体、时间、地域、定义口径、单位分母、重复和冲突等最低检查。
- **报告整合与交付检查：** `hehe-industry-researcher` 自行汇总专项报告；`hehe-report-writing` 安装后用于润色，不另走独立文本撰写模块。有 `baojie` 则执行成稿核对，核对事实、计算、引用、推理及报告与附件的一致性；未安装时由总入口自行检查，修改后复查受影响内容。

研究辅助能力均为可选增强，不是 `hehe-industry-researcher` 或专项 Skill的启动许可证。

## 研究分析类 Skill 调用规则说明

研究分析类 Skill 是 `hehe-industry-researcher` 组合的核心能力，包括市场规模、产业链、商业模式、竞争格局、PEST 外部环境、趋势、驱动力、痛点、公司画像、财务分析、治理与资本配置、估值分析和投资逻辑等。共覆盖 13 个专项 Skill，每个 Skill 负责一个专项能力。

- 行业研究默认调用 8 项行业研究 Skill：`hehe-market-sizing`、`hehe-industry-chain-map`、`hehe-business-model`、`hehe-competitive-landscape`、`hehe-pest-analysis`、`hehe-trend-analysis`、`hehe-industry-drivers` 和 `hehe-industry-pain-points`。研究目的包含行业投资机会、风险收益或退出条件时，另外调用 `hehe-investment-logic`；不包含投资问题时不调用。
- 企业研究默认调用5项专项分析 Skill：`hehe-business-model`、`hehe-competitive-landscape`、`hehe-company-profile`、`hehe-financial-analysis`、`hehe-governance-capital-allocation`。其他专项 Skill 视条件和需求进行调用。
- 某项能力与已经确认的研究目的明确无关时，可以说明理由后不调用，不为凑齐九项生成无关分析。
- 默认调用或条件调用的专项 Skill 若未安装，其他可执行专项仍可继续；缺失项不制作任务卡。缺失项会影响研究完整性时，最终成果必须标为有限范围报告；与本题无关而不调用的模块不算能力缺口。

用户进行行业研究或企业研究，可调用的专项 Skill 可参考下表；用户也可以单独调用专项Skill，直接回答某个明确问题，不受表中状态限制。

| 专项 Skill | 行业研究 | 企业研究 | 条件调用的判断 | 核心职责 |
|---|---|---|---|---|
| `hehe-market-sizing` | 默认调用 | 条件调用 | 企业研究涉及市场空间、增长上限、份额或可获得市场 | 市场边界、规模、情景和敏感性 |
| `hehe-industry-chain-map` | 默认调用 | 条件调用 | 企业研究涉及产业位置、上下游依赖、渠道、瓶颈或责任关系 | 产业结构、节点、四流与瓶颈 |
| `hehe-business-model` | 默认调用 | 默认调用 | — | 行业典型模式或企业经营闭环 |
| `hehe-competitive-landscape` | 默认调用 | 默认调用 | — | 行业格局或企业竞争位置 |
| `hehe-pest-analysis` | 默认调用 | 条件调用 | 需要分析目标企业所在行业的外部环境，或出海业务的目标市场环境 | 行业 P/E/S/T 因素、企业类型影响及国际关系 |
| `hehe-trend-analysis` | 默认调用 | 条件调用 | 技术、需求、商业化或行业结构变化会影响企业 | 趋势阶段、信号与证伪 |
| `hehe-industry-drivers` | 默认调用 | 条件调用 | 需要解释企业增长所依赖的行业驱动和约束 | 行业变化的驱动机制 |
| `hehe-industry-pain-points` | 默认调用 | 条件调用 | 需要判断企业解决了谁的什么损失，以及问题是否真实 | 行业角色承担的现实损失 |
| `hehe-company-profile` | 本阶段不调用 | 默认调用 | 行业研究结束后如进入代表企业研究，再在企业研究阶段调用 | 企业主体、业务和经营画像 |
| `hehe-financial-analysis` | 本阶段不调用 | 默认调用 | — | 财务、现金和资本效率 |
| `hehe-governance-capital-allocation` | 本阶段不调用 | 默认调用 | — | 治理与资本配置 |
| `hehe-valuation-analysis` | 本阶段不调用 | 条件调用 | 商业尽调、融资、并购、IPO 准备，或用户要求估值、价格、交易与投资回报判断 | 企业价值区间与隐含预期 |
| `hehe-investment-logic` | 条件调用 | 条件调用 | 研究目的包含投资机会、投资逻辑、风险收益或退出条件 | 条件化投资逻辑和退出条件 |

- “默认调用”适用于行业研究或企业研究。
- “条件调用”在表中条件成立时启用。
- “本阶段不调用”表示该能力留到另一研究阶段。

以上状态只决定是否启用，不规定调用专项 Skill 的固定先后顺序。
