import assert from "node:assert/strict";
import test from "node:test";
import {validateEvmAddress,validateTransactionHash} from "../app/evm-validation.mjs";

const bybit="0x1Db92e2EeBC8E0c075a02BeA49a2935BcD2dFCF4";
const suppliedMalformedBybit="0x1Db92e2EbE8E0c075a02BeA49a2935BcD2dFCF4";
const wazirx="0x27fD43BABfbe83a81d14665b1a6fB8030A60C9b4";
const knownHash="0xefc8bdb9b7c31df1c882de675de11d5ca83b7f176acec2f12c873ac76ff76f0f";

test("accepts valid EVM wallet-only submissions including trimmed pasted values",()=>{
  assert.equal(validateEvmAddress(bybit),"");
  assert.equal(validateEvmAddress(wazirx),"");
  assert.equal(validateEvmAddress(` \n${bybit}\t `),"");
  assert.equal(validateTransactionHash(""),"");
});

test("accepts a trimmed 32-byte transaction hash",()=>{
  assert.equal(validateTransactionHash(` ${knownHash}\n`),"");
});

test("rejects malformed wallet and transaction inputs with actionable messages",()=>{
  assert.match(validateEvmAddress(suppliedMalformedBybit),/exactly 40 hexadecimal characters/);
  assert.match(validateEvmAddress("1Db92e2EeBC8E0c075a02BeA49a2935BcD2dFCF4"),/start with 0x/);
  assert.match(validateEvmAddress("0x1Db92e2EeBC8E0c075a02BeA49a2935BcD2dFCG4"),/only hexadecimal/);
  assert.match(validateTransactionHash("0x1234"),/exactly 64 hexadecimal characters/);
});
