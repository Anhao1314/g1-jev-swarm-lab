# g1-fast-fix Skill v0.1 — 有界验收

**PASS_FAST_FIX_SKILL_V01_BOUNDED_NONPHYSICAL。**

基线PR23 HEAD1dbf67beb7edc8dcd6e8e22d6ffff16be43ae571，独立工作树D:/webcodex/mujoco-g1/fast-fix，分支ops/g1-fast-fix-v01。产品仅为一个repo-local SKILL.md及AGENTS入口，没有新增运行脚本、调度器、依赖或Agent Runtime。P0是交付优先级，不是降低权限/科学门禁。

Skill只承接明确R0/R1的小修复；语义上涉及P1/R2、科学判据、历史冻结、安全/执行权限时退出，即使路径路由较低。复用现有context/plan/reuse/run/closeout；只有已覆盖完整输入与相同实际调用的成功unit可复用。最新失败或pending不回退旧PASS。5分钟检查点/8分钟交付或阻断都是软预算，不能中断必要检查或虚称完成。满足预期结果和必要验证立即停止，不做相邻重构或额外子代理。

## 最小验证

- skill-creator quick_validate：合法frontmatter/名称，exit0；这不是行为证明。
- 原有ResearchOps针对性14/14检查通过：声明的claim升级、P1与final身份路线、precheck/spawn失败留存、中断pending阻止旧PASS。没有改工具代码或测试，也没有跑完整Ops/Console/科研回归；无需复制官方模型资产到本工作树。
- 一名独立前向检查者读取Skill一次：A实际在新临时目录只改拼写并检查字节；B～G仅判定。R0/R1接受、P1/阈值退出、失败不能复用、预算不放弃验证、完成不扩展等7情景符合约束。未再读context/历史、未执行第二轮测试或额外代理。
- 临时目录父路径初次不存在导致守卫停止且无写入；授权范围澄清后创建新临时子目录完成A。该setup结果保留在forward_check.json，不改写为首次顺利完成。

这是一个显式调用的有界前向检查，B的真实代码修复/客户端自动选择并未实测。Skill是模型指引，不是机械授权执行器；repo-local发现取决于客户端从正确仓库加载，可通过AGENTS或明确$g1-fast-fix访问。原严格协议与Owner物理门禁优先。

效率收益未测；不复用旧效率报告数字宣称该Skill节省时间/tokens。本轮无benchmark、physics、策略/provider调用、训练、冻结内容修改或合并。

## 复核入口与停止

实现：.agents/skills/g1-fast-fix/SKILL.md；入口：AGENTS.md。证据：validation.json、forward_check.json、receipts/与integrity.json。测试来源属于指定基线，无新测试框架。当前context38/38，原ops/state.json与科学决定不变。

原PR23修复、M2.6A及历史证据逐字节保留；新检查只首次封存小回执，没有复制历史bundle。独立Draft PR推送后立即停止，等待后续独立真实效率对照；不自动进入科研/执行阶段。
