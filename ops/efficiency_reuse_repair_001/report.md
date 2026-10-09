# PR #23 两项测试复用完整性修复

**PASS_PR23_TWO_REVIEW_FIXES；59/59非物理测试通过。保持Draft，等待外部复核，不合并。**

基线457656d8037e4bd9884a4d520f6d10f06f42c8c4。先读取GitHub review5471746535（review_reference.json）。只修调用身份与最新失败记录；旧效率报告、指标、原始失败和科研冻结不变，没有重跑效率benchmark。

## 1. 实际调用身份

Reusable run显式接受nonsecret_test_invocation_v1规格文件，必须nonsecret=true、literal argv列表、绝对可执行文件。规格argv必须与真正提交subprocess的命令完全一致。身份绑定完整argv（选择器/参数）、执行cwd、解析可执行文件路径及字节SHA；回执只保留身份SHA和schema，不记录raw argv。

Reuse必须提供期望规格并重算同一身份。旧回执没有身份、缺规格、改变命令/selector/flags、隐式PATH或可执行文件变化都不可复用。规格路径和JSON排版不是命令身份。未经执行的预期规格不能替代run实际命令的一致性检查。

Credential-free由调用者明确声明，工具不自动识别秘密；禁止对含凭证的命令开启该复用规格。普通run仍可不提供规格，但其结果不可复用。协议/独立审查/final-HEAD门禁仍强制新验证。

## 2. 最新失败尝试

在任何调用验证、输入绑定或进程启动前，先append pending attempt。可记录的预检查/启动错误追加TECHNICAL_NO_RUN，明确command_started=false、command_exit_code=null、shell_commands=0，并保留错误阶段与类型。实际命令退出码与包装完整性结果分别记录，post-binding故障也不丢失。

中断来不及finalize时，pending行仍是latest，从而拒绝旧PASS回退。Summary不将start/complete计为两次命令；单独列incomplete_attempts。流程继续限定可信串行，并不提供并发原子性。

## 真实验证

最终59/59PASS（原45检查+14新增故障检查），pytest5.14s、包裹5.5691686s。初次58/58PASS也保留；补充绝对exe歧义检查后进行最终59检查，没有benchmark/physics或其他科研回归。

新增案例包括同标签/同文件/同环境下改命令、selector、flags；真实pytest从test_one改test_two不能复用；缺身份与旧回执拒绝；缺绑定文件、重复绑定、未知exe、实际命令与声明不同、空命令均成为最新失败。恢复文件后只能证明旧PASS本来有效，latest失败仍阻止复用。模拟KeyboardInterrupt保留pending并统计为未完成。

独立只读代理ops_efficiency_audit检查本轮两项delta与原始测试日志，给出PASS_PR23_TWO_REVIEW_FIXES；没有重复测试/context或扩大审计。

## 留存与限制

旧ops/efficiency_001目录和科学记录逐字节保留；新receipt首次封存在本目录，故障日志不覆盖历史。review原意见保持原状。M2.6A main-codex保持HEAD44d7a664，科学来源绑定、P1修复、Owner物理授权及ops/state.json均未修改。

原性能数据属于原HEAD/API，新规格增加了身份校验，未重新测收益；历史benchmark脚本须在原固定版本使用。旧unit回执fail closed，不能以原45PASS或旧label强行升级。

依然要求调用者声明完整相关文件/配置/测试闭包和无秘密的调用。元数据环境匹配不等于全包字节审计，隐藏运行时输入仍需Owner判断。无法解析有效任务身份或无法追加journal时必须停止，不能沿用旧PASS；此工具不保证不可写存储中仍能封存记录，不是生产权限/并发防御。

本轮无physics、模型加载、策略/provider调用、训练或科研阈值变更。完成push、更新现有Draft PR的修复记录后停止，等待再次独立审查。
