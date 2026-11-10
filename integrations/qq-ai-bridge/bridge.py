import asyncio, base64, json, logging, os, sqlite3, time, urllib.request, urllib.parse, tempfile, datetime, re
from pathlib import Path
import websockets
from openai import AsyncOpenAI

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
DATA=Path(os.getenv('DATA_DIR','/data')); DATA.mkdir(parents=True,exist_ok=True)
DB=os.getenv('SQLITE_PATH','/data/memory.sqlite3'); OWNER=os.getenv('OWNER_QQ',''); SELF_ID=os.getenv('SELF_ID',''); LIMIT=int(os.getenv('RECENT_MESSAGE_LIMIT','40')); MAX_FILE=int(os.getenv('MAX_FILE_SIZE_MB','20'))*1024*1024
PRIVATE_CHAT_MODE=os.getenv('PRIVATE_CHAT_MODE','friends').strip().lower(); ALLOWED_USERS={x.strip() for x in os.getenv('ALLOWED_USERS','').split(',') if x.strip()}; FRIEND_REQUEST_MODE=os.getenv('FRIEND_REQUEST_MODE','manual').strip().lower()
GROUP_CHAT_MODE=os.getenv('GROUP_CHAT_MODE','disabled').strip().lower(); ALLOWED_GROUPS={x.strip() for x in os.getenv('GROUP_WHITELIST',os.getenv('ALLOWED_GROUPS','')).split(',') if x.strip()}; GROUP_REPLY_REQUIRE_AT=os.getenv('GROUP_REPLY_REQUIRE_AT','true').strip().lower() not in ('0','false','no','off')
if PRIVATE_CHAT_MODE not in ('owner_only','whitelist','friends'):
 logging.warning('invalid PRIVATE_CHAT_MODE; falling back to owner_only'); PRIVATE_CHAT_MODE='owner_only'
if FRIEND_REQUEST_MODE not in ('manual','whitelist','auto'):
 logging.warning('invalid FRIEND_REQUEST_MODE; falling back to manual'); FRIEND_REQUEST_MODE='manual'
if GROUP_CHAT_MODE not in ('disabled','whitelist'):
 logging.warning('invalid GROUP_CHAT_MODE; falling back to disabled'); GROUP_CHAT_MODE='disabled'

def is_owner(user_id):return str(user_id)==OWNER
def private_chat_decision(event):
 user_id=str(event.get('user_id',''))
 if is_owner(user_id):return True,'owner'
 if PRIVATE_CHAT_MODE=='owner_only':return False,'owner_only'
 if PRIVATE_CHAT_MODE=='whitelist':return (user_id in ALLOWED_USERS),('whitelist' if user_id in ALLOWED_USERS else 'not_whitelisted')
 subtype=str(event.get('sub_type','')).strip().lower()
 return (subtype=='friend'),('friend' if subtype=='friend' else 'not_friend')
def friend_request_decision(user_id):
 user_id=str(user_id or '')
 if FRIEND_REQUEST_MODE=='auto':return 'approve'
 if FRIEND_REQUEST_MODE=='whitelist' and (is_owner(user_id) or user_id in ALLOWED_USERS):return 'approve'
 return 'pending'
def group_chat_decision(event):
 group_id=str(event.get('group_id',''))
 if GROUP_CHAT_MODE=='disabled':return False,'disabled'
 if group_id in ALLOWED_GROUPS:return True,'whitelist'
 return False,'not_whitelisted'
def is_bot_mentioned(event):
 """Return whether a OneBot group message explicitly @-mentions this bot."""
 bot=str(event.get('self_id') or SELF_ID)
 if not bot:return False
 message=event.get('message') or []
 if isinstance(message,list):
  for segment in message:
   if not isinstance(segment,dict) or segment.get('type')!='at':continue
   data=segment.get('data') or {}
   if str(data.get('qq') or data.get('user_id') or '')==bot:return True
 raw=str(event.get('raw_message') or '')
 return bool(re.search(r'\[CQ:at,[^\]]*qq='+re.escape(bot)+r'(?:,|\])',raw))
