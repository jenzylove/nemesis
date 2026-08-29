import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

test("case enhancer cannot observe and rewrite its own character-data mutations",async()=>{
  const source=await readFile(new URL("../app/case-experience.tsx",import.meta.url),"utf8");
  assert.doesNotMatch(source,/characterData\s*:\s*true/);
  assert.match(source,/node\.textContent!==value/);
  assert.match(source,/requestAnimationFrame/);
});

test("investigation submission and polling are bounded and duplicate-safe",async()=>{
  const page=await readFile(new URL("../app/page.tsx",import.meta.url),"utf8");
  const auth=await readFile(new URL("../app/auth-gate.tsx",import.meta.url),"utf8");
  assert.match(page,/if\(submitting\.current\)return/);
  // Every request is bounded. The create call carries the larger bound because
  // discovery and candidate verification take real time; it no longer waits for
  // the deep trace, which continues on the event path. Asserting a ceiling
  // rather than one literal keeps this honest without pinning a magic number.
  const bounds=[...page.matchAll(/controller\.abort\(\),(\d+)\)/g)].map(m=>Number(m[1]));
  assert.ok(bounds.length>=2,`expected bounded requests, found ${bounds.length}`);
  assert.ok(bounds.every(ms=>ms>0&&ms<=180000),`unbounded or excessive timeout: ${bounds}`);
  assert.match(page,/if\(!api\|\|busy\)return/);
  assert.match(page,/controller\.abort\(\),10000/);
  assert.match(auth,/if\(refreshInFlight\.current\)return/);
});
test("account dock renders one intentional My investigations control",async()=>{
 const source=await readFile(new URL("../app/auth-gate.tsx",import.meta.url),"utf8");
 const dock=source.match(/<div className="authDock"[\s\S]*?<\/div>/)?.[0]||"";
 assert.equal((dock.match(/My investigations/g)||[]).length,0);
 assert.match(dock,/\{label\}/);
 assert.doesNotMatch(dock,/className="authMini"/);
});
test("a failed investigation reports its failure instead of hanging",async()=>{
  const page=await readFile(new URL("../app/page.tsx",import.meta.url),"utf8");
  const submit=page.slice(page.indexOf("async function submit("));
  const body=submit.slice(0,submit.indexOf("\n }"));

  // The progress poll's stop flag has to outlive the try. Declared inside it,
  // the catch that clears it throws ReferenceError before setError runs, so a
  // real API error is swallowed and the page appears to hang forever while the
  // poll keeps firing. This exact bug shipped once.
  const declaration=body.indexOf("let polling=false");
  assert.notEqual(declaration,-1,"the poll stop flag must be declared");
  assert.ok(declaration<body.indexOf("try{"),
    "the poll stop flag must be declared before the try, or catch cannot reach it");

  // finally runs on success, failure and abort, so stopping there covers paths
  // a catch block alone would miss.
  assert.match(body,/finally\{polling=false/,
    "the poll must be stopped in finally, not only on the success path");

  // Defence in depth: even if the flag were never cleared, the loop ends.
  assert.match(body,/ticks<\d+/,"the progress poll must be bounded");

  // A non-string detail must not become "[object Object]" in front of a victim.
  assert.match(body,/typeof payload\?\.detail==="string"/,
    "the error message must tolerate an unexpected response shape");
});
