"use client";
import {useEffect,useRef,useState} from "react";

type Transfer={log_index:number;token_contract:string;from_address:string;to_address:string;raw_amount:string};
type RealResponse={factual_source:"json_rpc";agent_runtime:"google_adk_gemini"|"unavailable";case:{id:string;state:string;wallet_address:string;chain:string;theft_transaction_hash:string;evidence:{transaction:{hash:string;chain:string;block_number:number;timestamp:string;status:"success"|"failed";from_address:string;to_address:string|null;native_value_wei:string;erc20_transfers:Transfer[]}};finding:{classification:string;summary:string;confidence:number;evidence_references:string[];limitations:string[]}|null;error:string|null}};
type TraceState={branches:{id:string;current_address:string;asset:string;amount:string;status:string;last_transaction:string}[];graph:{nodes:{id:string;label:string;address:string|null}[];edges:{id:string;source:string;target:string;asset:string;amount:string}[]};timeline:{id:string;type:string;message:string;created_at:string;data:Record<string,unknown>}[]};
type DemoStep={title:string;detail:string;time:string;tone?:string};
type CaseSection="overview"|"graph"|"evidence"|"timeline";

const demoSteps:DemoStep[]=[
{title:"Case opened",detail:"Evidence preserved and investigation queued",time:"12:41:02"},
{title:"Malicious approval isolated",detail:"USDC allowance granted to 0x8F21…A906",time:"12:41:04",tone:"alert"},
{title:"Attacker wallet traced",detail:"42,180.00 USDC received in theft transaction",time:"12:41:07"},
{title:"Fund split detected",detail:"Created branches BR 01 and BR 02",time:"12:41:10"},
{title:"Swap followed",detail:"31,500 USDC converted to 10.42 ETH",time:"12:41:14"},
{title:"Bridge continuation",detail:"Across Protocol transfer resolved on Base",time:"12:41:18"},
{title:"Branch BR 02 dormant",detail:"10,680 USDC stationary. Monitor armed.",time:"12:41:21",tone:"muted"},
{title:"Actionable destination detected",detail:"Coinbase deposit address received 10.42 ETH",time:"12:41:25",tone:"good"}];

const demoNodes=[
{label:"VICTIM",sub:"0x71C4…19E2",x:5,y:42,type:"victim"},{label:"ATTACKER",sub:"0x8F21…A906",x:24,y:42,type:"bad"},
{label:"SPLIT",sub:"2 branches",x:42,y:42,type:"process"},{label:"UNISWAP",sub:"USDC → ETH",x:58,y:17,type:"process"},
{label:"ACROSS",sub:"Ethereum → Base",x:74,y:17,type:"process"},{label:"COINBASE",sub:"10.42 ETH",x:89,y:17,type:"good"},
{label:"WALLET B",sub:"10,680 USDC",x:58,y:69,type:"dormant"},{label:"MONITORING",sub:"no movement",x:77,y:69,type:"dormant"}];

const demoEdges=[[0,1],[1,2],[2,3],[3,4],[4,5],[2,6],[6,7]];
const short=(value:string|null|undefined)=>value?value.length>14?`${value.slice(0,7)}…${value.slice(-5)}`:value:"Contract creation";

function Brand({onClick}:{onClick?:()=>void}={}){
 const contents=<><span className="brandMark">N</span><span>NEMESIS</span></>;
 return onClick
  ?<button type="button" className="brand" onClick={onClick} aria-label="Return to NEMESIS home" style={{background:"none",border:0,color:"inherit",padding:0,cursor:"pointer"}}>{contents}</button>
  :<div className="brand">{contents}</div>
}

