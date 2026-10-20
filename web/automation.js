"use strict";
let automationRules = [];
const workflowLabels = { overdue_invoice: 'Invoice is overdue', low_stock: 'Stock reaches a threshold', expiring_contract: 'Contract approaches expiry' };
function wfButton(label, action, id = '', version = 0) { return `<button type="button" class="btn" data-wf="${action}" data-rule="${escape(id)}" data-version="${version}">${escape(label)}</button>`; }
async function renderAutomations() {
    const organization = state.me.organization.id;
    const rules = await api('/workflows');
    if (state.page !== 'Automations' || state.me.organization.id !== organization)
        return;
    automationRules = rules;
    document.querySelector('#app').innerHTML = heading('Automations', 'Connect operational signals to accountable follow-up.', wfButton('Create automation', 'new')) + `<div class="notice">Rules create tasks or in-app notifications for their administrator owner. Financial transactions and purchase approvals still require their existing reviewed workflows. Daily rules are checked while this server is running; missed days are not replayed.</div><div class="record-grid">${rules.map(rule => { const latest = rule.versions[0], active = rule.versions.find(v => v.version === rule.active_version), definition = active?.definition || latest.definition; return `<article class="card block"><div class="flex"><span class="metric-icon tone-teal">↪</span><div><h2>${escape(rule.name)}</h2><p class="hint">${rule.enabled ? 'Active · V' + rule.active_version : 'Paused / draft'} · ${definition.schedule === 'daily' ? 'Daily check (UTC)' : 'Manual execution'}</p></div></div><div class="workflow-flow"><div><small>WHEN</small><b>${workflowLabels[definition.source]}</b></div><span>↓</span><div><small>IF</small><b>${definition.source === 'low_stock' ? 'On hand ≤ ' + definition.threshold : definition.source === 'overdue_invoice' ? 'Overdue by more than ' + definition.days + ' days' : 'Expires within ' + definition.days + ' days'}</b></div><span>↓</span><div><small>THEN</small><b>${definition.action === 'task' ? 'Create follow-up task' : 'Notify owner'}</b></div></div><div class="actions">${wfButton('Manage versions & runs', 'detail', rule.id)}${wfButton('Edit as new version', 'edit', rule.id)}</div></article>`; }).join('') || '<section class="card empty-state"><h2>Make recurring follow-up consistent.</h2><p>Start with overdue invoice follow-ups, stock alerts or contract expiry reminders.</p>' + wfButton('Create your first automation', 'new') + '</section>'}</div>` + footer();
}
function editAutomation(rule) {
    const d = rule?.versions[0].definition || { source: 'overdue_invoice', days: 0, threshold: 5, action: 'task', schedule: 'manual' };
    modal(rule ? 'Save a new workflow version' : 'Create automation', `<form id="workflowEditor" data-rule="${rule?.id || ''}"><div class="form-grid"><div class="full"><label for="wf-name">Automation name</label><input id="wf-name" name="name" required maxlength="160" value="${escape(rule?.name || '')}" ${rule ? 'readonly' : ''}></div><div><label for="wf-source">When</label><select id="wf-source" name="source">${Object.entries(workflowLabels).map(([id, label]) => `<option value="${id}" ${id === d.source ? 'selected' : ''}>${label}</option>`).join('')}</select></div><div><label for="wf-action">Then</label><select id="wf-action" name="action"><option value="task" ${d.action === 'task' ? 'selected' : ''}>Create task for owner</option><option value="notification" ${d.action === 'notification' ? 'selected' : ''}>Notify owner</option></select></div><div><label for="wf-days">Days (invoice grace / contract horizon)</label><input id="wf-days" name="days" type="number" min="0" max="365" required value="${d.days}"></div><div><label for="wf-threshold">Stock reorder threshold</label><input id="wf-threshold" name="threshold" type="number" min="0" max="1000000" required value="${d.threshold}"></div><div><label for="wf-schedule">Execution</label><select id="wf-schedule" name="schedule"><option value="manual" ${d.schedule === 'manual' ? 'selected' : ''}>Manual</option><option value="daily" ${d.schedule === 'daily' ? 'selected' : ''}>Daily while server runs</option></select></div></div><p class="hint">Saving creates an immutable draft version. Simulate it, then activate explicitly. At most one action is created per matching source record per UTC day, across all versions of this rule.</p><div role="alert" id="workflowError" class="form-error"></div><button class="btn primary" type="submit">Save draft version</button></form>`);
}
async function detailAutomation(id) {
    const rule = await api('/workflows/' + id);
    modal(rule.name, `<p>${rule.enabled ? 'Active version ' + rule.active_version : 'Paused / draft'}</p>${rule.versions.map(v => `<section class="card block"><h3>Version ${v.version}</h3><p>${workflowLabels[v.definition.source]} → ${v.definition.action === 'task' ? 'Create task' : 'Notify owner'} · ${v.definition.schedule}</p><div class="actions">${wfButton('Simulate', 'simulate', id, v.version)}${wfButton(v.version < rule.active_version ? 'Roll back to V' + v.version : 'Activate V' + v.version, 'activate', id, v.version)}${rule.enabled && v.version === rule.active_version ? wfButton('Run now', 'run', id, v.version) : ''}</div></section>`).join('')}<div class="actions">${rule.enabled ? wfButton('Pause automation', 'pause', id) : ''}</div><h3>Recent executions</h3>${rule.runs.map(r => `<section class="card block"><b>${escape(r.status)} · V${r.version} · ${escape(r.trigger_kind)}</b><p>${dt(r.created_at)} · ${r.matched} matched · ${r.applied} created · ${r.skipped} already handled</p>${r.error ? `<p class="error">${escape(r.error)}</p>` : ''}</section>`).join('') || '<p class="hint">No executions yet. Simulations do not create execution logs or business actions.</p>'}`, undefined, undefined, true);
}
document.addEventListener('click', async (event) => {
    const target = event.target.closest('[data-wf]');
    if (!target)
        return;
    const action = target.dataset.wf, id = target.dataset.rule, version = Number(target.dataset.version);
    target.disabled = true;
    try {
        if (action === 'new') {
            editAutomation();
            return;
        }
        if (action === 'edit') {
            editAutomation(automationRules.find(r => r.id === id));
            return;
        }
        if (action === 'detail') {
            await detailAutomation(id);
            return;
        }
        const result = await api('/workflows/' + id + '/' + action, 'POST', { version });
        if (action === 'simulate') {
            modal('Simulation · version ' + version, `<p><b>${result.matches.length} records match.</b> No tasks or notifications were created.</p><ul>${result.matches.map((m) => `<li>${escape(m.kind)} · ${escape(m.label)}</li>`).join('') || '<li>No matching records.</li>'}</ul>`);
            return;
        }
        toast(action === 'run' ? `${result.applied} actions created; ${result.skipped} already handled.` : action === 'pause' ? 'Automation paused.' : 'Version ' + version + ' activated. Existing actions remain.');
        await renderAutomations();
        await detailAutomation(id);
    }
    catch (error) {
        toast(error.message);
    }
    finally {
        if (target.isConnected)
            target.disabled = false;
    }
});
document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (form.id !== 'workflowEditor')
        return;
    event.preventDefault();
    const values = new FormData(form), rule = form.dataset.rule;
    const submit = form.querySelector('[type=submit]');
    submit.disabled = true;
    try {
        const definition = { source: values.get('source'), action: values.get('action'), schedule: values.get('schedule'), days: Number(values.get('days')), threshold: Number(values.get('threshold')) };
        const result = await api(rule ? '/workflows/' + rule + '/versions' : '/workflows', 'POST', { name: values.get('name'), definition });
        closeModal();
        await renderAutomations();
        await detailAutomation(result.id);
        toast('Draft version saved. Simulate before activation.');
    }
    catch (error) {
        form.querySelector('#workflowError').textContent = error.message;
    }
    finally {
        if (submit.isConnected)
            submit.disabled = false;
    }
});