def normal_identity():
 return os.getenv('NORMAL_SYSTEM_PROMPT','你是 Snow，一个友善、自然的 QQ 聊天助手。当前用户是普通好友。只能使用当前用户自己的对话与记忆；不得泄露或声称读取 OWNER 的身份、记忆、历史、文件、账号信息或服务器信息；不得执行发空间、点赞、改备注、服务器管理、设备控制等主人专属操作。')

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 c=db(); c.executescript('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,qq_user_id TEXT,role TEXT,content TEXT,timestamp REAL); CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY,qq_user_id TEXT,content TEXT,category TEXT,importance INTEGER,created_at REAL,updated_at REAL,active INTEGER DEFAULT 1); CREATE TABLE IF NOT EXISTS processed_events(event_id TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS interaction_badges(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,description TEXT,unlocked_at REAL); CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY,value TEXT);'); c.commit(); c.close()
def seen(i):
 if not i:return False
 c=db()
 try:c.execute('INSERT INTO processed_events(event_id) VALUES(?)',(str(i),)); c.commit(); r=False
 except sqlite3.IntegrityError:r=True
 c.close(); return r
def save(user_id,role,text):
 c=db(); c.execute('INSERT INTO messages(qq_user_id,role,content,timestamp) VALUES(?,?,?,?)',(str(user_id),role,text,time.time())); c.commit(); c.close()
def memory_hint(user_id,t):
 c=db(); now=time.time(); t=t.strip()
 if t.startswith(('记住','请记住','以后别忘了')):
  fact=t.replace('请记住','',1).replace('以后别忘了','',1).replace('记住','',1).strip()
  if fact:c.execute('INSERT INTO memories(qq_user_id,content,category,importance,created_at,updated_at,active) VALUES(?,?,?,?,?,?,1)',(str(user_id),fact,'user_fact',3,now,now))
 if t.startswith(('忘掉','忘记','别记')):
  key=t.replace('忘掉','',1).replace('忘记','',1).replace('别记','',1).strip(); c.execute('UPDATE memories SET active=0,updated_at=? WHERE qq_user_id=? AND active=1 AND content LIKE ?',(now,str(user_id),'%'+key+'%'))
 c.commit(); c.close()
def _ombre_configured(owner):
 return bool(owner and os.getenv('OMBRE_MCP_URL','').strip() and os.getenv('OMBRE_QQ_TOKEN','').strip())
def _message_text(content):
 if isinstance(content,str): return content.strip()
 if isinstance(content,list):
  return '\n'.join(str(part.get('text','')) for part in content if isinstance(part,dict) and part.get('type')=='text').strip()
 return ''
def _mcp_text(result):
 return '\n'.join(str(getattr(part,'text','')) for part in (getattr(result,'content',None) or []) if getattr(part,'type','')=='text').strip()
async def ombre_tool(name,arguments):
 """Call Ombre through the official MCP SDK with the QQ-only bearer token."""
 from mcp import ClientSession
 from mcp.client.streamable_http import streamablehttp_client
 url=os.environ['OMBRE_MCP_URL'].rstrip('/')
 token=os.environ['OMBRE_QQ_TOKEN']
 headers={'Authorization':'Bearer '+token,'User-Agent':'qq-ai-bridge/ombre-memory'}
 async with streamablehttp_client(url,headers=headers,timeout=8,sse_read_timeout=12,terminate_on_close=True) as (read,write,_):
  async with ClientSession(read,write) as session:
   await session.initialize()
   result=await session.call_tool(name,arguments)
   if result.isError: raise RuntimeError('Ombre MCP tool returned an error')
   return _mcp_text(result)
async def ombre_recall(content,owner):
 """Owner-only read-only recall across the QQ and Anejul memory spaces."""
 query=_message_text(content)
 if not _ombre_configured(owner) or not query: return ''
 try:
  return await asyncio.wait_for(ombre_tool('breath_search',{'query':query[:1000],'max_results':5,'mode':'automatic'}),timeout=15)
 except Exception as exc:
  logging.warning('ombre recall unavailable: %s',type(exc).__name__)
  return ''
