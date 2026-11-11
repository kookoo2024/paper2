"""发布新版本：读取 zhixue_simple.py 里的 APP_VERSION，生成 version.json（含各文件 sha256）
用法：python make_release.py "这次更新说明" """
import hashlib, json, re, sys

FILES = ["zhixue_simple.py", "README.md", "requirements.txt"]
src = open("zhixue_simple.py", encoding="utf-8").read()
version = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', src, re.M).group(1)
notes = sys.argv[1] if len(sys.argv) > 1 else ""
files = {f: hashlib.sha256(open(f, "rb").read()).hexdigest() for f in FILES}
json.dump({"version": version, "notes": notes, "files": files},
          open("version.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"version.json 已生成：v{version}")