function Landing({onStart,onDemo}:{onStart:()=>void;onDemo:()=>void}){
 const steps=["Investigate","Trace","Monitor","Movement detected","Resume","Escalate"];
 const capabilities=[
  {n:"01",title:"Multi-hop tracing",copy:"Follow value across successive wallets without losing the deterministic transaction path.",className:"wide",visual:<div className="miniPath"><i/><b/><i/><b/><i/><b/><i/></div>},
  {n:"02",title:"Fund splits",copy:"Every qualifying outgoing path becomes a persisted branch with its own state.",className:"split",visual:<div className="splitPath"><i/><b/><span/><span/><span/></div>},
  {n:"03",title:"Swaps, resolved",copy:"Connect the input asset to the output asset using receipt evidence—not inference.",className:"swap",visual:<div className="swapPair"><span>USDC</span><b>⇄</b><span>ETH</span></div>},
  {n:"04",title:"Cross-chain evidence",copy:"Continue across supported bridge events when the destination can be resolved deterministically.",className:"bridge",visual:<div className="bridgePair"><span>ETHEREUM</span><b>→</b><span>BASE</span></div>},
  {n:"05",title:"Dormant monitoring",copy:"Keep quiet branches alive in persistent state until new movement appears.",className:"dormantCap",visual:<div className="quietSignal"><i/><i/><i/><i/><i/></div>}
 ];
 return <main className="landing">
  <nav><Brand/><div className="landingNav"><a href="#system">How it works</a><a href="#intelligence">Intelligence</a><a href="#trust">Trust</a></div><button className="navCta" onClick={onStart}>Start investigation <span>↗</span></button></nav>
  <section className="heroScene" aria-label="NEMESIS autonomous crypto incident response">
   <div className="heroOrb orbOne"/><div className="heroOrb orbTwo"/>
   <div className="artifact artifactWallet"><span className="artifactLabel">SUBMITTED WALLET</span><b>0x71C4...19E2</b><div className="walletBalance"><small>EXPOSURE TRACED</small><strong>$42,180</strong></div><i className="walletPulse"/></div>
   <div className="artifact artifactEth"><span className="chainGlyph">◆</span><div><b>Ethereum</b><small>Block 21,847,201</small></div><em>VERIFIED</em></div>
   <div className="artifact artifactGraph"><span className="artifactLabel">PERSISTED FUND GRAPH</span><svg viewBox="0 0 180 92" aria-hidden="true"><path d="M18 45H65M76 45l29-25M76 45l29 25M116 20h43M116 70h43"/><circle cx="18" cy="45" r="7"/><circle cx="70" cy="45" r="8"/><circle cx="110" cy="20" r="7"/><circle cx="110" cy="70" r="7"/><circle cx="164" cy="20" r="7"/><circle cx="164" cy="70" r="7"/></svg><small>2 ACTIVE BRANCHES</small></div>
   <div className="artifact artifactTx"><div className="txTop"><span>TRANSACTION</span><i>CONFIRMED</i></div><b>0x3a91...d80f</b><div className="txFlow"><span>42,180 USDC</span><small>→</small><span>10.42 ETH</span></div></div>
   <div className="artifact artifactBase"><span className="baseGlyph">B</span><div><b>Base</b><small>Bridge resolved</small></div><em>CONTINUED</em></div>
   <div className="artifact artifactDormant"><span className="artifactLabel">BRANCH BR 02</span><div className="dormantIcon">◌</div><b>Dormant wallet</b><small>10,680 USDC stationary</small><div className="monitorLine"><i/> MONITORING</div></div>
   <div className="artifact artifactMovement"><div className="movementHead"><span>MOVEMENT DETECTED</span><i/></div><b>Trace automatically resumed</b><small>3 confirmations · just now</small><div className="movementBars"><i/><i/><i/><i/></div></div>
   <div className="artifact artifactEvidence"><span className="artifactLabel">EVIDENCE PACKAGE</span><div className="evidenceSeal">✓</div><b>Chain of evidence intact</b><small>18 RPC facts preserved</small></div>
   <div className="hero"><div className="eyebrow">AUTONOMOUS CRYPTO INCIDENT RESPONSE</div><h1>Trace stolen crypto.<br/><em>Follow where it goes.</em></h1><p>NEMESIS investigates compromised wallets, traces fund movement with deterministic evidence, and keeps watching when the trail goes quiet.</p><div className="heroActions"><button className="primary" onClick={onStart}>Start investigation <span>→</span></button><button className="textCta" onClick={onStart}>Explore the system</button></div><div className="promise"><span><i>01</i>Deterministic Evidence</span><span><i>02</i>Autonomous Monitoring</span><span><i>03</i>Actionable Escalation</span></div></div>
  </section>

  <section className="marquee" aria-label="NEMESIS capabilities"><div>INVESTIGATE <i/> TRACE <i/> MONITOR <i/> RESUME <i/> ESCALATE <i/> DETERMINISTIC EVIDENCE <i/> AUTONOMOUS RESPONSE</div></section>

  <section id="system" className="systemStory reveal"><div className="sectionIntro"><div><span className="sectionKicker">01 / THE SYSTEM</span><h2>From one transaction<br/>to the whole trail.</h2></div><p>NEMESIS keeps the mechanical truth of the chain separate from agent interpretation, then acts on every branch that evidence supports.</p></div><div className="storyRail">{steps.map((step,i)=><div className={`storyStep s${i+1}`} key={step}><span>{String(i+1).padStart(2,"0")}</span><strong>{step}</strong>{i<steps.length-1&&<i>→</i>}</div>)}<div className="railLine"><i/></div></div><div className="storyCaption"><b>A persistent investigation, not a one-shot answer.</b><span>Each trace state and timeline event is stored so the system can continue later without reconstructing the case.</span></div></section>

  <section id="intelligence" className="intelligence"><div className="sectionIntro reveal"><div><span className="sectionKicker">02 / TRACE INTELLIGENCE</span><h2>Evidence follows value.<br/><em>Even when the shape changes.</em></h2></div><p>Splits, swaps, bridges, and quiet wallets are represented as connected evidence—not disconnected alerts.</p></div><div className="capabilityGrid">{capabilities.map(c=><article key={c.title} className={`capabilityCard ${c.className} reveal`}><span>{c.n}</span><div className="capVisual">{c.visual}</div><h3>{c.title}</h3><p>{c.copy}</p></article>)}</div></section>

  <section className="monitoringFeature"><div className="monitorCopy reveal"><span className="sectionKicker light">03 / AUTONOMOUS MONITORING</span><h2>The trail goes quiet.<br/><em>NEMESIS does not.</em></h2><p>A dormant branch stays armed in persistent state. Cloud Scheduler triggers rechecks. When new movement is confirmed, Pub/Sub delivers the event and tracing resumes from the exact branch where it stopped.</p><div className="monitorFacts"><span><i/> Persistent branch state</span><span><i/> Automatic movement detection</span><span><i/> Idempotent event processing</span></div></div><div className="monitorStage reveal"><div className="monitorOrbit"><div className="orbitCenter"><span>BR 02</span><b>DORMANT</b><small>WATCHING</small></div><i className="orbitRing r1"/><i className="orbitRing r2"/><i className="orbitPing p1"/><i className="orbitPing p2"/></div><div className="eventCard dormantEvent"><span>12:41:21</span><b>Funds stationary</b><small>10,680 USDC · Base</small></div><div className="eventCard movementEvent"><span>MOVEMENT DETECTED</span><b>Tracing resumed</b><small>New transaction confirmed</small></div><div className="resumePath"><span>DORMANT</span><i>→</i><span>DETECTED</span><i>→</i><span>RESUMED</span></div></div></section>

  <section className="productSection"><div className="sectionIntro reveal"><div><span className="sectionKicker">04 / LIVE INVESTIGATION</span><h2>The case stays legible<br/>as the trail expands.</h2></div><p>The production case view reads from the same real API, persisted graph, and timeline used by the investigation workflow.</p></div><div className="productFrame reveal"><div className="productTop"><Brand/><span><i/> LIVE CASE</span><button onClick={onStart}>Open investigation ↗</button></div><div className="productBody"><div className="productSidebar"><small>CASE</small><b>Overview</b><span>Fund graph</span><span>Evidence</span><span>Timeline</span><div><i/> MONITOR ACTIVE</div></div><div className="productCanvas"><div className="caseTitle"><div><small>CASE NMS-2048</small><h3>Incident investigation</h3></div><span>ACTIONABLE</span></div><div className="caseStats"><div><small>CHAIN</small><b>ETHEREUM</b></div><div><small>TRACE BRANCHES</small><b>04</b></div><div><small>MONITORED</small><b>01</b></div><div><small>RPC STATUS</small><b className="verified">VERIFIED</b></div></div><div className="caseGrid"><div className="caseGraph"><div className="casePanelHead">LIVE FUND GRAPH <span>PERSISTED</span></div><div className="caseNodes"><span>VICTIM<small>0x71C4</small></span><i/><span>ATTACKER<small>0x8F21</small></span><i/><span>SPLIT<small>4 branches</small></span><i/><span>BASE<small>continued</small></span></div></div><div className="caseFeed"><div className="casePanelHead">TIMELINE <span>LIVE</span></div><div><i/><p><b>Actionable destination detected</b><small>RPC evidence persisted</small></p></div><div><i/><p><b>Cross-chain continuation</b><small>Bridge event resolved</small></p></div><div><i/><p><b>Movement detected</b><small>Trace automatically resumed</small></p></div></div></div></div></div></div></section>

  <section className="evidenceFirst"><div className="evidenceStatement reveal"><span className="sectionKicker">05 / EVIDENCE FIRST</span><h2>AI can interpret the evidence.<br/><em>It cannot rewrite it.</em></h2><p>Transaction receipts, block timestamps, transfer logs, and branch paths are normalized and stored before Gemini examines the case.</p></div><div className="evidenceFlow reveal"><div><span>01</span><b>Provider evidence</b><small>RPC receipts, blocks, logs</small></div><i>→</i><div><span>02</span><b>Deterministic record</b><small>Normalized and persisted</small></div><i>→</i><div><span>03</span><b>Agent interpretation</b><small>Finding with references</small></div></div><div className="evidenceRule reveal"><span>THE RULE</span><blockquote>“Every conclusion points back to facts the chain can prove.”</blockquote><small>Limitations remain visible. Attribution is never invented.</small></div></section>

  <section className="proofSection"><div className="proofIntro reveal"><span className="sectionKicker light">06 / SYSTEM PROOF</span><h2>Built as an autonomous system.<br/>Not a scripted prototype.</h2></div><div className="proofGrid">{["Ethereum + Base","Real RPC evidence","Multi-hop tracing","Google ADK","Gemini 3.5 Flash","Firestore persistence","Pub/Sub events","Cloud Scheduler","Movement detection"].map((x,i)=><div className="reveal" key={x}><span>{String(i+1).padStart(2,"0")}</span><b>{x}</b></div>)}</div><p className="proofNote">These are implementation facts—not invented performance claims.</p></section>

  <section id="trust" className="trustSection"><div className="sectionIntro reveal"><div><span className="sectionKicker">07 / TRUST & LIMITS</span><h2>Clear about what<br/>the chain can prove.</h2></div><p>NEMESIS is an investigation and evidence system. It does not promise recovery or claim access it does not have.</p></div><div className="faqList reveal">{[
   ["What happens when funds stop moving?","The branch becomes dormant and remains monitored. When confirmed movement appears, NEMESIS records the event and automatically resumes tracing."],
   ["Can NEMESIS identify the thief?","No. It can trace addresses and transaction paths, but an address alone does not prove a real-world identity."],
   ["Does NEMESIS have exchange KYC data?","No. It may detect a known service destination from supported attribution evidence, but it has no customer UID, email, or KYC access."],
   ["Can it freeze or recover funds?","No. NEMESIS prepares evidence for escalation; it cannot freeze assets, compel an exchange, or guarantee recovery."],
   ["How are swaps and bridges handled?","They are continued only where deterministic receipt and protocol evidence connects the input movement to the output or destination."],
   ["What makes the evidence deterministic?","Blockchain facts are retrieved from RPC providers, normalized, referenced, and persisted independently of the AI finding."]
  ].map(([q,a],i)=><details key={q} open={i===0}><summary><span>{String(i+1).padStart(2,"0")}</span>{q}<i>+</i></summary><p>{a}</p></details>)}</div></section>

  <section className="finalCta"><div className="ctaSignal"><i/><i/><i/><i/><i/></div><span className="sectionKicker light">THE TRAIL IS STILL THERE</span><h2>Start with the transaction.<br/><em>Let NEMESIS follow the rest.</em></h2><p>Open a real investigation or explore the complete tracing workflow with controlled deterministic evidence.</p><div><button className="primary" onClick={onStart}>Start investigation <span>→</span></button><button className="demoCta" onClick={onDemo}>Run deterministic demo</button></div></section>
  <footer><Brand/><p>Autonomous crypto incident response.<br/>Evidence first, always.</p><div><a href="#system">System</a><a href="#intelligence">Intelligence</a><a href="#trust">Trust</a></div><small>© 2026 NEMESIS</small></footer>
 </main>
}

