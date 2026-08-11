import time,sys,statistics,os,re
from pathlib import Path
from PIL import Image, ImageGrab
import pyperclip

MAX_BYTES=180
COLS=32
MAGIC=[75,84,48,54]
IDEAL=[31,92,163,224]
HERE=Path(__file__).resolve().parent
DEBUG=HERE/"debug_capture.png"

def save_debug(im, reason):
    try:
        im.save(DEBUG)
        print(f"[debug] {reason}. Screenshot saved: {DEBUG}")
    except Exception as e: print("[debug] save failed:",e)

def is_magenta(p):
    r,g,b=p[:3]
    return r>150 and b>120 and g<100 and r-g>80 and b-g>60

def locate_magenta(im):
    # Find magenta border; robust to resolution because we scan screenshot itself.
    # coarse -> bounds -> refine
    xs=[]; ys=[]
    step=4
    for y in range(0,im.height,step):
        for x in range(0,im.width,step):
            if is_magenta(im.getpixel((x,y))):
                xs.append(x); ys.append(y)
    if len(xs)<10:return None
    # Cluster around top-left-most dense region by using low quantiles.
    x0=max(0,min(xs)-6); y0=max(0,min(ys)-6)
    # Search a reasonable local window to get exact magenta extents.
    x1=min(im.width,x0+600); y1=min(im.height,y0+500)
    pts=[]
    for y in range(y0,y1):
        for x in range(x0,x1):
            if is_magenta(im.getpixel((x,y))): pts.append((x,y))
    if len(pts)<20:return None
    return min(x for x,y in pts),min(y for x,y in pts),max(x for x,y in pts),max(y for x,y in pts)

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
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=256)
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
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=256)
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

def translate_auto(text):
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

# Default until META from ChatFrame1 arrives.
rootui.geometry("520x220+20+20")
screen_h=rootui.winfo_screenheight()

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

def append_message(author,translation,direction="in"):
    # Auto-follow only when user is already at the bottom.
    y=text.yview()
    follow=(y[1] >= .97)
    text.configure(state="normal")

    if direction=="out":
        if author:
            text.insert("end","我 → "+author+": ","out_author")
        else:
            text.insert("end","我: ","out_author")
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
    global desired_geometry
    while events:
        kind,data=events.popleft()
        if kind=="msg_in":
            author,out=data
            append_message(author,out,"in")
        elif kind=="msg_out":
            author,out=data
            append_message(author,out,"out")
        elif kind=="meta":
            place_next_to_chat(data)
    if desired_geometry:
        w,h,x,y=desired_geometry
        rootui.geometry(f"{w}x{h}+{x}+{y}")
    rootui.after(100,poll_ui)

rootui.after(100,poll_ui)


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

def worker():
 print("WoWInterpreter Bridge 2.1", flush=True)
 print("Adaptive small-region capture; full-screen reacquire <= 0.5 Hz.")
 last=None; known_box=None; misses=0; last_scan=0.0; active_until=0.0
 def expand(box,m=16):
  l,t,r,bb=box
  return (max(0,l-m),max(0,t-m),r+m,bb+m)
 while True:
  try:
   now=time.time(); im=None; box=None
   if known_box is not None:
    roi=expand(known_box)
    im=ImageGrab.grab(bbox=roi)
    box=locate_magenta(im)
    if box: misses=0
    else: misses+=1
   if box is None and (known_box is None or misses>=4) and now-last_scan>=3.0:
    full=ImageGrab.grab(); last_scan=now
    found=locate_magenta(full)
    if found:
     known_box=found; roi=expand(found); im=full.crop(roi)
     box=locate_magenta(im); misses=0
    elif misses>=12: known_box=None
   if box is not None and im is not None:
    raw=adaptive_payload(im,box)
    if raw:
     if raw and raw!=last:
      parts=raw.split("\t",2)
      kind,author,msg=parts if len(parts)==3 else ("OUT","",raw)
      if kind=="META":
       events.append(("meta",msg))
      else:
       out,direction=translate_auto(msg)
       print("SOURCE:",repr(msg)); print(direction+":",repr(out))
       if kind=="OUT":
        pyperclip.copy(out); events.append(("msg_out",("",out)))
       elif kind=="CHATOUT":
        pyperclip.copy(out); events.append(("msg_out",(author,out)))
       else:
        events.append(("msg_in",(author,out)))
      last=raw; active_until=time.time()+2.0
    else: misses+=1
   elif known_box is not None and misses>=2:
    last=None
   time.sleep(0.10 if time.time()<active_until else (1.00 if known_box is not None else 1.00))
  except Exception as ex:
   print("ERROR:",repr(ex)); time.sleep(1.0)

threading.Thread(target=worker,daemon=True).start()
rootui.mainloop()
