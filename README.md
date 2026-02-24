# vdb_centor

## Push 到 GitHub

```bash
git add .
git commit -m "chore: add docker multi-arch workflow"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```

## 自动构建多架构镜像

仓库里已经新增工作流：

- `.github/workflows/docker-image.yml`

触发条件：

- push 到 `main`
- push tag（例如 `v1.0.0`）
- 手动触发 `workflow_dispatch`

发布位置：

- `ghcr.io/<owner>/<repo>`

平台：

- `linux/amd64`（Intel x86 机器、Intel Mac 上 Docker）
- `linux/arm64`（Apple Silicon Mac 上 Docker）

说明：Docker 镜像本质是 Linux 容器镜像，不会产出原生 `macOS` 镜像；在 macOS 上运行 Docker 时，实际拉取的是对应 CPU 架构的 Linux 镜像。

## 拉取示例

```bash
docker pull ghcr.io/<owner>/<repo>:latest
```