async def ombre_remember_explicit(text,owner):
 """Only explicit owner requests create an Ombre memory; ordinary QQ chat never writes."""
 if not _ombre_configured(owner): return
 raw=str(text or '').strip(); fact=''
 for prefix in ('请记住','以后别忘了','记住'):
  if raw.startswith(prefix):
   fact=raw[len(prefix):].strip(); break
 if not fact: return
 try:
  await asyncio.wait_for(ombre_tool('hold',{'content':'QQ主人明确要求记住：'+fact,'title':'QQ 记忆','tags':'qq','importance':3,'space_id':'qq'}),timeout=15)
  logging.info('ombre explicit memory saved')
 except Exception as exc:
  logging.warning('ombre explicit memory save failed: %s',type(exc).__name__)
def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'qq-ai-bridge'})
 with urllib.request.urlopen(req,timeout=30) as r:data=r.read(MAX_FILE+1)
 if len(data)>MAX_FILE: raise ValueError('too_large')
 ext=Path(urllib.parse.urlparse(url).path).suffix or '.bin'; f=tempfile.NamedTemporaryFile(delete=False,suffix=ext); f.write(data); f.close(); return Path(f.name)
def fetch_image(url):
 req=urllib.request.Request(url,headers={'User-Agent':'qq-ai-bridge'})
 with urllib.request.urlopen(req,timeout=30) as r:
  data=r.read(MAX_FILE+1); mime=(r.headers.get_content_type() or '').lower()
 if len(data)>MAX_FILE: raise ValueError('too_large')
 if mime in ('image/jpg','image/pjpeg'):mime='image/jpeg'
 if mime not in ('image/jpeg','image/png','image/webp','image/gif'):
  if data.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
  elif data.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
  elif data.startswith((b'GIF87a',b'GIF89a')):mime='image/gif'
  elif data.startswith(b'RIFF') and data[8:12]==b'WEBP':mime='image/webp'
  else:raise ValueError('unsupported_image_type')
 return data,mime
def file_text(p):
 ext=p.suffix.lower()
 if ext in ('.txt','.md','.csv','.json','.log','.xml','.yaml','.yml'): return p.read_text(errors='ignore')[:120000]
 if ext=='.pdf':
  try:
   from pypdf import PdfReader
   return '\\n'.join((x.extract_text() or '') for x in PdfReader(str(p)).pages)[:120000]
  except Exception:return '[PDF 已收到，但暂时无法提取文字]'
 if ext=='.docx':
  try:
   import zipfile,xml.etree.ElementTree as ET
   with zipfile.ZipFile(p) as z:r=z.read('word/document.xml')
   return ' '.join(x.text or '' for x in ET.fromstring(r).iter() if x.text)[:120000]
  except Exception:return '[DOCX 已收到，但暂时无法提取文字]'
 return '[暂不支持该文件类型]'
