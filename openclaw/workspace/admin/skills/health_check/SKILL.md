# Health Check

## 适用场景
诊断系统各组件运行状态，发现潜在故障。

## 输入
可选：指定检查范围（all / api / worker / infra）。

## 执行步骤
1. 检查 API 进程：HTTP 端点可达性和响应时间
2. 检查 Worker 进程：Temporal worker 注册状态
3. 检查基础设施：PostgreSQL / MinIO / Langfuse 连通性
4. 检查资源：磁盘空间、内存使用
5. 汇总异常项并给出修复建议

## 质量标准
- 每个组件必须有明确的 healthy/degraded/down 状态
- 响应时间超阈值标为 degraded

## 常见失败模式
- 只检查端口开放，未验证服务实际响应
- 遗漏检查 Temporal namespace 状态

## 输出格式
```
系统状态: HEALTHY / DEGRADED / DOWN
[healthy/degraded/down] 组件名 | 详情
```
