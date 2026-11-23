# 阿里云轻量服务器部署与恢复

部署单元是一台 x86_64 Linux 服务器上的两个容器。团队通过 SSH 使用制作台，玩家使用独立域名。以下命令在项目根目录执行。云账户、DNS 和服务器由实际运营者管理。

## 第一次启动

1. 安装 Docker Engine 与 Compose，在 DNS 将玩家域名指向该实例。轻量服务器防火墙开放 TCP 80、443，把 SSH 限定到团队的管理来源。应用端口 7860 只绑定回环地址。[阿里云防火墙设置](https://help.aliyun.com/zh/simple-application-server/user-guide/manage-the-firewall-of-a-server)
2. 将项目源码及 `docs/original/` 放在服务器固定目录，例如 `/opt/loop-atelier`。构建镜像时会打包资料索引和全部 60 张配图，团队经制作入口查阅。Linux 包版本在 `requirements-linux.lock` 中固定。
3. 创建权限为仅部署账户可读的环境文件，填写玩家域名、证书通知邮箱、团队口令和供应商凭据。请为上线单独签发模型凭据，聊天中出现过的凭据可在供应商后台轮换。
4. 启动服务，检查内部就绪结果并从公网访问样片。

```sh
umask 077
test -f .env || cp .env.example .env
chmod 600 .env
# 在服务器上编辑 .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:7860/readyz
```

| 配置 | 行为 |
| --- | --- |
| `DOMAIN`、`ACME_EMAIL` | 填玩家域名（主机名）和证书邮箱。Caddy 在公网终止 TLS，Compose 将 `https://DOMAIN` 作为分享链接的来源 |
| `STUDIO_ACCESS_KEY` | 团队制作台口令。Compose 和应用启动时检查，轮换后需要重新登录 |
| `ZAI_1_TOKEN` 等、`ZAI_MODEL` | 为生产及运营任务提供文本和多模态调用。默认 `glm-5.4`，协议为 `responses` |
| `STUDIO_ART_API_KEY`、`STUDIO_ART_BASE_URL`、`STUDIO_ART_RESPONSE_MODEL`、`STUDIO_ART_IMAGE_MODEL` | 美术独立调用 Responses 的生图工具。示例配置为 `gpt-image-2`，可用性取决于该网关授权 |
| `STUDIO_VOLUME` | 默认沿用 `loop-data`，持久化数据库、构建和素材。应用进程的 UID/GID 为 10001 |
| `STUDIO_RESEARCH_ONLINE` | 默认开启网络检索；置为 `0` 使用本地参考素材 |

团队成员在自己的电脑上建立隧道，将示例中的账户和主机替换成自己的。浏览器访问 [内部制作台](http://127.0.0.1:17860/) 后输入团队口令。工作台生成的试玩地址使用玩家域名。

```sh
ssh -N -L 127.0.0.1:17860:127.0.0.1:7860 team@your-server
```

公开入口的 `/` 跳转到《港湾引航》，`/sample` 可玩《潮汐信标》。正式版 `/play/{game_id}` 支持渠道参数 `entry`。在公网域名上访问 `/api/studio`、`/metrics`、`/openapi.json` 应返回 404。内部服务上的制作接口对匿名请求返回 401。玩家自然完局后才可跳转到团队为该活动配置的 HTTPS 目标页。

## 迁移已有工作室

停止旧的任务写入后，在旧数据目录的副本上使用本版 Python 环境执行导出。SQLite 的在线备份会合并已提交的 WAL，再校验数据库和被引用的构建。数据库和 `builds/`、`generated-art/` 应来自同一套数据。

```sh
.venv/bin/python -m studio.infra.backup export --data-dir /absolute/path/to/old-data > loop-migration.tar.gz
```

把备份放到服务器，照下面的恢复步骤导入新数据卷。启动时迁移脚本会补齐旧表字段并登记版本。沿用原 `loop-data` 卷的实例，应先做快照并检查 `/data` 的写权限。若旧卷属主为 root，停旧服务后可用 `docker compose run --rm --no-deps --user 0 app chown -R 10001:10001 /data` 将该卷交给应用账户。

## 在线备份、恢复与回切

```sh
./deploy/backup.sh
./deploy/restore.sh backup/实际备份文件.tar.gz loop-data-rehearsal
```

备份只为 SQLite 建临时副本，已完成的版本包和图片直接从不可变文件流入归档。脚本在 `backup/` 写入已校验的压缩包，未完成的导出留在临时文件。本地归档权限为 0600，含完整数据库、构建和美术。异地上传可设置 `OSS_URL`（ossutil）或 `S3_BUCKET`（AWS CLI）。脚本在上传请求中指定 AES256 服务端加密，配置 `BACKUP_KMS_KEY_ID` 时改用该桶对应的 KMS 密钥。恢复账号需要读取对象及使用密钥的权限。桶应限制为私有访问。[OSS 上传加密参数](https://www.alibabacloud.com/help/en/oss/developer-reference/upload-objects-6) · [S3 上传加密参数](https://docs.aws.amazon.com/cli/latest/reference/s3/cp.html)

需要定时备份时，可将 `/opt/loop-atelier/deploy/backup.sh` 加入服务器的定时任务。

恢复脚本要求新的卷名。它验证清单、SQLite 的完整性与外键、构建摘要和美术缓存的图片引用，成功后最后安装数据库。在隔离卷核验数据后，可以将 `.env` 的 `STUDIO_VOLUME` 改为该卷，执行 `docker compose up -d` 和就绪检查。需要回切时恢复原卷名和对应版本的应用。涉及上线后新增的对局，应先备份再决定切换时间。

## 运行检查

| 从服务器访问 | 检查内容 | 处理 |
| --- | --- | --- |
| `GET /healthz` | 服务可查询 SQLite | 先查看容器状态与日志 |
| `GET /readyz` | 写事务、卷剩余至少 10%、执行器任务存活且最老排队时间不超过 30 分钟 | 返回 503 时查看返回体的三项检查，分别处理卷容量、数据库权限或积压 |
| `GET /metrics` | 团队鉴权后可取分状态任务数与可用磁盘字节 | 在私有入口采集 |
| 团队运营页、项目历史 | 生产失败原因、每个节点的产物、待补证、批次和实验 | 根据失败节点修复后续跑，观察到期实验的样本与基线 |

每次登录产生独立的 12 小时会话。制作台页脚的“退出制作台”会吊销本次登录并清除本机编辑者标识。项目已经继承的偏好和冻结快照继续保存在项目内。升级旧版时间戳会话后，团队成员需要重新登录。团队脚本使用登录返回的 `X-Atelier-Session`。使用 Cookie 写入时请求需携带同源 Origin 或 Referer。

正式试玩按上海自然日限制 10,000 次有效开局，每个 IP 在 24 小时窗口内最多 1,200 次开局请求。单次玩家请求上限 256 KiB，每局最多执行 12,000 步。宿主将时钟、按键、坐标压紧后上报，旧版对象输入继续可用。服务端先逐步回放，再记分。原始回放保留 180 天，每天最多存储 24 MiB 压缩轨迹，满额后的完局仍会验算并记录指标。巡检分批清理到期轨迹、会话和限流计数。SQLite 回收的页面供后续写入复用。查看 `studio_today_omitted_replays` 可判断是否需要调整容量。备份由部署方另行设置生命周期。

每天北京时间 08:00 后按已结束的自然日生成报表，约每 30 分钟补查缺失批次、僵尸任务及到期实验。配额不足时保存当日排序、待办与基线，次日恢复。期间已切换版本的候选留存原因。健康检查把异常容器标记为 unhealthy；进程退出由 Compose 的重启策略处理。目标服务器上线验收包括公网域名与证书、实际 Linux 容器启动、恢复演练、预期并发和模型配额。在此仓库的离线回归和本机代理联测中使用独立数据。[验收记录](ACCEPTANCE.md)
