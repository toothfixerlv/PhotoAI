import ezdxf, numpy as np, json
doc=ezdxf.readfile("house.dxf"); msp=doc.modelspace()

# main plan region (rectilinear core + angled wing)
X0,X1,Y0,Y1=-84800,-82850,-7150,-5900
def inb(x,y): return X0<=x<=X1 and Y0<=y<=Y1

WALL={'EXWALLS','NEWALLS1','NEWALLS2'}
WIN={'NEWINDOW1','EXWINDOW','B2WINDOWS'}
DOOR={'EXDOORS'}
ROOMS={'PANTRY','MASTER BEDROOM','MASTER BATH','FAMILY ROOM','BEDROOM','HALL',
       'GARAGE','LIVING ROOM','DINING','UTILITY','WARD.','BATH','KITCHEN','P.K.'}

walls=[]; wins=[]; doors=[]; labels=[]
for e in msp:
    t=e.dxftype(); lay=e.dxf.layer
    if t=='LINE':
        s=(e.dxf.start.x,e.dxf.start.y); en=(e.dxf.end.x,e.dxf.end.y)
        if not(inb(*s) or inb(*en)): continue
        seg=[s[0],s[1],en[0],en[1]]
        if lay in WALL: walls.append(seg)
        elif lay in WIN: wins.append(seg)
        elif lay in DOOR: doors.append(seg)
    elif t=='TEXT' and lay=='ROOMNAME':
        ix,iy=e.dxf.insert.x,e.dxf.insert.y
        if inb(ix,iy) and e.dxf.text.strip() in ROOMS:
            labels.append([ix,iy,e.dxf.text.strip()])

# center & convert inches->feet
allx=[c for s in walls for c in (s[0],s[2])]
ally=[c for s in walls for c in (s[1],s[3])]
cx=(min(allx)+max(allx))/2; cy=(min(ally)+max(ally))/2
def tx(x): return round((x-cx)/12.0,3)
def ty(y): return round((y-cy)/12.0,3)
def conv(arr): return [[tx(a[0]),ty(a[1]),tx(a[2]),ty(a[3])] for a in arr]
def filt(arr):  # drop zero-length & dedup
    out=[];seen=set()
    for a in arr:
        if abs(a[0]-a[2])<0.02 and abs(a[1]-a[3])<0.02: continue
        k=(round(a[0],2),round(a[1],2),round(a[2],2),round(a[3],2))
        if k in seen: continue
        seen.add(k); out.append(a)
    return out
W=filt(conv(walls)); G=filt(conv(wins)); D=filt(conv(doors))
LB=[[tx(l[0]),ty(l[1]),l[2]] for l in labels]
scene=dict(walls=W,windows=G,doors=D,labels=LB,
           size=[round((max(allx)-min(allx))/12,1),round((max(ally)-min(ally))/12,1)],
           wall_height=9.0)
json.dump(scene,open("scene.json","w"))
print("walls:",len(W),"windows:",len(G),"doors:",len(D),"labels:",len(LB))
print("footprint (ft):",scene["size"])
print("labels:",[l[2] for l in LB])
print("json bytes:",len(open("scene.json").read()))
