const $=id=>document.getElementById(id),esc=s=>String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
let mode="brief";
function setMode(m){mode=m;$("tb").className=m=="brief"?"on":"";$("tf").className=m=="fix"?"on":"";$("fb").hidden=m=="fix";$("go").textContent=m=="brief"?"Build brief":"Fix failing tests";$("cap").value=m=="brief"?12000:6000}
$("tb").onclick=()=>setMode("brief");$("tf").onclick=()=>setMode("fix");
fetch("/api/status").then(r=>r.json()).then(s=>$("st").textContent=(s.bifrost||s.tavily)?"live: "+[s.bifrost&&"Bifrost",s.tavily&&"Tavily"].filter(Boolean).join(" + "):"offline replay").catch(()=>$("st").textContent="backend not reachable");
const bars=r=>{const w=Math.min(100,r.receipt.tokens/r.baseline_tokens*100);return `<h3>Token receipt</h3><table>${r.receipt.calls.map(c=>`<tr><td>${esc(c.label)} (${c.tier})</td><td>${c.in+c.out} tok</td></tr>`).join("")}<tr><td><b>Ledger total</b></td><td><b>${r.receipt.tokens} tok · $${r.receipt.usd}</b></td></tr></table>
<div class="bar"><i style="width:${w}%"></i></div><div class="bar b"><i style="width:100%"></i></div><p class="tag" style="line-height:20px">Black: Ledger. Red: ungated baseline estimate (${r.baseline_tokens} tok, all text to the strong model). Prices are placeholders.</p>`};
function brief(r){const a=r.audit;return `<h2>${esc(r.company)}</h2><p class="tag">Brief for ${esc(r.meeting)} · window ${r.window[0]} to ${r.window[1]}</p>
<h3>Last 30 days</h3><ul>${r.bullets.map(b=>`<li>${esc(b.text)}${b.cites.map(c=>`<sup>${c}</sup>`).join("")}</li>`).join("")||"<li class=empty>No claim passed the gate, so no synthesis call was made.</li>"}</ul>
<h3>Open questions</h3><ul>${r.open_questions.map(q=>`<li class="q">${esc(q)}</li>`).join("")}</ul>
<h3>Sources</h3><table>${r.sources.map(s=>`<tr><td><sup>${s.n}</sup> <a href="${esc(s.url)}">${esc(s.title)}</a></td><td>${s.date}</td></tr>`).join("")}</table>
<h3>Verification audit</h3><p><span class="stamp pass">${a.accepted} passed</span><span class="stamp fail">${a.rejected.length} rejected</span><span class="stamp fail">${a.pre_dropped.length} sources dropped</span></p>
<table>${a.rejected.map(x=>`<tr><td>${esc(x.claim)}</td><td class="fail">${esc(x.reason)}</td></tr>`).join("")}${a.pre_dropped.map(x=>`<tr><td>${esc(x.title)}</td><td class="fail">${esc(x.reason)}</td></tr>`).join("")}</table>
${bars(r)}<p>Cost per verified claim: <b>$${r.cost_per_verified}</b></p>`}
function fix(r){return `<h2>Fix mode</h2><p><span class="stamp ${r.status=="green"?"pass":"fail"}">${r.status}</span></p>
<table>${r.steps.map(s=>`<tr><td><span class="${s.ok?"pass":"fail"}">${s.ok?"✓":"✗"}</span> ${esc(s.step)}</td><td style="text-align:left">${esc(s.detail)}</td></tr>`).join("")}</table>
${(r.diff||[]).map(d=>`<h3>Edit</h3><pre class="fail">- ${esc(d.old.trim())}</pre><pre class="pass">+ ${esc(d.new.trim())}</pre>`).join("")}${r.baseline_tokens?bars(r):""}`}
$("go").onclick=async()=>{$("out").innerHTML='<p class="empty">Running…</p>';$("go").disabled=true;
 try{const response=await fetch("/api/"+mode,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({company:$("co").value,meeting:$("mt").value,cap:+$("cap").value})});
 const r=await response.json();if(!response.ok){const detail=Array.isArray(r.detail)?r.detail.map(x=>x.msg).join("; "):r.detail||"Request failed";throw new Error(detail)}
 $("out").innerHTML=mode=="brief"?brief(r):fix(r)}catch(e){$("out").innerHTML=`<p class="fail">Request failed: ${esc(e.message)}</p>`}finally{$("go").disabled=false}};
