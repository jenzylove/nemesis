"use client";

import {useEffect,useMemo,useRef,useState} from "react";
import {
  createUserWithEmailAndPassword,
  getAuth,
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import {getApps,initializeApp} from "firebase/app";

type CaseSummary={
  id:string;
  state:string;
  wallet_address:string;
  chain:string;
  created_at?:string;
  updated_at?:string;
  theft_transaction_hash?:string|null;
  finding?:{classification?:string;confidence?:number;summary?:string}|null;
};

type TraceData={
  branches:Array<{id:string;current_address:string;asset:string;amount:string;status:string;last_transaction?:string}>;
  timeline:Array<{id:string;type:string;message:string;created_at:string}>;
};

type ReopenedCase={case:CaseSummary;trace:TraceData};

type PendingRequest={
  input:RequestInfo|URL;
  init?:RequestInit;
  resolve:(response:Response)=>void;
  reject:(error:unknown)=>void;
};

const API=(process.env.NEXT_PUBLIC_NEMESIS_API_URL||"").replace(/\/$/,"");
const firebaseConfig={
  apiKey:process.env.NEXT_PUBLIC_FIREBASE_API_KEY||"",
  authDomain:process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN||"",
  projectId:process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID||"",
  appId:process.env.NEXT_PUBLIC_FIREBASE_APP_ID||"",
};

const configured=Boolean(firebaseConfig.apiKey&&firebaseConfig.authDomain&&firebaseConfig.projectId&&firebaseConfig.appId);
const app=configured?(getApps()[0]||initializeApp(firebaseConfig)):null;
const auth=app?getAuth(app):null;

function withToken(init:RequestInit|undefined,token:string){
  const headers=new Headers(init?.headers||{});
  headers.set("Authorization",`Bearer ${token}`);
  return {...init,headers};
}

function isNemesisApi(input:RequestInfo|URL){
  const value=typeof input==="string"?input:input instanceof URL?input.toString():input.url;
  return Boolean(API&&value.startsWith(API+"/v1/"));
}

function isCreateCase(input:RequestInfo|URL,init?:RequestInit){
  const value=typeof input==="string"?input:input instanceof URL?input.toString():input.url;
  return isNemesisApi(input)&&value===`${API}/v1/cases`&&(init?.method||"GET").toUpperCase()==="POST";
}

const short=(value:string|undefined|null)=>value&&value.length>16?`${value.slice(0,8)}…${value.slice(-6)}`:(value||"—");
const human=(value:string|undefined|null)=>value?value.replaceAll("_"," "):"Incident investigation";

export default function AuthGate(){
  const [user,setUser]=useState<User|null>(null);
  const [ready,setReady]=useState(!configured);
  const [modal,setModal]=useState(false);
  const [historyOpen,setHistoryOpen]=useState(false);
  const [mode,setMode]=useState<"signin"|"signup">("signin");
  const [email,setEmail]=useState("");
  const [password,setPassword]=useState("");
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [cases,setCases]=useState<CaseSummary[]>([]);
  const [historyBusy,setHistoryBusy]=useState(false);
  const [pending,setPending]=useState<PendingRequest|null>(null);
  const [reopened,setReopened]=useState<ReopenedCase|null>(null);
  const refreshInFlight=useRef(false);

  const label=useMemo(()=>user?"My investigations":"Sign in",[user]);

  useEffect(()=>{
    if(!auth){setReady(true);return;}
    return onAuthStateChanged(auth,next=>{setUser(next);setReady(true);});
  },[]);

  useEffect(()=>{
    if(typeof window==="undefined")return;
    const original=window.fetch.bind(window);
    window.fetch=async(input:RequestInfo|URL,init?:RequestInit)=>{
      if(!isNemesisApi(input))return original(input,init);
      const current=auth?.currentUser||null;
      if(!current&&isCreateCase(input,init)){
        setModal(true);
        return new Promise<Response>((resolve,reject)=>setPending({input,init,resolve,reject}));
      }
      if(!current)return original(input,init);
      const token=await current.getIdToken();
      return original(input,withToken(init,token));
    };
    return()=>{window.fetch=original;};
  },[]);

  useEffect(()=>{
    if(!pending||!user)return;
    let cancelled=false;
    (async()=>{
      try{
        const token=await user.getIdToken();
        const response=await fetch(pending.input,withToken(pending.init,token));
        if(!cancelled)pending.resolve(response);
      }catch(err){if(!cancelled)pending.reject(err);}finally{
        if(!cancelled){setPending(null);setModal(false);}
      }
    })();
    return()=>{cancelled=true;};
  },[pending,user]);

  // A returning user opens the modal from the account dock, so there is no
  // intercepted request to resolve and nothing else closes it. Without this the
  // sign-in succeeds, the dock updates behind the backdrop, and the modal stays
  // over the page with pointer events captured. When a request is pending the
  // effect above keeps the modal up until that investigation resumes.
  useEffect(()=>{
    if(user&&!pending)setModal(false);
  },[user,pending]);

  useEffect(()=>{
    if(!reopened||!auth?.currentUser)return;
    const id=setInterval(()=>void refreshOpenCase(reopened.case.id,false),15000);
    return()=>clearInterval(id);
  },[reopened?.case.id]);

  async function google(){
    if(!auth)return setError("Authentication is not configured yet.");
    setBusy(true);setError("");
    try{await signInWithPopup(auth,new GoogleAuthProvider());}
    catch(err){setError(err instanceof Error?err.message:"Unable to sign in.");}
    finally{setBusy(false);}
  }

  async function emailAuth(){
    if(!auth)return setError("Authentication is not configured yet.");
    if(!email||password.length<6)return setError("Enter a valid email and a password of at least 6 characters.");
    setBusy(true);setError("");
    try{
      if(mode==="signup")await createUserWithEmailAndPassword(auth,email,password);
      else await signInWithEmailAndPassword(auth,email,password);
    }catch(err){setError(err instanceof Error?err.message:"Unable to continue.");}
    finally{setBusy(false);}
  }

  async function loadCases(){
    if(!auth?.currentUser)return setModal(true);
    setHistoryOpen(true);setHistoryBusy(true);setError("");
    try{
      const token=await auth.currentUser.getIdToken();
      const response=await fetch(`${API}/v1/me/cases`,{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw new Error(`Could not load investigations (${response.status}).`);
      setCases(await response.json());
    }catch(err){setError(err instanceof Error?err.message:"Could not load investigations.");}
    finally{setHistoryBusy(false);}
  }

  async function refreshOpenCase(caseId:string,showBusy=true){
    if(!auth?.currentUser)return;
    if(refreshInFlight.current)return;
    refreshInFlight.current=true;
    if(showBusy)setHistoryBusy(true);
    setError("");
    try{
      const token=await auth.currentUser.getIdToken();
      const headers={Authorization:`Bearer ${token}`};
      const [caseRes,traceRes]=await Promise.all([
        fetch(`${API}/v1/cases/${caseId}`,{headers}),
        fetch(`${API}/v1/cases/${caseId}/trace`,{headers}),
      ]);
      if(!caseRes.ok||!traceRes.ok)throw new Error("Could not reopen this investigation.");
      setReopened({case:await caseRes.json(),trace:await traceRes.json()});
      setHistoryOpen(false);
    }catch(err){setError(err instanceof Error?err.message:"Could not reopen this investigation.");}
    finally{refreshInFlight.current=false;if(showBusy)setHistoryBusy(false);}
  }

  async function logout(){if(auth)await signOut(auth);setCases([]);setHistoryOpen(false);setReopened(null);}

  if(!ready)return null;
  const dormant=reopened?.trace.branches.filter(branch=>branch.status==="DORMANT").length||0;
  const actionable=reopened?.trace.branches.filter(branch=>branch.status==="ACTIONABLE").length||0;
  return <>
    <div className="authDock" role="navigation" aria-label="Account">
      <button type="button" className="authPrimary" onClick={()=>user?loadCases():setModal(true)}>{label}</button>
    </div>

    {modal&&<div className="authBackdrop" onMouseDown={e=>{if(e.target===e.currentTarget&&!pending)setModal(false);}}>
      <section className="authModal" role="dialog" aria-modal="true" aria-label="Sign in to NEMESIS">
        <button className="authClose" type="button" disabled={Boolean(pending)} onClick={()=>setModal(false)}>×</button>
        <span className="authEyebrow">NEMESIS ACCOUNT</span>
        <h2>{pending?"Continue your investigation":"Welcome back"}</h2>
        <p>{pending?"Sign in to begin tracing this wallet and keep the case available while NEMESIS monitors fund movement.":"Sign in to open your saved investigations and continue monitoring from any device."}</p>
        {!configured&&<div className="authNotice">Firebase Authentication still needs to be enabled for this deployment.</div>}
        <button className="authGoogle" type="button" onClick={google} disabled={busy||!configured}>Continue with Google</button>
        <div className="authDivider"><span>or</span></div>
        <div className="authTabs"><button className={mode==="signin"?"active":""} onClick={()=>setMode("signin")}>Sign in</button><button className={mode==="signup"?"active":""} onClick={()=>setMode("signup")}>Create account</button></div>
        <input value={email} onChange={e=>setEmail(e.target.value)} type="email" autoComplete="email" placeholder="Email address"/>
        <input value={password} onChange={e=>setPassword(e.target.value)} type="password" autoComplete={mode==="signup"?"new-password":"current-password"} placeholder="Password"/>
        {error&&<div className="authError">{error}</div>}
        <button className="authContinue" type="button" onClick={emailAuth} disabled={busy||!configured}>{busy?"Please wait…":mode==="signup"?"Create account":"Continue"}</button>
      </section>
    </div>}

    {historyOpen&&<div className="historyBackdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setHistoryOpen(false);}}>
      <aside className="historyPanel" aria-label="My investigations">
        <header><div><span>YOUR CASES</span><h2>My investigations</h2></div><button onClick={()=>setHistoryOpen(false)}>×</button></header>
        <p className="historyIntro">Your cases stay attached to this account while monitoring continues in the backend.</p>
        {historyBusy&&<div className="historyEmpty">Loading investigations…</div>}
        {!historyBusy&&cases.length===0&&<div className="historyEmpty">No investigations yet. Start one from the NEMESIS home page.</div>}
        <div className="historyList">{cases.map(item=><button key={item.id} type="button" onClick={()=>refreshOpenCase(item.id)} className="historyCard">
          <div><span>{item.state}</span><small>{item.chain?.toUpperCase()}</small></div>
          <strong>{human(item.finding?.classification)}</strong>
          <code>{item.wallet_address}</code>
          <footer><span>{item.id}</span><span>{item.finding?.confidence!=null?`${Math.round(item.finding.confidence*100)}% confidence`:"Open case"} →</span></footer>
        </button>)}</div>
        {error&&<div className="authError">{error}</div>}
        <button className="historySignout" onClick={logout}>Sign out</button>
      </aside>
    </div>}

    {reopened&&<div className="reopenBackdrop">
      <section className="reopenCase" aria-label={`Investigation ${reopened.case.id}`}>
        <header><div><span>SAVED CASE · {reopened.case.id}</span><h2>Incident investigation</h2></div><button onClick={()=>setReopened(null)}>×</button></header>
        <div className="reopenMetrics"><div><small>CHAIN</small><strong>{reopened.case.chain.toUpperCase()}</strong></div><div><small>TRACE PATHS</small><strong>{reopened.trace.branches.length}</strong></div><div><small>MONITORED</small><strong>{dormant}</strong></div><div><small>STATUS</small><strong>{actionable?"ACTIONABLE":dormant?"MONITORING":reopened.case.state}</strong></div></div>
        <section className="reopenFinding"><span>WHAT NEMESIS FOUND</span><h3>{human(reopened.case.finding?.classification)}</h3><p>{reopened.case.finding?.summary||"This case contains persisted deterministic evidence and remains available for review."}</p><div><code>{reopened.case.wallet_address}</code>{reopened.case.finding?.confidence!=null&&<b>{Math.round(reopened.case.finding.confidence*100)}% confidence</b>}</div></section>
        <section className="reopenBranches"><div className="reopenHead"><span>FUND PATHS</span><small>{dormant?`${dormant} being monitored`:"Current trace state"}</small></div>{reopened.trace.branches.length?reopened.trace.branches.map((branch,index)=><article key={branch.id}><div><span>BRANCH {String(index+1).padStart(2,"0")}</span><b>{branch.status}</b></div><strong>{short(branch.current_address)}</strong><small>{short(branch.asset)} · on-chain amount {branch.amount}</small></article>):<p>No qualifying outgoing fund path is currently stored for this case.</p>}</section>
        <section className="reopenTimeline"><div className="reopenHead"><span>LATEST ACTIVITY</span><button onClick={()=>refreshOpenCase(reopened.case.id)}>Refresh</button></div>{reopened.trace.timeline.slice(-6).reverse().map(event=><div key={event.id}><time>{new Date(event.created_at).toLocaleString()}</time><p><b>{event.message}</b><small>{human(event.type)}</small></p></div>)}</section>
        <footer><span>{dormant?`NEMESIS is monitoring ${dormant} dormant ${dormant===1?"fund path":"fund paths"} and will continue server-side even when you leave this page.`:"This case remains saved to your account."}</span><button onClick={()=>{setReopened(null);loadCases();}}>Back to my investigations</button></footer>
      </section>
    </div>}
  </>;
}
