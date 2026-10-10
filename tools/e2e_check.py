import json, os, urllib.request, tempfile
B = "http://127.0.0.1:18771"
def call(p, b=None, t=60):
    req = urllib.request.Request(B+p, data=(json.dumps(b).encode() if b is not None else None),
        headers={"Content-Type":"application/json"}, method="POST" if b is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=t) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())

ok = lambda c: "OK " if c else "FAIL "
r = [ ]
# 1. 齿轮菜单两个只读端点（问题1）
s, d = call("/api/logs"); txt = d.get("text","")
# 版本号用正则断言：升版不必改脚本（硬编码版本号必然随每次发版误报）
_r = __import__("re")
r.append((ok(s==200 and "运行日志" in txt and _r.search(r"G-POT 翻译器 v\d+\.\d+\.\d+", txt)),
          "logs 端点 %d，有版本行=%s" % (s, bool(_r.search(r"v\d+\.\d+\.\d+", txt)))))
s, d = call("/api/kit/check"); r.append((ok(s==200), "kit/check %d：%s" % (s, d.get("message"))))

# 2. 重置到干净态 → 测「没游戏目录就提取」必须早退（问题4）
call("/api/reset", {})
s, d = call("/api/extract", {"mode":"merge"})
r.append((ok(s==200 and d.get("ok") is False and d.get("error")=="no_game"),
          "空态提取 → %d %s（早退，不报新增0条）" % (s, d.get("message","")[:40])))
s, d = call("/api/state")
r.append((ok(d["extract"]["status"]=="idle" and d["max_step"]==0),
          "空态 extract.status=%s max_step=%d（没被污染成 done）" % (d["extract"]["status"], d["max_step"])))

# 3. 跳步拦截（问题3）：干净态直接点第 3 步
s, d = call("/api/nav", {"step":3})
r.append((ok(s==400 and d.get("blocked_reason")), "干净态跳第3步 → %d 理由=%r" % (s, d.get("blocked_reason"))))
s, d = call("/api/nav", {"step":6})
r.append((ok(s==400), "干净态跳第6步 → %d 理由=%r" % (s, d.get("blocked_reason"))))

# 4. 造一个真 RPG Maker 小游戏 → 选目录应自动认引擎（FR-63 回认）
tmp = tempfile.mkdtemp(prefix="rpgtest_")
os.makedirs(os.path.join(tmp,"www","data"), exist_ok=True)
os.makedirs(os.path.join(tmp,"js"), exist_ok=True)
open(os.path.join(tmp,"js","rpg_core.js"),"w").write("// x")
open(os.path.join(tmp,"www","data","Actors.json"),"w",encoding="utf-8").write(
  json.dumps([{"id":1,"name":"Alpha","description":"Hello there friend"}], ensure_ascii=False))
open(os.path.join(tmp,"www","data","MapInfos.json"),"w",encoding="utf-8").write(
  json.dumps([{"id":1,"name":"Town"}], ensure_ascii=False))
s, d = call("/api/game", {"path": tmp})
s2, st = call("/api/state")
r.append((ok(st["engine"] and st["engine"]["key"]=="rm"), "选目录后自动认引擎=%s" % (st["engine"] or {}).get("name")))
s, d = call("/api/nav", {"step":3}); r.append((ok(s==200), "有目录+引擎后进第3步 → %d" % s))
s, d = call("/api/extract", {"mode":"merge"})
r.append((ok(s==200 and d.get("added",0)>0), "真提取 → 新增 %s 条，在表 %s 条" % (d.get("added"), d.get("total"))))
s, d = call("/api/nav", {"step":5}); r.append((ok(s==200), "提取后直达第5步 → %d" % s))

# 5. FR-64 校验注入工具：逐项带 marker（判定文件）+ 路径斜杠已归一
# 注意：第 4 步造的是 RPG Maker（引擎原生机制 → 工具清单本就为空，这是对的），
# 所以这里换真 Unity 游戏目录测，才能拿到有工具包的引擎。
GAME_UNITY = r"F:\erogame\Starmaker_Story\Starmaker Story(1.8e\Starmaker 1.8E"
if os.path.isdir(GAME_UNITY):
    call("/api/game", {"path": GAME_UNITY})
    s, d = call("/api/kit/check")
    _tools = d.get("tools") or []
    r.append((ok(s==200 and _tools and all(t.get("marker") for t in _tools)),
              "FR-64 Unity 逐项校验 %d 项工具，均带判定文件" % len(_tools)))
    _paths = [d.get("sink_path") or ""] + [t.get("dest") or "" for t in _tools] + \
             [t.get("marker") or "" for t in _tools]
    r.append((ok(all("/" not in p for p in _paths if p)), "FR-64 展示路径斜杠已统一（无 // 混乱）"))
else:
    r.append((ok(False), "FR-64 未找到真 Unity 游戏目录，跳过"))

# 6. RPG Maker 走原生机制 → 工具清单为空是正确行为（不是 bug）
call("/api/game", {"path": tmp})
s, d = call("/api/kit/check")
r.append((ok(s==200 and not (d.get("tools") or [])),
          "RPG Maker 无注入工具（引擎原生机制），校验如实报告：%s" % d.get("message","")))

print("\n".join("%-4s %s" % (a, b) for a, b in r))
print("\n结果：%d/%d 通过" % (sum(1 for a,_ in r if a=="OK "), len(r)))
