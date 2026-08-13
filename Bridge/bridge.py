import time,sys,statistics,os,re
from pathlib import Path
from PIL import Image, ImageGrab
import pyperclip

from Bridge.kt07_tracker import KT07GeometryTracker

MAX_BYTES=180
COLS=32
MAGIC=[75,84,48,55]
IDEAL=[31,92,163,224]
HERE=Path(__file__).resolve().parent
DEBUG=HERE/"debug_capture.png"

def save_debug(im, reason):
    try:
        im.save(DEBUG)
        print(f"[debug] {reason}. Screenshot saved: {DEBUG}")
    except Exception as e: print("[debug] save failed:",e)


ANCHOR_COLORS=((255,0,0),(0,255,0),(0,0,255),(255,255,0),(0,255,255),(255,0,255))

def _near_color(pixel,target,tol=80):
    return all(abs(pixel[i]-target[i])<=tol for i in range(3))

# KT07 idle CPU fast path -----------------------------------------------------
KT07_IDLE_ROI=(0,0,120,45)
KT07_IDLE_INTERVAL_OPT=0.50
KT07_GENERIC_FALLBACK_EVERY=20

def fast_locate_kt07_anchor(im):
 """Cheap top-left prefilter. Return True only when RGB/YCM anchor is plausible."""
 pix=im.load(); w,h=im.size
 sig=((255,0,0),(0,255,0),(0,0,255),(255,255,0),(0,255,255),(255,0,255))
 def close(px,t,tol=45):
  return abs(px[0]-t[0])<=tol and abs(px[1]-t[1])<=tol and abs(px[2]-t[2])<=tol
 # Known physical anchor is around y=1..11 and six adjacent colour blocks.
 # Scan several plausible block widths to remain DPI tolerant.
 for block in range(8,13):
  span=block*6
  for y in range(1,min(15,h)):
   for x in range(0,min(25,w-span)):
    if all(close(pix[min(w-1,x+i*block+block//2),y],t) for i,t in enumerate(sig)):
     return True
 return False

def locate_kt07_anchor(im):
    # Fast idle rejection: crop only the tiny known anchor region from the already
    # captured image. Expensive generic scanning runs only when signature is plausible.
    try:
     if im.size[0] > KT07_IDLE_ROI[2] or im.size[1] > KT07_IDLE_ROI[3]:
      _tiny=im.crop(KT07_IDLE_ROI)
     else:
      _tiny=im
     if not fast_locate_kt07_anchor(_tiny):
      return None
    except Exception:
     pass
    """Locate ordered RGB/YCM anchor in the fixed top-left WoW UI region."""
    max_w=min(im.width,420); max_h=min(im.height,260)
    for d in range(4,17): # rendered width of one 8-UI-unit anchor block
        half=max(1,int(round(d*.25)))
        for cy in range(half,max_h-half,2):
            for cx in range(half,max_w-6*d-half,2):
                valid=True
                for i,target in enumerate(ANCHOR_COLORS):
                    px=cx+i*d
                    pts=[im.getpixel((px+sx,cy+sy))
                         for sx in (-half,0,half) for sy in (-half,0,half)
                         if 0<=px+sx<im.width and 0<=cy+sy<im.height]
                    if sum(_near_color(p,target) for p in pts)<max(3,len(pts)//2):
                        valid=False; break
                if valid:
                    scale=d/8.0; cell=d/2.0
                    left=cx-d/2.0; top=cy-d/2.0
                    ox=left+2*scale
                    oy=top+10*scale
                    box=(round(left),round(top),round(left+6*d),round(top+d))
                    return ox,oy,cell,box
    return None

def save_kt07_diagnostic(im,geo):
    """Persist evidence from the exact screenshot in which KT07 is visible."""
    try:
        ox,oy,cell,abox=geo
        path=os.path.join(os.path.dirname(__file__),"kt07_visible_capture.png")
        im.save(path)

        # Save a generous crop around anchor + expected payload.
        left=max(0,int(abox[0]-20))
        top=max(0,int(abox[1]-20))
        right=min(im.width,int(max(abox[2]+40,ox+COLS*cell+40)))
        bottom=min(im.height,int(max(abox[3]+40,oy+ROWS*cell+40)))
        crop_path=os.path.join(os.path.dirname(__file__),"kt07_visible_crop.png")
        im.crop((left,top,right,bottom)).save(crop_path)

        log_path=os.path.join(os.path.dirname(__file__),"kt07_geometry.txt")
        radius=max(12,int(round(cell*3)))
        with open(log_path,"w",encoding="utf-8") as f:
            f.write("WoWInterpreter 2.1.10 KT07 geometry diagnostic\\n")
            f.write(f"image={im.width}x{im.height}\\n")
            f.write(f"anchor_box={abox}\\n")
            f.write(f"expected_origin=({ox:.3f},{oy:.3f})\\n")
            f.write(f"detected_cell={cell:.3f}\\n")
            f.write(f"COLS={COLS} ROWS={ROWS}\\n\\n")
            f.write("Expected MAGIC sample positions / decoded bytes:\\n")
            vals=[]
            for i in range(4):
                x=ox+i*cell; y=oy
                v=read_byte(im,ox,oy,cell,i)
                vals.append(v)
                pix=im.getpixel((max(0,min(im.width-1,int(round(x+cell*.5)))),
                                 max(0,min(im.height-1,int(round(y+cell*.5))))))
                f.write(f"  byte[{i}] pos~({x:.2f},{y:.2f}) center_rgb={pix} decoded={v}\\n")
            f.write(f"decoded_magic={vals}; expected={MAGIC}\\n\\n")

            # Dump a compact RGB map around expected origin to diagnose scale/origin.
            f.write(f"RGB samples around expected origin (+/- {radius}px), 1px steps:\\n")
            for yy in range(max(0,int(oy)-radius),min(im.height,int(oy)+radius+1)):
                row=[]
                for xx in range(max(0,int(ox)-radius),min(im.width,int(ox)+radius+1)):
                    r,g,bb=im.getpixel((xx,yy))[:3]
                    row.append(f"{r:02X}{g:02X}{bb:02X}")
                f.write(f"y={yy}: "+" ".join(row)+"\\n")
        print(f"[DIAG] KT07 visible screenshot: {path}",flush=True)
        print(f"[DIAG] KT07 visible crop: {crop_path}",flush=True)
        print(f"[DIAG] KT07 geometry report: {log_path}",flush=True)
    except Exception as e:
        print("[DIAG] Failed to save KT07 diagnostic:",repr(e),flush=True)

def kt07_payload(im,geo):
    """Decode KT07 by calibrating the *symbol* grid from MAGIC.

    Important protocol detail confirmed from the addon and the 2.1.10 capture:
    one byte is encoded as FOUR grayscale symbol cells (base-4), not one cell.
    We therefore reuse read_byte()/classify() and search the small physical
    neighbourhood below the already-proven RGB/YCM anchor for the real symbol
    origin and symbol pitch.
    """
    _ox,_oy,anchor_cell,abox=geo

    # At the observed UI scale the addon CELL=4 renders near 5 physical px.
    # Search a narrow scale range so this remains robust across UI scale/DPI.
    pitches=[]
    lo=max(2.5,anchor_cell*0.65)
    hi=min(8.0,anchor_cell*1.35)
    p=lo
    while p<=hi+1e-6:
        pitches.append(round(p,2))
        p+=0.25

    # The data grid is directly below the six-block anchor. Rather than trust
    # rounded anchor-box geometry, search a compact image-space rectangle.
    left=max(0,int(abox[0]-12))
    right=min(im.width-1,int(abox[2]+12))
    top=max(0,int(abox[1]+4))
    bottom=min(im.height-1,int(abox[3]+28))

    for cell in pitches:
        # A KT07 MAGIC byte occupies 4 symbol cells; four MAGIC bytes occupy 16.
        # Avoid origins that cannot fit those symbols inside the image.
        max_x=min(right, int(im.width-16*cell-1))
        for y in range(top,bottom+1):
            for x in range(left,max_x+1):
                vals=[read_byte(im,float(x),float(y),cell,i) for i in range(4)]
                if vals != MAGIC:
                    continue
                result=payload(im,(float(x),float(y),cell))
                if result is not None:
                    print(f"[KT07] Symbol-grid calibration succeeded: origin=({x},{y}), symbol_pitch={cell:.2f}px, MAGIC={vals}.",flush=True)
                    return result

    return None


def is_magenta(p):
    r,g,b=p[:3]
    return r>150 and b>120 and g<100 and r-g>80 and b-g>60

def _magenta_components(im):
    """Return local magenta components instead of one global scenery-sized box."""
    # Coarse component search is deliberately dependency-free (Pillow only).
    step=4
    W=(im.width+step-1)//step; H=(im.height+step-1)//step
    mask=set()
    for gy,y in enumerate(range(0,im.height,step)):
        for gx,x in enumerate(range(0,im.width,step)):
            if is_magenta(im.getpixel((x,y))):
                mask.add((gx,gy))
    comps=[]
    while mask:
        seed=mask.pop(); stack=[seed]
        minx=maxx=seed[0]; miny=maxy=seed[1]; n=0
        while stack:
            x,y=stack.pop(); n+=1
            minx=min(minx,x); maxx=max(maxx,x); miny=min(miny,y); maxy=max(maxy,y)
            for q in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                if q in mask:
                    mask.remove(q); stack.append(q)
        bw=(maxx-minx+1)*step; bh=(maxy-miny+1)*step
        # Purple scenery generated 200-300px false regions in Darnassus.
        if n>=3 and bw<=180 and bh<=180:
            comps.append((minx*step,miny*step,
                          min(im.width,(maxx+1)*step),
                          min(im.height,(maxy+1)*step),n))
    return comps

def locate_magenta_candidates(im):
    """Generate local candidate boxes; colour is a hint, never the final lock."""
    comps=_magenta_components(im)
    comps.sort(key=lambda c:c[4],reverse=True)
    candidates=[]; seen=set()
    for l,t,r,bb,_ in comps[:100]:
        # Refine exact local magenta extents without merging distant scenery.
        margin=12
        x0=max(0,l-margin); y0=max(0,t-margin)
        x1=min(im.width,r+margin); y1=min(im.height,bb+margin)
        pts=[]
        for y in range(y0,y1):
            for x in range(x0,x1):
                if is_magenta(im.getpixel((x,y))): pts.append((x,y))
        if not pts: continue
        exact=(min(x for x,y in pts),min(y for x,y in pts),
               max(x for x,y in pts),max(y for x,y in pts))
        if exact not in seen:
            seen.add(exact); candidates.append(exact)
    return candidates

def locate_magenta(im):
    # Compatibility helper for the ROI/resized calibration path.
    c=locate_magenta_candidates(im)
    return c[0] if c else None

def calibrate(im,b):
    l,t,r,bot=b
    outer_w=r-l+1; outer_h=bot-t+1
    # Addon has 4 logical px border each side and 32*8 logical px data width.
    # infer physical scale from outer width, then cell size.
    scale=outer_w/(32*8+8)
    cell=8*scale
    border=4*scale
    ox=l+border; oy=t+border
    if cell<2:
        return None
    return ox,oy,cell,scale

def cell_rgb(im,ox,oy,cell,idx):
    col=idx%COLS; row=idx//COLS
    cx=ox+(col+.5)*cell; cy=oy+(row+.5)*cell
    vals=[]
    radius=max(0,int(cell*.18))
    for dy in range(-radius,radius+1):
        for dx in range(-radius,radius+1):
            x=int(round(cx+dx)); y=int(round(cy+dy))
            if 0<=x<im.width and 0<=y<im.height:
                rr,gg,bb=im.getpixel((x,y))[:3]
                if max(rr,gg,bb)-min(rr,gg,bb)<35:
                    vals.append((rr+gg+bb)//3)
    if not vals:return None
    return int(statistics.median(vals))

def classify(v):
    if v is None:return None
    return min(range(4),key=lambda i:abs(v-IDEAL[i]))

def read_byte(im,ox,oy,cell,i):
    d=[classify(cell_rgb(im,ox,oy,cell,i*4+j)) for j in range(4)]
    if any(x is None for x in d):return None
    return d[0]*64+d[1]*16+d[2]*4+d[3]

def try_offsets(im,cal):
    ox,oy,cell,scale=cal
    # Compensate for WoW/UI interpolation and border measurement rounding.
    for fy in (-.30,-.15,0,.15,.30):
      for fx in (-.30,-.15,0,.15,.30):
        x=ox+fx*cell; y=oy+fy*cell
        vals=[read_byte(im,x,y,cell,i) for i in range(4)]
        if vals==MAGIC:return x,y,cell
    return None

def payload(im,geo):
    ox,oy,cell=geo
    n=read_byte(im,ox,oy,cell,4)
    if n is None or not 0<n<=MAX_BYTES:return None
    vals=[read_byte(im,ox,oy,cell,5+i) for i in range(n)]
    if any(v is None for v in vals):return None
    got=read_byte(im,ox,oy,cell,5+n)
    exp=(sum(MAGIC)+n+sum(vals))%256
    if got!=exp:
        print("[pixel] checksum mismatch",got,exp); return None
    try:return bytes(vals).decode("utf-8")
    except UnicodeDecodeError:return None

MODEL_NAME = "facebook/nllb-200-distilled-600M"
SRC_LANG = "eng_Latn"
TGT_LANG = "zho_Hans"

tokenizer = None
model = None
torch = None

def ensure_model_loaded():
    """Load NLLB only when the first real translation is requested."""
    global tokenizer, model, torch
    if tokenizer is not None and model is not None:
        return
    print("[BRIDGE] Loading NLLB model:", MODEL_NAME, flush=True)
    print("The first translation after Start may take longer.")
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    import torch as _torch

    torch = _torch
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, src_lang=SRC_LANG)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
    model.eval()
    print("[BRIDGE] NLLB ready.", flush=True)
    # Runtime tuning after lazy NLLB/PyTorch initialization.
    try:
        import torch as _torch_runtime
        _torch_runtime.set_num_threads(2)
        _torch_runtime.set_num_interop_threads(1)
        torch = _torch_runtime
        print(f"[CPU] PyTorch configured intraop={_torch_runtime.get_num_threads()} interop={_torch_runtime.get_num_interop_threads()}",flush=True)
    except Exception as e:
        print("[CPU] PyTorch runtime configuration failed:",repr(e),flush=True)
    try:
        if getattr(model, 'generation_config', None) is not None:
            model.generation_config.max_length = None
    except Exception:
        pass

    global _cpu_nllb_loaded
    _cpu_nllb_loaded=True
    _cpu_report(force=True)
    try:
        print(f"[CPU] torch_threads intraop={torch.get_num_threads()} interop={torch.get_num_interop_threads()}",flush=True)
    except Exception as e:
        print("[CPU] torch thread query unavailable:",repr(e),flush=True)


# Keep post-processing conservative: NLLB should translate the whole sentence itself.
# Normalize only a few common WoW terms when the source explicitly contains them.
def normalize_wow_terms(source, out):
    """Normalize NLLB output only when the matching WoW concept exists in source."""
    low = source.lower()

    # Instances / group content
    if "dungeon" in low:
        for bad in ("监狱", "地牢", "地下牢", "地下监狱"):
            out = out.replace(bad, "地下城")
    if "battleground" in low or re.search(r"\bbg\b", low):
        for bad in ("战斗场", "战斗场地", "战场地", "战斗地点"):
            out = out.replace(bad, "战场")
    if "raid" in low:
        for bad in ("突袭", "袭击", "团队地牢"):
            out = out.replace(bad, "团队副本")

    # Roles
    if "healer" in low:
        for bad in ("医医", "医生", "医师", "治疗师", "治疗者"):
            out = out.replace(bad, "治疗")
    if re.search(r"\btank(s)?\b", low):
        for bad in ("坦克车", "战车"):
            out = out.replace(bad, "坦克")
    if re.search(r"\bdps\b", low):
        for bad in ("每秒伤害", "伤害输出"):
            out = out.replace(bad, "输出")

    # Common WoW actions / social terms
    if "summon" in low:
        for bad in ("召唤我", "召我", "召唤一下我"):
            out = out.replace(bad, "拉我")
    if "guild" in low:
        out = out.replace("行会", "公会")
    if "party" in low and "party" not in ("birthday party",):
        out = out.replace("聚会", "小队")

    # Classes: normalize common alternate/literal translations.
    class_terms = {
        "mage": [("魔法师","法师")],
        "warrior": [("勇士","战士")],
        "rogue": [("流氓","盗贼")],
        "warlock": [("巫师","术士")],
        "hunter": [("猎手","猎人")],
        "priest": [("祭司","牧师")],
        "paladin": [("圣武士","圣骑士")],
        "shaman": [("巫医","萨满")],
    }
    for eng, reps in class_terms.items():
        if eng in low:
            for bad,good in reps:
                out=out.replace(bad,good)

    # Major Classic cities
    cities = {
        "orgrimmar": [("奥格里玛","奥格瑞玛")],
        "stormwind": [("暴风","暴风城")],
        "ironforge": [("铁炉","铁炉堡")],
    }
    for eng,reps in cities.items():
        if eng in low:
            for bad,good in reps:
                out=out.replace(bad,good)

    # Chinese punctuation cleanup.
    out = out.replace(" ,", "，").replace(",", "，")
    out = out.replace(" .", "。")
    if out.endswith("."): out=out[:-1]+"。"
    if out.endswith("?"): out=out[:-1]+"？"
    if out.endswith("!"): out=out[:-1]+"！"
    return out.strip()

def contains_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)

def normalize_english_wow_terms(source, out):
    """Normalize Chinese WoW concepts to the terminology English WoW players use."""
    # Only apply a replacement if the corresponding Chinese concept is present
    # in the original source, to avoid changing unrelated English output.
    rules = [
        ("战场", ("battlefield", "battle field", "field of battle"), "battleground"),
        ("地下城", ("underground city", "underground dungeon", "instance"), "dungeon"),
        ("团队副本", ("team copy", "team dungeon", "group copy"), "raid"),
        ("治疗", ("treatment", "therapy", "healing person", "healing"), "healer"),
        ("坦克", ("tank vehicle",), "tank"),
        ("输出", ("output", "damage output"), "DPS"),
        ("公会", ("association", "society"), "guild"),
        ("小队", ("small team", "squad"), "party"),
        ("法师", ("magician", "wizard"), "mage"),
        ("战士", ("fighter",), "warrior"),
        ("牧师", ("pastor", "clergyman"), "priest"),
        ("盗贼", ("thief", "bandit"), "rogue"),
        ("术士", ("sorcerer",), "warlock"),
        ("猎人", ("huntsman",), "hunter"),
        ("德鲁伊", ("druid",), "druid"),
        ("圣骑士", ("holy knight",), "paladin"),
        ("萨满", ("shaman",), "shaman"),
    ]
    low_source=source.lower()
    for zh,bads,good in rules:
        if zh in source:
            for bad in bads:
                out=re.sub(r"\b"+re.escape(bad)+r"\b",good,out,flags=re.I)

    # Particularly common NLLB outputs for 战场.
    if "战场" in source:
        out=re.sub(r"\bthe battlefield\b","the battleground",out,flags=re.I)
        out=re.sub(r"\bbattlefield\b","battleground",out,flags=re.I)

    # Natural English punctuation/spacing.
    out=re.sub(r"\s+([?.!,])",r"\1",out)
    return out.strip()

def translate_en_to_zh(text):
    ensure_model_loaded()
    tokenizer.src_lang = "eng_Latn"
    inputs = tokenizer(text, return_tensors="pt", truncation=True)
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids("zho_Hans"),
            max_new_tokens=256,
            num_beams=4,
            early_stopping=True
        )
    out = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
    return normalize_wow_terms(text, out)

def translate_zh_to_en(text):
    ensure_model_loaded()
    tokenizer.src_lang = "zho_Hans"
    inputs = tokenizer(text, return_tensors="pt", truncation=True)
    with torch.no_grad():
        generated = model.generate(
            **inputs,
            forced_bos_token_id=tokenizer.convert_tokens_to_ids("eng_Latn"),
            max_new_tokens=256,
            num_beams=4,
            early_stopping=True
        )
    out = tokenizer.batch_decode(generated, skip_special_tokens=True)[0]
    return normalize_english_wow_terms(text, out)

def _strip_kt07_envelope(text):
    """Return only the user payload from KT07 OUT records.

    KT07 transports outgoing text as: OUT<TAB>author<TAB>payload.
    /wi can also feed that record back to the bridge. Translation must never
    send the OUT/author envelope to NLLB.
    """
    if not isinstance(text, str):
        return text
    # Split at most twice so tabs inside the actual message remain untouched.
    parts=text.split("\t",2)
    if len(parts)==3 and parts[0].strip().upper()=="OUT":
        return parts[2].strip()
    return text.strip()

def translate_auto(text):
    text=_strip_kt07_envelope(text)
    if contains_chinese(text):
        return translate_zh_to_en(text), "ZH→EN"
    return translate_en_to_zh(text), "EN→ZH"

import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import threading
from collections import deque
print("[BRIDGE] Module imports complete.", flush=True)

events=deque()
desired_geometry=None
screen_h=None

rootui=tk.Tk()
rootui.title("WoWInterpreter")
rootui.attributes("-topmost",True)
try: rootui.attributes("-alpha",0.90)
except: pass
rootui.configure(bg="#101010")

def close_overlay():
    """Closing the overlay is equivalent to Stop Translator."""
    print("[BRIDGE] Overlay closed by user; stopping translator process.",flush=True)
    try:
        rootui.quit()
        rootui.destroy()
    finally:
        # The capture/translation worker can still be alive after Tk exits.
        # Terminate the bridge child explicitly so the tray observes STOPPED
        # and Windows releases the preloaded NLLB/PyTorch memory immediately.
        os._exit(0)

rootui.protocol("WM_DELETE_WINDOW",close_overlay)

# Default until META from ChatFrame1 arrives.
rootui.geometry("520x220+20+20")
screen_h=rootui.winfo_screenheight()

# KT07 capture safety ---------------------------------------------------------
# Users may freely move/resize the overlay. We intervene only after a manual
# movement settles AND the final window rectangle actually overlaps KT07.
KT07_PROTECTED_RECT=(0,0,215,180)  # full observed KT07 frame + safety margin
KT07_SAFE_MARGIN=12
_overlay_guard_after=None
_programmatic_geometry=False
_user_has_positioned_overlay=False

def _overlay_rect():
    rootui.update_idletasks()
    x=rootui.winfo_x(); y=rootui.winfo_y()
    w=max(1,rootui.winfo_width()); h=max(1,rootui.winfo_height())
    return x,y,x+w,y+h

def _rects_overlap(a,b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])

def _safe_geometry(w,h,x,y):
    """Return the nearest non-overlapping overlay position.

    The user keeps full freedom everywhere except the complete KT07 transport
    rectangle. If overlap occurs, choose the smallest valid displacement among
    right/below (and left/above when usable), rather than always jumping right.
    """
    w,h,x,y=int(w),int(h),int(x),int(y)
    if not _rects_overlap((x,y,x+w,y+h),KT07_PROTECTED_RECT):
        return w,h,x,y

    sw=rootui.winfo_screenwidth(); sh=rootui.winfo_screenheight()
    px1,py1,px2,py2=KT07_PROTECTED_RECT
    candidates=[]

    def add(nx,ny):
        nx=int(max(0,min(nx,max(0,sw-w))))
        ny=int(max(0,min(ny,max(0,sh-h))))
        rect=(nx,ny,nx+w,ny+h)
        if not _rects_overlap(rect,KT07_PROTECTED_RECT):
            dist=(nx-x)*(nx-x)+(ny-y)*(ny-y)
            candidates.append((dist,nx,ny))

    # Just outside each protected edge.
    add(px2+KT07_SAFE_MARGIN, y)          # right
    add(x, py2+KT07_SAFE_MARGIN)          # below
    add(px1-KT07_SAFE_MARGIN-w, y)        # left
    add(x, py1-KT07_SAFE_MARGIN-h)        # above

    if candidates:
        _,nx,ny=min(candidates,key=lambda c:c[0])
        return w,h,nx,ny

    # Conservative fallback for unusually large windows/screens.
    nx=max(0,min(px2+KT07_SAFE_MARGIN,max(0,sw-w)))
    ny=max(0,min(py2+KT07_SAFE_MARGIN,max(0,sh-h)))
    return w,h,nx,ny


def _apply_overlay_geometry(w,h,x,y):
    global _programmatic_geometry
    w,h,x,y=_safe_geometry(int(w),int(h),int(x),int(y))
    try:
        _programmatic_geometry=True
        rootui.geometry(f"{w}x{h}+{x}+{y}")
    finally:
        rootui.after(120,lambda: _clear_programmatic_geometry())
    return w,h,x,y

def _clear_programmatic_geometry():
    global _programmatic_geometry
    _programmatic_geometry=False

def _guard_after_manual_move():
    global desired_geometry,_user_has_positioned_overlay
    rect=_overlay_rect()
    w=rect[2]-rect[0]; h=rect[3]-rect[1]
    safe=_safe_geometry(w,h,rect[0],rect[1])
    _user_has_positioned_overlay=True
    # A manual position wins over automatic META placement from now on.
    desired_geometry=None
    if safe != (w,h,rect[0],rect[1]):
        _apply_overlay_geometry(*safe)
        print(f"[OVERLAY] KT07 area protected; overlay adjusted to ({safe[2]},{safe[3]}).",flush=True)

def _on_overlay_configure(_event=None):
    global _overlay_guard_after
    if _programmatic_geometry:
        return
    # Debounce Configure events: do not fight the mouse while dragging.
    try:
        if _overlay_guard_after is not None:
            rootui.after_cancel(_overlay_guard_after)
    except Exception:
        pass
    _overlay_guard_after=rootui.after(300,_guard_after_manual_move)

rootui.bind("<Configure>",_on_overlay_configure,add="+")

header=tk.Frame(rootui,bg="#181818",height=26)
header.pack(fill="x")
title=tk.Label(header,text="WoWInterpreter  英文 → 中文",bg="#181818",fg="#8fd3ff",
               font=("Microsoft YaHei UI",10,"bold"))
title.pack(side="left",padx=7,pady=3)

text=ScrolledText(rootui,wrap="word",bg="#101010",fg="#f2f2f2",
                  insertbackground="white",font=("Microsoft YaHei UI",11),
                  relief="flat",borderwidth=0,padx=8,pady=6)
text.pack(fill="both",expand=True)
text.configure(state="disabled")
text.tag_configure("in_author",foreground="#ffd36a")
text.tag_configure("in_text",foreground="#ffffff")
text.tag_configure("out_author",foreground="#6ee7a8")
text.tag_configure("out_text",foreground="#9fffc9")
text.tag_configure("system",foreground="#8fd3ff")

def append_message(author,translation,direction="in",translation_direction=None):
    # Auto-follow only when user is already at the bottom.
    y=text.yview()
    follow=(y[1] >= .97)
    text.configure(state="normal")

    if direction=="out":
        # Label the local user in their source language:
        # EN→ZH means an English-speaking user; ZH→EN means a Chinese-speaking user.
        self_label="我" if translation_direction=="ZH→EN" else "Me"
        if author:
            text.insert("end",self_label+" → "+author+": ","out_author")
        else:
            text.insert("end",self_label+": ","out_author")
        text.insert("end",translation+"\n","out_text")
    else:
        if author:
            text.insert("end",author+": ","in_author")
        text.insert("end",translation+"\n","in_text")

    # Keep roughly the last 500 lines.
    lines=int(text.index("end-1c").split(".")[0])
    if lines>500:
        text.delete("1.0",f"{lines-500}.0")
    text.configure(state="disabled")
    if follow:
        text.see("end")

def place_next_to_chat(meta):
    global desired_geometry
    try:
        left,bottom,w,h,scale=map(float,meta.split(","))
        # Convert WoW UI coords to physical screen pixels.
        x=int(round(left*scale))
        chat_bottom_px=int(round(bottom*scale))
        ww=max(300,int(round(w*scale)))
        hh=max(120,int(round(h*scale)))
        # Windows origin is top-left.
        chat_top=screen_h-int(round((bottom+h)*scale))
        gap=6

        # Preferred: directly ABOVE ChatFrame1 with same width, never overlapping.
        overlay_h=min(max(150,hh),300)
        y=chat_top-overlay_h-gap
        if y>=0:
            desired_geometry=(ww,overlay_h,x,y)
        else:
            # Not enough room above: put to the RIGHT; if no room, LEFT.
            right=x+ww+gap
            sw=rootui.winfo_screenwidth()
            side_w=ww
            if right+side_w<=sw:
                desired_geometry=(side_w,hh,right,chat_top)
            else:
                lx=x-side_w-gap
                if lx>=0: desired_geometry=(side_w,hh,lx,chat_top)
                else:
                    # Last resort: above screen bottom-safe with minimal overlap avoidance.
                    desired_geometry=(ww,min(160,hh),x,max(0,chat_top-min(160,hh)-gap))
    except Exception as e:
        print("[overlay] invalid META:",repr(e),repr(meta))

def poll_ui():
    _ui_t0=time.perf_counter()
    global desired_geometry
    while events:
        kind,data=events.popleft()
        if kind=="msg_in":
            author,out=data
            append_message(author,out,"in")
        elif kind=="msg_out":
            author,out,translation_direction=data
            append_message(author,out,"out",translation_direction)
        elif kind=="meta":
            if not _user_has_positioned_overlay:
                place_next_to_chat(data)
    if desired_geometry and not _user_has_positioned_overlay:
        w,h,x,y=desired_geometry
        desired_geometry=_apply_overlay_geometry(w,h,x,y)
    _perf_add("ui_poll",time.perf_counter()-_ui_t0)
    rootui.after(200,poll_ui)

rootui.after(200,poll_ui)


def adaptive_matrix_geometry(im, locator_box):
    """
    Estimate rendered matrix geometry from the locator itself.
    No fixed monitor resolution, Windows DPI or WoW UI scale is assumed.
    KT06 has 32 columns; the magenta locator tightly surrounds the matrix.
    Returns (cell_pitch, data_origin_x, data_origin_y).
    """
    l,t,r,bb=locator_box
    w=max(1,r-l)
    h=max(1,bb-t)

    # Locator includes a small border. Estimate pitch from both dimensions.
    # The payload grid has COLS columns; rows are derived from FRAME_BYTES.
    rows=(DATA_CELLS + COLS - 1)//COLS if "DATA_CELLS" in globals() else None
    # Existing bridge constants may use lowercase names; infer rows from visual aspect if needed.
    pitch_x=w/float(COLS)
    if rows:
        pitch_y=h/float(rows)
        pitch=max(1.0,min(pitch_x,pitch_y))
    else:
        pitch=max(1.0,pitch_x)

    # Search a few plausible border offsets and let the proven KT06 calibration
    # validate which sampling lattice is correct.
    return pitch

def adaptive_calibrate(im, box):
    """Try the existing robust calibration first, then scale-aware nearby candidates."""
    cal=calibrate(im,box)
    if cal:
        geo=try_offsets(im,cal)
        if geo: return geo

    l,t,r,bb=box
    pitch=adaptive_matrix_geometry(im,box)
    # The existing decoder's calibration object is implementation-specific.
    # Probe resized views around common effective pitches so its validated KT06
    # magic/checksum remains the final authority rather than accepting guesses.
    candidates=[]
    for target in (4.0,8.0):
        scale=target/max(1.0,pitch)
        if 0.45 <= scale <= 3.0:
            nw=max(1,int(round(im.width*scale)))
            nh=max(1,int(round(im.height*scale)))
            candidates.append((scale,im.resize((nw,nh),Image.Resampling.NEAREST)))
    for scale,view in candidates:
        sb=locate_magenta(view)
        if not sb: continue
        c=calibrate(view,sb)
        g=try_offsets(view,c) if c else None
        if g:
            return ("RESIZED",scale,view,g)
    return None

def adaptive_payload(im, box):
    result=adaptive_calibrate(im,box)
    if not result: return None
    if isinstance(result,tuple) and len(result)==4 and result[0]=="RESIZED":
        return payload(result[2],result[3])
    return payload(im,result)

# Actual Bridge process CPU diagnostics
_cpu_last_wall=time.perf_counter()
_cpu_last_proc=time.process_time()
_cpu_nllb_loaded=False

def _cpu_report(force=False):
 global _cpu_last_wall,_cpu_last_proc
 nw=time.perf_counter(); np=time.process_time()
 wall=nw-_cpu_last_wall
 if not force and wall<10.0: return
 cpu=np-_cpu_last_proc
 phase="NLLB_LOADED" if _cpu_nllb_loaded else "PRE_NLLB"
 print(f"[CPU] phase={phase} one_core={cpu/wall*100.0:.2f}% cpu_time={cpu:.3f}s wall={wall:.1f}s threads={threading.active_count()}",flush=True)
 _cpu_last_wall=nw; _cpu_last_proc=np

# Lightweight performance diagnostics
_perf_lock=threading.Lock()
_perf={}
_perf_last_report=time.perf_counter()
def _perf_add(name,elapsed):
 try:
  with _perf_lock:
   row=_perf.setdefault(name,[0.0,0]); row[0]+=elapsed; row[1]+=1
 except Exception: pass
def _perf_report():
 global _perf_last_report
 now=time.perf_counter()
 if now-_perf_last_report < 10.0: return
 with _perf_lock:
  snap=dict(_perf); _perf.clear()
 interval=now-_perf_last_report; _perf_last_report=now
 total=sum(v[0] for v in snap.values())
 parts=[f"{k}={v[0]*1000:.0f}ms/{v[1]}" for k,v in sorted(snap.items(),key=lambda kv:kv[1][0],reverse=True)]
 print(f"[PERF] {interval:.1f}s window; measured={total/interval*100:.1f}% wall; "+" ".join(parts),flush=True)

# Capture performance
KT07_CAPTURE_BOX=(0,0,360,260)
KT07_IDLE_INTERVAL=0.30
KT07_ACTIVE_INTERVAL=0.045
KT07_BURST_INTERVAL=0.025

def _grab_kt07_region():
 t0=time.perf_counter()
 im=ImageGrab.grab(bbox=KT07_CAPTURE_BOX)
 _perf_add("capture",time.perf_counter()-t0)
 return im

def worker():
 print("WoWInterpreter Bridge 2.1.34",flush=True)
 print("KT07 adaptive validated geometry tracking.",flush=True)

 last=None
 last_diag=0.0
 debug_saved=False

 tracker=KT07GeometryTracker(
  local_after=2,
  unlock_after=5,
  exhaustive_after=9,
 )

 # Anchor information is a calibration hint only.
 # It is NEVER sufficient to lock geometry.
 anchor_box=None
 anchor_pitch=None

 def diag(msg):
  nonlocal last_diag
  now=time.time()
  if now-last_diag>=5:
   print("[CAPTURE] "+msg,flush=True)
   last_diag=now

 print(
  f"[CAPTURE] Screen size: "
  f"{rootui.winfo_screenwidth()}x{rootui.winfo_screenheight()}",
  flush=True,
 )
 print(
  f"[CAPTURE] KT07 ROI: {KT07_CAPTURE_BOX}; "
  f"idle={KT07_IDLE_INTERVAL:.2f}s "
  f"active={KT07_ACTIVE_INTERVAL:.3f}s",
  flush=True,
 )
 print(
  "[CAPTURE] Waiting for KT07 RGB/YCM anchor...",
  flush=True,
 )

 try:
  print("[BRIDGE] Preloading translator model...",flush=True)
  ensure_model_loaded()
  print("[BRIDGE] Translator ready.",flush=True)
 except Exception as e:
  print(
   "[BRIDGE] Translator preload failed:",
   repr(e),
   flush=True,
  )

 while True:
  try:
   raw=None
   result=None

   # ---------------------------------------------------------
   # LOCKED
   # ---------------------------------------------------------
   # Once a complete KT07 frame has validated, capture the full
   # screen and use decode_at() through the tracker's fast path.
   #
   # The anchor is not searched again on every frame.
   # ---------------------------------------------------------

   if tracker.locked:
    _t=time.perf_counter()
    im=ImageGrab.grab()
    _perf_add(
     "capture_full",
     time.perf_counter()-_t,
    )

    _t=time.perf_counter()
    result=tracker.decode(
     im,
     anchor_box,
     anchor_pitch,
    )
    _perf_add(
     "decode",
     time.perf_counter()-_t,
    )

    raw=result.text

    if result.state=="fast":
     debug_saved=False

    elif result.state=="transient":
     diag(
      "KT07 validated geometry missed one frame; "
      "keeping lock."
     )

    elif result.state=="local-recalibrated":
     print(
      "[KT07] Geometry locally recalibrated: "
      f"{result.geometry}",
      flush=True,
     )
     debug_saved=False

    elif result.state=="local-miss":
     diag(
      "KT07 local recalibration missed; "
      "validated geometry retained temporarily."
     )

    elif result.state=="unlocked":
     print(
      "[KT07] Validated geometry lost after "
      "repeated decode failures; reacquiring anchor.",
      flush=True,
     )

   # ---------------------------------------------------------
   # UNLOCKED
   # ---------------------------------------------------------
   # Cheap tiny ROI first. Only when the RGB/YCM anchor looks
   # plausible do we pay for a full-screen capture.
   #
   # Crucially: finding the anchor DOES NOT lock geometry.
   # The tracker locks only if decode_near_anchor() validates
   # the complete KT07 frame.
   # ---------------------------------------------------------

   else:
    _t=time.perf_counter()
    idle_im=ImageGrab.grab(bbox=KT07_IDLE_ROI)
    _perf_add(
     "capture_idle_roi",
     time.perf_counter()-_t,
    )

    anchor_plausible=fast_locate_kt07_anchor(idle_im)

    if anchor_plausible:
     _t=time.perf_counter()
     im=ImageGrab.grab()
     _perf_add(
      "capture_payload_full",
      time.perf_counter()-_t,
     )

     _t=time.perf_counter()
     found=locate_kt07_anchor(im)
     _perf_add(
      "anchor",
      time.perf_counter()-_t,
     )

     if found is not None:
      ox,oy,cell,box=found

      anchor_box=box
      anchor_pitch=cell

      _t=time.perf_counter()
      result=tracker.decode(
       im,
       anchor_box,
       anchor_pitch,
      )
      _perf_add(
       "calibration",
       time.perf_counter()-_t,
      )

      raw=result.text

      if result.state in (
       "calibrated",
       "exhaustive-calibrated",
      ):
       print(
        "[KT07] Frame validated; geometry locked: "
        f"{result.geometry}",
        flush=True,
       )
       debug_saved=False

      elif result.state=="calibration-miss":
       diag(
        "KT07 anchor found but complete frame "
        "has not validated yet."
       )

      elif result.state=="exhaustive-miss":
       diag(
        "KT07 exhaustive calibration found no "
        "valid MAGIC/length/checksum/UTF-8 frame."
       )

     else:
      diag(
       "KT07 anchor prefilter matched but robust "
       "anchor detection failed."
      )

    else:
     im=idle_im

     diag(
      "KT07 anchor not found in top-left UI region."
     )

     if not debug_saved:
      save_debug(
       im,
       "KT07 anchor not found",
      )
      debug_saved=True

   # ---------------------------------------------------------
   # VALID TRANSPORT FRAME
   # ---------------------------------------------------------

   if raw:
    if raw!=last:
     parts=raw.split("\t",2)

     kind,author,msg=(
      parts
      if len(parts)==3
      else ("OUT","",raw)
     )

     if kind=="META":
      events.append(("meta",msg))
     else:
      out,direction=translate_auto(msg)

      print("SOURCE:",repr(msg),flush=True)
      print(direction+":",repr(out),flush=True)

      if kind=="OUT":
       pyperclip.copy(out)
       events.append(
        ("msg_out",("",out,direction))
       )

      elif kind=="CHATOUT":
       pyperclip.copy(out)
       events.append(
        ("msg_out",(author,out,direction))
       )

      else:
       events.append(
        ("msg_in",(author,out))
       )

     last=raw

   else:
    # Only clear duplicate suppression after the validated
    # transport geometry has genuinely disappeared.
    if not tracker.locked:
     last=None

   _perf_report()
   _cpu_report()

   time.sleep(
    KT07_ACTIVE_INTERVAL
    if tracker.locked
    else KT07_IDLE_INTERVAL_OPT
   )

  except Exception as e:
   print("ERROR:",repr(e),flush=True)
   time.sleep(.3)

threading.Thread(target=worker,daemon=True).start()
rootui.mainloop()
