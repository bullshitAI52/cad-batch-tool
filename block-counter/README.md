# 独立 CAD 块数量统计工具

只读统计图纸中的 INSERT 块引用，导出 Excel（.xlsx）和 CSV。不炸开、不清理、不修改原图，也不启动 AutoCAD。可独立下载此目录使用，不依赖仓库里的其他脚本。

## 使用

1. 安装 Python 3.10+。DWG 还需安装 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)；DXF 无需转换器。
2. 双击 `Setup.cmd` 安装依赖。
3. 将一张或多张 DWG/DXF 拖到 `Count-Blocks.cmd`；或双击它，弹窗选择图纸。
4. 第一张图纸旁的「块统计结果」目录生成 Excel、统计 CSV 和处理记录 CSV。每次运行使用独立文件名。

Excel 包含「块数量统计」和「处理记录」两张表。列为文件路径、空间/布局、有效图层、原始块名、类别、直接数量、嵌套数量，可筛选。不同文件的同名块不合并，避免不同块定义被混为一谈。

## 统计口径

- **直接数量**：模型空间或布局直接放置的块实例数。
- **嵌套数量**：块内部的子块引用，乘以各级父块的数量。例如 3 个组件各含 2 个螺栓，组件直接数量为 3，螺栓嵌套数量为 6。两列不可不分块名就相加作为设备总量。
- 阵列块按行列及间距展开计数，零间距的重叠阵列位置按一个位置计算，与 ezdxf 的 multi_insert 规则一致；不实际复制图形。
- 默认遍历模型及全部布局，包括隐藏对象和关闭/冻结图层。布局中的视口不额外重复计算其显示的模型图形。
- 嵌套块在 0 图层时继承父块的有效图层。
- 外参只计引用次数，不进入外部文件；缺失块定义、循环引用、深度或遍历上限会在处理记录里警告。
- 匿名/动态块保留原始名称（如 *U123），不会自动识别或合并有效块名。代理对象或未以 INSERT 表示的对象不作为块数量统计。
- 循环引用及深度超过 32 层的分支停止，默认最多遍历十万个引用节点；出现警告须检查是否数量不完整。
- 本工具不识别散线拼出的设备。只有图纸按块绘制时，块数量才可能对应实际设备数量。

## 参数

```powershell
.\.venv\Scripts\python.exe .\block_count.py --scope model --no-nested 'D:\图纸\示例.dwg'
.\.venv\Scripts\python.exe .\block_count.py --oda-path 'C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe' --output-dir 'D:\统计结果' 'D:\图纸\一.dwg' 'D:\图纸\二.dxf'
```

CSV 使用 UTF-8 BOM，方便 Excel 显示中文。可疑公式前缀的名称在 CSV 中加单引号保护；XLSX 中保留原名称并明确存为文本。

当前测试范围为程序生成的 DXF 样图及 Excel/CSV 读回核验。真实 DWG 的 ODA 转换仍需在安装了转换器的电脑上验证，不能据此保证所有专业图纸的统计准确性。