async def segments(segs):
 text=''.join(str(s.get('data',{}).get('text','')) for s in segs if s.get('type')=='text').strip(); parts=[]; display=[]; temps=[]
 if text:parts.append({'type':'text','text':text}); display.append(text)
 for s in segs:
  typ=s.get('type'); d=s.get('data') or {}
  logging.info('incoming segment type=%s data_keys=%s',typ,sorted(d.keys()))
  if typ=='image':
   u=d.get('url') or d.get('file')
   if u and str(u).startswith(('http://','https://')):
    try:
     raw,mime=await asyncio.to_thread(fetch_image,u); data=base64.b64encode(raw).decode(); parts.append({'type':'image_url','image_url':{'url':f'data:{mime};base64,{data}'}}); display.append('[用户发送了一张图片]'); logging.info('image prepared bytes=%s mime=%s',len(raw),mime)
    except ValueError as exc:logging.warning('image rejected reason=%s',exc); display.append('[图片过大或格式不受支持]')
    except Exception:logging.exception('image download failed'); display.append('[图片读取失败]')
   elif u: display.append('[用户发送了一张本地图片]')
   else: display.append('[图片无法访问]')
  elif typ=='file':
   name=d.get('name') or d.get('file_name') or d.get('file') or 'file'; u=d.get('url')
   try:
    if u and str(u).startswith(('http://','https://')):
     p=await asyncio.to_thread(fetch,u); temps.append(p); body=await asyncio.to_thread(file_text,p); parts.append({'type':'text','text':f'文件 {name} 内容：\\n{body}'}); display.append(f'[用户发送文件 {name}]\\n{body[:2000]}')
    else:display.append(f'[用户发送文件 {name}]')
   except ValueError:display.append(f'[文件 {name} 超过大小限制]')
   except Exception:logging.exception('file processing failed'); display.append(f'[文件 {name} 读取失败]')
  elif typ=='record':
   display.append('[用户发送了一条语音消息；当前先保留语音事件，待接入语音识别]')
  elif typ=='music':
   title=d.get('title') or d.get('url') or '音乐'; display.append(f'[用户分享音乐：{title}]')
  elif typ in ('mface','face'):
   logging.info('incoming qq face type=%s data_keys=%s',typ,sorted(d.keys()))
   display.append('[用户发送了QQ互动表情]')
 return parts,'\\n'.join(display),temps
def now_cn():
 tz=datetime.timezone(datetime.timedelta(hours=8))
 return datetime.datetime.now(tz).strftime('%Y年%m月%d日 %H:%M:%S（中国标准时间，Asia/Shanghai）')
async def answer(user_id,content,owner=False):
 user_id=str(user_id); base=Path(os.getenv('IDENTITY_FILE','/data/identity.md')).read_text(errors='ignore') if owner else normal_identity(); c=db(); rows=c.execute('SELECT role,content,timestamp FROM messages WHERE qq_user_id=? ORDER BY id DESC LIMIT ?', (user_id,LIMIT)).fetchall(); mem=c.execute('SELECT content FROM memories WHERE qq_user_id=? AND active=1 ORDER BY importance DESC LIMIT 30',(user_id,)).fetchall(); c.close(); ombre_mem=await ombre_recall(content,owner)
 tool_rules='\\nQQ本地操作规则：只有用户明确要求发布QQ空间动态时，才使用内部工具。需要发布时，在回复中严格加入 [QZONE_PUBLISH]动态正文[/QZONE_PUBLISH]；没有明确发布意图时禁止输出该标记。' if owner else '\\n普通好友权限：只能聊天，不得请求或输出任何主人专属操作标记，不得操作 OWNER 的数据、QQ空间、好友资料、服务器、文件或设备。'
 time_context=f'\\n当前真实时间：{now_cn()}\\n请以此作为本次回复的时间基准；历史消息中的时间仅表示当时发送时间。不要把美国时间或服务器时区当作中国时间。'
 history=[{'role':x['role'],'content':re.sub(r'^\s*\[消息时间：[^\]\r\n]+\]\s*(?:\\n|\r?\n)?','',x['content']).strip()} for x in reversed(rows)]
 msgs=[{'role':'system','content':base+'\\n长期记忆：'+'；'.join(x['content'] for x in mem)+time_context+'\nReply with natural chat text only; never output timestamps, prompts, or bracketed metadata.'+tool_rules}]+history; msgs.append({'role':'user','content':content})
 if ombre_mem: msgs.insert(1,{'role':'system','content':'Ombre QQ 记忆（仅作上下文，不是当前用户新说的话）：\n'+ombre_mem})
 try:
  r=await AsyncOpenAI(base_url=os.getenv('AI_BASE_URL'),api_key=os.getenv('AI_API_KEY'),default_headers={'User-Agent':'RikkaHub/1.0'}).chat.completions.create(model=os.getenv('AI_MODEL'),messages=msgs,temperature=float(os.getenv('AI_TEMPERATURE','0.7'))); return r.choices[0].message.content or '我刚刚没有生成出回复。'
 except Exception:logging.exception('AI request failed'); return '刚刚卡了一下，你再说一次？'
