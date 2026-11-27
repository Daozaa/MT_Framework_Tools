# MT Framework Tools（MHGU Blender 插件）

《怪物猎人 XX / GU》的 Blender 侧建模插件：把游戏里的 `arc / mod / mrl / tex / ctc / xfs / ccl`
读进 Blender、改完再写回，也支持把 MMD / 自制模型做成可用的装备、武器、随从猫外观。

当前版本 **1.4.17**，已在 Windows 上用 Blender 3.0.1 验证。

> 本仓库只提供 `clean` 分支：**去注释 / 去 docstring** 的发布版。
> 源码由 `tools/strip_comments.py` 生成，可直接安装；功能与开发版一致。

## 安装

1. 从 [Releases](https://github.com/Daozaa/MT_Framework_Tools/releases/latest) 下载 `MT_Framework_Tools_1.4.17_clean.zip`。
2. Blender → 编辑 → 偏好设置 → 插件 → 安装… → 选 zip
3. 勾选 **MT Framework Tools**。在 3D 视图按 `N` 打开「MTFramework」侧栏。
4. 装完请重启 Blender（插件改动需要重启才生效）

## 主要功能

| 区域 | 功能 |
| --- | --- |
| MOD 模型 | 导入 / 导出 `.mod`、`.arc`；跨部位、跨防具、跨性别导出；分件槽自动分配 |
| TEX 贴图 / 图集 | `.tex` 导入 / 导出（DXT1/DXT5/ATI1，自动 mip / swizzle）；图集合并、按图集 UV 导出、跨部位带图集导出 |
| CTC 物理骨骼 | 按部位和链长设初始参数，支持登记后融并同步与跨组锁死连接骨 |
| CCL 碰撞胶囊 | 自动生成，预览与拖动 A/B 端点或整条胶囊，左右镜像联动 |
| XFS 头部显示 | XFS disp0/disp1；猎人藏头；**随从猫藏头**；body 源跨移植 helm 时带待写入 XFS |
| VWG 顶点组 / 名称 | 复制/粘贴顶点组、替换名称、**权重归一化（删非骨骼组）** |
| MMD 转换 | T 姿势、握持烘焙、身体骨对齐、面部与辅助骨整理、物理骨迁移和网格绑定 |

导出成功后会在 arc 旁写入 `xxx.arc.mtbones.json` 骨骼尾端信息；重新导入同一 arc 时优先用该文件精确还原骨骼尾端。
模板随 `.blend` 工程保存，并在另存 / 分支工程时自动校验和自愈。

## 目录

```
MT_Framework_Tools/       插件本体（放进 Blender addons 目录即可）
tools/strip_comments.py   clean 源码生成脚本
README.md
LICENSE
.gitignore
```

## 已知限制

- 只测试过 Blender **3.0**（Windows）；其它版本未验证
- `.mod` 每顶点最多 4 根骨，导出会按前 4 根归一化（格式限制）
- CCL 只在 `helm` / `hair` 槽生效（引擎只为这两个槽查 CCL）
- 导出的模型坐标必须在 ±1 内（int16），超出会被压平

## 免责声明

本项目是非官方的粉丝工具，与 CAPCOM 无关；不包含任何游戏原始资源。
使用前请备份存档与 `romfs` 文件，风险自负。

## 许可

MIT，见 `LICENSE`。
