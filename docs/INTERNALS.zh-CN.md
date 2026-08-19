# 内部实现

<p align="center"><a href="INTERNALS.md">English</a> · <b>简体中文</b></p>

> 产品怎么用看 [README](../README.md)。这一页是它内部怎么跑的，以及几个当时选错过的地方。

## 原理

它盯着 `~/.dsh` 里的进程、会话活动和一个可选的提示文件，把看到的东西映射成六个状态。想手动驱动的话：

```bash
echo '{"kind":"working"}' > ~/.dsh/pet-activity.json
rm ~/.dsh/pet-activity.json          # 交还给自动检测
```

它把看到的写进 `~/.dsh-desk-pet/state.json`。第二次启动靠这个文件判断是不是已经有一只在跑，`--stop` 也靠它找进程。

页面里曾经还有一只镜像宠物，我后来整个删了。一个屏幕上两只宠物本来就像 bug，而且出问题的一直是那只镜像。真正值得留的是浮在所有窗口之上的这个窗口。

### 为什么是 AppKit 不是 Tk

macOS 自带的 Tcl/Tk 是 2010 年发布的 8.5.9，在 macOS 26 上它的绘制路径已经到不了屏幕。窗口能建出来，画布自报已映射、可见、尺寸正确、图片在正确的坐标上，屏幕上是一个空的灰方块。

我一开始完全不信是 Tk 的问题，觉得肯定是自己哪里写错了。换透明、换无边框、换回不透明、换 MacWindowStyle，一样。两天就这么没了。

最后改成用 `ctypes` 直接建在 AppKit 上。代码是多了不少，但白拿了三件 Tk 根本给不了的东西：真 alpha，不再是 GIF 那种一位遮罩；能跨全屏 Space 的窗口层级；以及作为子窗口跟着宠物一起搬的会话面板。

## 开发

```bash
/usr/bin/python3 -m unittest discover -t . -s tests -v     # 267 个测试，不需要显示器
DSH_PET_ART_CHECK=1 /usr/bin/python3 -m unittest discover -t . -s tests   # 加上逐像素素材闸
node tests/plugin_smoke.mjs                                 # 插件那一侧
```

### 素材流水线

```bash
./scripts/generate_frames.py    # 补齐缺的姿势
./scripts/build_frames.py       # 抠底、对齐、缩放
./scripts/check_frames.py       # 逐像素体检
./scripts/contact_sheet.py      # 拼一张总览图，不开窗也能看
./scripts/media_sheets.py       # 出 README 用的预览图和动图
```

新素材的背景一律用品红 `#FF00FF`，装饰也不能用品红。底色必须是画面里绝不出现的颜色。第一批我生在粉彩底上，水母那套是薄荷绿，和角色自己的颜色太近，抠图阈值怎么调都会误伤。那批水母的眼睛就是这么被抠没的，而且当时 87 个测试全绿，因为没有一个测试在看像素。

`generate_frames` 从不凭空重画角色，每次请求都是拿一张已有的图做 image-to-image。状态的第一帧参考本套皮肤的 idle 姿势，第二帧参考它自己的第一帧，因为循环要的是同一个姿势差一瞬间，不是两个不同的姿势。

`check_frames` 是唯一会看像素的测试。其余测试只能比文件名，某套皮肤曾经带着一脸窟窿通过了全部测试。

### 自定义皮肤

皮肤就是一个装帧的目录。只要 `assets/web/<id>/<状态>/*.png` 存在，它自动进换肤循环，不用改代码。
