"""Desktop folder-based CAD block statistics UI (Tkinter)."""
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from block_count import configure_oda, run_batch
from overlap import load_rules
from ezdxf.addons import odafc


def discover_files(folder, recursive):
    root = Path(folder).expanduser()
    if not root.is_dir():
        raise ValueError('请选择有效的 CAD 文件夹')
    items = root.rglob('*') if recursive else root.iterdir()
    return sorted((p for p in items if p.is_file() and p.suffix.lower() in ('.dwg','.dxf')),
                  key=lambda p: str(p).casefold())


class App:
    def __init__(self, root):
        self.root = root
        root.title('CAD 块数量统计 · 分类与重叠检查')
        root.geometry('930x760')
        root.minsize(780,660)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.inputs = []
        self.source = tk.StringVar()
        self.destination = tk.StringVar()
        self.oda = tk.StringVar(value=os.environ.get('ODA_FILE_CONVERTER',''))
        self.rules = tk.StringVar(value=str(Path(__file__).with_name('classification.json')))
        self.recursive = tk.BooleanVar(value=True)
        self.nested = tk.BooleanVar(value=True)
        self.dedup = tk.BooleanVar(value=True)
        self.scope = tk.StringVar(value='模型空间及全部布局')
        self.tolerance = tk.StringVar(value='0.1')
        self.status = tk.StringVar(value='选择图纸文件夹和结果文件夹后，点击开始统计。')
        self.amount = tk.StringVar(value='尚未开始')
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        ttk.Label(outer, text='CAD 块数量统计', font=('',20,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,5))
        ttk.Label(outer,text='不启动 AutoCAD · 原图只读 · 导出 Excel 与 CSV').grid(row=1,column=0,columnspan=3,sticky='w',pady=(0,18))
        self.path_row(outer,2,'CAD 文件夹',self.source,'source')
        self.path_row(outer,3,'结果文件夹',self.destination,'destination')
        self.path_row(outer,4,'ODA 程序（可选）',self.oda,'oda')
        self.path_row(outer,5,'分类配置',self.rules,'rules')
        settings = ttk.LabelFrame(outer,text='统计设置',padding=12)
        settings.grid(row=6,column=0,columnspan=3,sticky='ew',pady=12)
        for i,(label,var) in enumerate([('包含子文件夹',self.recursive),('统计嵌套块',self.nested),('分类和重叠去重',self.dedup)]):
            widget=ttk.Checkbutton(settings,text=label,variable=var)
            widget.grid(row=0,column=i,sticky='w',padx=(0,18));self.inputs.append(widget)
        ttk.Label(settings,text='统计范围').grid(row=1,column=0,sticky='w',pady=(12,0))
        choice=ttk.Combobox(settings,textvariable=self.scope,state='readonly',width=24,
                            values=['模型空间及全部布局','仅模型空间'])
        choice.grid(row=1,column=1,sticky='w',pady=(12,0));self.inputs.append(choice)
        ttk.Label(settings,text='疑似位置容差').grid(row=2,column=0,sticky='w',pady=(10,0))
        entry=ttk.Entry(settings,textvariable=self.tolerance,width=12)
        entry.grid(row=2,column=1,sticky='w',pady=(10,0));self.inputs.append(entry)
        ttk.Label(settings,text='单位跟随图纸；只标疑似，不按容差扣数').grid(row=2,column=2,sticky='w',pady=(10,0))
        controls=ttk.Frame(outer)
        controls.grid(row=7,column=0,columnspan=3,sticky='ew',pady=(0,12))
        self.start=ttk.Button(controls,text='开始统计',command=self.begin)
        self.start.pack(side='left',ipadx=18)
        self.cancel=ttk.Button(controls,text='处理完当前文件后停止',command=self.request_stop,state='disabled')
        self.cancel.pack(side='left',padx=10)
        self.open_button=ttk.Button(controls,text='打开结果文件夹',command=self.open_output)
        self.open_button.pack(side='right')
        ttk.Label(outer,textvariable=self.status,wraplength=850).grid(row=8,column=0,columnspan=3,sticky='w')
        self.bar=ttk.Progressbar(outer,maximum=100,mode='determinate')
        self.bar.grid(row=9,column=0,columnspan=3,sticky='ew',pady=8)
        ttk.Label(outer,textvariable=self.amount).grid(row=10,column=0,columnspan=3,sticky='w')
        self.log=ScrolledText(outer,height=12,wrap='word',state='disabled')
        self.log.grid(row=11,column=0,columnspan=3,sticky='nsew',pady=(10,0))
        outer.rowconfigure(11,weight=1)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)

    def path_row(self,parent,row,label,var,kind):
        ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',padx=(0,12),pady=5)
        entry=ttk.Entry(parent,textvariable=var)
        entry.grid(row=row,column=1,sticky='ew',pady=5)
        button=ttk.Button(parent,text='浏览…',command=lambda:self.browse(kind,var))
        button.grid(row=row,column=2,padx=(8,0),pady=5)
        self.inputs.extend([entry,button])

    def browse(self,kind,var):
        if kind in ('source','destination'):
            value=filedialog.askdirectory(title='选择文件夹')
        else:
            types=[('JSON','*.json')] if kind=='rules' else [('所有文件','*')]
            value=filedialog.askopenfilename(title='选择文件',filetypes=types)
        if value:
            var.set(value)
            if kind=='source' and not self.destination.get():
                self.destination.set(str(Path(value)/'块统计结果'))

    def append(self,text):
        self.log.configure(state='normal')
        self.log.insert('end',text+'\n');self.log.see('end')
        self.log.configure(state='disabled')

    def set_running(self,value):
        self.running=value
        self.start.configure(state='disabled' if value else 'normal')
        self.cancel.configure(state='normal' if value else 'disabled')
        for widget in self.inputs:
            widget.configure(state='disabled' if value else ('readonly' if isinstance(widget,ttk.Combobox) else 'normal'))

    def begin(self):
        if self.running:return
        try:
            tolerance=float(self.tolerance.get())
            if not math.isfinite(tolerance) or tolerance<=0:raise ValueError('容差必须是大于零的有限数值')
            if not self.source.get().strip() or not self.destination.get().strip():
                raise ValueError('请先选择 CAD 文件夹和结果文件夹')
            settings=dict(source=self.source.get().strip(),destination=self.destination.get().strip(),
                          oda=self.oda.get().strip(),rules=self.rules.get().strip(),recursive=self.recursive.get(),
                          nested=self.nested.get(),dedup=self.dedup.get(),tolerance=tolerance,
                          scope='model' if self.scope.get()=='仅模型空间' else 'all')
        except ValueError as exc:
            messagebox.showerror('设置有误',str(exc));return
        self.stop.clear();self.set_running(True);self.bar['value']=0
        self.status.set('正在扫描图纸文件夹…');self.amount.set('扫描中')
        self.append('—— 新任务 ——')
        threading.Thread(target=self.worker,args=(settings,),daemon=True).start()

    def worker(self,settings):
        try:
            files=discover_files(settings['source'],settings['recursive'])
            if not files:raise ValueError('文件夹中未找到 DWG 或 DXF 图纸')
            rules=load_rules(Path(settings['rules'])) if settings['dedup'] else []
            configure_oda(settings['oda'] or None)
            if any(p.suffix.lower()=='.dwg' for p in files) and not odafc.is_installed():
                raise ValueError('发现 DWG 文件，但未找到 ODA 转换器。请安装并在界面选择其程序路径。')
            destination=Path(settings['destination']).expanduser()
            destination.mkdir(parents=True,exist_ok=True)
            self.events.put({'stage':'scanned','total':len(files)})
            result=run_batch(files,destination,settings['scope'],settings['nested'],settings['dedup'],
                             settings['tolerance'],rules,self.events.put,self.stop)
            self.events.put({'stage':'done','result':result})
        except Exception as exc:
            self.events.put({'stage':'error','message':str(exc)})

    def poll(self):
        try:
            # Bound per-tick work so large logs do not starve the UI.
            for _ in range(100):
                event=self.events.get_nowait();stage=event['stage']
                if stage=='scanned':
                    self.append(f'发现 {event["total"]} 份图纸。进度按完成文件数计算，不是预计耗时。')
                elif stage in ('file_start','counting','deduplicating'):
                    label={'file_start':'读取/转换','counting':'基础计数','deduplicating':'分类与重叠检查'}[stage]
                    self.status.set(f'{label}：{Path(event["file"]).name}')
                    self.amount.set(f'已完成 {event["completed"]}/{event["total"]} 份')
                    if stage=='file_start':self.append('开始：'+event['file'])
                elif stage=='file_done':
                    self.bar['value']=95*event['completed']/max(1,event['total'])
                    self.amount.set(f'已完成 {event["completed"]}/{event["total"]} 份')
                    self.append(f'{event["status"]}：{Path(event["file"]).name}')
                    for message in event['messages']:self.append('  '+message)
                elif stage=='exporting':
                    self.status.set('正在生成 Excel 和 CSV…')
                elif stage=='done':
                    result=event['result'];self.set_running(False)
                    if not result['cancelled']:self.bar['value']=100
                    label='已停止，导出已处理部分' if result['cancelled'] and result['reports'] else ('已停止，未生成结果' if result['cancelled'] else '处理结束')
                    self.status.set(f'{label}：{result["completed"]}/{result["total"]} 份，失败 {result["failed"]} 份，警告 {result["warnings"]} 份')
                    self.amount.set('请查看处理记录；警告或失败不代表数量为零。')
                    for path in result['reports']:self.append('已导出：'+str(path))
                elif stage=='error':
                    self.set_running(False);self.status.set('任务未完成：'+event['message'])
                    self.append('错误：'+event['message']);messagebox.showerror('任务未完成',event['message'])
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def request_stop(self):
        self.stop.set();self.cancel.configure(state='disabled')
        self.append('已请求停止：等待当前图纸处理完成，再导出已有结果。')

    def open_output(self):
        path=Path(self.destination.get()).expanduser()
        if not self.destination.get() or not path.is_dir():
            messagebox.showinfo('结果文件夹','请先选择或生成结果文件夹');return
        try:
            if os.name=='nt':os.startfile(str(path.resolve()))
            else:subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',str(path.resolve())])
        except OSError as exc:messagebox.showerror('无法打开',str(exc))

    def close(self):
        if self.running:
            messagebox.showinfo('任务正在进行','请先点击停止，等待当前文件处理及结果导出完成后再关闭。')
            return
        self.root.destroy()


if __name__=='__main__':
    app_root=tk.Tk();App(app_root);app_root.mainloop()
