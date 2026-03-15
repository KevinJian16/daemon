# Task Decomposition

## 适用场景
将用户请求拆解为结构化的 Task/Job DAG。

## 输入
用户的自然语言请求或目标描述。

## 执行步骤
1. 识别请求中的独立目标，每个目标对应一个 Task
2. 将每个 Task 拆为可执行的 Job，指定 agent 和 goal
3. 分析 Job 间依赖关系，设置 depends_on
4. 验证 DAG 无环且所有依赖可达
5. 为每个 Step 的 goal 提供足够的上下文，使 agent 无需额外信息即可执行

## Agent 选择指南
- **researcher**: 搜索、分析、信息获取（学术+网页）
- **engineer**: 编码、调试、代码分析
- **writer**: 写作、文档、图表生成、结构化计划
- **reviewer**: 审查、评估、事实核查
- **publisher**: 对外发布（Telegram/GitHub）
- **admin**: 系统诊断、维护

## 质量标准
- 每个 Job 必须是单一明确目标，可由一个 agent 独立完成
- depends_on 必须准确反映数据/逻辑依赖
- Step goal 描述具体（"搜索 X 的 Y 方面" 而非 "搜索 X"）

## 常见失败模式
- Job 粒度过粗，混合多个目标
- 遗漏隐含依赖导致并行执行时数据竞争
- Step goal 过于模糊，agent 不知道具体做什么

## 输出格式
```yaml
tasks:
  - name: ...
    jobs:
      - id: j1
        agent: ...
        goal: ...
        depends_on: []
```
