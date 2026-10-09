# M2.6A P1 修复最终独立科研审查

固定 HEAD：3082e2b92b5b18171e06295d1c2d09af39f430ac（用户指定 Draft PR21）。未切换 HEAD、迁移、安装、恢复资产或修改工作树。此次审查不授权物理采集。

**Independent Verdict：P1_SCOPE_PASS_NONPHYSICAL；CURRENT_TARGET_ACQUISITION_BLOCKED。**

未发现本轮四个关注点的残留 P1 或新增科学资格误判。但本工作目录不能通过采集 readiness：91 个官方非版本化资产缺失。不能将旧封存 161/161 当成本环境已通过。M2.6A 真实科研结果仍 UNMEASURED。

## 实际执行的证据

限定三套离线测试共161项：154 PASS、7 FAIL。collector66/66与raw auditor67/67全部PASS；readiness21/28。offline.xml、offline.log和offline_receipt.json保留真实失败。禁用pytest缓存和Python bytecode；basetemp在仓库外。重用既有外部解释器 D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe，不迁移环境；模块路径指向本固定checkout。实际执行中未尝试导入mujoco/torch/onnxruntime，physics与policy inference均0。

7个失败均为本地readiness条件：target environment、wrong execution-head测试在此前资产检查已失败、XML parser因scene.xml缺失，以及4个expected-source-closure/archive测试因缺失来源文件失败。wrong execution-head本次不是在完整实际资源条件下成功复验，不应声称完整target错误HEAD rejection通过。未修测试、改预期或补资产。

check_source.py独立逐项核验438项来源：347项现存文件精确匹配，91项官方资产缺失，0项现存哈希不等。readiness中所有绑定文件哈希一致。Source SHA27c6157625cd5853dfd735040555d024ff004d5b9da194c8827e974afb1fbd48；Readiness SHA7129f1de6fcad8d403814d75c0cb39b270f4b7890b84b62e9b14f029256c74af。local_source_integrity.json给出全部缺失与哈希。显式运行固定HEAD/readiness gate，实际因motion.pt缺失失败；日志current_readiness.log。

142个相关design/blocked/repair文件测试前后哈希无变化；Git状态仍干净。全套物理、策略、训练、live observer等价性未运行。

## 四个问题的独立判断

1. **已确认Hold失败不被后续技术中断洗掉。** audit.py323–364从raw重算，把rolling/path/finite/standing/fall等不可逆违反记入observed_physical_failures；缺后续样本只使completion=TECHNICAL_PARTIAL。最后瞬时速度仅在完整1000步末端评分，避免用中间速度虚构最终失败。acquire.py485起将hold_physical_status与技术完成状态分开；campaign层保留已独立合格的早期反例，不要求之后所有单元完成才能承认负结果。

2. **控制计算异常不被普通物理失败替代。** exception_observer(acquire.py89起)保存原qualified type、operation、cause、traceback、raw捕获情况，并原样抛出。只有simulation.step的SimulationStateError、完成了新增native step且qpos/qvel非有限三者同时满足才归为原生物理非有限。InvalidControlError、compute_torques与_policy_torques错误均技术，ctrl NaN本身不是物理状态非有限证据。Router UNSAFE标签不能独立给物理HaltFAIL。无新native步的counter/action更新必须通过异常raw snapshot绑定；audit.py177–206不伪造一步physics。

3. **独立评分保持。** 三历史control使用完整raw native轨迹与封存历史逐项复现，而非只前缀/collector PASS。Normal Walk/Turn/Stop从状态及command重算，parent label不能授予资格。state difference从与journal绑定的request/terminal qpos/qvel按冻结descriptor计算。控制轴/世界平移旋转不被当新state。条件/pair/routing失效保留raw数值负结果，但排除合格反例、分母与支持资格；后续失效条件不会删除此前有效反例。聚合campaign_score只应消费完整audit_campaign产物，任意手造VALID字典不是科研证据。

