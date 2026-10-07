# Research Efficiency Upgrade v0.1

Implementation verdict: **COMPLETE_V0_1_WITH_LIMITED_EFFICIENCY_EVIDENCE**.
管理上下文和确定性工作流回放有明显收益；完整 Codex 开发任务的实际 token、
reasoning 时间与端到端耗时改善尚未建立。没有新机器人实验或科学结论。

## 证据与瓶颈

真实样本是 Console mechanism replay，交付 commit `ffa840d`。父会话时间窗
2026-10-07 22:09:29–23:10:27（Asia/Shanghai），约 **60.96 分钟**。
原始记录本地 SHA 和 ordinal 2047–2801 保存在
[历史提取](benchmarks/console_001/historical_parent_v2.json)。只提交计数与 locator，
不复制原始 prompt、模型 reasoning、外部配置或凭据。

| 历史父任务指标 | 可取得的值 | 限制 |
| --- | ---: | --- |
| 外层 tool calls | 82 | 包括 50 exec、24 browser、8 代理协调；不是 82 shell calls |
| 可解析的嵌套 shell commands | 38 | 一个调用可含多个读/检查；子代理成本不在内 |
| Get-Content 读取引用 | 47 | 31 个不同 locator，16 个重复；是尝试的下限，包含部分读取及失败 locator |
| reasoning 段 | 123 | 不等于 123 个重复语义决策，隐藏推理内容未提取 |
| stage 推断 | context 11 / audit 2 / browser 24 / Git 20 | 按调用文本启发式分类；不是实测阶段耗时 |
| tool 文本输出 | 497,352 字符 | 排除图片二进制，仍包含包装信息；不是 unique prompt token |
| response usage input | 15,535,312 | 重复上下文累计，14,713,472 cached |
| uncached input / output | 821,840 / 70,409 | 父任务 per-response usage 合计；不是整个团队或账单口径 |
| reasoning output | 35,283 | output 的子集，不额外相加 |

1. **入口缺口有实证。** 原任务先搜 memory/仓库与实验目录，再多次读来源、Console
   和 worktree 元数据。旧 AGENTS 尾注仍写 Phase3A.4b，最新源决策已是 4d。
   状态指针、科学决定、可复用检查命令缺少一个可校验入口。
2. **重复读取不是全部无用。** server 6 次、app 5 次、AGENTS 3 次；app/server
   在修订后再读可能必要。v0.1 优化入口与确定性管理，不把所有重复一概删除。
3. **临时验证逻辑可复用。** 原 parent ordinal 2635 临时组合 ConsoleData、61 个
   export hashes、QA 和最终 receipt；新的 check/closeout 提供稳定命令。
   原有 ConsoleData 是好资产，继续复用，不重写第三套 evidence verifier。
4. **browser/Git 是显著调用成本。** 浏览器有修订、reload、视窗、JSON 客户端
   限制检查，不能整体取消。首个 push 到最后 remote/status 检查约 4 分钟，
   包含重复等待与网络诊断。建议一次 bounded push，失败明确 pending；不预测
   网络本身会因 Skill 而变快。
5. **原任务已做 proportionate validation。** 12 builder + 30 server + 8 frontend
   检查，scientific full regression 未跑。普通实现没有被实际跑成完整科学 campaign；
   不能虚构这部分节省。科学实验、render/implementation/QA 的必要工作保留。

## 架构与用法

只有两个 repo-local Skills：

- `g1-research-ops`：状态入口、分级、确定性检查、测量与收口。
- `g1-visual-evidence`：保留 acquisition pose、time/frame、metrics/provenance、
  render-only 与最终浏览器 QA 的具体工作方式。

`AGENTS.md` 只保留短入口与科学约束，Skills 保存方法，`ops/state.json` 保存少量
明确的来源指针与六个 SHA anchors。branch/head 实时从 Git 读取；verdict/blocker
从验证过的 FINAL_AUDIT 提取。检查实验/Console namespace 相对基线的变化，
包含未跟踪文件，发生 drift 则 STALE/UNVERIFIED。不开启自动“最新实验”推断，
不按 mtime 选择，不自动重写指针或决定。状态不是完整历史知识库。

