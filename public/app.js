const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const escapeHTML = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = (v, currency="INR") => new Intl.NumberFormat("en", {style:"currency",currency}).format(v/100);
let currentBill = null, currentDraft = null, selectedFile = null, savedBills = [];

async function api(path, options={}) {
  const response = await fetch(path, {...options, headers: options.body instanceof FormData ? {} : {"Content-Type":"application/json"}});
  const isJSON = (response.headers.get("content-type") || "").includes("application/json");
  if (!isJSON) {
    throw new Error(`The server returned an unexpected response (HTTP ${response.status}). Check that Vercel is using the FastAPI framework and the repository root, then inspect its runtime logs.`);
  }
  const data = await response.json().catch(() => ({detail: "The server returned invalid JSON. Please retry."}));
  if (!response.ok) {
    let message = data.detail || "Something went wrong.";
    if (Array.isArray(message)) message = message.map(x => `${x.loc?.slice(1).join(" → ")}: ${x.msg}`).join("; ");
    throw new Error(message);
  }
  return data;
}
function error(e) { $("#alert").textContent = e.message || e; $("#alert").hidden = false; window.scrollTo({top:0,behavior:"smooth"}); }
function toast(text) { $("#toast").textContent=text; $("#toast").hidden=false; setTimeout(()=>$("#toast").hidden=true,4000); }
async function busy(button, label, fn) {
  const old = button.innerHTML; button.disabled=true; button.textContent=label; $("#alert").hidden=true;
  try { return await fn(); } catch(e) { error(e); } finally { button.disabled=false; button.innerHTML=old; }
}
function screen(name) {
  $("#review-view").hidden = name === "history"; $("#history-view").hidden = name !== "history";
  $("#nav-review").classList.toggle("active",name !== "history"); $("#nav-history").classList.toggle("active",name === "history");
}
function step(n) {
  screen("review");
  ["upload","confirm","result"].forEach((x,i)=>$(`#${x}-panel`).hidden=i+1!==n);
  $$(".steps li").forEach((li,i)=>li.classList.toggle("current", i+1===n));
  $("#alert").hidden=true;
}
function reset() { currentBill=null;currentDraft=null;step(1);window.scrollTo({top:0,behavior:"smooth"}); }
$("#nav-review").onclick=()=>screen("review");
$("#nav-history").onclick=()=>loadHistory(true).catch(error);
$$(".restart").forEach(b=>b.onclick=reset);
$("#file").onchange=e=>chooseFile(e.target.files[0]);
function chooseFile(file) {
  if(!file) return;
  if(file.size>10*1024*1024) {error("Choose a file smaller than 10 MB.");return;}
  selectedFile=file;$("#file-label").textContent=file.name;
}
$("#dropzone").ondragover=e=>{e.preventDefault();$("#dropzone").classList.add("dragover");};
$("#dropzone").ondragleave=()=>$("#dropzone").classList.remove("dragover");
$("#dropzone").ondrop=e=>{e.preventDefault();$("#dropzone").classList.remove("dragover");chooseFile(e.dataTransfer.files[0]);};
$("#extract").onclick=()=>busy($("#extract"),"Reading the lines…",async()=>{
  if(!selectedFile) throw new Error("Choose a bill first, or use manual entry.");
  if(!$("#consent").checked) throw new Error("Confirm consent before sending your bill to Groq.");
  const form=new FormData();form.append("file",selectedFile);form.append("consent","true");
  fillForm(await api("/api/extract",{method:"POST",body:form}));
});
$("#manual").onclick=()=>fillForm({lines:[{description:"",amount:"",kind:"base"}]});
$("#demo").onclick=()=>fillForm({
  provider:"Northstar Broadband",currency:"INR",bill_date:"2026-10-01",period_start:"2026-09-01",period_end:"2026-09-30",
  total:1378.82,expected:1178.82,promise_source:"Sample plan confirmation: ₹999 plus 18% tax",promise_date:"2026-09-01",
  lines:[{description:"Monthly broadband plan",amount:999,kind:"base"},{description:"GST",amount:179.82,kind:"tax",tax_rate:18,tax_base:999},{description:"Entertainment add-on",amount:200,kind:"extra"}],
  warnings:["This is a fictional sample to explore the workflow. It is not a real user test."]
});
function fillForm(data) {
  const form=$("#bill-form");form.reset();
  for(const [key,value] of Object.entries(data)) if(form.elements.namedItem(key) && value!=null) form.elements.namedItem(key).value=String(value);
  if(!data.bill_date) form.elements.bill_date.value="";
  $("#line-rows").innerHTML="";
  (data.lines?.length?data.lines:[{}]).forEach(addLine);
  $("#confirmed").checked=false;
  $("#extraction-warnings").hidden=!data.warnings?.length;
  $("#extraction-warnings").textContent=(data.warnings||[]).join(" ");
  step(2);
}
function addLine(line={}) {
  const tr=document.createElement("tr");
  tr.innerHTML=`<td><input class="description" aria-label="Line description" required maxlength="200" placeholder="Charge description" value="${escapeHTML(line.description)}"><div class="tax-fields" ${line.kind==="tax"?"":"hidden"}><label>Tax rate %<input class="tax-rate" type="number" min="0" max="100" step=".001" value="${escapeHTML(line.tax_rate)}"></label><label>Taxable base<input class="tax-base" type="number" min="0" max="10000000" step=".01" value="${escapeHTML(line.tax_base)}"></label></div></td>
  <td><select class="kind" aria-label="Line type">${["base","tax","extra","credit","late_fee"].map(k=>`<option value="${k}" ${k===(line.kind||"base")?"selected":""}>${({base:"Plan / usage",tax:"Tax",extra:"Extra charge",credit:"Credit",late_fee:"Late fee"})[k]}</option>`).join("")}</select></td>
  <td><input class="amount" aria-label="Line amount" required type="number" min="-10000000" max="10000000" step=".01" value="${escapeHTML(line.amount)}"></td>
  <td><input class="accepted" type="checkbox" aria-label="Confirmed adjustment outside promised price" ${line.accepted?"checked":""}></td>
  <td><button type="button" class="remove-line" aria-label="Remove line">×</button></td>`;
  tr.querySelector(".kind").onchange=e=>tr.querySelector(".tax-fields").hidden=e.target.value!=="tax";
  tr.querySelector(".remove-line").onclick=()=>tr.remove();
  $("#line-rows").append(tr);
}
$("#add-line").onclick=()=>addLine();
$("#bill-form").onsubmit=e=>{
  e.preventDefault();
  busy($("#analyze"),"Checking the maths…",async()=>{
    const body=Object.fromEntries(new FormData(e.target));
    body.promise_includes_tax=body.promise_includes_tax==="true";body.confirmed=$("#confirmed").checked;
    ["period_start","period_end","due_date","paid_date","promise_date"].forEach(k=>body[k]=body[k]||null);
    body.lines=$$("#line-rows tr").map(tr=>({
      description:tr.querySelector(".description").value,amount:tr.querySelector(".amount").value,
      kind:tr.querySelector(".kind").value,accepted:tr.querySelector(".accepted").checked,
      tax_rate:tr.querySelector(".tax-rate").value||null,tax_base:tr.querySelector(".tax-base").value||null
    }));
    const result=await api("/api/bills",{method:"POST",body:JSON.stringify(body)});
    await openBill(result.id);
    await loadHistory();
    if(result.snapshot_warning)toast(result.snapshot_warning);
  });
};
async function openBill(id) {
  currentBill=await api(`/api/bills/${id}`);currentDraft=currentBill.drafts.at(-1)||null;renderResult();step(3);
}
const verdictText={unexplained:"A few things need explaining.",explained:"The difference is accounted for.",checks_out:"The confirmed totals check out."};
const verdictShort={unexplained:"Needs clarification",explained:"Difference explained",checks_out:"Totals check out"};
function renderResult() {
  const b=currentBill,r=b.finding,m=v=>money(v,b.currency);
  $("#result-panel").innerHTML=`
    <div class="result-banner ${r.verdict==="unexplained"?"attention":""}"><span class="verdict-icon">${r.verdict==="unexplained"?"?":"✓"}</span><div><h2>${verdictText[r.verdict]}</h2><p>${escapeHTML(b.provider)} · ${escapeHTML(b.bill_date)} · ${r.verdict==="unexplained"?"An unexplained charge is a question, not a verdict.":"Based on your reviewed lines and promised price."}</p></div></div>
    <div class="stats"><div class="stat"><span>EXPECTED TOTAL</span><strong>${m(r.expected_cents)}</strong><small>Including confirmed promise tax</small></div><div class="stat"><span>BILLED TOTAL</span><strong>${m(r.total_cents)}</strong><small>As printed on the bill</small></div><div class="stat"><span>DIFFERENCE</span><strong>${m(r.gap_cents)}</strong><small>Billed minus expected</small></div></div>
    <div class="result-grid"><div class="card"><div class="section-label">FOLLOW THE NUMBERS</div><h2>Here’s the maths.</h2>
    <div class="math-row"><span>Sum of confirmed lines</span><b>${m(r.line_sum_cents)}</b></div>
    <div class="math-row"><span>Printed total − line sum</span><b>${m(r.total_mismatch_cents)}</b></div>
    <div class="math-row"><span>Billed − expected</span><b>${m(r.gap_cents)}</b></div>
    <div class="math-row"><span>Confirmed adjustments</span><b>${m(r.accepted_extras_cents)}</b></div>
    <div class="math-row total"><span>Remaining difference</span><b>${m(r.unexplained_cents)}</b></div>
    <p class="muted">${escapeHTML(r.scope)}</p>
    ${r.missing_info.length?`<div class="notice">${r.missing_info.map(escapeHTML).join("<br>")}</div>`:""}
    <h3>Which lines should the message ask about?</h3><p class="muted">Select the lines you want the provider to explain.</p>
    ${r.lines.map(l=>`<div class="line-result ${r.flagged_positions.includes(l.position)?"flagged":""}"><label><input type="checkbox" class="dispute-line" value="${l.position}" ${r.flagged_positions.includes(l.position)?"checked":""}><span>${escapeHTML(l.description)}</span><b>${m(l.amount_cents)}</b></label>${l.notes.map(n=>`<p>${escapeHTML(n)}</p>`).join("")}</div>`).join("")}
    <button class="text-button" id="revise">+ Add evidence or correct inputs</button><p class="muted">Creates a new review so the earlier result remains in history.</p></div>
    <div class="card"><div class="section-label">MAKE THE NEXT MOVE</div><h2>A message worth sending.</h2><p class="muted">Choose the lines and a tone. Every amount comes from the checks on the left.</p>
    <div class="draft-tools"><select id="tone" aria-label="Message tone"><option value="polite">Polite & clear</option><option value="firm">Firm & factual</option><option value="concise">Short & direct</option></select><button class="primary" id="draft-button">Draft message</button></div>
    <label class="check"><input type="checkbox" id="ai-style"><span>Use AI for the greeting and closing. Verified amounts stay fixed.</span></label>
    <div id="draft-area" ${currentDraft?"":"hidden"}><textarea id="draft-text" class="draft-text" aria-label="Edit your message" maxlength="8000"></textarea><div class="word-count" id="word-count"></div><p class="muted">After editing, check any amounts you changed yourself.</p>
    <div class="draft-actions"><button class="secondary" id="copy">Copy message</button><button class="secondary" id="email">Open email ↗</button><button class="text-button" id="save-edit">Save edits</button></div>
    <div class="notice">Copying or opening email does not mean it was sent. After sending it yourself, record what happened.</div>
    <label class="check"><input type="checkbox" id="sent-confirm"><span>I actually sent this message to the provider.</span></label><button class="primary full" id="mark-sent">Record as sent <span>✓</span></button>
    </div><div class="event-list" id="events"></div></div></div>
    <div class="result-links"><a href="/api/bills/${b.id}/snapshot" target="_blank" rel="noopener">View sanitized snapshot ↗</a><button class="text-button" id="export">Download review</button><button class="text-button restart">Review another bill →</button></div>`;
  $("#revise").onclick=()=>fillForm(b.input);
  $("#result-panel .restart").onclick=reset;
  $("#draft-button").onclick=()=>busy($("#draft-button"),"Drafting…",async()=>{
    const positions=$$(".dispute-line:checked").map(x=>Number(x.value));
    if(!positions.length)throw new Error("Select at least one line to link to the message.");
    currentDraft=await api(`/api/bills/${b.id}/draft`,{method:"POST",body:JSON.stringify({positions,tone:$("#tone").value,use_ai:$("#ai-style").checked})});
    $("#draft-area").hidden=false;$("#draft-text").value=currentDraft.draft_text;updateCount();
  });
  $("#draft-text").oninput=updateCount;
  $("#copy").onclick=()=>busy($("#copy"),"Copying…",async()=>{
    await navigator.clipboard.writeText($("#draft-text").value);await logEvent("copied");toast("Copied. Send it to your provider when you’re ready.");
  });
  $("#email").onclick=()=>busy($("#email"),"Opening…",async()=>{
    const link=document.createElement("a");
    link.href=`mailto:?subject=${encodeURIComponent("Bill clarification — "+b.provider)}&body=${encodeURIComponent($("#draft-text").value)}`;
    link.click();await logEvent("email_opened");toast("Email compose requested. Add the provider’s address and send it yourself.");
  });
  $("#save-edit").onclick=()=>busy($("#save-edit"),"Saving…",async()=>{await logEvent("edited");toast("Edits saved.");});
  $("#mark-sent").onclick=()=>busy($("#mark-sent"),"Recording…",async()=>{
    if(!$("#sent-confirm").checked)throw new Error("Only confirm after you have actually sent the message.");
    const result=await logEvent("sent");toast(result.success_bar_met?"Sent, with fewer than 20 words changed. Success bar met!":"Sent status recorded. Thank you for closing the loop.");await loadHistory();
  });
  $("#export").onclick=()=>{
    const blob=new Blob([JSON.stringify(currentBill,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=url;a.download="billshield-review.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  if(currentDraft) {
    const last=b.events.filter(e=>e.message_id===currentDraft.id).at(-1);
    $("#draft-text").value=last?.final_text||currentDraft.draft_text;updateCount();
  }
  renderEvents();
}
function distance(a,b) {
  a=a.trim().split(/\s+/).filter(Boolean);b=b.trim().split(/\s+/).filter(Boolean);
  let row=Array.from({length:b.length+1},(_,i)=>i);
  for(let i=1;i<=a.length;i++){let next=[i];for(let j=1;j<=b.length;j++)next[j]=Math.min(next[j-1]+1,row[j]+1,row[j-1]+Number(a[i-1]!==b[j-1]));row=next;}return row[b.length];
}
function updateCount(){if(currentDraft)$("#word-count").textContent=`${distance(currentDraft.draft_text,$("#draft-text").value)} words changed · success bar: sent with fewer than 20 words changed`;}
async function logEvent(action) {
  if(!currentDraft)throw new Error("Create a draft first.");
  const event=await api(`/api/messages/${currentDraft.id}/events`,{method:"POST",body:JSON.stringify({action,final_text:$("#draft-text").value})});
  currentBill.events.push(event);renderEvents();return event;
}
function renderEvents(){
  $("#events").innerHTML=currentBill.events.length?`<strong>What happened</strong>`+currentBill.events.map(e=>`<p>${escapeHTML(new Date(e.event_time).toLocaleString())} · ${escapeHTML(({copied:"Copied",email_opened:"Email opened",sent:"Sent (self-reported)",edited:"Edits saved"})[e.action])} · ${e.words_changed} words changed</p>`).join(""):"Your actions will appear here. Nothing is sent automatically.";
}
async function loadHistory(show=false) {
  savedBills=await api("/api/bills");$("#history-count").textContent=savedBills.length;
  if(!show)return;
  screen("history");
  $("#history-stats").innerHTML=`<div class="stat"><span>BILLS REVIEWED</span><strong>${savedBills.length}</strong></div><div class="stat"><span>NEED CLARIFICATION</span><strong>${savedBills.filter(x=>x.finding.verdict==="unexplained").length}</strong></div><div class="stat"><span>MESSAGES SENT · SELF-REPORTED</span><strong>${savedBills.filter(x=>x.sent).length}</strong></div>`;
  $("#history-list").innerHTML=savedBills.length?savedBills.map(b=>`<article class="history-item"><div><h3>${escapeHTML(b.provider)}<span class="badge">${verdictShort[b.finding.verdict]}</span></h3><p>${escapeHTML(b.bill_date)} · ${money(b.finding.total_cents,b.currency)} billed${b.sent?" · Message sent":""}</p></div><div class="button-row"><button class="text-button open-bill" data-id="${b.id}">Open review ↗</button><button class="text-button danger delete-bill" data-id="${b.id}">Delete</button></div></article>`).join(""):`<div class="empty"><h2>Your first review starts here.</h2><p class="muted">Upload a bill or try the sample to see how it works.</p><button id="empty-start" class="primary">Review a bill →</button></div>`;
  $$(".open-bill").forEach(btn=>btn.onclick=()=>busy(btn,"Opening…",()=>openBill(btn.dataset.id)));
  $$(".delete-bill").forEach(btn=>btn.onclick=()=>{
    if(window.confirm("Delete this bill, drafts, snapshot, and event history? This cannot be undone."))busy(btn,"Deleting…",async()=>{await api(`/api/bills/${btn.dataset.id}`,{method:"DELETE"});if(currentBill?.id===btn.dataset.id){currentBill=null;currentDraft=null;step(1);}await loadHistory(true);});
  });
  if($("#empty-start"))$("#empty-start").onclick=reset;
}
async function init(){
  const health=await api("/api/health");$("#storage-label").textContent=health.storage==="local"?"Local storage · this browser session":"Supabase · private session";
  await loadHistory();
}
init().catch(error);
