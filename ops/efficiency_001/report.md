# Research Ops 轻量效率优化验收

**PASS_BOUNDED_NONPHYSICAL_EFFICIENCY_WORKFLOW。45/45测试通过，独立只读工程审查通过。**

基线为PR #22 HEAD44d7a664e9d9ecca57661e98ea15200a216e5517。在独立ops-efficiency工作树开发，M2.6A固定main-codex仍保持该HEAD与clean状态。没有更改ops/state.json、历史科学证据、冻结协议、采集器或控制器；无physics、策略/provider调用或训练。P1/正式科学声明继续独立审查，Owner物理授权保持独立。

## 最小改进

- R0文档/R1实现/R2科学、未知范围、P1或最终身份分级；--p1与--final-head增加要求，不降低现有tier。
- 一位owner执行检查，handoff共享简短上下文；仅在HEAD、输入、环境、锚点或范围变化时重开。独立审查仍自行检查必要源码/证据。本任务只使用1名只读审查子代理，无重复测试/context。
- run --bindings记录完整声明的代码/配置/测试字节和实时解释器、版本、editable metadata，前后相同且成功才可复用；reuse取最新匹配记录，失败不能被早期PASS隐藏。protocol/independent/final-head门禁永不由此复用。覆盖不确定则重跑；这仍是辅助管理工具，不是对抗环境权限系统。
- 已提交证据以完整commit/path/blob/SHA增量引用；新原始失败先封存一次。Git blob与Windows工作字节明确区分，LFS pointer拒绝，原始科研闭包不改。历史复制件不删除。
- begin/end测实际窗口，晚启动标为observed-window，时钟/主机不一致保持null；阶段命令合计不当作端到端时间。可导入实际sanitized session统计，缺失tokens/child costs不填0。本轮全任务与token收益未测。

## 可比实测

三次同机非物理管理回放，原始样本见benchmark.json。不是三名真实Agent或完整科研任务。

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| 3方管理回放context/handoff函数中位耗时 | 0.7417s | 0.2794s |
| 指引+交接文本序列化字符 | 54,939 | 22,375 |
| 同一七用例unit检查的两次未变请求，中位总耗时 | 1.3914s | 0.8880s |
| 每组真实检查启动数 | 2 | 1 + 1次绑定复核 |
| 30个已封存重复Git blob的逻辑载荷/引用JSON | 234,901 bytes | 18,340 bytes |

context计时不包含预载指引、LLM或网络成本；instruction_read_requests字段表示模拟角色的指引载荷份数，不是观测到的文件I/O。文本数字对应测量时指引，交付随后追加README命令示例，不能将其当作最终文档体积或token节省。

九次七用例检查仅用于这个匹配测量，顺序交替降低单向热缓存影响；3个小样本不证明稳定延迟分布或未来所有任务的收益。Git已经去重blob，引用比较不是Git实际磁盘节省。不能凭历史测试命令数量认定重复检查没有必要。

## 历史与负面回执

PR19～22四个冻结命名空间共197项Git文件，30组重复blob逻辑对。PR20/21/22已有测试命令计时分别12次37.8115s、16次162.989s、1次6.7161s；这些不是全任务耗时。历史reasoning/tokens缺失。historical_references.json绑定原Git回执，无再次拷贝整个历史bundle。

本轮首次39检查为36PASS/3FAIL：隔离工作树缺官方资产，保持失败回执，按原非覆盖机制恢复91项哈希匹配资源后39PASS。之后新增删除绑定输入故障测试暴露test ROOT/default参数位置问题，44PASS/1FAIL回执保留；修正显式ROOT后最终45PASS，pytest4.37s、包裹4.7715365s。没有修改任何科学标准或旧测试预期。

独立审查发现一个真实漏记失败边界：测试删除绑定文件后，后置哈希异常可能阻止写最新记录。修复为保留退出码/原日志/绑定错误，再判定不可复用；故障注入证明恢复文件后仍不复用旧PASS。审查者未重复运行测试/context。

本轮早期observed窗口是开发中的旧字段，无法确认clock continuity，耗时null。最终观测窗口498.328s，仅覆盖14:33:39至14:41:57，不含前期开发和之后Git发布。全任务耗时收益、tokens及Agent成本收益都未测，不估算为事实。

## 复核与停止

实现：scripts/research_ops.py及小型research_ops_efficiency.py；说明：AGENTS、Research Ops Skill、verification-policy、README；测试：tests/test_research_ops.py及新增效率测试；benchmark.py可在新回执目录重新执行，但本轮不再测试。

raw日志与绑定：receipts/、benchmark.json、historical_references.json、integrity.json。提供参考/复用资格不自动运行其他命令，不替代独立科研审查、不授予Owner权限。

普通Docs最后修改不重跑已通过的实现测试。完成Git封存与独立Draft交付后停止，不扩大成Agent Runtime或新科研阶段。