function Intake({onBack,onReal,onDemo}:{onBack:()=>void;onReal:(data:RealResponse)=>void;onDemo:()=>void}){
 const[wallet,setWallet]=useState("");const[chain,setChain]=useState("ethereum");const[hash,setHash]=useState("");const[loading,setLoading]=useState(false);const[error,setError]=useState("");
 async function submit(){
  setLoading(true);setError("");
  try{
   const api=process.env.NEXT_PUBLIC_NEMESIS_API_URL;
   if(!api)throw new Error("The real investigation API is not configured for this deployment.");
   const response=await fetch(`${api.replace(/\/$/,"")}/v1/cases`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({wallet_address:wallet,chain,theft_transaction_hash:hash})});
   const payload=await response.json();
   if(!response.ok)throw new Error(payload.detail||"Investigation failed");
   onReal(payload as RealResponse);
  }catch(reason){setError(reason instanceof Error?reason.message:"Investigation failed")}finally{setLoading(false)}
 }
 return <main className="intake page"><nav><Brand/><button className="linkBtn" onClick={onBack}>← Back</button></nav><div className="formWrap"><div className="eyebrow">OPEN A REAL CASE</div><h2>Start an investigation</h2><p>Submit a confirmed transaction. The backend will retrieve and normalize its evidence before the agent investigates it.</p><div className="fields"><label>Wallet address<input value={wallet} onChange={e=>setWallet(e.target.value)} placeholder="0x…"/></label><label>Chain<select value={chain} onChange={e=>setChain(e.target.value)}><option value="ethereum">Ethereum</option><option value="base">Base</option></select></label><label className="wide">Theft transaction hash<input value={hash} onChange={e=>setHash(e.target.value)} placeholder="0x…"/></label></div><div className="evidenceNote"><span>◆</span><p><strong>Evidence first</strong>RPC evidence is stored before Gemini receives it. The agent cannot replace deterministic transaction facts.</p></div>{error&&<div className="formError">{error}</div>}<button className="primary submit" disabled={loading||wallet.length!==42||hash.length!==66} onClick={submit}>{loading?"Investigating onchain evidence…":"Create case & begin investigation"} <span>↗</span></button><button className="demoButton" onClick={onDemo}>Run deterministic demo instead</button></div></main>
}

