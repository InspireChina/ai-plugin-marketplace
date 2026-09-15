# 安全策略

## 支持版本

安全修复面向以下已公开预发布版本（2026-09-15 更新）：

| 插件 | 当前支持版本 |
| --- | --- |
| AI SOW | [0.1.0-beta.1](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-v0.1.0-beta.1) |
| AI SOW Lite | [0.1.0-alpha.2](https://github.com/InspireChina/ai-plugin-marketplace/releases/tag/ai-sow-lite-v0.1.0-alpha.2) |

两者均为试用版本，支持与限制分别见各插件 README。不维护首次公开预发布前内部原型的数据迁移或兼容层。

## 报告漏洞

疑似安全问题请使用 GitHub 私密漏洞报告。公共 Issue 中不得包含漏洞利用细节、凭据、
客户数据或私有仓库信息。报告应包括受影响版本、影响、最小复现步骤和建议的缓解措施。

不会造成安全或隐私风险的普通缺陷可以使用 GitHub Issues。维护者会确认私密报告、开展
调查、在适当情况下协调修复与披露，并按报告者意愿公开致谢。

AI SOW 工作流会处理来自输入来源和客户环境的衍生数据。使用前请检查项目的
`.gitignore` 和共享策略；不得假定生成的工作簿、`.ai-sow/` 或 `.ai-sow-lite/` 项目数据适合公开发布。