4. **未发现新增科学资格误判。** 有违反的不完整Hold保持负事实；无不可逆违反的不完整前缀仍technical/unassessed。condition-new但state-alias的负结果单独报告，不算unseen-state反例。技术异常、未触发、缺失/未运行均不转成物理FAIL或PASS。两个required primary必须满足独立new-state与Halt/Hold，控制和所有计划条件完整才能支持正结论；负反例可在partial completion中保留。

## 独立额外复算和故障注入

independent_probes.py为新写的纯评分调用，不依赖封存PASS：rolling首步1m/s将seed .1的500点均值推至.1018、路径首步.21m、首步fallen分别在后续缺失时仍HOLD_FAILED；单点.15m/s但无全程判据违反保持TECHNICAL_PARTIAL；完整1000步合法合成Hold保持PASS。ctrl NaN加compute_torques RuntimeError、无新增native步明确技术错误。全部实际PASS；independent_probes.json保留类型与来源hash，不能视为物理样本。

实际重跑failure_contrast.py：修前rolling/path违反后中断仅TECHNICAL_PARTIAL，修后HOLD_FAILED+TECHNICAL_PARTIAL；普通合法完整路径未回归。原InvalidControlError误报普通父物理失败的对照修为技术分类。failure_contrast_recomputed.json保留实际输出。

独立子代理额外执行：FakeBackend第1Hold row已rolling违反、第2次state_row抛OSError，run_cell原样抛出并未写完整outcome。这是重要限制：任意observer中断后的负事实恢复依赖已写native/command journals与offline diagnostic，不是adapter outcome总能完整。已有测试实际覆盖缺派生row/截断末行/hardkill diagnostic；条件资格失效后的诊断只能是UNQUALIFIED，不冒充有效反例。若原始可读prefix本身缺失，无法恢复负事实，必须阻止科研资格。

独立子代理实际标准库几何metamorphic计算：worldXY平移(100,-50)、全局yaw1.4rad并同步旋转线速度不产生新descriptor(max noise3.10e-17)；jointRMS .02001rad跨冻结.02rad门槛。代码审查与主suite均无remaining P1。子代理未重复整套161测试；不能重复计数为独立物理replication。

## 采集资格与剩余阻断

**代码P1修复可以接受为非物理candidate；当前固定工作目录不可采集。** 已确认本机缺91资产，实际完整readiness失败；本轮不修。后续只在另外明确授权的准备任务里恢复并校验资源，重新完成固定head/readiness的clean-process preflight；该准备也不等于physics授权。正式采集仍需独立Owner明确绑定exact runnable HEAD、Readiness与冻结一轮六格预算。禁止直接据此次审查启动采集、重试、调参、合并或晋升基线。

未实际执行：本环境完整target PASS、real dynamics observer equivalence、真实控制异常在MuJoCo中的行为、未见条件物理结果、策略hidden memory字节验证、hardware/production安全。不能由离线测试授予这些资格。M2.4 INCONCLUSIVE/M2.5A bounded结论与全部历史失败不变；D011/Language Runtime和其余安全gate不解除。

## 复现命令（仓库外输出）

```powershell
$py='D:/work/g1-jev-swarm-lab/.venv/Scripts/python.exe'
$a='D:/webcodex/mujoco-g1/audit-m26a-3082e2b-20261009'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
& $py -B "$a/run_offline.py" #完整161项；现环境7 readiness FAIL被保留
& $py -B "$a/independent_probes.py"
python -B "$a/check_source.py"
#从固定repository cwd，纯复算：
& $py -B experiments/m2/unseen_halt_hold_p1_repair_001/failure_contrast.py
& $py -B experiments/m2/unseen_halt_hold_p1_repair_001/readiness.py --expected-sha 7129f1de6fcad8d403814d75c0cb39b270f4b7890b84b62e9b14f029256c74af --execution-head 3082e2b92b5b18171e06295d1c2d09af39f430ac
```

run_offline.py的临时输出基目录若已存在，pytest只清理该外部task临时目录；不会写仓库。0physics，0inference，0training。输出是独立derived audit，不提交到PR21，不更改封存结果。

停止原因：P1四项问题已有最小可靠离线证据、来源核验、真实环境失败与独立审查支持明确verdict；已记录阻断，不再扩大检查或准备采集。
