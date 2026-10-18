# ezdxf + ODA 版本（实验版）

流程：DWG → ODA 转 DXF → ezdxf 整理 → ODA 转 DWG 2004。无需安装或启动 AutoCAD，但需要 Python 3.10+ 和 ODA File Converter。不是纯 Python 原生读取 DWG，也不保证比 Core Console 快。

## Windows 使用

1. 安装 Python 3.10 或以上版本。
2. 从 https://www.opendesign.com/guestfiles/oda_file_converter 安装 ODA File Converter，按其许可使用；本仓库不分发转换器。
3. 双击 `Setup-ODA.cmd`，安装隔离的 Python 依赖环境。
4. 选中 DWG 文件拖到 `Run-ODA.cmd`，支持多个文件逐个处理。
5. 在原目录查看 `原名_oda_随机编号.dwg` 和 `.json` 处理报告。

程序会尝试发现标准 ODA 安装目录；找不到时可以明确指定路径：

```powershell
.\.venv\Scripts\python.exe .\cad_batch.py --oda-path 'C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe' 'D:\图纸\示例.dwg'
```

默认最多四轮拆解普通无属性块和无宽度多段线，处理模型及布局。锁定对象、属性块、外参、阵列块、非均匀缩放块等不强行拆解；部分带扩展数据的对象也保留。不会删除源文件，不覆盖旧结果。默认将可处理的非块对象移到 0 图层，使用 `--keep-layers` 可关闭。

## 与 AutoCAD 版本的区别

- 不执行 AutoCAD 命令；使用库的对象操作，无法保证与 EXPLODE 的所有行为完全一致。
- 不做全库 PURGE 或强制删层，避免破坏未知对象引用；不能保证只剩 0 图层。
- 经过 DWG/DXF 往返转换，动态块、代理对象、专业图元、字体、布局和渲染外观可能变化。保存成功或文件头正确不代表视觉完全一致。
- 输出留在原目录，尽量维持相对外参路径；不自动打包外参。
- 按 ezdxf 文档，Windows 调用会抑制转换器 GUI；macOS 不保证隐藏转换器窗口，但都不会启动 AutoCAD。

## 验证范围

提供 `test_cad_batch.py` 验证嵌套块、多段线、锁定层、属性块、布局及源文件不变等处理逻辑。
当前开发环境未安装 ODA File Converter，尚未完成实际 DWG→DXF→DWG 转换和视觉验证。交付前必须拿真实样图验证。

```sh
python -m unittest discover -s . -p 'test_*.py'
python cad_batch.py --dxf-only sample.dxf
```

官方接口说明：https://ezdxf.readthedocs.io/en/stable/addons/odafc.html
