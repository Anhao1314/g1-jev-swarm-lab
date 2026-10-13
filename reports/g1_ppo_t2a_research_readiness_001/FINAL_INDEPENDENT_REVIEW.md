# Final independent freeze review (verbatim)

Reviewer: `/root/t2a_path_audit`, native Codex read-only subagent.

**独立审查结论：`READY_FOR_OWNER_T2A_ACQUISITION`**

完成只读核验，未重跑测试、未修改文件、未启动模型或物理执行。

冻结身份：

- `C_exec`：`81f9fa9c13c167f7163dfb695d419f4be27bb773`
- Git tree：`ba8fae0f3ab29498ced1160fa2ba19b431dd7fcc`
- Source SHA256：`a854a022224c567dd7a25dba04ecfc756a350931d0fc3a20705098c10821f185`
- Readiness SHA256：`1c78628fa49e8cfc535366939cc528abeb8d88b74d1a22ea5d164f7c1c3790b3`
- Protocol SHA256：`1181c673cf34c0886bedd68351ce6ee2baef25999097b7150a590bfba7d2e77c`

实际工作树 clean。相对基线 `ec1ee7ef` 仅三个允许文件发生变化；`comparison.py`、`protocol.json`、历史 T1 watchdog 无差异。独立重算 Source、Readiness、三个源码/测试文件哈希，与冻结材料及最终 LF 字节回执匹配。

最终回执：

- 监督测试 **41/41 PASS**，原始日志 13.22 秒。
- 分类器测试 **65/65 PASS**，原始日志 0.29 秒。
- 两套测试原生退出码均为 0。
- 实际执行源码入口完成 `main → 原 verify → fork Worker → 原 verify → postguard 假执行`。未替换生产 guard。
- 完整入口回执覆盖 177 项来源文件（包含 30 项资产）、21,121 项安装文件及 30 项依赖；Worker 成功退出并完成清理。
- 错误 HEAD、来源、协议、Readiness 和缺少确认 flag 五个负例均拒绝。
- 595 秒截止、600 秒总预算及 5 秒清理余量保持不变。

关键边界已验证：直接 Worker 拒绝、复制旧 Worker flag 无效、Manifest 篡改拒绝、旧目录重放拒绝、超时/崩溃/escaped descendant 清理、清理异常和回执异常不能冒充成功。

**可以进入 Owner 单次采集审批。READY 不是授权。** 冻结材料明确 `acquisition_authorized=false`；PR #29 旧 Readiness 不适用于该执行身份。

结论仅限 WSL/Linux 专用、单线程、无既有子进程的可信串行科研入口。未证明恶意同用户安全、Supervisor 被强制杀死或内核不可中断阻塞下的保证。假执行与非物理测试不证明 PPO 科学收益。

本轮 **MuJoCo steps=0、Policy inference=0、Optimizer updates=0**。保持 `PIPELINE_PASS / LEARNING_GAIN_NOT_PROVEN`，等待新的 Owner 物理采集决定。