function Shell({children,onExit,onHome,monitor=false}:{children:(section:CaseSection)=>React.ReactNode;onExit:()=>void;onHome:()=>void;monitor?:boolean}){
 const[section,setSection]=useState<CaseSection>("overview");
 return <main className="casePage"><aside><Brand onClick={onHome}/><div className="caseNav"><span>CASE</span>
  <button className={section==="overview"?"selected":""} onClick={()=>setSection("overview")}>◈ Overview</button>
  <button className={section==="graph"?"selected":""} onClick={()=>setSection("graph")}>⌁ Fund graph</button>
  <button className={section==="evidence"?"selected":""} onClick={()=>setSection("evidence")}>◎ Evidence</button>
  <button className={section==="timeline"?"selected":""} onClick={()=>setSection("timeline")}>▤ Timeline</button>
 </div>{monitor&&<div className="monitorBox"><i/><div><b>MONITOR ACTIVE</b><small>1 dormant branch</small></div></div>}<button className="newCase" onClick={onExit}>＋ New investigation</button></aside>{children(section)}</main>
}

function RealGraph({data,trace}:{data:RealResponse;trace:TraceState|null}){
 const tx=data.case.evidence.transaction;if(trace?.graph.nodes.length){const positions=new Map(trace.graph.nodes.map((n,i)=>[n.id,{x:8+(i%4)*27,y:25+Math.floor(i/4)*45}]));return <div className="graph realGraph"><div className="graphGrid"/><svg viewBox="0 0 100 100" preserveAspectRatio="none">{trace.graph.edges.map(e=>{const a=positions.get(e.source),b=positions.get(e.target);return a&&b?<line key={e.id} x1={a.x+4} y1={a.y+3} x2={b.x+4} y2={b.y+3}/>:null})}</svg>{trace.graph.nodes.map(n=>{const p=positions.get(n.id)!;return <div key={n.id} className="node process" style={{left:`${p.x}%`,top:`${p.y}%`}}><span>{n.label.toUpperCase()}</span><small>{short(n.address)}</small></div>})}</div>}
 const graphNodes=[{label:"SUBMITTED WALLET",sub:short(data.case.wallet_address),x:8,type:"victim"},{label:"TRANSACTION FROM",sub:short(tx.from_address),x:35,type:"process"},{label:tx.to_address?"TRANSACTION TO":"CONTRACT CREATED",sub:short(tx.to_address),x:63,type:tx.status==="success"?"process":"bad"},{label:"RPC VERIFIED",sub:`block ${tx.block_number}`,x:88,type:"good"}];return <div className="graph realGraph"><div className="graphGrid"/><svg viewBox="0 0 100 100" preserveAspectRatio="none"><line x1="12" y1="45" x2="39" y2="45"/><line x1="39" y1="45" x2="67" y2="45"/><line x1="67" y1="45" x2="92" y2="45"/></svg>{graphNodes.map(n=><div key={n.label} className={`node ${n.type}`} style={{left:`${n.x}%`,top:"45%"}}><span>{n.label}</span><small>{n.sub}</small></div>)}</div>
}