```powershell
.venv/Scripts/python.exe scripts/research_ops.py context
.venv/Scripts/python.exe scripts/research_ops.py plan --kind implementation --paths console/web/app.js
.venv/Scripts/python.exe scripts/research_ops.py check console
```

最后用 `closeout --base BASE --paths TASK_PATHS...` 做 scoped Git 检查。
`--retained-experiment` 另外复用当前 4d 的冻结协议/全部 exports/决定/独立 review
locators，明确标注不是新的 independent audit。没有通用实验 runner、daemon、
provider 调用、额外依赖或未来 Skill 骨架。

当前 Codex 官方机制支持 `.agents/skills` 的 repo discovery 和按需读取 Skill；
[Skills 文档](https://learn.chatgpt.com/docs/build-skills)与
[AGENTS 文档](https://learn.chatgpt.com/docs/agent-configuration/agents-md)已核实。
**会话应从此 repo 启动**；当前根目录 D:/work/mujoco 的会话需要显式读取此 repo
入口，repo-local 不会自动扫描无关 sibling repo。本轮没有改用户配置或全局安装。

Tier 独立于 Git delivery：implementation（Surgical）、mechanism（Experimental）、
claim。后者覆盖新 safety/generalization/held-out/baseline adoption/formal scientific
PASS/FAIL，要求 strict provenance 与独立 evidence/interpretation audit。
显示既有 FAIL 的 UI 仍可属于 implementation。Shared runtime/evaluator bugfix 也
要查受影响契约与 equivalence；unknown paths 要 review。参见
[完整 policy](verification-policy.md)。分类依赖真实 intent，不是权限防火墙。

## 实际 retrospective replay

[三轮交替回放](benchmarks/console_001/management_replay_v2.json)比较同一组管理工作：
Git/状态、科学边界、测试路由、保留源/资产完整性、scoped closeout。
传统组以历史 ordinal 对应的读操作合理重建，执行八个只读命令；Ops 组实际执行
context/plan/check/closeout 四个命令。未重新生成 pose、视频或正式 acquisition。

| 管理回放指标 | 传统重建 | Ops 实测 | 改善 |
| --- | ---: | ---: | ---: |
| shell 启动/命令请求 | 8 | 4 | 50% |
| 三轮 elapsed 中位数 | 2.5094s | 1.0441s | 58.4%，绝对约 1.47s |
| 返回模型的文本 | 109,040 字符 | 4,991 字符 | 95.4% |
| 加上两个 Skill 与新增 AGENTS 成本 | 109,040 字符 | 10,218 字符 | **90.6%** |
| 字符/4 的 token proxy（计入指令） | 27,260 | 2,555 | 约 **24,706** 少输入上下文 token |

传统组向模型暴露约 12 个状态/报告/manifest/QA 文件的原文；Ops 返回四份摘要，
加两个短 Skill 和增量入口。Ops 的 context 内部仍读 state/decision 并验证六个
anchors；完整检查依然读取文件。**没有证明底层 files-read/I/O 减少**，状态
验证还增加了少量 hashes。减少的是模型需要消费的原文和反复决定如何检查。
原任务 47/31/16 的读取数字与这里 12 个原文文件不是同一口径，不直接相减。

两组验证 coverage parity 已实际检查：当前 visual 58 derived / 41 source，原
vertical slice 34 / 13，科学 exports 61，全部原样核对。两组都验证原 QA byte
identity；client JSON navigation limitation 原样保留。没有因新命令而少做 hash。
新的 UI/数据/服务变更仍需实际 browser QA；当前 UI 未变，明确复用旧 receipt。

**不能将 82 calls/61min 与四个管理命令直接比较。** 实现、必要 source-code
阅读、3,226 帧的原 render、50 个原 targeted tests、24 次原 browser 交互和
commit/push/remote 验证都保持在 full-workflow 重建之外，未算成“被优化掉”。
这不是完整 LLM A/B；没有 measured after reasoning token、总 token 或端到端时间。
如果每个独立模型/tool roundtrip 需 10–30s，少四个 roundtrip 的情景收益约
40–120s；充分批处理时可能只有上述约 1.47s。区间是情景估算，不是 benchmark
实测，也不能声称把 61 分钟变成 6 分钟。

## 质量、失败与无收益设计

[验证记录](validation/results.json)：**22 Ops + 42 Console Python + 8 frontend =
72 项通过**，两个 Skill frontmatter 验证通过；scoped diff 无科学目录变更。
Ops 测试涵盖 claim escalation、未知路径、source tamper、browser drift、stale
decision/new untracked namespace、只读 closeout、失败命令与未测量阶段。

- [首次测试失败](validation/first-ops-tests.log)：3 fail / 18 pass。真正的缺口是
  Git status normal 折叠未跟踪父目录，导致新 research namespace 未标 STALE；
  改用限定 science/Console 的 ls-files 查询。另两项是测试断言未归一化 Windows
  path，修正后通过。失败不删除。
- [首次 session 提取](benchmarks/console_001/historical_parent.json)误把 text output
  list 当字符串，得到 0 chars；此指标无效，v2 修正为 497,352 并有 schema test。
  初始 artifact 保留，不能拿 0 当节省。
- [首轮 replay](benchmarks/console_001/management_replay.json)发现 closeout 输出被
  unrelated untracked names 占据；后改为 count/sample 与 task-scoped names，v2
  重测。旧结果保留，不仅挑最佳单轮。
- 不做 mtime-only hash cache：收益未证实，容易降低 byte-integrity。暂保完整
  rehash；进一步加速需安全的 content identity 与清晰失效条件。
- 不自动 browser QA、不做通用 experiment closeout：两者覆盖差异大，v0.1
  只有短 checklist 和当前 retained-schema adapter。Browser wall time、full
  scientific audit runtime 没有新改善数据。
- 遥测 wrapper 有启动/写日志开销；在 phase 边界使用，不包每个微小读取。
  不建立复杂观测平台，未测量阶段输出 null，不能把它们报为零。

## 保留的科研保证与局限

科学 verdict **INCONCLUSIVE**，strict FAIL、阈值、原案例与历史 bytes 都保留；
Phase 3A.5 继续暂停。PPO/optimizer/provider/Jev/Multi-Swarm/new physics/render
均为 0；Language Runtime gate 未改。Console 仍是 observer，状态 playback 与
derived replay 区别、原始 metrics/paired operands、endpoint 与 nearest-frame
区别、negative evidence 和独立 review identity 均保留。

AGENTS 是本轮授权升级的工程入口，历史 source manifest 中记录的旧 AGENTS
hash 不改写。它记录 acquisition 时的身份；不能把新的工程入口伪称为旧字节。
本轮没有复跑历史 scientific numeric audit 或宣称任何新的科学 PASS。

一个真实样本、parent-only usage、合理重建对照、三个交替运行、未绑定新机器/
浏览器环境，无法建立跨任务泛化效率。Pointers 仍需人工授权选择，自动校验
能发现漂移但不自动理解新 verdict。Tier intent 也依赖 agent 正确声明。
本轮开发 Skills/脚本的投入是工程成本，不能从单次 replay 证明已经回本。

v0.2 建议只做：在 3–5 次真实 UI/bugfix/mechanism 任务中自动保留阶段区间与
session usage，验证 amortization；补新任务的真正 matched workflow A/B；只有
出现第二个实际 schema 时才扩展 experiment closeout。不要先扩充 Skills 数量。

最终 Git 状态由交付记录/最终回复提供。到达 v0.1 工程和安全回放验收后停止；
无后续科研阶段或自动执行计划。
