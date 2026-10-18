from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import ezdxf
from openpyxl import load_workbook
from block_count import run_batch
from gui import discover_files, App
import tkinter as tk


class BatchTests(unittest.TestCase):
    def test_folder_scan_and_stop_exports_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'sub').mkdir()
            first=root/'first.dxf';second=root/'sub'/'second.DXF'
            for p in (first,second):ezdxf.new().saveas(p)
            (root/'ignore.txt').write_text('not a drawing')
            self.assertEqual(len(discover_files(root,False)),1)
            self.assertEqual(len(discover_files(root,True)),2)
            stop=threading.Event();events=[]
            def event(e):
                events.append(e)
                if e['stage']=='file_done':stop.set()
            result=run_batch([first,second],root/'out',progress=event,stop=stop)
            self.assertTrue(result['cancelled'])
            self.assertEqual(result['completed'],1)
            self.assertEqual(events[-1]['stage'],'exporting')
            book=load_workbook(result['reports'][0])
            self.assertTrue(any(row[1].value=='已停止' for row in list(book['处理记录'].rows)[2:]))
            book.close()

    def test_ui_background_start_and_export(self):
        try:root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        root.withdraw()
        try:
            with tempfile.TemporaryDirectory() as td:
                directory=Path(td)
                doc=ezdxf.new()
                doc.blocks.new('灯具').add_circle((0,0),1)
                doc.modelspace().add_blockref('灯具',(0,0))
                doc.saveas(directory/'test.dxf')
                app=App(root)
                app.source.set(str(directory));app.destination.set(str(directory/'out'))
                app.rules.set(str(Path(__file__).with_name('classification.json')))
                with patch('gui.messagebox.showerror') as error:
                    app.start.invoke()
                    self.assertTrue(app.running)
                    deadline=time.monotonic()+15
                    while app.running and time.monotonic()<deadline:
                        root.update();time.sleep(.02)
                    self.assertFalse(app.running)
                    error.assert_not_called()
                    self.assertEqual(float(app.bar['value']),100)
                    self.assertEqual(str(app.start['state']),'normal')
                    self.assertEqual(len(list((directory/'out').glob('*.xlsx'))),1)
                    self.assertIn('处理结束',app.status.get())
        finally:root.destroy()


if __name__=='__main__':unittest.main()
