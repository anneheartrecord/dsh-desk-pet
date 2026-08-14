# DSH Desk Pet

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-Python-3776AB.svg)](src/dsh_desk_pet)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-111111.svg)](https://github.com/topics/dsh-plugin)

置顶桌面宠物。默认鲸鱼，四套皮肤，四种状态。不是网页里的挂件，是盖在 DSH 上的系统窗口。

[English](README_EN.md)

## 安装

已有 DSH。一条命令：

```bash
dsh plugin --profile web add github:anneheartrecord/dsh-desk-pet#main
```

macOS 需要系统自带的 `/usr/bin/python3`（带 Tk）。

## 启动

```bash
dsh web
```

DSH 起来后，宠物自己弹出。拖到浏览器上的 DSH 即可。

不要 DSH、只开宠物：克隆后执行 `./bin/dsh-desk-pet`。

## 使用

- 拖：按住窗口任意处。
- 换肤：点底部四个圆点（鲸 / 线核 / 鹦鹉螺 / 水母）。换肤不改状态。
- 状态：空闲、干活、等你、报错。跟着本地 DSH 自动变，不用管。

## 关闭

- 这只宠物：窗口上按 `Esc`。
- 连 DSH 一起关：停掉 `dsh web`，插件拉起的宠物一起没。
- 卸掉插件：

```bash
dsh plugin --profile web remove dsh-desk-pet
```

然后重新 `dsh web`。

## 皮肤

| 圆点 | id |
| --- | --- |
| 蓝 | `whale`（默认） |
| 橙 | `threadcore` |
| 棕 | `nautilus` |
| 紫 | `jellyfish` |

## 开发

```bash
/usr/bin/python3 -m unittest discover -s tests -v
```
