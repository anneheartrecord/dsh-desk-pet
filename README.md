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
| 睡着 | agent 没事干**且**你的鼠标也不动了才打盹；一有动静或者你戳它就醒 |

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
DSH_PET_ART_CHECK=1 /usr/bin/python3 -m unittest discover -s tests   # 连素材一起验（多约 10 秒）
./bin/dsh-desk-pet --probe                          # 不开窗，打印自检
./bin/dsh-desk-pet --inventory                      # 每套皮肤每个状态有几帧
./bin/dsh-desk-pet --small --reset                  # 半尺寸，并忘掉已保存的位置
```

### 素材流水线

三个脚本，按顺序跑：

```bash
./scripts/generate_frames.py       # 用生图接口补齐缺的姿势（需要 ARTGEN__IMAGE_* 环境变量）
./scripts/build_frames.py          # 抠底、对齐、缩放，产出两套帧
./scripts/check_frames.py          # 逐像素体检
./scripts/contact_sheet.py         # 拼一张总览图，不开窗也能看效果
```

新素材的**背景一律用品红 `#FF00FF`**，装饰（ZZZ、星星）不能用品红或背景色。底色必须是画面里绝不出现的颜色：早期素材生在粉彩底上（水母是薄荷绿），和角色自身颜色太近，抠图阈值怎么调都会误伤——那批水母的眼睛就是这么被抠没的。品红离这四套角色都很远，键容差放到 0.24 也完全不伤画。

**generate_frames** 从不凭空重画角色：每次请求都是拿一张已有的图做 image-to-image。文生图跨次调用锁不住身份，问两次会得到两只不同的鲸、两种配色、两种尺寸，切状态时角色就当场变形。状态的第一帧参考本套皮肤的 idle 静止姿势，第二帧参考**它自己的第一帧**——两帧循环要的是同一个姿势差一瞬间，不是两个不同姿势。

**build_frames** 一份原图产出两套：`assets/skins/` 下的透明 GIF 给桌面窗（macOS 的 Tk 8.5 只认 GIF，不认 PNG），`assets/web/` 下的 RGBA PNG 给网页镜像。用 `colorkey` 而不是 `chromakey`——后者只比较色度、不看亮度，碰上水母那种低饱和底色会把角色的黑眼睛一起吃掉。抠完还会做一次洞填充：背景按定义就是「与画面边缘连通的透明区域」，四面被角色包住的透明区一律补回不透明。裁切框在**相对坐标**里按每套皮肤统一算（源图有 360/1024/1254 三种分辨率），并按身体底边对齐基线，所以换状态、换皮肤都不会跳。

**check_frames** 是唯一会看像素的测试。其余测试只能比较文件名——水母曾经带着一脸窟窿通过全部测试。

同一状态放两帧以上就会自动循环；`idle` 的第二帧当作闭眼帧，脚本会给它排一个长睁短闭的双眨节奏。

### 自定义皮肤

皮肤就是一个装帧的目录。只要 `assets/skins/<id>/<状态>/*.gif` 存在，它就会自动出现在右键菜单里，不用改代码。
