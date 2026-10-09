# 独立只读环境阻断审查

独立代理 new_workspace_environment_audit（未参与恢复或源码修改）确认：原冻结解释器、41项版本均匹配；唯一不同的依赖字段是 module_origins_without_import 中的 g1swarm 绝对路径。

readiness.py:203 固定原解释器，:215–217 计算当前root源码路径，:315 要求完整回执相等；:321–322 才检查execution HEAD。旧路径 D:/work/g1-m26a-p1-repair/src/g1swarm/__init__.py 与新路径 D:/webcodex/mujoco-g1/main-codex/src/g1swarm/__init__.py 不同，不能通过恢复模型资产解决。独立stdlib/metadata探针已确认此差异，无simulator/policy导入。恢复后的真实159/161与两个gate失败证实这一阻断。

P1修复的原有科学/工程审查结论不在本轮重写。禁止修改冻结metadata、mock gate或利用路径alias制造PASS。本轮应封存BLOCKED并停止。
