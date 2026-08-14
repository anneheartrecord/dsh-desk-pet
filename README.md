# DSH Desk Pet

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-Python-3776AB.svg)](src/dsh_desk_pet)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-111111.svg)](https://github.com/topics/dsh-plugin)

置顶桌面宠物。跟着本地 DeepSeek Harness 的活动在四种状态间切换：空闲、干活、等你、报错。默认鲸鱼，自带四套皮肤。**不是网页内嵌插件**，装进 DSH 后会在系统桌面弹出一只可拖的宠物，盖在浏览器上即可。

[English](README_EN.md)

## 装进 DSH 插件生态

仓库带 `dsh.bundle` + `cordis.patch.yml`，可被 `dsh plugin add` 发现和安装。GitHub topic：`dsh-plugin`。

```bash
dsh plugin --profile web add "github:anneheartrecord/dsh-desk-pet#main"
# 或本地：
dsh plugin --profile web add /path/to/dsh-desk-pet
```

然后重启 Web：

```bash
dsh --profile web web
```

DSH 启动时 Cordis 会加载本包的 `plugin/index.mjs`，由它拉起桌面宠物；卸载插件时进程一起关掉。

只想单独开宠物、不经过 DSH：

```bash
chmod +x bin/dsh-desk-pet
./bin/dsh-desk-pet
```

需要 macOS 自带的 `/usr/bin/python3`（带 Tk）。Homebrew 的 Python 3.14 没有 `_tkinter`。窗口无边框、始终置顶。Esc 退出。底部四个圆点换皮肤。

## 皮肤

| id | 名称 |
| --- | --- |
| `whale` | 鲸（默认） |
| `threadcore` | 线核 |
| `nautilus` | 鹦鹉螺 |
| `jellyfish` | 水母 |

换皮肤不会改当前状态。

## 状态从哪来

`src/dsh_desk_pet/mapper.py` 把 `AgentActivity` 映射到四态。桌面端通过 `observer.py` 看：

1. 环境变量 `DSH_PET_ACTIVITY`
2. `~/.dsh/pet-activity.json`（或 `$DSH_HOME`）
3. `~/.dsh/sessions` 里能读的 json/jsonl 尾事件
4. 是否有 DSH 进程、会话文件是否刚写过

没有 DSH 时保持空闲。测试注入 activity，不必真的开着 DSH。

## 测试

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```
