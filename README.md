# 回路制作室

回路制作室让运营团队把一个活动创意做成可试玩的小游戏，再用正式对局判断下一版该改什么。团队负责选方向、试玩验收和批准发布。玩家打开分享链接即可游玩。小游戏、活动入口和实验共用同一套开局、完局和版本口径。

本仓库交付给一个内部制作团队，在阿里云轻量应用服务器上对外提供试玩。制作台通过 SSH 隧道访问。模型、图片、审批和运营数据都由团队管理。适用客户和试点指标见 [试点说明](docs/PILOT.md)。

[v1 版本说明](docs/V1.md) · [七图工程验收](docs/ACCEPTANCE.md) · [阿里云部署](docs/RUNBOOK.md)

## 本地运行

在项目根目录使用 Python 3.12。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 7860
```

打开[本机制作台](http://127.0.0.1:7860/)或[试玩《潮汐信标》](http://127.0.0.1:7860/sample)。这款灯阵解谜有三章十二关，依次引入四邻联动、跨海缆线和锁站。另一款横版[《山间邮局》](http://127.0.0.1:7860/sample?game=post)有十二趟邮车，逐步加入左右转寄和限时分拣。两款都可离线试玩。《港湾引航》保留了三关联调时实际发布的版本。[试玩《港湾引航》](http://127.0.0.1:7860/sample?game=harbor)

新项目需要在服务器环境或本地 `.env` 中设置至少一个 `ZAI_1_TOKEN`、`ZAI_2_TOKEN`、`ZAI_EXTRA_TOKEN`。文本和调研使用 AgentScope 2.0.12、`glm-5.4` 和 Responses 协议。美术使用独立网关的 `STUDIO_ART_API_KEY` 和 `gpt-image-2`。无生图凭据时默认使用本地绘制。配置项见 [.env.example](.env.example)。

## 从创意到经营验证

1. 团队选定一个北极星指标，写明目标玩家、创意和行动边界。调研角色查找参考图，团队选图后进入逐图分析和选方向。
2. 制作人组织策划、美术和关卡设计。新项目通常规划 12–18 关，团队也可指定 3–24 关。方案经人确认后，关卡程序员先编写棋盘、机关或事件序列，游戏程序员拿着真实关卡实现操作与反馈。构建器逐关回放，独立评审检查设计兑现情况，团队可直接选择任意关试玩。
3. 团队分享玩家地址或按渠道生成的活动入口。正式事件保存游戏版本、构建、关卡和回放。样片和验收试玩与正式报表分别计数。
4. 存量改版由四位专家独立首评，随后质询、答复和复核。主持人收敛成一条可执行提案或补证清单。新游立项先确认约束和已知死路，再比较候选玩法。人审批准的改版才能进入生产与 A/B 实验。
5. 到期结算对照实际交付、预注册目标、样本和外部变化。运营可以追溯一条建议依据的证据、实际修改的参数和上线后的结果。样本不足时保留未验证状态。

开发从 [studio/application/](studio/application/) 开始。这里按角色、流程编排、记忆、提示词、工具和业务用例分成六个目录。修改美术师、增加角色及追踪一个任务的示例见 [代码目录与阅读顺序](docs/ARCHITECTURE.md#代码目录)。七张原图的逐章核对和反例见 [工程验收](docs/ACCEPTANCE.md)。

两款章节样片的设计、关卡与程序分别在 [examples/tidal-beacon](examples/tidal-beacon/) 和 [examples/mountain-post](examples/mountain-post/)。修改后运行 `.venv/bin/python -m scripts.build_sample`，即可用正式构建器重新生成内置样片。

## 阿里云部署

服务器使用 x86_64 Linux、Docker Engine 和 Compose。配置玩家域名、证书邮箱、私有制作台口令和模型凭据后，在服务器的项目目录执行以下命令。

```sh
docker compose config --quiet
docker compose up -d --build
curl --fail http://127.0.0.1:7860/readyz
```

玩家访问域名根路径即可试玩样片，正式作品使用 `/play/{game_id}`。团队通过 SSH 转发访问制作台，复制出的试玩链接使用配置的公网域名。端口、首次迁移、在线备份及恢复切换见 [部署与恢复手册](docs/RUNBOOK.md)。

## 开发与验证

```sh
.venv/bin/python -m scripts.check
```

本地验收需要 Node.js、Bash 和 Ruff 0.17.6。已安装 uv 时，命令会自动取得指定版本的 Ruff。

测试创建独立数据库，使用受控模型输出，运行实际审批、SQLite 事务、游戏构建、QuickJS 回放及实验结算。变更 HTTP 路由后执行 `.venv/bin/python -m scripts.sync_web_routes` 更新前端接口表。仓库 CI 检查 Python、JavaScript 和 Linux 容器启动。它通过 Chrome 操作桌面与手机尺寸下的样片，再在测试发布的迷宫上通关、提交反馈并核对活动跳转。[持续集成](.github/workflows/check.yml)

调整提示、技能或 GLM 版本后，执行 `.venv/bin/python -m scripts.evaluate_agents --live`。它使用临时数据库和合成案例，调用已配置的文本模型并输出分项 JSON 结果。常规 CI 的离线评测使用同一份案例集。八项约束、代码入口及扩展方法见 [Agent 工程验收](docs/ARCHITECTURE.md#agent-工程的八项验收)。