function RealCaseScreen({data,onExit,onHome}:{data:RealResponse;onExit:()=>void;onHome:()=>void}){
 const c=data.case,tx=c.evidence.transaction,f=c.finding||{classification:"agent unavailable",summary:c.error||"Deterministic evidence was stored, but Gemini classification is not available.",confidence:0,evidence_references:[],limitations:["Gemini classification requires configured Google credentials."]};
 const[trace,setTrace]=useState<TraceState|null>(null);useEffect(()=>{let active=true;const api=process.env.NEXT_PUBLIC_NEMESIS_API_URL?.replace(/\/$/,"");async function refresh(){if(!api)return;try{const r=await fetch(`${api}/v1/cases/${c.id}/trace`);if(r.ok&&active)setTrace(await r.json())}catch{}}refresh();const id=setInterval(refresh,5000);return()=>{active=false;clearInterval(id)}},[c.id]);
 const exportJson=()=>{const a=document.createElement("a");a.href=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));a.download=`${c.id}-evidence.json`;a.click();URL.revokeObjectURL(a.href)};
 return <Shell onExit={onExit} onHome={onHome} monitor={!!trace?.branches.some(b=>b.status==="DORMANT")}>{section=><section className="caseMain"><header><div><div className="eyebrow">CASE {c.id}</div><h2>Incident investigation</h2></div><div className={`status ${tx.status==="success"?"actionable":"dormant"}`}><i/>{c.state}</div></header><div className="metrics"><div><small>CHAIN</small><strong>{c.chain.toUpperCase()}</strong><span>RPC verified</span></div><div><small>TRANSACTION STATUS</small><strong className="accent">{tx.status.toUpperCase()}</strong><span>Receipt confirmed</span></div><div><small>TRACE BRANCHES</small><strong>{trace?.branches.length||0}</strong><span>{trace?.branches.filter(b=>b.status==="DORMANT").length||0} monitored</span></div><div><small>ERC20 TRANSFERS</small><strong>{tx.erc20_transfers.length}</strong><span>Decoded from receipt</span></div></div><div className="workspace" style={section==="overview"?undefined:{gridTemplateColumns:"1fr"}}>
  {(section==="overview"||section==="graph")&&<section className="panel graphPanel"><div className="panelHead"><div><span>LIVE FUND GRAPH</span><small> PERSISTED RPC EVIDENCE</small></div></div><RealGraph data={data} trace={trace}/></section>}
  {(section==="overview"||section==="timeline")&&<section className="panel activity realActivity"><div className="panelHead"><span>TASKMASTER ACTIVITY</span><small>LIVE</small></div><div className="now"><i/><div><b>{trace?.timeline.at(-1)?.message||"Tracing funds"}</b><span>Persisted backend events</span></div></div><div className="timeline">{(trace?.timeline||[]).slice().reverse().map(e=><div key={e.id}><time>{new Date(e.created_at).toLocaleTimeString()}</time><i/><p><b>{e.message}</b><span>{e.type.replaceAll("_"," ")}</span></p></div>)}</div></section>}
  {(section==="overview"||section==="evidence")&&<section className="panel diagnosis"><div className="panelHead"><span>WHAT HAPPENED</span><small>{Math.round(f.confidence*100)}% CONFIDENCE</small></div><h3>{f.classification.replaceAll("_"," ")}</h3><p>{f.summary}</p><div className="evidenceRows"><span>Submitted wallet <b>{short(c.wallet_address)}</b></span><span>Transaction <b>{short(tx.hash)}</b></span><span>From <b>{short(tx.from_address)}</b></span><span>To <b>{short(tx.to_address)}</b></span></div>{f.limitations.length>0&&<small className="caution">{f.limitations.join(" · ")}</small>}</section>}
  {section==="overview"&&<section className="panel destination"><div className="panelHead"><span>TRACE BRANCHES</span><small>{trace?.branches.length||0} FOUND</small></div>{trace?.branches.length?<div className="transferList">{trace.branches.map(b=><div key={b.id}><span>{b.status}</span><b>{short(b.current_address)}</b><small>{short(b.asset)} · raw amount {b.amount}</small></div>)}</div>:<div className="emptyTrace">No qualifying outgoing fund path was present.</div>}</section>}
  {(section==="overview"||section==="evidence")&&<section className="panel escalation"><div className="panelHead"><span>DETERMINISTIC EVIDENCE</span><small>STORED</small></div><div className="packageIcon">▤</div><div><h3>Normalized transaction package</h3><p>RPC facts and ADK classification are separated and structured.</p></div><button onClick={exportJson}>Download JSON</button></section>}
 </div></section>}</Shell>
}

