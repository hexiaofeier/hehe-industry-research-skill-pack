# 盒盒行业研究技能包

**Hehe Industry Research Skill Pack** 是一组面向公开信息研究的中文 Skill。首批版本由 `hehe-industry-researcher` 统筹 13 个专项 Skill，覆盖完整行业研究、企业研究和单独专项研究。

所有本包分析 Skill 使用 `hehe-` 命名空间，便于识别来源。啥好用（`sha-hao-yong`）、探子（`tanzi`）和搜查令（`sou-cha-ling`）保留原名；它们不属于本仓库首批安装内容，也不是本包的运行前提。

## 包含的 Skill

| 类型 | Skill | 核心任务 |
|---|---|---|
| 总路由 | `hehe-industry-researcher` | 研究开题、搜索与审核组织、专项路由、完整 Markdown 报告整合 |
| 专项 Skill | `hehe-market-sizing` | 市场规模、情景与敏感性 |
| 专项 Skill | `hehe-industry-chain-map` | 产业链、四流、瓶颈与结构图 |
| 专项 Skill | `hehe-business-model` | 商业模式与经营闭环 |
| 专项 Skill | `hehe-competitive-landscape` | 竞争格局、企业比较与标的位置 |
| 专项 Skill | `hehe-pest-analysis` | PEST 外部环境及影响传导 |
| 专项 Skill | `hehe-trend-analysis` | 趋势阶段、信号与证伪 |
| 专项 Skill | `hehe-industry-drivers` | 驱动机制、约束与持续性 |
| 专项 Skill | `hehe-industry-pain-points` | 角色损失、痛点机制与机会边界 |
| 专项 Skill | `hehe-company-profile` | 公司主体、业务与经营画像 |
| 专项 Skill | `hehe-financial-analysis` | 完整或有限披露财务分析 |
| 专项 Skill | `hehe-governance-capital-allocation` | 治理机制与资本配置质量 |
| 专项 Skill | `hehe-valuation-analysis` | 上市、非上市及商业尽调估值 |
| 专项 Skill | `hehe-investment-logic` | 条件化投资逻辑、风险与退出条件 |

## 安装与使用

完整行业或企业研究请同时安装 `skills/` 下全部 14 个 Skill，并由 `hehe-industry-researcher` 统筹；运行时按研究问题选择适用专项，不机械生成无关章节。

用户直接调用任一专项 Skill 时，由该专项独立执行，不因总入口已安装而重新路由。部分安装只能交付已安装专项或明确标注的有限范围研究，不能称为完整行业或企业研究。

把需要的 Skill 目录复制到所用 Agent 的 Skills 目录即可。不同宿主的 Skills 目录和加载方式不同，请遵循该宿主的安装说明；本仓库不要求固定的本地路径、私有插件或付费服务。

## 工具与证据边界

研究可使用宿主当前可用的网页搜索、浏览器、数据库、MCP/API、文件解析或公开信息采集能力。没有专用搜索或审核 Skill 时，按各 Skill 内的后备规则自行完成关键词设计、原文取得和最低材料核验。

市场规模、财务分析和估值在触发实际计算时默认需要带公式的 Excel 附件。可使用任何能创建、保存并重算 `.xlsx` 的工具；环境不具备该能力时，应交付 Markdown、参数、公式和结果，并把工作簿标为待生成，不能声称完成了公式模型。

## 交付原则

- Markdown 主报告是所有专项的基础交付物，首个正文章节为核心摘要。
- Excel、图源、结构数据或其他附件只按专项规则和实际任务触发。
- 结论区分事实、计算、推断、情境和待核实项，关键来源可追溯。
- 缺少会影响完整性的专项或材料时，交付名称、摘要和正文明确写成有限范围。

## 校验

在仓库根目录运行：

```bash
python scripts/validate_release.py
```

校验覆盖 Skill 数量与名称、总路由完整包合同、包内 Markdown 链接、交付模板结构、本地路径与私有能力泄漏，以及缓存和维护文件排除。

## 许可

本项目采用 [MIT License](LICENSE)。
