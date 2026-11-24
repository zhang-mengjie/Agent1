# spine-agent 架构

和 rag / cs / finance 一样是独立的 FastAPI 服务，但这一条流水线不检索知识库，也不写 Postgres。

```text
描述
  → 文生图模型生成一张全身图
  → 视觉模型看着这张图标出部件矩形和骨骼父子
  → 从整图裁开，写出 Spine 4.1 character.json + character.atlas
  → 页面用同一套骨骼公式播放
```

| 步骤 | 谁决定 | 谁执行 |
| --- | --- | --- |
| 整图 | 用户的角色描述 | `services/image_gen.py` 只出一张全身图 |
| 碎图 | 视觉模型按整图像素框出部件，并给出父子骨骼 | 从 `portrait.png` 裁切，`rig.py` 换算局部变换 |
| 动画 | 模型给出相对 setup 的偏移关键帧 | `services/animate.py` 烘焙成绝对值后写入 JSON |

坐标有两套：

- 贴图像素：左上角为原点，y 向下。atlas 的 `xy` 与此相同。
- 角色 / Spine：脚底中心为原点，y 向上，旋转逆时针。1 个单位等于 1 像素。

带部件的骨骼放在该部件的轴点（头和耳朵在底部，四肢在顶部，尾巴在右侧）。附件偏移把图片中心放回原来的站立位置，所以预览和站立稿对齐。

导出文件在工程目录：

```text
data/projects/spn_xxxxxxxx/
  project.json
  texture.png
  assembled.png
  pieces/*.png
  character.json
  character.atlas
```

页面预览实现的是 Spine 4.1 `Bone.updateWorldTransformWith` 的 Normal 模式（无剪切）。下载的 JSON 用 Spine 4.1 打开。