function DemoGraph({progress,awakened}:{progress:number;awakened:boolean}){const visible=demoNodes.filter((_,i)=>i<=Math.min(7,progress+1));const shown=demoEdges.filter(([a,b])=>visible[a]&&visible[b]);return <div className="graph"><div className="graphGrid"/><svg viewBox="0 0 100 100" preserveAspectRatio="none">{shown.map(([a,b],i)=><line key={i} x1={demoNodes[a].x+4} y1={demoNodes[a].y+3} x2={demoNodes[b].x+4} y2={demoNodes[b].y+3} className={b===7&&awakened?"wakeLine":""}/>)}</svg>{visible.map((n,i)=><div key={n.label} className={`node ${n.type} ${i===7&&awakened?"awake":""}`} style={{left:`${n.x}%`,top:`${n.y}%`}}><span>{i===7&&awakened?"MOVEMENT":n.label}</span><small>{i===7&&awakened?"resuming trace":n.sub}</small></div>)}</div>}

function DemoCaseScreen({onExit,onHome}:{onExit:()=>void;onHome:()=>void}){
 const[progress,setProgress]=useState(0);const[awakened,setAwakened]=useState(false);const timer=useRef<ReturnType<typeof setInterval>|null>(null);
 useEffect(()=>{timer.current=setInterval(()=>setProgress(p=>{if(p>=7){if(timer.current)clearInterval(timer.current);return 7}return p+1}),900);return()=>{if(timer.current)clearInterval(timer.current)}},[]);
 const status=progress<3?"MOVING":progress<7?"DORMANT":"ACTIONABLE";
 return <Shell onExit={onExit} onHome={onHome} monitor>{section=><section className="caseMain"><header><div><div className="eyebrow">DETERMINISTIC SYNTHETIC CASE</div><h2>Incident investigation</h2></div><div className={`status ${status.toLowerCase()}`}><i/>{status}</div></header><div className="metrics"><div><small>STOLEN VALUE</small><strong>$42,180.00</strong><span>42,180 USDC</span></div><div><small>LOCATED VALUE</small><strong className="accent">$42,180.00</strong><span>100% traced</span></div><div><small>UNRESOLVED</small><strong>$10,680.00</strong><span>1 branch monitored</span></div><div><small>RECOVERED</small><strong>$0.00</strong><span>Not claimed</span></div></div><div className="workspace" style={section==="overview"?undefined:{gridTemplateColumns:"1fr"}}>
  {(section==="overview"||section==="graph")&&<section className="panel graphPanel"><div className="panelHead"><span>LIVE FUND GRAPH</span><small>DEMO DATA</small></div><DemoGraph progress={progress} awakened={awakened}/></section>}
  {(section==="overview"||section==="timeline")&&<section className="panel activity"><div className="panelHead"><span>AGENT ACTIVITY</span><small>SIMULATED</small></div><div className="now"><i/><div><b>{progress<7?demoSteps[Math.min(progress+1,6)].title:awakened?"Tracing resumed on branch BR 02…":"Evidence package ready"}</b><span>Deterministic demonstration sequence</span></div></div><div className="timeline">{demoSteps.slice(0,progress+1).reverse().map(s=><div key={s.title}><time>{s.time}</time><i className={s.tone||""}/><p><b>{s.title}</b><span>{s.detail}</span></p></div>)}</div>{progress>=6&&!awakened&&<button className="simulate" onClick={()=>setAwakened(true)}>Simulate dormant branch movement</button>}</section>}
  {(section==="overview"||section==="evidence")&&<section className="panel diagnosis"><div className="panelHead"><span>WHAT HAPPENED</span><small>DEMO CLASSIFICATION</small></div><h3>Malicious approval theft</h3><p>This is controlled synthetic evidence for demonstrating the deeper tracing workflow.</p></section>}
  {(section==="overview"||section==="evidence")&&<section className="panel destination"><div className="panelHead"><span>WHERE THE MONEY IS</span><small>{progress>=7?"1 ACTIONABLE":"TRACING"}</small></div>{progress>=7?<><div className="alertTitle"><i/>ACTIONABLE DESTINATION DETECTED</div><h3>Coinbase</h3><p className="disclaimer">Synthetic demo attribution. No real exchange account holder or KYC identity is claimed.</p></>:<div className="emptyTrace">Following the synthetic active branch…</div>}</section>}
 </div></section>}</Shell>
}

export default function Home(){
 const[view,setView]=useState<"landing"|"intake"|"real"|"demo">("landing");const[real,setReal]=useState<RealResponse|null>(null);
 if(view==="landing")return <Landing onStart={()=>setView("intake")} onDemo={()=>setView("demo")}/>;
 if(view==="intake")return <Intake onBack={()=>setView("landing")} onReal={data=>{setReal(data);setView("real")}} onDemo={()=>setView("demo")}/>;
 if(view==="real"&&real)return <RealCaseScreen data={real} onExit={()=>setView("intake")} onHome={()=>setView("landing")}/>;
 return <DemoCaseScreen onExit={()=>setView("intake")} onHome={()=>setView("landing")}/>;
}
