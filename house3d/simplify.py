import json,math
s=json.load(open("scene.json"))
def simplify(segs,minlen,snap):
    out=set()
    for a in segs:
        x1,y1,x2,y2=a
        if math.hypot(x2-x1,y2-y1)<minlen: continue
        q=lambda v:round(v/snap)*snap
        x1,y1,x2,y2=q(x1),q(y1),q(x2),q(y2)
        if (x1,y1)==(x2,y2): continue
        key=tuple(sorted([(x1,y1),(x2,y2)]))
        out.add(key)
    return [[p[0][0],p[0][1],p[1][0],p[1][1]] for p in out]
W=simplify(s["walls"],1.0,0.25)
G=simplify(s["windows"],1.5,0.25)
def flat(a): return [round(v,2) for seg in a for v in seg]
data=dict(w=flat(W),g=flat(G),
          L=[[round(l[0],1),round(l[1],1),l[2]] for l in s["labels"]],
          h=s["wall_height"],size=s["size"])
p=json.dumps(data,separators=(",",":"))
open("payload2.json","w").write(p)
print("walls",len(W),"windows",len(G),"bytes",len(p))
