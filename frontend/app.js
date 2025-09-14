// Frontend for Bundle v3 — talks to FastAPI backend
const $ = (id) => document.getElementById(id);
const API = (path, opts={}) => {
  const token = localStorage.getItem('authToken') || '';
  opts.headers = Object.assign({'Content-Type':'application/json'}, opts.headers||{});
  if (token) opts.headers['Authorization'] = 'Bearer ' + token;
  return fetch(path, opts);
};

function toast(msg) {
  const div = document.createElement('div');
  div.textContent = msg;
  div.style.position='fixed'; div.style.bottom='20px'; div.style.left='50%'; div.style.transform='translateX(-50%)';
  div.style.background='#111832'; div.style.border='1px solid #33406b'; div.style.padding='10px 12px'; div.style.borderRadius='8px';
  document.body.appendChild(div);
  setTimeout(()=>div.remove(), 2000);
}

// Login
$('loginBtn').onclick = async () => {
  const username = $('username').value.trim();
  if (!username) { toast('Enter a username'); return; }
  const r = await API('/auth/login', {method:'POST', body: JSON.stringify({username})});
  if (!r.ok) { toast('Login failed'); return; }
  const j = await r.json();
  localStorage.setItem('authToken', j.token);
  await bootstrap();
};

$('logoutBtn').onclick = () => {
  localStorage.removeItem('authToken');
  location.reload();
};

async function bootstrap() {
  const token = localStorage.getItem('authToken');
  if (!token) {
    $('loginCard').style.display = '';
    $('appCard').style.display = 'none';
    $('holdingsCard').style.display = 'none';
    $('resultsCard').style.display = 'none';
    return;
  }
  $('loginCard').style.display = 'none';
  $('appCard').style.display = '';
  $('holdingsCard').style.display = '';
  $('resultsCard').style.display = '';

  // Load assumptions + holdings
  await loadAssumptions();
  await loadHoldings();
}

async function loadAssumptions() {
  const r = await API('/assumptions');
  if (!r.ok) { toast('Failed to load assumptions'); return; }
  const a = await r.json();
  $('target').value = a.target;
  $('defaultCAGR').value = a.default_cagr;
  $('monthlyContrib').value = a.monthly_contrib;
  $('cashAPY').value = a.cash_apy;
  $('priceProvider').value = a.price_provider || 'none';
  $('alphaKey').value = a.alpha_key || '';
}

$('saveAssumptions').onclick = async () => {
  const body = {
    target: +$('target').value || 1000000,
    default_cagr: +$('defaultCAGR').value || 7.0,
    basis: 12, // fixed monthly
    monthly_contrib: +$('monthlyContrib').value || 0,
    cash_apy: +$('cashAPY').value || 0,
    price_provider: $('priceProvider').value || 'none',
    alpha_key: $('alphaKey').value.trim()
  };
  const r = await API('/assumptions', {method:'PUT', body: JSON.stringify(body)});
  if (!r.ok) { toast('Save failed'); return; }
  toast('Assumptions saved.');
};

// Holdings
$('resetForm').onclick = () => resetForm();
function resetForm() {
  $('holdingForm').reset(); $('editId').value=''; $('saveBtn').textContent='Save holding';
}

$('holdingForm').onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    type: $('hType').value,
    name: $('hName').value.trim(),
    units: +$('hUnits').value || 0,
    price: +$('hPrice').value || 0,
    cagr: +$('hCAGR').value || +$('defaultCAGR').value || 7,
    monthly_contrib: +$('hContrib').value || 0
  };
  if (!body.name) { toast('Name required'); return; }
  const editId = $('editId').value;
  let r;
  if (editId) r = await API('/holdings/' + editId, {method:'PUT', body: JSON.stringify(body)});
  else r = await API('/holdings', {method:'POST', body: JSON.stringify(body)});
  if (!r.ok) { toast('Save failed'); return; }
  resetForm();
  await loadHoldings();
};

async function loadHoldings() {
  const r = await API('/holdings');
  if (!r.ok) { toast('Failed to load holdings'); return; }
  const rows = await r.json();
  const el = $('holdingsList');
  if (!rows.length) { el.innerHTML = '<p class="muted">No holdings yet.</p>'; return; }
  el.innerHTML = '';
  for (const h of rows) {
    const row = document.createElement('div'); row.className='row';
    const meta = document.createElement('div'); meta.className='meta';
    const title = document.createElement('h3'); title.textContent = `${h.name} — ${h.type}`;
    const sub = document.createElement('div'); sub.className='muted';
    sub.textContent = `Units/Value: ${h.units} • Price: $${h.price||0} • CAGR: ${h.cagr}% • Monthly: $${h.monthly_contrib||0}`;
    meta.appendChild(title); meta.appendChild(sub);
    const actions = document.createElement('div');
    const edit = document.createElement('button'); edit.textContent='Edit'; edit.onclick = () => editHolding(h);
    const del = document.createElement('button'); del.textContent='Delete'; del.onclick = () => deleteHolding(h.id);
    actions.appendChild(edit); actions.appendChild(del);
    row.appendChild(meta); row.appendChild(actions);
    el.appendChild(row);
  }
}

function editHolding(h) {
  $('editId').value = h.id;
  $('hType').value = h.type;
  $('hName').value = h.name;
  $('hUnits').value = h.units;
  $('hPrice').value = h.price;
  $('hCAGR').value = h.cagr;
  $('hContrib').value = h.monthly_contrib;
  $('saveBtn').textContent = 'Update holding';
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function deleteHolding(id) {
  if (!confirm('Delete this holding?')) return;
  const r = await API('/holdings/' + id, {method:'DELETE'});
  if (r.ok) { await loadHoldings(); } else { toast('Delete failed'); }
}

$('refreshPrices').onclick = async () => {
  const r = await API('/prices/refresh', {method:'POST'});
  if (!r.ok) { const t = await r.text(); toast('Price refresh failed: ' + t); return; }
  const j = await r.json();
  toast(`Prices updated=${j.updated}${j.failed?`, failed=${j.failed}`:''}`);
};

$('run').onclick = async () => {
  const r = await API('/projections/run', {method:'POST'});
  if (!r.ok) { toast('Projection failed'); return; }
  const out = await r.json();
  renderResults(out);
};

function renderResults(out) {
  const res = $('results');
  const runAt = new Date(out.run_at).toLocaleString();

  // Build the monthly table HTML (limit display to 65 years = 780 rows)
  const rows = out.table || [];
  // Build header: Date | Total ($)
  let html = `
    <p><strong>Run at:</strong> ${runAt}</p>
    <p><strong>Start total:</strong> $${out.start_total.toFixed(2)}</p>
    ${out.millionaire_date
      ? `<p><strong>Projected millionaire date:</strong> ${new Date(out.millionaire_date).toLocaleDateString()} (<em>${out.days_to_target} days</em>)</p>`
      : `<p><strong>Projected millionaire date:</strong> Not reached.</p>`
    }
    <hr>
    <h3>Monthly Projection (65 years)</h3>
    <div style="max-height: 420px; overflow:auto; border:1px solid #253058; border-radius:8px;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr>
            <th style="text-align:left; padding:8px; border-bottom:1px solid #253058;">Date (1st of month)</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid #253058;">Total ($)</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(([iso, total]) => {
            const d = new Date(iso + 'T00:00:00Z');
            return `<tr>
              <td style="padding:6px 8px;">${d.toLocaleDateString()}</td>
              <td style="padding:6px 8px; text-align:right;">$${Number(total).toFixed(2)}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;

  res.innerHTML = html;
}


// Start
bootstrap();
