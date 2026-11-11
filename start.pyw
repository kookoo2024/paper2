# 双击 start.pyw 启动「阅卷」，不弹黑色命令行窗口（Windows 用 pythonw 打开 .pyw）
import os
import sys
import traceback

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
sys.path.insert(0, APP_DIR)

# 没有控制台时，把输出和报错写进 run.log，方便排查
_log = open(os.path.join(APP_DIR, "run.log"), "w", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log

try:
    import zhixue_simple
    zhixue_simple.main()
except Exception:
    traceback.print_exc()
    try:
        import tkinter.messagebox as mb
        mb.showerror("阅卷 启动失败", traceback.format_exc()[-800:] + "\n\n详细信息见 run.log")
    except Exception:
        pass
