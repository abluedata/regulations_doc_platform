# W5 质量运维验证报告

日期：2026-08-15  
范围：W5-2、W5-4、W5-5、W5-6、W5-7

## 执行摘要

本次补齐后端 fake 依赖集成/容量/观测测试、前端组件与视图测试隔离、Playwright 固定页面夹具、2pp 回归门 CI、三视口截图和决策门归档。自动化门均通过；M-01/M-02、M-06、M-08、M-09、M-10 等需要真实模型或人工试验的数据仍需在正式验收环境采集，不能以合成/机制测试替代。

## 新鲜验证证据

| 验证 | 命令 | 结果 |
| --- | --- | --- |
| 后端质量/评测/引擎/API | `python -m pytest test_quality_operations test_eval_gold_manifest test_eval_metrics test_review_engine test_review_api -q` | 19 passed |
| 前端组件/视图 | `npm test` | 12 files, 32 tests passed |
| 前端类型 | `npm run typecheck` | passed |
| 三视口 E2E | `npm exec playwright test tests/e2e/review-responsive.spec.ts` | 3 passed |
| 回归门 CLI | `python -m backend.eval.regression ... --max-drop-pp 2` | passed，降幅 0pp |

## M-01 至 M-15

| 指标 | 状态 | 本次证据/剩余条件 |
| --- | --- | --- |
| M-01 高风险召回率 >=90% | 待生产实测 | 金标 30 份及分层计算器已锁定；需要真实引擎预测报告 |
| M-02 高风险精确率 >=80% | 待生产实测 | 同 M-01 |
| M-03 规则版本+原文证据 100% | 机制通过 | API/引擎契约测试覆盖版本与 anchor |
| M-04 同六元组 diff=0 | 机制通过 | 引擎快照测试覆盖 seed/model/prompt/eval hash；需正式批次重跑留档 |
| M-05 终态唯一率 100% | 通过 | API SSE 契约断言唯一 complete/done |
| M-06 上传到定稿 20/20 | 待环境实测 | 当前 E2E 覆盖固定控制台夹具；需要启动完整后端依赖执行 20 次干净命名空间 |
| M-07 三视口横向滚动 0 | 通过 | desktop-1440、tablet-1024、mobile-390，3/3 |
| M-08 人工时间下降 >=30% | 待人工试验 | 尚无前后对照计时样本 |
| M-09 校准误差 <=5pp | 待生产实测 | 校准工具已测试；需要真实置信度预测 |
| M-10 complete 覆盖率 100% | 待生产实测 | coverage 工具已测试；需要正式 run payload |
| M-11 回归降幅 <=2pp | 通过 | CI/CLI 阈值为 2pp，严格 `drop > 2pp` 阻断 |
| M-12 XSS 拦截率 100% | 通过 | SafeMarkdown 组件安全用例纳入 32 项前端测试 |
| M-13 UI 原始堆栈 0 | 机制通过 | 错误中间件/API 契约不返回原始异常；需完整故障注入 E2E |
| M-14 审计篡改检出率 100% | 机制通过 | 审计链测试由平台安全套件覆盖；正式验收需归档篡改样本 |
| M-15 单任务 token 成本 | 机制通过 | 指标记录 prompt/completion token、estimated_cost、耗时、错误和死信；真实成本待模型任务采集 |

## 容量与可观测

- `CapacityGovernor` 提供线程安全 FIFO 并发上限、有限排队背压和固定窗口速率限制；超限抛出明确容量错误。
- `ReviewJobRunner` 记录任务耗时、错误和死信；指标注册表支持 token 与估算成本聚合。
- `/api/health/metrics` 只读返回聚合指标，不包含请求、文档、提示词或密钥内容。
- Review API 列表维持 `page >= 1`、`1 <= page_size <= 200` 的服务端约束。

## 截图

- `screenshots/desktop-1440.png`
- `screenshots/tablet-1024.png`
- `screenshots/mobile-390.png`

桌面与移动截图已人工检查：内容非空、主阅读区与审查面板完整，移动端纵向重排，无横向溢出或控件重叠。

## 未关闭风险

业务质量 KPI 与人工效率指标必须使用获授权的真实文档、真实模型和审查人员重新测量。CI 中的 baseline/current 固定报告用于证明回归门执行语义，不能作为 M-01/M-02 的生产达标证据。

