"use client";

import {useEffect} from "react";

export default function AutoChainEnhancer(){
 useEffect(()=>{
  const enhance=()=>{
   const select=document.querySelector<HTMLSelectElement>("main.intake .fields select");
   if(!select||select.dataset.autoChainEnhanced==="true")return;
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
  };
  enhance();
  const observer=new MutationObserver(enhance);
  observer.observe(document.body,{childList:true,subtree:true});
  return()=>observer.disconnect();
 },[]);
 return null;
}
