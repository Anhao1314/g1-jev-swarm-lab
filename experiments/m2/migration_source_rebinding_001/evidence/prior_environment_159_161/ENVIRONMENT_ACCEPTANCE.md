# M2.6A 新工作区非物理环境验收 — 2026-10-09

**Verdict: BLOCKED_FROZEN_ABSOLUTE_SOURCE_ORIGIN_AFTER_ASSET_RESTORATION。** 官方资产阻断已消除；冻结绝对源码路径仍阻断最终环境验收，不能宣称161/161或新工作区preflight PASS。

## 执行身份

- 工作树：`D:\webcodex\mujoco-g1\main-codex`
- HEAD：`3082e2b92b5b18171e06295d1c2d09af39f430ac`
- Readiness SHA-256：`7129f1de6fcad8d403814d75c0cb39b270f4b7890b84b62e9b14f029256c74af`
- Source Manifest SHA-256：`27c6157625cd5853dfd735040555d024ff004d5b9da194c8827e974afb1fbd48`

## 资产恢复与来源

使用冻结readiness.py原有 `--restore-from D:\work\g1-m26a-p1-repair` 模式。它先验证全部来源及已有目标，再以 xb 独占创建恢复，仅91项白名单文件；copied=91、already_present=0。总58,704,665字节。91/91完整SHA及逐文件路径/字节数在asset_restore.json、full-source-assets-dependencies.json。

完整438项来源逐项SHA匹配：223 Git原始字节、124明确Windows CRLF字节、91官方资产，保持域区别。31项Readiness绑定、84项补充文件也全部匹配；2份MJCF/28项资源链接只做XML解析，无模型编译。

41项依赖版本及解释器匹配冻结回执。没有复制/安装venv，借用明确冻结的旧解释器 D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe。新目录仍依赖该原位解释器，不代表自包含环境。

## 真实离线回归

一轮三套冻结测试：159 PASS / 2 FAIL，共161；collector66/66、raw auditor67/67、readiness26/28。原始pytest为20.74s，Research Ops包裹测量21.1964813s；两者不是同一计时口径。

失败为test_target_environment_no_imports与test_wrong_execution_head_rejected。原154/161失败回执15个顶层证据文件逐项前后hash相同，未重写；其pytest-temp原位保留。新offline.xml、offline_receipt.json及完整日志独立封存。三份冻结设计/工程/修复目录142文件前后哈希无变化。

## Clean-process与HEAD拒绝

固定正确HEAD+固定Readiness真实CLI预检退出1：Target dependency/origin receipt drift。

全91资产条件下，错误HEAD=40个0、固定Readiness的真实CLI也退出1，同一来源错误。test_wrong_execution_head_rejected仍FAIL，因先经过来源门槛、未到HEAD门槛；**不得把拒绝原因偷换为错误HEAD验证通过**。

唯一依赖回执差异：g1swarm源码路径由冻结 D:/work/g1-m26a-p1-repair/src/g1swarm/__init__.py 变为当前 D:/webcodex/mujoco-g1/main-codex/src/g1swarm/__init__.py。readiness.py:315对完整来源回执相等检查，而HEAD检查在:321–322。独立审查及实际失败吻合。没有修改dependencies.json、检查函数或测试，没有用symlink/junction/mock绕过。

## 状态与边界

Git tracked/untracked均0，HEAD不变；third_party恢复资产为既有ignored域。本次报告在仓库外，无commit、push或merge。Research Ops CURRENT38/38、选择指针不变；M2.4 INCONCLUSIVE、M2.5A限定结论及M2.6A无新物理结果均保持。

旧资产/解释器、artifacts、历史数据与未跟踪实验数据原位保留，只复制91项明确授权官方资源。无MuJoCo physics、策略推理、provider调用、模型加载、训练或实机控制。测试主进程拒绝mujoco/torch/onnxruntime导入，尝试数0；真实preflight以标准库元数据解析，不能以它的拒绝推断物理资格。

## 剩余阻断与停止理由

唯一已确认剩余工程阻断是冻结源码绝对路径不适配迁移位置。解除需要另行授权迁移来源绑定方案、独立审查及新的冻结身份；本轮不具备修改该冻结回执的权限，故原样保留BLOCKED并停止。外部独立审查/最终Owner授权仍是任何未来采集的必要条件，本报告不授予物理权限。

## 复核入口

- `asset_restore.json`：原机制恢复结果与91项完整哈希。
- `full-source-assets-dependencies.json`：438来源验证、41版本及唯一来源差异。
- `offline.xml` / `offline_receipt.json`：实际161个case，保留2FAIL。
- `m26a-migrated-environment-*.log`：恢复、测试、完整核验、正确/错误HEAD原始日志。
- `prior_failure_receipt_hashes.json`：原失败证据保护。
- `acceptance_receipt.json` / `independent_environment_review.md` / `research_ops_telemetry.json`：机器回执、独立审查与阶段记录。
- 仓库外 `run_offline.py`：带导入限制的实际离线测试复算入口，复用时须用新输出目录，禁止覆盖本轮回执。
