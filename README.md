# DSH Desk Pet

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Language](https://img.shields.io/badge/language-Python-3776AB.svg)](src/dsh_desk_pet)
[![dsh-plugin](https://img.shields.io/badge/topic-dsh--plugin-111111.svg)](https://github.com/topics/dsh-plugin)

盖在所有窗口之上的桌面宠物，跟着本地 DSH 的状态自己变表情。默认鲸鱼，四套皮肤。

不是网页里的挂件——是一个无边框透明的系统窗口。DSH 页面里那只是它的镜像。

[English](README_EN.md)

## 安装

已有 DSH，一条命令：

```bash
dsh plugin --profile web add github:anneheartrecord/dsh-desk-pet#main
```

macOS 用系统自带的 `/usr/bin/python3`，不需要装任何依赖。

## 启动

```bash
dsh web
```

宠物会自己浮在桌面上。DSH 页面右下角还有一只同步的镜像。

不要 DSH、只开宠物：克隆后执行 `./bin/dsh-desk-pet`。

## 使用

- **拖**：按住身体任意处。
- **点一下**：它会跳一下；在打盹的话会被叫醒。
- **换肤**：右键（或 Control+点击）出菜单，也可以按 `1`–`4`。换肤不改状态。
- **关掉**：`Esc` 或 `q`，或右键菜单里选退出。

## 状态

跟着本地 DSH 自动变，不用管。

| 状态 | 什么时候 |
| --- | --- |
| 空闲 | 没事干，会呼吸、偶尔眨眼 |
| 干活 | DSH 正在跑 |
| 等你 | 卡在确认、授权、要你输入 |
| 报错 | 跑挂了 |
| 开心 | 刚跑完一轮，几秒后自己回到空闲 |
| 睡着 | 闲够五分钟就打盹，一有动静或者你戳它就醒 |

## 皮肤

| 圆点 | id |
| --- | --- |
| 蓝 | `whale`（默认） |
| 橙 | `threadcore` |
| 棕 | `nautilus` |
| 紫 | `jellyfish` |

## 关闭与卸载

- 只关宠物：窗口上按 `Esc`。
- 连 DSH 一起关：停掉 `dsh web`，插件拉起的宠物一起没。
- 卸掉插件：

```bash
dsh plugin --profile web remove dsh-desk-pet
```

然后重新 `dsh web`。

## 开发

```bash
/usr/bin/python3 -m unittest discover -s tests -v   # 全套测试，无需窗口
./bin/dsh-desk-pet --probe                          # 不开窗，打印自检
./bin/dsh-desk-pet --inventory                      # 每套皮肤每个状态有几帧
```

### 加素材

原图放 `assets/source/<皮肤>/<状态>/NN.png`，纯色背景即可（每张自己什么底色都行，脚本按四角自动取样）。然后：

```bash
./scripts/build_frames.py          # 抠图、对齐、缩放，产出两套帧
./scripts/contact_sheet.py         # 拼一张总览图，不开窗也能看效果
```

`build_frames.py` 一份原图产出两套：`assets/skins/` 下的透明 GIF 给桌面窗（macOS 的 Tk 8.5 只认 GIF，不认 PNG），`assets/web/` 下的 RGBA PNG 给网页镜像。裁切框按**每套皮肤**统一算，所以切换状态时宠物不会跳、不会忽大忽小。

同一状态放两帧以上就会自动循环；`idle` 的第二帧当作闭眼帧，脚本会给它排一个长睁短闭的双眨节奏。
