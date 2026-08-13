local KT=CreateFrame("Frame","WoWInterpreterFrame",UIParent)
local MAX_BYTES=180
local COLS=32
local CELL=4
local ANCHOR_H=8
local MAGIC={75,84,48,55} -- KT07
local levels={0.12,0.36,0.64,0.88}
local FRAME_BYTES=5+MAX_BYTES+1
local DATA_CELLS=FRAME_BYTES*4
local ROWS=math.ceil(DATA_CELLS/COLS)
local cells={}

KT:SetSize(COLS*CELL+4,ROWS*CELL+4+ANCHOR_H)
KT:SetPoint("TOPLEFT",UIParent,"TOPLEFT",2,-2)
KT:SetFrameStrata("TOOLTIP")
KT:Hide()

local bg=KT:CreateTexture(nil,"BACKGROUND")
bg:SetAllPoints(); bg:SetColorTexture(0,0,0,1)

-- KT07: deterministic RGB/YCM visual anchor. World colours are irrelevant.
local anchorColors={{1,0,0},{0,1,0},{0,0,1},{1,1,0},{0,1,1},{1,0,1}}
for i,c in ipairs(anchorColors) do
 local a=KT:CreateTexture(nil,"OVERLAY")
 a:SetSize(ANCHOR_H,ANCHOR_H)
 a:SetPoint("TOPLEFT",KT,"TOPLEFT",2+(i-1)*ANCHOR_H,-2)
 a:SetColorTexture(c[1],c[2],c[3],1)
end

local inner=CreateFrame("Frame",nil,KT)
inner:SetSize(COLS*CELL,ROWS*CELL)
inner:SetPoint("TOPLEFT",KT,"TOPLEFT",2,-(2+ANCHOR_H))

for i=1,COLS*ROWS do
 local t=inner:CreateTexture(nil,"OVERLAY")
 t:SetSize(CELL,CELL)
 local z=i-1; local col=z%COLS; local row=math.floor(z/COLS)
 t:SetPoint("TOPLEFT",inner,"TOPLEFT",col*CELL,-row*CELL)
 t:SetColorTexture(0,0,0,1); cells[i]=t
end

local function sym(i,n)
 local v=levels[n+1]; cells[i]:SetColorTexture(v,v,v,1)
end
local function byte(i,b)
 local k=(i-1)*4+1
 sym(k,math.floor(b/64)%4); sym(k+1,math.floor(b/16)%4)
 sym(k+2,math.floor(b/4)%4); sym(k+3,b%4)
