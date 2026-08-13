"""Adaptive KT07 symbol-grid decoder."""
from dataclasses import dataclass
import statistics
MAX_BYTES=180; COLS=32; MAGIC=(75,84,48,55); IDEAL=(31,92,163,224)
@dataclass(frozen=True)
class Geometry:
    x: float; y: float; pitch: float
def _classify(v):
    return None if v is None else min(range(4),key=lambda i:abs(v-IDEAL[i]))
def _symbol_value(im,g,idx):
    col,row=idx%COLS,idx//COLS; cx=g.x+(col+.5)*g.pitch; cy=g.y+(row+.5)*g.pitch
    vals=[]; radius=max(0,int(g.pitch*.18))
    for dy in range(-radius,radius+1):
      for dx in range(-radius,radius+1):
        x=int(round(cx+dx)); y=int(round(cy+dy))
        if 0<=x<im.width and 0<=y<im.height:
          r,gg,b=im.getpixel((x,y))[:3]
          if max(r,gg,b)-min(r,gg,b)<35: vals.append((r+gg+b)//3)
    return int(statistics.median(vals)) if vals else None
def read_byte(im,g,i):
    d=[_classify(_symbol_value(im,g,i*4+j)) for j in range(4)]
    return None if any(x is None for x in d) else d[0]*64+d[1]*16+d[2]*4+d[3]
def decode_at(im,g):
    if tuple(read_byte(im,g,i) for i in range(4))!=MAGIC:return None
    n=read_byte(im,g,4)
    if n is None or not 0<n<=MAX_BYTES:return None
    vals=[read_byte(im,g,5+i) for i in range(n)]
    if any(v is None for v in vals):return None
    if read_byte(im,g,5+n)!=(sum(MAGIC)+n+sum(vals))%256:return None
    try:return bytes(vals).decode('utf-8')
    except UnicodeDecodeError:return None
def decode_near_anchor(im,anchor_box,anchor_symbol_pitch):
    l,t,r,b=anchor_box; p=max(2.0,anchor_symbol_pitch*.55); pmax=min(10.0,anchor_symbol_pitch*1.55)
    while p<=pmax+1e-9:
      pitch=round(p,3); maxx=min(im.width-1,int(r+16),int(im.width-16*pitch-1))
      for y in range(max(0,int(t+2)),min(im.height-1,int(b+36))+1):
       for x in range(max(0,int(l-16)),maxx+1):
        g=Geometry(float(x),float(y),pitch)
        if tuple(read_byte(im,g,i) for i in range(4))==MAGIC:
         decoded=decode_at(im,g)
         if decoded is not None:return decoded,g
      p+=.25
    return None