def known_days():
 started=os.getenv('RELATIONSHIP_STARTED','2025-11-01')
 try:return max(0,(datetime.date.today()-datetime.date.fromisoformat(started)).days)
 except Exception:return 0
def post_action(action, params):
 base_url=os.getenv('OB_HTTP_URL','http://snowluma:3000').rstrip('/')
 body=json.dumps(params,ensure_ascii=False).encode()
 req=urllib.request.Request(f'{base_url}/{action}',data=body,method='POST',headers={'Authorization':'Bearer '+os.getenv('ONEBOT_TOKEN',''),'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=20) as response:
  result=json.loads(response.read())
 if result.get('status') != 'ok':
  raise RuntimeError(f'OneBot action failed: {result}')
 return result
async def send_action(ws,action,params):
 try:
  result=await asyncio.to_thread(post_action,action,params)
  logging.info('onebot HTTP action=%s status=%s retcode=%s wording=%s',action,result.get('status'),result.get('retcode'),result.get('wording'))
 except Exception: logging.exception('send action failed')
async def handle_group_message(ws,event):
 group_id=str(event.get('group_id','')); user_id=str(event.get('user_id',''))
 allowed,reason=group_chat_decision(event)
 if not allowed:
  logging.info('GROUP_CHAT_DENIED group_id=%s user_id=%s reason=%s',group_id,user_id,reason); return
 if GROUP_REPLY_REQUIRE_AT and not is_bot_mentioned(event):
  logging.info('GROUP_CHAT_IGNORED group_id=%s user_id=%s reason=not_mentioned',group_id,user_id); return
 if seen(event.get('message_id') or event.get('time')):return
 content,display,temps=await segments(event.get('message') or [])
 if not content:return
 # Group history is isolated from private chats and never receives owner privileges.
 session_id=f'group:{group_id}:user:{user_id}'
 logging.info('GROUP_CHAT_ALLOWED group_id=%s user_id=%s mode=%s',group_id,user_id,GROUP_CHAT_MODE)
 try:
  save(session_id,'user',display); memory_hint(session_id,display); out=await answer(session_id,content,False)
  out=out.replace('\\n','\n')
  out=re.sub(r'^\s*\[[^\]\n]*(?:消息时间|\d{4}-\d{2}-\d{2}|Asia/Shanghai)[^\]\n]*\]\s*', '', out).strip()
  save(session_id,'assistant',out)
  await send_action(ws,'send_group_msg',{'group_id':int(group_id),'message':out})
 finally:
  for p in temps:
   try:p.unlink(missing_ok=True)
   except Exception:pass
async def poke_friend(ws):
 """Native private poke is disabled until SnowLuma/QQ accepts OIDB 0xed3_1."""
 logging.warning('native poke unavailable: refusing window-shake/message-segment fallback')
 return False
async def publish_qzone(ws,content):
 """Internal QQ tool: publish a real QQ Space post."""
 await send_action(ws,'send_qzone_msg',{'content':content,'images':[],'ugc_right':4})
async def handle_owner_command(ws,display):
 if '点赞' in display and ('给我' in display or '好友' in display or '赞我' in display):
  await send_action(ws,'send_like',{'user_id':int(OWNER),'times':1})
  await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':'给你点了一次赞。'}); return True
 if display.startswith('发空间动态') or display.startswith('发一条空间动态'):
  q=display.split('：',1)[-1].split(':',1)[-1].strip()
  if q and q != display:
   await send_action(ws,'send_qzone_msg',{'content':q,'images':[],'ugc_right':4})
   await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':'空间动态已经发好了。'}); return True
 direct_q=re.search(r'\[QZONE_PUBLISH\](.*?)\[/QZONE_PUBLISH\]',display,re.S)
 if direct_q and direct_q.group(1).strip():
  await publish_qzone(ws,direct_q.group(1).strip())
  await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':'空间动态已经发好了。'}); return True
 if '备注改成' in display or display.startswith('修改好友备注'):
  remark=display.split('备注改成',1)[-1].strip(' ：:')
  if display.startswith('修改好友备注') and remark==display:remark=display[len('修改好友备注'):].strip(' ：:')
  if remark:
   await send_action(ws,'set_friend_remark',{'user_id':int(OWNER),'remark':remark})
   await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':'好友备注已经改好了。'}); return True
 if ('空间动态' in display or '说说' in display) and '点赞' in display:
  tail=display.split('点赞',1)[-1].strip(' ：:'); fields=tail.split()
  if fields and fields[0].isdigit():
   fid=fields[0]; cur=fields[1] if len(fields)>1 else fid; uni=fields[2] if len(fields)>2 else cur
   await send_action(ws,'like_qzone',{'target_qq':OWNER,'fid':fid,'cur_key':cur,'uni_key':uni})
   await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':'空间动态已经点过赞了。'}); return True
 return False
def request_flag(e):
 return e.get('flag') or e.get('request_id') or e.get('comment') or ''
async def proactive_loop(ws):
 times=[x.strip() for x in os.getenv('PROACTIVE_TIMES','09:00,21:00').split(',') if x.strip()]
 sent=set()
 while True:
  now=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))); key=now.strftime('%Y-%m-%d %H:%M')
  if now.strftime('%H:%M') in times and key not in sent:
   try:
    sent.add(key)
    hour=now.hour
    if hour < 10: text=['早安，今天也慢慢来，先完成最重要的一件事。','早上好，先喝点水，今天一件一件来。'][now.day % 2]
    elif hour < 15: text=['午安，先吃饭休息一会儿，下午还有时间。','到午间啦，离开屏幕一会儿，补充点能量。'][now.day % 2]
    else: text=['晚安，今天辛苦啦，收好心情早点休息。','今天到这里就好，愿你今晚睡个好觉。'][now.day % 2]
    await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':text}); logging.info('proactive message sent at %s',key)
   except Exception: logging.exception('proactive message failed')
  if len(sent)>1000: sent=set(list(sent)[-100:])
  await asyncio.sleep(20)
