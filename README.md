# CAD 图纸批处理工具

新增 [ezdxf + ODA 转换器版本](oda-version/README.md)：无需 AutoCAD，通过 DXF 中间格式处理后输出 DWG。与下述 Core Console 版本独立，依赖和兼容性限制见对应说明。

用于 Windows AutoCAD 的 DWG 批处理脚本：先复制原图，再进行有限轮次炸开、图层整理、清理未使用定义，并输出 AutoCAD 2004 格式副本。

**当前为未经过真实 AutoCAD 转换验证的初版。仅完成静态检查，请先用样图测试，不要直接用于正式交付。**

## 使用方法

1. 下载并解压仓库（Code → Download ZIP）。
2. 保持 `Run-CAD.cmd`、`Run-CAD.ps1` 和 `process.lsp` 在同一目录。
3. 在装有完整 Windows AutoCAD 的电脑上，将一个或多个 DWG 拖到 `Run-CAD.cmd`。
4. 在原图目录查看 `_copy_随机编号.dwg` 副本及日志，人工核对结果。

也可下载仓库内的 [独立工具包](CAD-batch-tool.zip)。

## 功能与边界

- 独立工作副本，不对原图执行保存；输出使用随机名称，拒绝覆盖已有文件。
- 多图纸逐个处理，独立日志，默认每份图纸超时十分钟。
- 默认最多四轮炸开普通无属性块和普通多段线，每轮重新选择对象。
- 处理模型空间及布局；保留带属性块、外参、锁定对象等，不承诺完全炸平。
- 将可修改的非块对象移动到 0 图层，使用 PURGE 清理未使用定义，不强制删除仍有对象的图层。
- 检查完成标记及 DWG 2004 文件头。

图层变化可能改变 ByLayer 外观，炸开会改变结构；专业对象、代理对象、外部参照与中文路径需实际验证。此工具不使用 AI 服务，不上传图纸。

环境：Windows PowerShell + 完整版 AutoCAD Core Console，以 AutoCAD 2021 为目标。Mac、AutoCAD 网页版及第三方 CAD 不在支持范围。

详见 [使用说明](使用说明.md)。
