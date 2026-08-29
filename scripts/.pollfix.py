"""The progress poll must not be able to swallow the result of an investigation."""
import io

p = 'app/page.tsx'
s = io.open(p, encoding='utf-8').read()

# 1. The stop flag was declared inside the try, so the catch referencing it threw
#    ReferenceError before setError ran: the API answered, and the user saw
#    nothing. It now lives beside the abort controller and is cleared in finally,
#    which runs on success, failure and abort alike.
old = '''  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),180000);
  try{'''
new = '''  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),180000);
  // Declared out here on purpose. Held inside the try it is invisible to catch
  // and finally, and clearing it there throws before the error can be shown.
  let polling=false;
  try{'''
assert old in s, 'submit preamble not found'
s = s.replace(old, new, 1)

s = s.replace('''   let polling=true;
   const poll=async()=>{
    while(polling){''', '''   polling=true;
   const poll=async()=>{
    // Bounded as well as flagged. A stop that never arrives can then only cost
    // a few minutes of polling rather than the lifetime of the page.
    for(let ticks=0;polling&&ticks<160;ticks++){''', 1)

s = s.replace('''     await new Promise(done=>setTimeout(done,2500));
    }
   };''', '''     await new Promise(done=>setTimeout(done,2500));
    }
   };''', 1)

# success no longer needs to stop it; finally does that on every path
s = s.replace('''   onReal(payload as RealResponse);
   polling=false;
  }catch(reason){polling=false;setError(''', '''   onReal(payload as RealResponse);
  }catch(reason){setError(''', 1)

s = s.replace('''}finally{clearTimeout(timeout);submitting.current=false;setLoading(false);setStage(null)}''',
              '''}finally{polling=false;clearTimeout(timeout);submitting.current=false;setLoading(false);setStage(null)}''', 1)

# 2. A failure the user cannot see is the same as a hang. Make sure the message
#    is always something, even if the API sends an unexpected shape.
old_throw = 'if(!response.ok)throw new Error(payload.detail||"Investigation failed");'
new_throw = 'if(!response.ok)throw new Error(typeof payload?.detail==="string"?payload.detail:"The investigation could not be completed. Please try again.");'
assert old_throw in s, 'error throw not found'
s = s.replace(old_throw, new_throw, 1)

io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('page.tsx: poll flag scoped correctly, stopped in finally, bounded')
