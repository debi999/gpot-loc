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
r.append((ok(s==200 and "运行日志" in txt and "G-POT 翻译器 v0.5.1" in txt), "logs 端点 %d，有版本行=%s" % (s, "G-POT" in txt)))
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

print("\n".join("%-4s %s" % (a, b) for a, b in r))
print("\n结果：%d/%d 通过" % (sum(1 for a,_ in r if a=="OK "), len(r)))