end
local function checksum(s)
 local c=0
 for _,v in ipairs(MAGIC) do c=(c+v)%256 end
 c=(c+#s)%256
 for i=1,#s do c=(c+string.byte(s,i))%256 end
 return c
end
local function hide()
 KT:Hide()
end
local function publish(text)
 if not text or text=="" then print("|cff33ff99KT:|r /kt <text>"); return end
 if #text>MAX_BYTES then print("|cffff5555KT:|r max "..MAX_BYTES.." bytes"); return end
 for i=1,#cells do cells[i]:SetColorTexture(0,0,0,1) end
 local bi=1
 for _,v in ipairs(MAGIC) do byte(bi,v); bi=bi+1 end
 byte(bi,#text); bi=bi+1
 for i=1,#text do byte(bi,string.byte(text,i)); bi=bi+1 end
 byte(bi,checksum(text))
 KT:Show()
 -- debug output intentionally suppressed in v1.3
 C_Timer.After(3.0,hide)
end
local queue={}
local busy=false
local incomingEnabled=true
local translateMode="manual"
local recentMessages={}
local MAX_RECENT=50

local function queuePayload(kind,author,text)
 local payload=kind.."\t"..(author or "").."\t"..text
 if #payload>MAX_BYTES then
  local room=MAX_BYTES-#kind-#(author or "")-2
  text=string.sub(text,1,math.max(1,room))
  payload=kind.."\t"..(author or "").."\t"..text
 end
 table.insert(queue,payload)
 if not busy then
  local function pump()
   if #queue==0 then busy=false return end
   busy=true
   local p=table.remove(queue,1)
   publish(p)
   C_Timer.After(3.2,pump)
  end
  pump()
 end
end

local events={"CHAT_MSG_SAY","CHAT_MSG_YELL","CHAT_MSG_PARTY","CHAT_MSG_PARTY_LEADER",
"CHAT_MSG_RAID","CHAT_MSG_RAID_LEADER","CHAT_MSG_GUILD","CHAT_MSG_WHISPER","CHAT_MSG_WHISPER_INFORM"}
for _,e in ipairs(events) do KT:RegisterEvent(e) end

KT:SetScript("OnEvent",function(self,event,msg,author)
 if not msg or msg=="" then return end
 local letters=select(2,msg:gsub("[A-Za-z]",""))
 local chinese=msg:find("[\228-\233]") ~= nil
 if letters<2 and not chinese then return end

 if event=="CHAT_MSG_WHISPER_INFORM" then
   -- Outgoing normal whisper: only automatic mode sends it to Bridge.
   if incomingEnabled and translateMode=="auto" then
     queuePayload("CHATOUT",author or "?",msg)
   end
   return
 end

 -- Incoming messages are cheap to remember in Lua; no Bridge work in manual mode.
 local channelMap={
   CHAT_MSG_SAY="SAY",
   CHAT_MSG_YELL="YELL",
   CHAT_MSG_PARTY="PARTY",
   CHAT_MSG_PARTY_LEADER="PARTY",
   CHAT_MSG_RAID="RAID",
   CHAT_MSG_RAID_LEADER="RAID",
   CHAT_MSG_GUILD="GUILD",
   CHAT_MSG_WHISPER="WHISPER"
 }
 table.insert(recentMessages,{
   author=author or "?",
   msg=msg,
   event=event,
   channel=channelMap[event] or "CHAT"
 })
 if #recentMessages>MAX_RECENT then table.remove(recentMessages,1) end

 if incomingEnabled and translateMode=="auto" then
   queuePayload("IN",author or "?",msg)
 end
end)


-- Manual message picker -------------------------------------------------------
local picker=CreateFrame("Frame","WoWInterpreterMessagePicker",UIParent,"BackdropTemplate")
picker:SetSize(650,350)
picker:SetFrameStrata("DIALOG")
picker:SetClampedToScreen(true)
picker:SetMovable(true)
picker:EnableMouse(true)
picker:RegisterForDrag("LeftButton")
picker:SetScript("OnDragStart",picker.StartMoving)
picker:SetScript("OnDragStop",picker.StopMovingOrSizing)
picker:SetBackdrop({
 bgFile="Interface\\DialogFrame\\UI-DialogBox-Background",
 edgeFile="Interface\\DialogFrame\\UI-DialogBox-Border",
 tile=true,tileSize=32,edgeSize=24,
 insets={left=7,right=7,top=7,bottom=7}
})
picker:Hide()

local pickerTitle=picker:CreateFontString(nil,"OVERLAY","GameFontNormalLarge")
pickerTitle:SetPoint("TOPLEFT",16,-14)
pickerTitle:SetText("Translate message")

local pickerHint=picker:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
pickerHint:SetPoint("TOPLEFT",pickerTitle,"BOTTOMLEFT",0,-5)
pickerHint:SetText("Select a recent message to translate")

local close=CreateFrame("Button",nil,picker,"UIPanelCloseButton")
close:SetPoint("TOPRIGHT",-5,-5)

local scroll=CreateFrame("ScrollFrame","WoWInterpreterPickerScroll",picker,"UIPanelScrollFrameTemplate")
scroll:SetPoint("TOPLEFT",14,-58)
scroll:SetPoint("BOTTOMRIGHT",-34,14)

local content=CreateFrame("Frame",nil,scroll)
content:SetSize(500,1)
scroll:SetScrollChild(content)

local rows={}
local ROW_H=34
local MAX_VISIBLE_HISTORY=50

local function shortText(txt,maxChars)
 if not txt then return "" end
 if #txt>maxChars then return string.sub(txt,1,maxChars-3).."..." end
 return txt
end

local function translateHistoryItem(item)
 if not item then return end
 queuePayload("IN",item.author or "?",item.msg)
 picker:Hide()
end

local function refreshPicker()
 for _,row in ipairs(rows) do row:Hide() end
 local count=math.min(#recentMessages,MAX_VISIBLE_HISTORY)
 local width=math.max(520,scroll:GetWidth()-8)
 content:SetWidth(width)
 content:SetHeight(math.max(1,count*ROW_H))

 for displayIndex=1,count do
  local historyIndex=#recentMessages-displayIndex+1
  local item=recentMessages[historyIndex]
  local row=rows[displayIndex]
  if not row then
   row=CreateFrame("Button",nil,content)
   row:SetHeight(ROW_H)
   row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight")
   local num=row:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
   num:SetPoint("LEFT",4,0); num:SetWidth(24); num:SetJustifyH("RIGHT")
   local channel=row:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
   channel:SetPoint("LEFT",num,"RIGHT",8,0); channel:SetWidth(72); channel:SetJustifyH("LEFT")
   local author=row:CreateFontString(nil,"OVERLAY","GameFontNormal")
   author:SetPoint("LEFT",channel,"RIGHT",6,0); author:SetWidth(105); author:SetJustifyH("LEFT")
   local msg=row:CreateFontString(nil,"OVERLAY","GameFontHighlight")
   msg:SetPoint("LEFT",author,"RIGHT",8,0); msg:SetPoint("RIGHT",-6,0); msg:SetJustifyH("LEFT")
   row.num=num; row.channelText=channel; row.authorText=author; row.msgText=msg
   rows[displayIndex]=row
  end
  row:SetWidth(width)
  row:SetPoint("TOPLEFT",0,-(displayIndex-1)*ROW_H)
  row.num:SetText(displayIndex..".")
  local ch=item.channel or "CHAT"
  row.channelText:SetText("["..ch.."]")
  local colors={
   SAY={1.00,1.00,1.00},
   YELL={1.00,0.25,0.25},
   PARTY={0.67,0.67,1.00},
   RAID={1.00,0.50,0.00},
   GUILD={0.25,1.00,0.25},
   WHISPER={1.00,0.50,1.00},
   CHAT={0.80,0.80,0.80}
  }
  local c=colors[ch] or colors.CHAT
  row.channelText:SetTextColor(c[1],c[2],c[3])
  row.authorText:SetText(shortText(item.author or "?",18))
  row.msgText:SetText(shortText(item.msg or "",70))
  row.item=item
  row:SetScript("OnClick",function(self) translateHistoryItem(self.item) end)
  row:SetScript("OnEnter",function(self)
   GameTooltip:SetOwner(self,"ANCHOR_RIGHT")
   GameTooltip:SetText("["..(self.item.channel or "CHAT").."]  "..(self.item.author or "?"),1,.82,0)
   GameTooltip:AddLine(self.item.msg or "",1,1,1,true)
   GameTooltip:AddLine("Click to translate",.4,1,.6)
   GameTooltip:Show()
  end)
  row:SetScript("OnLeave",function() GameTooltip:Hide() end)
  row:Show()
 end
 if count==0 then
  pickerHint:SetText("No recent messages")
 else
  pickerHint:SetText("Select one of the last "..count.." messages")
 end
 scroll:SetVerticalScroll(0)
end

local function togglePicker()
 if picker:IsShown() then picker:Hide(); return end
 refreshPicker()
 picker:ClearAllPoints()
 if ChatFrame1 then
  picker:SetPoint("BOTTOMLEFT",ChatFrame1,"TOPLEFT",0,34)
 else
  picker:SetPoint("CENTER")
 end
 picker:Show()
end

local function translateLastMessage()
 local item=recentMessages[#recentMessages]
 if not item then
  print("|cff33ff99WoWInterpreter:|r no recent chat message.")
  return
 end
 queuePayload("IN",item.author or "?",item.msg)
end

local function setIncomingMode(mode)
 if mode=="auto" then
  incomingEnabled=true; translateMode="auto"
  print("|cff33ff99WoWInterpreter:|r incoming mode: AUTO")
 elseif mode=="manual" then
  incomingEnabled=true; translateMode="manual"
  print("|cff33ff99WoWInterpreter:|r incoming mode: MANUAL")
 elseif mode=="off" then
  incomingEnabled=false
  print("|cff33ff99WoWInterpreter:|r incoming translation OFF")
 end
end

local function printHelp()
 print("|cff33ff99WoWInterpreter v2.1.34|r - English <-> Simplified Chinese")
 print("|cffffff00/wi <text>|r - translate text")
 print("|cffffff00/wi last|r - translate latest received message")
 print("|cffffff00/wi list|r - choose a recent message")
 print("|cffffff00/wi manual|r - manual incoming translation")
 print("|cffffff00/wi auto|r - automatic incoming translation")
 print("|cffffff00/wi off|r - disable incoming translation")
 print("|cffffff00/wi help|r - show this help")
end

SLASH_WOWINTERPRETER1="/wi"
SlashCmdList["WOWINTERPRETER"]=function(raw)
 local msg=(raw or ""):match("^%s*(.-)%s*$")
 local cmd=string.lower(msg)
 if msg=="" or cmd=="help" then
  printHelp()
 elseif cmd=="last" then
  translateLastMessage()
 elseif cmd=="list" then
  togglePicker()
 elseif cmd=="manual" or cmd=="auto" or cmd=="off" then
  setIncomingMode(cmd)
 else
  queuePayload("OUT","You",msg)
 end
end

local translateButton=CreateFrame("Button","WoWInterpreterLastButton",UIParent,"UIPanelButtonTemplate")
translateButton:SetSize(28,24)
translateButton:SetText("译")
translateButton:SetFrameStrata("DIALOG")
local function positionTranslateButton()
 if not ChatFrame1 then return end
 translateButton:ClearAllPoints()
 translateButton:SetPoint("BOTTOMLEFT",ChatFrame1,"TOPLEFT",0,4)
end
translateButton:SetScript("OnClick",function()
 togglePicker()
end)
translateButton:SetScript("OnEnter",function(self)
 GameTooltip:SetOwner(self,"ANCHOR_TOPLEFT")
 GameTooltip:SetText("Choose message to translate")
 GameTooltip:AddLine("Click: recent message list",1,1,1)
 GameTooltip:AddLine("/wi last: translate latest directly",.8,.8,.8)
 GameTooltip:AddLine("/wi list: open message list",.8,.8,.8)
 GameTooltip:Show()
end)
translateButton:SetScript("OnLeave",function() GameTooltip:Hide() end)
C_Timer.After(1.0,positionTranslateButton)
C_Timer.NewTicker(10.0,positionTranslateButton)


local lastGeom=""
local function sendChatGeometry()
 if not ChatFrame1 then return end
 local scale=UIParent:GetEffectiveScale() or 1
 local left=ChatFrame1:GetLeft()
 local bottom=ChatFrame1:GetBottom()
 local width=ChatFrame1:GetWidth()
 local height=ChatFrame1:GetHeight()
 if not left or not bottom or not width or not height then return end
 -- WoW coordinates use bottom-left origin. Bridge receives logical UI coords + effective scale.
 local geom=string.format("%.1f,%.1f,%.1f,%.1f,%.4f",left,bottom,width,height,scale)
 if geom~=lastGeom then
   lastGeom=geom
   queuePayload("META","CHAT1",geom)
 end
end
C_Timer.NewTicker(10.0,sendChatGeometry)
C_Timer.After(1.0,sendChatGeometry)

-- startup chat message suppressed in v1.3
