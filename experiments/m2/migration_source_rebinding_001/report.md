# M2.6A Migration Source Rebinding — 非物理工程验收

**PASS_MIGRATION_SOURCE_REBINDING_NONPHYSICAL。仅建立独立迁移来源身份，不授予采集权限。**

旧 PR #21 gate 拒绝迁移路径是其冻结契约的正确行为。本轮在独立命名空间新增门禁，未修改或 monkeypatch 旧 gate、回执、采集器、审计器、控制器和科学协议。历史154/161与159/161失败结果原样保留；新版53/53迁移测试是独立验收，不将原失败改称通过。

## 冻结身份

| 项目 | 身份 |
|---|---|
| 原始基线 | 3082e2b92b5b18171e06295d1c2d09af39f430ac |
| 新迁移执行代码提交 | fb85e13e3ad36d267a991aea1f0972c1205dffd2 |
| 首次真实门禁通过的清单提交 | 693503c37a4bf95d1207261d5ace826c09adf638 |
| 新 Source Manifest SHA-256 | 17be268d950b2799aff72b6042921ce85be9307cea89cafad17c4fd5fedd9ad6 |
| 新 Readiness SHA-256 | ed618a31de837f87aca0b855a21013701f9ac762939c841b371cd911fef1b21e |

最终可执行提交是报告封存后的完整 Draft PR HEAD，单独发布并进行 fresh-process 核验，以避免提交自哈希循环。上表代码和清单字节不会随最终文档提交改变。

## 最小契约

1. 调用者必须提供完整40位执行HEAD和64位Readiness SHA。固定新工作树 D:/webcodex/mujoco-g1/main-codex，核对实际Git顶层、worktree注册、独立gitdir、.git指针和回链、GitHub来源与无alternates的对象库。原2787项Git mode/blob保持不变，脏工作树和额外执行文件拒绝。
2. 在加载不可变PR21标准库helper之前先校验其字节。重新验证原438项来源、91项官方资产、2份XML与28条资源链接、31项旧Readiness绑定。新版520项来源还覆盖完整85文件P1交付、34项历史失败归档、新代码及迁移元数据。三份运行代码绑定Git代码提交；归档中的.py仅为原字节证据，不作为运行代码。
3. 外部Python解释器、41版本及包来源完全保持冻结值，唯一允许的来源变化是g1swarm由旧repair工作树迁至指定新root。新preflight显式将新src置于解析路径首位，并核对真实PathFinder解析结果，不导入g1swarm。旧editable .pth及direct_url保留并绑定哈希。普通任意外部Python进程仍可能沿旧editable指针解析；本契约只约束受控preflight来源选择，不夸大为所有进程的来源保证。
4. 新Readiness逐项继承原六组、预算及2s Hold契约，physics_authorized=false。旧Readiness不能授权新迁移身份；新入口只有preflight，没有acquire/worker或隐藏采集桥接。独立SHA、来源字节与Git pin检查始终保留。

## 实测验收

- 迁移专用离线53/53 PASS：pytest6.41秒，Research Ops包裹6.716089秒，计时口径分开。
- 清单提交693503c的完整真实clean-process CLI PASS：520来源、91资产、41依赖，0模型加载、0physics、0策略推理。
- 同一完整资源条件下，错误40零HEAD明确被拒绝：Current HEAD differs from exact execution HEAD。不是旧origin错误先行遮蔽；正确完整gate已独立通过。
- 53套件覆盖固定root、Git顶层与注册HEAD漂移、真实Windows junction拒绝、外部来源/绑定回执漂移、缺失或旧SHA。内容篡改测试使用真实隔离临时Git文件，验证磁盘字节与固定Git代码字节；临时fixture的成员缩减有明确标注，不宣传为对完整实际工作树的篡改采集。
- 独立早期审查指出worktree注册身份缺口，已在首次代码冻结前修复并增加3项故障测试。开发中46PASS/1FAIL的binding fixture滞后失败保留，只调整新测试fixture。
- 34项历史回执与原外部位置SHA逐项一致，不复制pytest-temp或改写原始科研数据。归档记录的绝对旧路径用于追溯，不作为新授权。
- 独立只读Codex审查 PASS_MIGRATION_SOURCE_REBINDING_ENGINEERING_REVIEW；不代表Owner最终批准。

## 复核入口

在固定新工作树，使用原位外部解释器：

```powershell
& 'D:\work\g1-jev-swarm-lab\.venv\Scripts\python.exe' -B experiments/m2/migration_source_rebinding_001/readiness.py --expected-sha ed618a31de837f87aca0b855a21013701f9ac762939c841b371cd911fef1b21e --execution-head <已审阅的最终完整HEAD>
& 'D:\work\g1-jev-swarm-lab\.venv\Scripts\python.exe' -B -m pytest experiments/m2/migration_source_rebinding_001/test_readiness.py -q -p no:cacheprovider
```

额外核验应使用新回执输出目录，不覆盖本轮日志。归档helper保留旧路径与输入，不能视为迁移执行入口。freeze_sources.py以独占创建生成新清单，不能替换已冻结文件。

## 限制与停止条件

旧PR21 gate及其迁移后的159/161结果不变。原采集器仍使用未改动的旧preflight；本轮没有接入新身份。未来接入采集入口需要单独审查与授权，不能凭本报告启动physics。

外部Python仍在D:/work/g1-jev-swarm-lab/.venv；路径绑定不自动适用于language-codex或其他root。可信串行工程验证不证明TOCTOU或并发原子性、对抗环境安全、机器人动态可靠性或硬件安全。Owner物理授权不存在。M2.4 INCONCLUSIVE、M2.5A有界结果、P1修复、科学协议和Research Ops选择指针均不变。

Draft PR、最终精确HEAD fresh-process回执交付后停止，等待外部独立审查与Owner决定。无physics、策略/provider调用、训练或合并。
