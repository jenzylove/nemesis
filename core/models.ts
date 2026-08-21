export type Chain="ethereum"|"base"|"arbitrum"|"polygon";
export type CaseState="MOVING"|"DORMANT"|"OBSCURED"|"ACTIONABLE"|"RECOVERED";
export interface TokenTransfer{asset:string;contract:string;from:string;to:string;amount:string;decimals:number}
export interface NormalizedTransaction{hash:string;chain:Chain;timestamp:string;status:"success"|"failed";from:string;to:string;nativeValue:string;tokenTransfers:TokenTransfer[];contractInteractions:{contract:string;method?:string;input?:string}[];blockNumber:number}
export interface TraceBranch{id:string;state:CaseState;currentAddress:string;chain:Chain;amountUsd:number;transactions:NormalizedTransaction[];parentBranchId?:string;confidence:number}
export interface IncidentCase{id:string;victimWallet:string;chain:Chain;theftTransactionHash?:string;approximateIncidentTime?:string;state:CaseState;totals:{stolen:number;located:number;unresolved:number;recovered:number};branches:TraceBranch[];createdAt:string;updatedAt:string}
