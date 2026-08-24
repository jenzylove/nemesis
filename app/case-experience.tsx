"use client";

import {useEffect} from "react";

function text(el: Element | null){return el?.textContent?.trim()||""}
function setText(node: Node | null | undefined,value:string){if(node&&node.textContent!==value)node.textContent=value}

export default function CaseExperienceEnhancer(){
 useEffect(()=>{
  const enhance=()=>{
   const page=document.querySelector<HTMLElement>("main.casePage");
   if(!page)return;

   const aside=page.querySelector<HTMLElement>("aside");
   const homeButton=aside?.querySelector<HTMLButtonElement>(".brand");
   const newCaseButton=aside?.querySelector<HTMLButtonElement>(".newCase");

   if(!page.querySelector(".caseMobileBar")){
    const bar=document.createElement("div");
    bar.className="caseMobileBar";
    const home=document.createElement("button");
    home.type="button";
    home.className="caseMobileHome";
    home.textContent="NEMESIS";
    home.onclick=()=>homeButton?.click();
    const fresh=document.createElement("button");
    fresh.type="button";
    fresh.className="caseMobileNew";
    fresh.textContent="New investigation";
    fresh.onclick=()=>newCaseButton?.click();
    bar.append(home,fresh);
    page.prepend(bar);
   }

   const branchRows=Array.from(page.querySelectorAll<HTMLElement>(".transferList > div"));
   const dormantCount=branchRows.filter(row=>text(row.querySelector("span")).toUpperCase()==="DORMANT").length;
   const movingCount=branchRows.filter(row=>text(row.querySelector("span")).toUpperCase()==="MOVING").length;
   const actionableCount=branchRows.filter(row=>text(row.querySelector("span")).toUpperCase()==="ACTIONABLE").length;

   const status=page.querySelector<HTMLElement>(".caseMain header .status");
   if(status){
    if(actionableCount>0)setText(status.lastChild,"ACTIONABLE");
    else if(dormantCount>0)setText(status.lastChild,"MONITORING");
    else if(movingCount>0)setText(status.lastChild,"TRACING");
    else if(text(status).toUpperCase().includes("COMPLETE"))setText(status.lastChild,"EVIDENCE READY");
   }

   const monitorBox=page.querySelector<HTMLElement>(".monitorBox");
   if(monitorBox){
    const title=monitorBox.querySelector<HTMLElement>("b");
    const detail=monitorBox.querySelector<HTMLElement>("small");
    setText(title,dormantCount>0?"MONITORING FUNDS":"MONITOR ACTIVE");
    setText(detail,dormantCount>0?`${dormantCount} dormant ${dormantCount===1?"branch":"branches"}`:"Watching case activity");
   }

   const activityHead=Array.from(page.querySelectorAll<HTMLElement>(".panelHead span")).find(el=>text(el)==="TASKMASTER ACTIVITY");
   setText(activityHead,"INVESTIGATION ACTIVITY");

   const now=page.querySelector<HTMLElement>(".realActivity .now");
   if(now){
    const subtitle=now.querySelector<HTMLElement>("span");
    if(subtitle){
     if(dormantCount>0)setText(subtitle,`${dormantCount} fund ${dormantCount===1?"path is":"paths are"} stationary. NEMESIS will recheck ${dormantCount===1?"this destination":"these destinations"} and resume tracing when verified movement appears.`);
     else setText(subtitle,"Live case events from the persisted investigation workflow.");
    }
   }

   const destination=page.querySelector<HTMLElement>(".panel.destination");
   if(destination&&!destination.querySelector(".branchExplanation")&&branchRows.length){
    const note=document.createElement("div");
    note.className="branchExplanation";
    note.innerHTML=dormantCount>0
      ? `<strong>${dormantCount} ${dormantCount===1?"fund path is":"fund paths are"} currently dormant.</strong><span>Dormant means NEMESIS found no verified onward movement from the current destination. The branch remains persisted and monitored so tracing can resume automatically later.</span>`
      : `<strong>${branchRows.length} traced ${branchRows.length===1?"path":"paths"}.</strong><span>Each branch below represents a persisted fund path created from verified on-chain evidence.</span>`;
    const head=destination.querySelector(".panelHead");
    head?.insertAdjacentElement("afterend",note);
   }

   branchRows.forEach((row,index)=>{
    if(row.dataset.humanized==="true")return;
    row.dataset.humanized="true";
    const state=row.querySelector<HTMLElement>("span");
    const address=row.querySelector<HTMLElement>("b");
    const detail=row.querySelector<HTMLElement>("small");
    if(state)state.textContent=`BRANCH ${String(index+1).padStart(2,"0")} · ${text(state)}`;
    if(address)address.insertAdjacentHTML("beforebegin","<em class=\"branchLabel\">Current destination</em>");
    if(detail)detail.textContent=detail.textContent?.replace("raw amount ","on-chain amount ")||"";
   });

   const graphPanel=page.querySelector<HTMLElement>(".graphPanel");
   if(graphPanel&&!graphPanel.querySelector(".graphExplanation")){
    const note=document.createElement("div");
    note.className="graphExplanation";
    note.textContent="This graph is generated from the persisted trace state. Every visible node and edge represents a recorded fund path, not a decorative demo path.";
    graphPanel.querySelector(".panelHead")?.insertAdjacentElement("afterend",note);
   }
  };

  enhance();
  let frame=0;
  const observer=new MutationObserver(()=>{
   if(frame)return;
   frame=requestAnimationFrame(()=>{frame=0;enhance()});
  });
  observer.observe(document.body,{childList:true,subtree:true});
  return()=>{observer.disconnect();if(frame)cancelAnimationFrame(frame)};
 },[]);
 return null;
}
