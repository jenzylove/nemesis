"use client";

import {useEffect} from "react";

export default function AutoChainEnhancer(){
 useEffect(()=>{
  const enhance=()=>{
   const select=document.querySelector<HTMLSelectElement>("main.intake .fields select");
   if(select&&select.dataset.autoChainEnhanced!=="true"){
    select.dataset.autoChainEnhanced="true";
    if(!Array.from(select.options).some(option=>option.value==="auto")){
     const option=document.createElement("option");
     option.value="auto";
     option.textContent="Auto detect · Ethereum + Base";
     select.insertBefore(option,select.firstChild);
    }
    select.value="auto";
    select.dispatchEvent(new Event("change",{bubbles:true}));
    const label=select.closest("label");
    if(label)label.childNodes.forEach(node=>{
     if(node.nodeType===Node.TEXT_NODE&&node.textContent?.trim()==="Chain")node.textContent="Network ";
    });
   }

   const note=document.querySelector<HTMLElement>("main.intake .evidenceNote p");
   if(note?.textContent?.includes("Bitquery")){
    const strong=note.querySelector("strong")?.outerHTML||"<strong>Evidence first</strong>";
    note.innerHTML=`${strong} Indexed wallet history searches the supported networks; risk intelligence can enrich candidates; RPC still verifies the selected transaction before Gemini receives it.`;
   }

   document.querySelectorAll<HTMLElement>(".evidenceRows span").forEach(row=>{
    if(row.textContent?.includes("BITQUERY ·"))row.innerHTML=row.innerHTML.replace("BITQUERY ·","INDEXED DISCOVERY ·");
   });
  };
  enhance();
  const observer=new MutationObserver(enhance);
  observer.observe(document.body,{childList:true,subtree:true});
  return()=>observer.disconnect();
 },[]);
 return null;
}
