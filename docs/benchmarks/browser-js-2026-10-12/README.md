# 浏览器 JS 同机性能原始数据

测试代码版本：本地冻结 `87195ff`（对应如 0.16.0／如书 0.4.0，后续仅文档变化）。场景为 `rushu/examples/ruguan/solar-system-math.ru`，只替换请求帧率 20／30／60；原生参考使用相同轨道、18 次逐帧三角计算、形状、标签、说明与交互。完整方法和限制见 [验证记录](../../rushu-0.4.0-validation.md)。

`forward-summary.json` 是先 Ru 后原生的三档统计，`reverse-summary.json` 是先原生后 Ru 的 60 档复测。`js-*-raw.json` 中 `frames[].end` 为每帧最后一条 Canvas 文字提交完成的时间；`native-*-raw.json` 的相同序列名为 `paintCompletionTimes`。`reverse-` 前缀表示反向复测。

重算公式：`1000 * (N - 1) / (times[N - 1] - times[0])`。不要把请求帧率或 Canvas 提交帧率写成物理屏幕呈现帧率。`checksums.json` 保存全部 JSON 及场景源码 SHA-256。两轮都保留，不挑选最佳结果。
