import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './style.css';

type Msg = {id:string; text:string; role:string; kind:string; speaker:string; evidence_ids?:string[]};
type Source = {id:string; title:string; text:string; sensitivity:string};
type Chunk = Source & {source_id:string; start:number; end:number};
type Alert = {id:string; title:string; detail:string; question:string; status:string; origin:string; evidence_ids:string[]};
type Trace = {id:string; role:string; detail:string; ms:number; status:string};
type Session = {id:string; title:string; mode:string; cloud:boolean; messages:Msg[]; sources:Source[]; chunks?:Chunk[]; alerts:Alert[]; traces:Trace[]; version:number};
type Summary = {id:string; title:string; mode:string};
type Recognition = {lang:string; continuous:boolean; interimResults:boolean; start:()=>void; stop:()=>void; onresult:((event:any)=>void)|null; onerror:((event:any)=>void)|null; onend:(()=>void)|null};
declare global { interface Window {SpeechRecognition?:new()=>Recognition; webkitSpeechRecognition?:new()=>Recognition;} }

async function api(path:string, method='GET', body?:unknown) {
  const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json();
  if(!r.ok) throw new Error(typeof data.detail==='string'?data.detail:'请求失败，请检查输入');
  return data;
}

function App(){
  const [sessions,setSessions]=useState<Summary[]>([]), [s,setS]=useState<Session|null>(null);
  const [status,setStatus]=useState({model_available:false,model:''}),[error,setError]=useState('');
  const [text,setText]=useState(''),[kind,setKind]=useState('question'),[speaker,setSpeaker]=useState('我');
  const [busy,setBusy]=useState(false),[connected,setConnected]=useState(false),[tab,setTab]=useState('alerts');
  const [sourceOpen,setSourceOpen]=useState(false),[sourceTitle,setSourceTitle]=useState(''),[sourceText,setSourceText]=useState('');
  const [secret,setSecret]=useState(false),[listening,setListening]=useState(false),[interim,setInterim]=useState('');
  const [autoRead,setAutoRead]=useState(false);
  const socket=useRef<WebSocket|null>(null),recognizer=useRef<Recognition|null>(null),end=useRef<HTMLDivElement|null>(null);
  const selected=useRef('');
  const sendSettings=useRef({kind,speaker});sendSettings.current={kind,speaker};
  const read=useRef(false);read.current=autoRead;
  const seenAnswers=useRef(new Set<string>());

  function accept(data:Session){
    if(selected.current && data.id!==selected.current)return;
    setS(data);setBusy(false);
    for(const m of data.messages.filter(m=>m.role==='assistant')){
      if(!seenAnswers.current.has(m.id)){
        if(read.current && 'speechSynthesis' in window){window.speechSynthesis.cancel();const u=new SpeechSynthesisUtterance(m.text);u.lang='zh-CN';window.speechSynthesis.speak(u);}
        seenAnswers.current.add(m.id);
      }
    }
  }
  async function refresh(){setSessions(await api('/sessions'));}
  async function choose(id:string){
    recognizer.current?.stop();window.speechSynthesis?.cancel();
    socket.current?.close();selected.current=id;setBusy(false);setError('');
    const data=await api('/sessions/'+id);if(selected.current!==id)return;
    for(const m of data.messages)seenAnswers.current.add(m.id);setS(data);
  }
  useEffect(()=>{(async()=>{
    setStatus(await api('/status'));const all=await api('/sessions');setSessions(all);
    if(all.length)await choose(all[0].id);else{const a=await api('/sessions','POST',{title:'我的决策对话'});selected.current=a.id;setS(a);await refresh();}
  })().catch(e=>setError(e.message));return()=>{socket.current?.close();recognizer.current?.stop();};},[]);
  useEffect(()=>{
    if(!s?.id)return;
    const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${s.id}`);socket.current=ws;
    ws.onopen=()=>setConnected(true);
    ws.onclose=()=>{if(socket.current===ws){setConnected(false);setBusy(false);}};
    ws.onerror=()=>{if(socket.current===ws)setError('实时连接中断，可刷新页面恢复；对话已保存在本机。');};
    ws.onmessage=e=>{if(socket.current!==ws)return;const d=JSON.parse(e.data);if(d.type==='state')accept(d.session);else if(d.type==='processing')setBusy(true);else if(d.type==='error'){setError(d.message);setBusy(false);}};
    return()=>{ws.close();};
  },[s?.id]);
  useEffect(()=>{end.current?.scrollIntoView({behavior:'smooth'});},[s?.messages.length,busy]);

  function send(value=text, k=kind, who=speaker){
    if(!value.trim()||busy)return;
    if(socket.current?.readyState!==WebSocket.OPEN){setError('实时连接尚未就绪，请刷新页面后重试。');return;}
    window.speechSynthesis?.cancel();setError('');setBusy(true);
    socket.current.send(JSON.stringify({request_id:crypto.randomUUID(),text:value.trim(),kind:k,speaker:who}));setText('');
  }
  async function settings(mode:string,cloud:boolean){
    if(!s||busy)return;
    try{accept(await api(`/sessions/${s.id}/settings`,'PUT',{mode,cloud}));}catch(e){setError((e as Error).message);}
  }
  async function newSession(){if(busy)return;try{const a=await api('/sessions','POST',{title:'对话 '+new Date().toLocaleString('zh-CN')});await choose(a.id);await refresh();}catch(e){setError((e as Error).message);}}
  async function addSource(e:React.FormEvent){e.preventDefault();if(!s)return;try{accept(await api(`/sessions/${s.id}/sources`,'POST',{title:sourceTitle,text:sourceText,sensitivity:secret?'confidential':'internal'}));setSourceOpen(false);setSourceText('');setSourceTitle('');}catch(e){setError((e as Error).message);}}
  async function demo(){
    if(busy)return;
    try{const a=await api('/sessions','POST',{title:'演示 · 供应商付款谈判'});await choose(a.id);
      accept(await api(`/sessions/${a.id}/sources`,'POST',{title:'上次谈判纪要（虚构）',text:'双方原约定预付30%，验收后支付70%尾款。付款条件调整必须重新确认交付保障。',sensitivity:'internal'}));
      setKind('speech');setSpeaker('供应商');setText('这次希望发货前把货款付清。');await refresh();
    }catch(e){setError((e as Error).message);}
  }
  function toggleMic(){
    if(listening){recognizer.current?.stop();return;}
    const C=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(!C){setError('当前浏览器不支持语音识别，请使用文字输入。浏览器语音识别尚非独立ASR服务。');return;}
    if(!window.confirm('语音由浏览器识别，可能经浏览器服务商处理。是否开启麦克风？'))return;
    window.speechSynthesis?.cancel();
    const r=new C();r.lang='zh-CN';r.continuous=true;r.interimResults=true;
    r.onresult=e=>{let final='',temp='';for(let i=e.resultIndex;i<e.results.length;i++){if(e.results[i].isFinal)final+=e.results[i][0].transcript;else temp+=e.results[i][0].transcript;}
      setInterim(temp);if(final)setText(v=>v+final);};
    r.onerror=e=>{setError('语音识别未完成：'+e.error+'。可以继续用文字输入。');setListening(false);};
    r.onend=()=>{setListening(false);setInterim('');};recognizer.current=r;
    try{r.start();setListening(true);}catch{setError('麦克风启动失败，请检查浏览器权限。');}
  }
  function evidence(ids:string[]){return ids.map(id=>{const c=s?.chunks?.find(c=>c.id===id),d=c||s?.sources.find(d=>d.id===id),m=s?.messages.find(m=>m.id===id);return <details className="citation" key={id}><summary>{d?'资料 · '+d.title+(c?` · 字符 ${c.start+1}–${c.end}`:''):m?'原话 · '+m.speaker:'来源已移除'}</summary><p>{d?.text||m?.text||'无法读取'}</p></details>;});}
  const active=s?.alerts.filter(a=>a.status!=='clarified')||[];
  return <div className="app">
    <aside className="sidebar"><div className="brand"><span className="logo">D<span>↗</span></span><div>DecisionFlow RAG<small>FastAPI · React · BM25 · Multi-Agent</small></div></div>
      <button className="new" onClick={newSession} disabled={busy}>＋ 新建对话</button><div className="section-label">对话记录</div>
      <nav>{sessions.map(a=><button key={a.id} disabled={busy} onClick={()=>choose(a.id).catch(e=>setError(e.message))} className={a.id===s?.id?'session selected':'session'}><span>◌</span>{a.title}</button>)}</nav>
      <div className="sidebar-bottom"><div className="mini-label">开始一次完整体验</div><button className="demo" onClick={demo} disabled={busy}>↗ 加载谈判演示</button><p>虚构背景 · 条件变化 · 证据追溯</p><div className="local-tag">◉ 数据保存在本机</div></div>
    </aside>
    <main><header><div><div className="eyebrow">WORKSPACE / CONVERSATION</div><h1>{s?.title||'正在连接…'}</h1></div><div className="connection"><i className={connected?'online':''}/>{connected?'实时连接':'连接中'}</div></header>
      <div className="toolbar"><select aria-label="参与模式" value={s?.mode||'proactive'} disabled={busy} onChange={e=>settings(e.target.value,s?.cloud||false)}><option value="proactive">主动提醒</option><option value="ask_first">征询后展开</option><option value="record_only">仅记录</option></select>
      <span className="engine">{s?.cloud?'● 云端模型分析':'○ 离线规则演示'}</span>
      <label className="toggle"><input type="checkbox" checked={s?.cloud||false} disabled={!status.model_available||busy} onChange={e=>{if(e.target.checked&&!confirm('开启后，本会话的相关原话与检索资料将发送到服务端配置的模型供应商。是否开启？'))return;settings(s?.mode||'proactive',e.target.checked);}}/>云端分析</label>
      <button className="text-button" disabled={busy||!s} onClick={async()=>{if(s&&confirm('删除本机这段会话及关联资料？')){try{await api('/sessions/'+s.id,'DELETE');await newSession();}catch(e){setError((e as Error).message);}}}}>删除会话</button></div>
      {error&&<div role="alert" className="error">{error}<button onClick={()=>setError('')}>×</button></div>}
      <section className="messages">{!s?.messages.length&&<div className="welcome"><div className="welcome-icon">✦</div><h2>把对话变成更清晰的判断</h2><p>记录现场发言，结合你的资料发现变化。<br/>也可以直接提问，一起梳理问题。</p><div className="suggestions"><button onClick={demo}>试试付款谈判演示 <span>↗</span></button><button onClick={()=>{setSourceOpen(true);setTab('sources');}}>先添加一份背景资料 <span>＋</span></button></div><small>离线模式只演示预设规则；通用问答需配置模型。</small></div>}
        {s?.messages.map(m=><article key={m.id} className={'message '+(m.role==='assistant'?'assistant':'user')}><div className="avatar">{m.role==='assistant'?'✦':m.speaker.slice(0,1)}</div><div className="bubble"><div className="message-label">{m.speaker}<span>{m.kind==='speech'?'现场发言':m.role==='assistant'?'上下文回答':'向 AI 提问'}</span></div><div className="message-body">{m.text}</div>{m.evidence_ids&&evidence(m.evidence_ids)}</div></article>)}
        {busy&&<div className="thinking"><span/>正在检索背景与分析上下文…</div>}<div ref={end}/></section>
      <div className="composer-area"><div className="composer"><div className="composer-top"><div className="segments"><button className={kind==='question'?'on':''} onClick={()=>setKind('question')}>向 AI 提问</button><button className={kind==='speech'?'on':''} onClick={()=>setKind('speech')}>现场发言</button></div>{kind==='speech'&&<input aria-label="发言人" className="speaker" value={speaker} onChange={e=>setSpeaker(e.target.value)} maxLength={60}/>}</div>
        <textarea value={text} maxLength={6000} onChange={e=>setText(e.target.value)} placeholder={kind==='question'?'问问当前话题，或让 AI 帮你梳理选择…':'输入现场听到的话，系统将检查值得关注的变化…'} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send();}}}/>
        {interim&&<div className="interim">正在识别：{interim}</div>}<div className="composer-bottom"><button className={listening?'mic recording':'mic'} onClick={toggleMic}>{listening?'■ 停止识别':'♩ 语音输入'}</button><label className="read"><input type="checkbox" checked={autoRead} onChange={e=>{setAutoRead(e.target.checked);if(!e.target.checked)window.speechSynthesis?.cancel();}}/>朗读回答</label><button className="send" disabled={busy||!connected||!text.trim()} onClick={()=>send()}>{busy?'分析中':'发送 ↑'}</button></div></div><p className="footnote">语音识别后可编辑再发送 · Enter 发送 / Shift + Enter 换行 · 建议供判断参考</p></div>
    </main>
    <aside className="inspector"><div className="inspector-title">对话洞察 <span>LIVE</span></div><div className="tabs">{[['alerts','提醒',active.length],['sources','资料',s?.sources.length||0],['traces','轨迹',s?.traces.length||0]].map(([id,label,n])=><button key={id} onClick={()=>setTab(id as string)} className={tab===id?'active':''}>{label}<small>{n}</small></button>)}</div>
      <div className="inspector-body">{tab==='alerts'&&<><div className="panel-caption">只在值得关注时介入</div>{!s?.alerts.length&&<div className="empty"><span>◇</span><h3>暂时没有提醒</h3><p>添加背景资料并发送现场发言，重要变化会出现在这里。</p></div>}{s?.alerts.slice().reverse().map(a=><div key={a.id} className={'alert-card '+a.status}><div className="alert-top">{a.status==='clarified'?'✓ 已澄清':a.status==='pending'?'◌ 待展开':'↗ 值得关注'}<small>{a.origin==='model'?'模型分析':'规则演示'}</small></div><h3>{a.title}</h3>{a.status==='pending'?<button className="expand" onClick={()=>api(`/sessions/${s.id}/alerts/${a.id}/expand`,'POST').then(accept).catch(e=>setError(e.message))}>查看分析</button>:<><p>{a.detail}</p><div className="question">建议追问<br/><strong>{a.question}</strong></div>{evidence(a.evidence_ids)}</>}</div>)}<div className="channel-note">当前提醒仅显示在应用内。个人微信与邮件尚未接入。</div></>}
      {tab==='sources'&&<><div className="panel-caption">知识库 · BM25 分块检索<button className="text-button" onClick={()=>setSourceOpen(true)}>＋ 添加</button></div>{!s?.sources.length&&<div className="empty"><span>▤</span><h3>让分析有据可依</h3><p>添加历史约定、企业背景或你的明确偏好。</p></div>}{s?.sources.map(d=><div className="source-card" key={d.id}><small>{d.sensitivity==='confidential'?'机密':'内部'} · {d.id}</small><h3>{d.title}</h3><small>{s.chunks?.filter(c=>c.source_id===d.id).length||0} 个检索片段</small><p>{d.text}</p><button className="text-button" disabled={busy} onClick={()=>{if(confirm('删除该资料及引用它的派生提醒和回答？'))api(`/sessions/${s.id}/sources/${d.id}`,'DELETE').then(accept).catch(e=>setError(e.message));}}>删除资料</button></div>)}</>}
      {tab==='traces'&&<><div className="panel-caption">执行轨迹 · 可观察的工作流</div>{!s?.traces.length&&<div className="empty"><span>⌁</span><h3>等待第一条输入</h3><p>这里记录检索、分析、复核及提醒控制的实际执行。</p></div>}{s?.traces.slice().reverse().map(t=><div className={'trace '+t.status} key={t.id}><div><strong>{t.role}</strong>{t.ms>0&&<small>{t.ms} ms</small>}</div><p>{t.detail}</p></div>)}</>}
      </div><div className="inspector-footer">DecisionFlow RAG · v0.2 <span>本地个人版</span></div></aside>
    {sourceOpen&&<div className="overlay" onClick={()=>setSourceOpen(false)}><form className="modal" onClick={e=>e.stopPropagation()} onSubmit={addSource}><div className="modal-heading"><h2>添加背景资料</h2><button type="button" className="text-button" onClick={()=>setSourceOpen(false)}>×</button></div><p>保存到当前会话。开启云端分析后，相关片段可能发送给模型。</p><label>资料名称<input required maxLength={100} value={sourceTitle} onChange={e=>setSourceTitle(e.target.value)} placeholder="例如：上次谈判纪要"/></label><label>资料内容<textarea required maxLength={12000} value={sourceText} onChange={e=>setSourceText(e.target.value)} placeholder="粘贴明确事实、历史约定或个人偏好…"/></label><label className="secret"><input type="checkbox" checked={secret} onChange={e=>setSecret(e.target.checked)}/>标记为机密资料</label><button className="save" type="submit">保存资料</button></form></div>}
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