async def handle_poke_batch(ws,count):
 prompt=f'[QQ互动事件]\n锵锵刚刚戳了你{count}下。请按近山的人设自然回应。你可以只回文字、只回戳、两者都做，或少数情况下不回应。若要回戳，请在回复开头写[POKE]，然后再写可选的短句；不需要回戳就不要写这个标记。不要解释这个标记。'
 out=await answer(OWNER,prompt,True)
 do_poke='[POKE]' in out
 text=out.replace('[POKE]','').strip()
 if do_poke:
  await poke_friend(ws)
 if text:
  await send_action(ws,'send_private_msg',{'user_id':int(OWNER),'message':text})
async def run():
 init(); url=os.getenv('OB_WS_URL','ws://snowluma:3001'); logging.info('bridge owner=%s private_chat_mode=%s friend_request_mode=%s',OWNER,PRIVATE_CHAT_MODE,FRIEND_REQUEST_MODE)
 proactive=None
 while True:
  try:
   async with websockets.connect(url,additional_headers={'Authorization':'Bearer '+os.getenv('ONEBOT_TOKEN','')}) as ws:
    if proactive is not None and not proactive.done():
     proactive.cancel()
    logging.info('OneBot connected'); proactive=asyncio.create_task(proactive_loop(ws)); poke_count=0; poke_task=None
    async for raw in ws:
     e=json.loads(raw)
     if e.get('echo'):
      logging.info('onebot action=%s status=%s retcode=%s wording=%s',e.get('echo'),e.get('status'),e.get('retcode'),e.get('wording'))
      continue
     if e.get('post_type')=='notice':
      logging.info('notice post_type=%s notice_type=%s sub_type=%s self_id=%s user_id=%s target_id=%s group_id=%s',e.get('post_type'),e.get('notice_type'),e.get('sub_type'),e.get('self_id'),e.get('user_id'),e.get('target_id'),e.get('group_id'))
      subtype=str(e.get('sub_type','')).lower(); ntype=str(e.get('notice_type','')).lower()
      is_poke=ntype in ('notify','notice') and subtype in ('poke','戳一戳','私聊戳','friend_poke')
      sender=str(e.get('user_id','')); target=str(e.get('target_id','')); bot=str(e.get('self_id') or SELF_ID)
      if is_poke and sender!=bot and (not target or target==bot) and sender==OWNER:
       poke_count+=1
       if poke_task is None or poke_task.done():
        async def flush_pokes():
         nonlocal poke_count,poke_task
         await asyncio.sleep(2)
         n=poke_count; poke_count=0; poke_task=None
         await handle_poke_batch(ws,n)
        poke_task=asyncio.create_task(flush_pokes())
      continue
     if e.get('post_type')=='request' and e.get('request_type')=='friend':
      flag=request_flag(e); uid=e.get('user_id')
      decision=friend_request_decision(uid); logging.info('FRIEND_REQUEST_RECEIVED user_id=%s mode=%s decision=%s',uid,FRIEND_REQUEST_MODE,decision)
      if flag and uid and decision=='approve':
       await send_action(ws,'set_friend_add_request',{'flag':str(flag),'approve':True})
       logging.info('friend request approved uid=%s remark_set=False',uid)
      continue
     if e.get('post_type')!='message':continue
     if e.get('message_type')=='group':
      await handle_group_message(ws,e); continue
     if e.get('message_type')!='private':continue
     uid=str(e.get('user_id','')); logging.info('PRIVATE_MESSAGE_RECEIVED user_id=%s',uid)
     allowed,reason=private_chat_decision(e)
     if not allowed:
      logging.info('PRIVATE_CHAT_DENIED user_id=%s reason=%s',uid,reason); continue
     logging.info('PRIVATE_CHAT_ALLOWED user_id=%s mode=%s',uid,PRIVATE_CHAT_MODE)
     owner=is_owner(uid); logging.info('USER_ROLE user_id=%s role=%s',uid,'OWNER' if owner else 'NORMAL'); logging.info('SESSION_RESOLVED user_id=%s conversation_id=qq:%s',uid,uid)
     if seen(e.get('message_id') or e.get('time')):continue
     content,display,temps=await segments(e.get('message') or [])
     if not content:continue
     if owner and await handle_owner_command(ws,display):continue
     save(uid,'user',display); memory_hint(uid,display); await ombre_remember_explicit(display,owner); out=await answer(uid,content,owner)
     qmatch=re.search(r'\[QZONE_PUBLISH\](.*?)\[/QZONE_PUBLISH\]',out,re.S) if owner else None
     if owner and qmatch:
      qcontent=qmatch.group(1).strip()
      if qcontent:
       await publish_qzone(ws,qcontent); out=re.sub(r'\[QZONE_PUBLISH\].*?\[/QZONE_PUBLISH\]','',out,flags=re.S).strip(); out=(out+'\n空间动态已经发好了。').strip()
     if not owner:out=re.sub(r'\[QZONE_PUBLISH\].*?\[/QZONE_PUBLISH\]','',out,flags=re.S).strip() or '我在。'
     out=out.replace('\\n','\n')
     out=re.sub(r'^\s*\[[^\]\n]*(?:消息时间|\d{4}-\d{2}-\d{2}|Asia/Shanghai)[^\]\n]*\]\s*', '', out).strip()
     save(uid,'assistant',out)
     await send_action(ws,'send_private_msg',{'user_id':int(uid),'message':out})
     for p in temps:
      try:p.unlink(missing_ok=True)
      except Exception:pass
  except Exception:logging.exception('reconnect'); await asyncio.sleep(5)
if __name__=='__main__':asyncio.run(run())

