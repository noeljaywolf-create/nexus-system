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
var NexusProduct;
(function (NexusProduct) {
    let quotes = [], orders = [], tickets = [], customers = [], projects = [], people = [], apps = [], records = [];
    let homePreferences = { intro: true, shortcuts: true, revenue: true, projects: true, agenda: true, meetings: true };
    let appArchived = false, formFields = [];
    let salesView = 'pipeline', ticketView = 'board', selectedApp = null, editingApp = null, builderFields = [], brainQuery = '', brainData = null, dragField = -1;
    const e = (value) => escape(value);
    const button = (label, action, id = '', primary = false, extra = '') => `<button type="button" class="btn ${primary ? 'primary' : ''}" data-product="${action}" data-key="${e(id)}" ${extra}>${e(label)}</button>`;
    const route = (label, page, icon = 'arrow') => `<button class="btn" data-action="navigate" data-id="${e(page)}">${nexusIcon(icon)} ${e(label)}</button>`;
    const status = (value) => `<span class="status status-${e(value)}">${e(value.replaceAll('_', ' '))}</span>`;
    const blank = (title, description, action = '') => `<section class="card product-empty"><span class="empty-illustration">${nexusIcon('layers')}</span><h2>${e(title)}</h2><p>${e(description)}</p>${action}</section>`;
    const panel = () => document.querySelector('#app');
    const current = (page, org) => state.page === page && state.me.organization.id === org;
    const orgId = () => state.me.organization.id;
    const customerName = (id) => customers.find(c => c.id === id)?.name || 'Workspace';
    const projectSelect = () => select('project_id', 'Project / access context', [['', 'Workspace-wide'], ...projects.map(p => [p.id, p.name + (p.private ? ' · Private' : '')])]);
    const formEnd = (label) => `<div class="form-error" role="alert"></div><div class="actions form-footer"><button type="submit" class="btn primary">${e(label)}</button></div>`;
    const moneySummary = (label, value, description, icon, tone) => `<div class="card commerce-metric"><span class="metric-icon tone-${tone}">${nexusIcon(icon)}</span><div><small>${e(label)}</small><strong>${e(value)}</strong><p>${e(description)}</p></div></div>`;
    async function refs() { [customers, projects, people] = await Promise.all([api('/customers'), api('/projects'), api('/people')]); }
    function renderNavigation() {
        const groups = [['YOUR WORKSPACE', [['Overview', 'Home', 'overview', 'indigo'], ['Tasks', 'Workspace', 'check', 'teal'], ['Nexus Connect', 'Chat', 'chat', 'violet'], ['Documents', 'Documents', 'folder', 'amber']]], ['RUN YOUR BUSINESS', [['Customers', 'Customers', 'users', 'rose'], ['Sales', 'Sales', 'chart', 'teal'], ['Operations', 'Operations', 'box', 'amber'], ['Finance', 'Finance', 'wallet', 'blue'], ['Projects', 'Projects', 'briefcase', 'blue'], ['People', 'People', 'users', 'violet'], ['Support', 'Service desk', 'shield', 'rose']]], ['BUILD & UNDERSTAND', [['Intelligence', 'Analytics', 'chart', 'blue'], ['Business Brain', 'Business Brain', 'spark', 'violet'], ['Apps', 'Apps & workflows', 'layers', 'teal']]]];
        const activeMap = { Meetings: 'Tasks', Procurement: 'Operations', Assets: 'Operations', Contracts: 'Operations', 'Approval policies': 'Apps', Automations: 'Apps', 'Industry apps': 'Apps' };
        document.querySelector('#nav').innerHTML = groups.map(([label, items]) => `<div class="navlabel">${label}</div>${items.filter(item => item[0] !== 'Finance' || isRole('admin', 'finance')).map(([page, name, icon, tone]) => `<button aria-label="${name}" title="${name}" data-action="navigate" data-id="${page}" class="${(activeMap[state.page] || state.page) === page ? 'active' : ''}" ${state.page === page ? 'aria-current="page"' : ''}><span class="nav-icon-shell tone-${tone}">${nexusIcon(icon)}</span><span class="navtext">${name}</span></button>`).join('')}`).join('');
    }
    NexusProduct.renderNavigation = renderNavigation;
    async function home() {
        const org = orgId();
        await Promise.all([renderExecutiveOverview(), api('/preferences').then((p) => homePreferences = p)]);
        if (!current('Overview', org))
            return;
        const title = panel().querySelector('.titlebar');
        title?.insertAdjacentHTML('afterend', `<section class="business-hero"><div class="hero-copy"><span class="hero-kicker"><span></span> YOUR BUSINESS. IN SYNC.</span><h2>Less chasing.<br><em>More moving.</em></h2><p>Bring the conversation, the decision and the next step together. Make today a good day for business.</p><div class="actions">${route('Open your workspace', 'Tasks', 'check')}${button('Take a quick tour', 'tour', '0')}</div></div><div class="hero-orbit" aria-hidden="true"><div class="orbit-ring"></div><div class="orbit-core">N<span>NEXUS</span></div><span class="orbit-node orbit-chat">${nexusIcon('chat')} Conversations</span><span class="orbit-node orbit-work">${nexusIcon('briefcase')} Work</span><span class="orbit-node orbit-knowledge">${nexusIcon('folder')} Knowledge</span><span class="orbit-node orbit-decisions">${nexusIcon('spark')} Decisions</span><span class="orbit-caption">One connected business.</span></div></section><section class="home-pathways">${[['Sales', 'From opportunity to order', 'Keep the customer and the commercial next step connected.', 'chart', 'teal'], ['Support', 'A better customer experience', 'Give every request an owner and a clear resolution.', 'shield', 'rose'], ['Apps', 'Your way of working', 'Create forms and records that fit your business.', 'layers', 'violet']].map(([page, title, copy, icon, tone]) => `<button class="pathway" data-action="navigate" data-id="${page}"><span class="metric-icon tone-${tone}">${nexusIcon(icon)}</span><span><b>${title}</b><small>${copy}</small></span>${nexusIcon('arrow')}</button>`).join('')}</section>`);
        panel().querySelector('.titlebar>.actions')?.insertAdjacentHTML('afterbegin', button('Customize home', 'customize-home'));
        applyHomePreferences();
    }
    NexusProduct.home = home;
    function applyHomePreferences() { const selectors = { intro: '.business-hero', shortcuts: '.home-pathways', revenue: '.revenue-card', projects: '.dashboard-projects', agenda: '.agenda-card', meetings: '.upcoming-card' }; for (const [key, selector] of Object.entries(selectors)) {
        const el = panel().querySelector(selector);
        if (el)
            el.hidden = !homePreferences[key];
    } panel().querySelectorAll('.dashboard-columns').forEach(row => { const visible = Array.from(row.children).filter(el => !el.hidden); row.classList.toggle('single-panel', visible.length === 1); row.hidden = visible.length === 0; }); }
    function customizeHome() { const labels = { intro: 'Welcome and platform overview', shortcuts: 'Connected workflow shortcuts', revenue: 'Revenue chart', projects: 'Project portfolio', agenda: 'My next steps', meetings: 'Upcoming meetings' }; modal('Make Home your own', `<form id="productHomePreferences"><p class="form-note">Choose what helps you focus. These preferences are saved for your account in this workspace. Access permissions still apply to every card.</p><div class="preference-options">${Object.entries(labels).map(([key, label]) => `<label><input type="checkbox" name="${key}" ${homePreferences[key] ? 'checked' : ''}><span>${label}</span></label>`).join('')}</div>${formEnd('Save home layout')}</form>`); }
    function pageLabel(page) { return { Overview: 'Home', Tasks: 'Workspace', 'Nexus Connect': 'Chat', Support: 'Service desk', Intelligence: 'Analytics', Apps: 'Apps & workflows' }[page] || page; }
    NexusProduct.pageLabel = pageLabel;
    async function sales() {
        const org = orgId();
        [quotes, orders] = await Promise.all([api('/quotes'), api('/sales-orders')]);
        if (!current('Sales', org))
            return;
        const open = quotes.filter(q => ['draft', 'sent', 'accepted'].includes(q.status)), won = orders.filter(o => o.status !== 'cancelled');
        panel().innerHTML = heading('Sales', 'Good relationships. Clear proposals. Business that moves forward.', button('Export quotations', 'export', 'quotes') + (canWrite() ? button('Create quotation', 'new-quote', '', true) : '')) + `<div class="commerce-metrics">${moneySummary('Open quotation value', currency(open.reduce((a, q) => a + q.total, 0)), open.length + ' opportunities in progress', 'chart', 'violet')}${moneySummary('Confirmed order value', currency(won.reduce((a, o) => a + o.total, 0)), won.length + ' orders, excluding cancellations', 'briefcase', 'teal')}${moneySummary('Ready for a decision', String(quotes.filter(q => q.status === 'sent').length), 'Quotations marked sent for review', 'clock', 'amber')}</div><div class="section-toolbar"><div class="segmented">${button('Pipeline', 'sales-view', 'pipeline', salesView === 'pipeline')}${button('Sales orders', 'sales-view', 'orders', salesView === 'orders')}</div><p class="section-help">${salesView === 'pipeline' ? 'A clear next step for every opportunity.' : 'Track fulfilment and prepare invoices from confirmed orders.'}</p></div><div id="salesContent"></div>` + footer();
        renderSalesContent();
    }
    NexusProduct.sales = sales;
    function renderSalesContent() {
        const host = document.querySelector('#salesContent');
        if (!host)
            return;
        if (salesView === 'orders') {
            host.innerHTML = orders.length ? `<section class="card simple-table-wrap"><table class="table"><thead><tr><th>ORDER</th><th>CUSTOMER</th><th>VALUE</th><th>STATUS</th><th>NEXT STEP</th></tr></thead><tbody>${orders.map(o => `<tr><td><button class="record-title" data-product="order" data-key="${o.id}">${e(o.number)}</button><small class="subtext">${e(o.title)}</small></td><td>${e(o.customer_name)}</td><td class="amount-cell">${currency(o.total)}</td><td>${status(o.status)}</td><td>${button('Open order', 'order', o.id)}</td></tr>`).join('')}</tbody></table></section>` : blank('Your first order starts with a quotation.', 'Record the customer’s acceptance, then create a connected order.');
            return;
        }
        host.innerHTML = `<div class="sales-board" tabindex="0" role="region" aria-label="Sales pipeline">${[['draft', 'Draft', 'Shape the proposal'], ['sent', 'In review', 'Waiting for the customer'], ['accepted', 'Accepted', 'Ready for an order'], ['converted', 'Ordered', 'Keep delivery moving']].map(([stage, label, description]) => { const items = quotes.filter(q => q.status === stage); return `<section class="sales-column"><div class="board-column-heading"><div><h2><i class="stage-dot stage-${stage}"></i>${label}<span>${items.length}</span></h2><small>${description}</small></div></div><p class="column-total">${currency(items.reduce((a, q) => a + q.total, 0))}</p>${items.map(q => `<button class="opportunity-card" data-product="quote" data-key="${q.id}"><span class="opportunity-top"><span>${e(q.number)}</span>${nexusIcon('more')}</span><h3>${e(q.title)}</h3><p>${e(q.customer_name)}</p><strong>${currency(q.total)}</strong><div class="opportunity-footer"><span class="customer-monogram tone-${q.customer_name.length % 2 ? 'blue' : 'teal'}">${initials(q.customer_name)}</span><span>${q.valid_until ? 'Valid until ' + e(q.valid_until) : 'No expiry date'}</span>${nexusIcon('arrow')}</div></button>`).join('') || '<div class="board-placeholder">Nothing here yet.<br>Every opportunity starts with a conversation.</div>'}</section>`; }).join('')}</div>${quotes.some(q => q.status === 'declined') ? `<p class="section-help">${quotes.filter(q => q.status === 'declined').length} declined quotations. ${button('View declined', 'declined')}</p>` : ''}`;
    }
    async function quoteForm(customerId = '', quoteId = '') {
        await refs();
        if (!customers.length) {
            toast('Add a customer before creating a quotation.');
            return;
        }
        const q = quoteId ? await api('/quotes/' + quoteId) : null;
        modal(q ? 'Edit quotation draft' : 'Create a quotation', `<form id="productQuote" data-key="${quoteId}" data-revision="${q?.revision || 1}"><div class="form-grid">${field('number', 'Quotation number', 'text', q?.number || 'Q-' + Date.now().toString().slice(-7), { maxlength: 80 })}${select('customer_id', 'Customer', customers.map(c => [c.id, c.name]), q?.customer_id || customerId)}${field('title', 'Proposal title', 'text', q?.title || '', { full: true, maxlength: 200 })}${q ? '<input type="hidden" name="project_id" value="' + e(q.project_id || '') + '"><div><label>Access context</label><p class="form-note">' + e(projects.find(p => p.id === q.project_id)?.name || 'Workspace-wide') + ' · Fixed for this record</p></div>' : projectSelect()}${field('valid_until', 'Valid until', 'date', q?.valid_until || '', { required: false })}</div><div class="line-items-heading"><h3>What are you proposing?</h3><p>Prices exclude tax. Amounts use your workspace currency.</p></div><div id="quoteLines">${q ? q.lines.map((line, i) => quoteLine(i, line)).join('') : quoteLine(0)}</div>${button('Add line item', 'add-line')}<div class="form-grid">${area('notes', 'Notes / scope', q?.notes || '')}</div>${formEnd('Save quotation draft')}</form>`, undefined, undefined, true);
    }
    function quoteLine(index, line) { return `<div class="quote-line" data-line><div><label for="ql-description-${index}">Description</label><input id="ql-description-${index}" data-line-description required maxlength="500" value="${e(line?.description || '')}" placeholder="Product, service or deliverable"></div><div><label for="ql-quantity-${index}">Quantity</label><input id="ql-quantity-${index}" data-line-quantity type="number" min="1" max="1000000" required value="${line?.quantity || 1}"></div><div><label for="ql-price-${index}">Unit price</label><input id="ql-price-${index}" data-line-price value="${line ? (line.unit_price / 100).toFixed(2) : ''}" type="number" min="0" step=".01" max="1000000000" required placeholder="0.00"></div><button type="button" class="icon-button" data-product="remove-line" aria-label="Remove line item">${nexusIcon('close')}</button></div>`; }
    async function quoteDetail(id) {
        const q = await api('/quotes/' + id);
        const canProgress = isRole('admin', 'manager');
        modal(q.number, `<div class="record-overview"><div><span class="record-kicker">QUOTATION</span><h2>${e(q.title)}</h2><p>${e(customerName(q.customer_id))}</p></div>${status(q.status)}</div><div class="record-facts"><span><small>QUOTATION VALUE</small><b>${currency(q.total)}</b></span><span><small>VALID UNTIL</small><b>${e(q.valid_until || 'No expiry date')}</b></span></div><div class="commercial-steps">${['draft', 'sent', 'accepted', 'converted'].map((s, i) => `<span class="${['draft', 'sent', 'accepted', 'converted'].indexOf(q.status) >= i ? 'reached' : ''}"><i>${i + 1}</i>${s === 'converted' ? 'Ordered' : s === 'sent' ? 'Sent' : s === 'draft' ? 'Draft' : 'Accepted'}</span>`).join('')}</div><div class="simple-table-wrap"><table class="table"><thead><tr><th>DESCRIPTION</th><th>QTY</th><th>UNIT PRICE</th><th>AMOUNT</th></tr></thead><tbody>${q.lines.map(l => `<tr><td>${e(l.description)}</td><td>${l.quantity}</td><td>${currency(l.unit_price)}</td><td>${currency(l.total)}</td></tr>`).join('')}</tbody></table></div><p class="preformatted">${e(q.notes)}</p><div class="actions">${q.status === 'draft' && canWrite() && (canProgress || q.created_by === state.me.user.user_id) ? button('Edit draft', 'edit-quote', id) : ''}${canProgress && q.status === 'draft' ? button('Mark as sent', 'quote-send', id, true, `data-revision="${q.revision}"`) : ''}${canProgress && q.status === 'sent' ? button('Record customer acceptance', 'quote-accept', id, true, `data-revision="${q.revision}"`) + button('Mark declined', 'quote-decline', id, false, `data-revision="${q.revision}"`) : ''}${canProgress && q.status === 'accepted' ? button('Create sales order', 'quote-order', id, true, `data-revision="${q.revision}"`) : ''}<button class="btn" data-action="record-chat" data-id="quote:${id}">${nexusIcon('chat')} Discuss quotation</button></div>${q.history?.length ? `<details class="record-history"><summary>View earlier drafts (${q.history.length})</summary>${q.history.map(h => `<div><b>Revision ${h.revision} · ${dt(h.created_at)}</b><p>${e(h.snapshot.title)} · ${currency(h.snapshot.total)}</p><dl>${h.snapshot.lines.map(l => `<dt>${e(l.description)}</dt><dd>${l.quantity} × ${currency(l.unit_price)}</dd>`).join('')}</dl></div>`).join('')}</details>` : ''}<p class="form-note">These actions record internal commercial status. Nexus does not email a proposal, obtain a customer signature or post revenue here.</p>`, undefined, undefined, true);
    }
    async function orderDetail(id) {
        const o = await api('/sales-orders/' + id);
        modal(o.number, `<div class="record-overview"><div><span class="record-kicker">SALES ORDER</span><h2>${e(o.title)}</h2><p>${e(customerName(o.customer_id))}</p></div>${status(o.status)}</div><div class="record-facts"><span><small>ORDER VALUE</small><b>${currency(o.total)}</b></span><span><small>INVOICE</small><b>${o.invoice_id ? 'Draft or posted invoice linked' : 'Ready for invoicing'}</b></span></div><div class="actions">${button('View source quotation', 'quote', o.quote_id)}${isRole('admin', 'manager') && o.status === 'confirmed' ? button('Record fulfilment', 'order-fulfil', id, true) + button('Cancel order', 'order-cancel', id) : ''}${isRole('admin', 'finance') && !o.invoice_id && o.status !== 'cancelled' ? button('Prepare draft invoice', 'invoice-form', id, true) : ''}${o.invoice_id && isRole('admin', 'finance') ? route('Open finance', 'Finance', 'wallet') : ''}<button class="btn" data-action="record-chat" data-id="sales_order:${id}">Discuss order</button></div><p class="form-note">Fulfilment records completion of this order. It does not automatically ship goods or adjust stock. A draft invoice requires a separate finance review and issue action.</p>`, undefined, undefined, true);
    }
    async function support() {
        const org = orgId();
        [tickets, customers, people, projects] = await Promise.all([api('/tickets'), api('/customers'), api('/people'), api('/projects')]);
        if (!current('Support', org))
            return;
        const live = tickets.filter(t => !['resolved', 'closed'].includes(t.status));
        panel().innerHTML = heading('Service desk', 'Turn customer questions into confidence.', button('Export tickets', 'export', 'tickets') + (canWrite() ? button('Create ticket', 'new-ticket', '', true) : '')) + `<div class="commerce-metrics">${moneySummary('Open requests', String(live.length), 'Requests still needing a resolution', 'chat', 'blue')}${moneySummary('High priority', String(live.filter(t => ['high', 'urgent'].includes(t.priority)).length), 'Give these requests attention first', 'alert', 'rose')}${moneySummary('Resolved', String(tickets.filter(t => ['resolved', 'closed'].includes(t.status)).length), 'Customer requests with a recorded outcome', 'checkCircle', 'teal')}</div><div class="section-toolbar"><div class="segmented">${button('Board', 'ticket-view', 'board', ticketView === 'board')}${button('All tickets', 'ticket-view', 'list', ticketView === 'list')}</div><span class="section-help">Ownership, context and the next step. In one place.</span></div><div id="ticketContent"></div>` + footer();
        renderTickets();
    }
    NexusProduct.support = support;
    function ticketCard(t) { return `<button class="ticket-card" data-product="ticket" data-key="${t.id}"><div><span>${e(t.number)}</span><span class="priority priority-${t.priority}">${e(t.priority)}</span></div><h3>${e(t.subject)}</h3><p>${e(t.customer_name || 'Internal request')}</p><div class="ticket-footer"><span class="customer-monogram tone-blue">${initials(t.assignee_name || 'Team')}</span><b>${e(t.assignee_name || 'Team')}</b></div></button>`; }
    function renderTickets() {
        const host = document.querySelector('#ticketContent');
        if (!tickets.length) {
            host.innerHTML = blank('Every great service team starts with ownership.', 'Create your first request and keep the discussion, responsibility and resolution together.', canWrite() ? button('Create first ticket', 'new-ticket', '', true) : '');
            return;
        }
        host.innerHTML = ticketView === 'board' ? `<div class="ticket-board" tabindex="0" role="region" aria-label="Service request board">${[['open', 'New'], ['in_progress', 'In progress'], ['waiting', 'Waiting'], ['resolved', 'Resolved']].map(([s, label]) => `<section class="ticket-column"><div class="board-column-heading"><h2><i class="stage-dot stage-${s}"></i>${label}<span>${tickets.filter(t => t.status === s).length}</span></h2></div>${tickets.filter(t => t.status === s).map(ticketCard).join('') || '<p class="board-placeholder">No requests here.</p>'}</section>`).join('')}</div>` : `<div class="card simple-table-wrap"><table class="table"><thead><tr><th>REQUEST</th><th>CUSTOMER</th><th>OWNER</th><th>PRIORITY</th><th>STATUS</th></tr></thead><tbody>${tickets.map(t => `<tr><td><button class="record-title" data-product="ticket" data-key="${t.id}">${e(t.subject)}</button><small class="subtext">${e(t.number)}</small></td><td>${e(t.customer_name || 'Internal')}</td><td>${e(t.assignee_name)}</td><td><span class="priority priority-${t.priority}">${e(t.priority)}</span></td><td>${status(t.status)}</td></tr>`).join('')}</tbody></table></div>`;
    }
    async function ticketForm(messageId = '') {
        await refs();
        let source = null;
        if (messageId) {
            const message = await api('/messages/' + messageId);
            const conversations = await api('/conversations');
            const conversation = conversations.find((c) => c.id === message.conversation_id);
            source = { body: message.body, project_id: conversation?.project_id };
        }
        modal('Create a service ticket', `<form id="productTicket" data-source="${messageId}"><div class="form-grid">${field('subject', 'Request subject', 'text', source?.body.slice(0, 200) || '', { full: true, maxlength: 200 })}${select('customer_id', 'Customer', [['', 'Internal request'], ...customers.map(c => [c.id, c.name])])}${select('assignee_id', 'Owner', people.filter(p => p.role !== 'viewer').map(p => [p.id, p.name]), state.me.user.user_id)}${select('project_id', 'Project / access context', [['', 'Workspace-wide'], ...projects.map(p => [p.id, p.name])], source?.project_id || '')}${select('priority', 'Priority', [['normal', 'Normal'], ['low', 'Low'], ['high', 'High'], ['urgent', 'Urgent']])}${area('description', 'What needs to happen?', source?.body || '', true)}</div>${source ? '<p class="form-note">The ticket retains its source conversation permissions. The owner must have access to that conversation.</p>' : ''}${formEnd('Create ticket')}</form>`);
    }
    async function ticketDetail(id) {
        const t = await api('/tickets/' + id);
        const transitions = { open: ['in_progress', 'waiting', 'resolved'], in_progress: ['waiting', 'resolved'], waiting: ['in_progress', 'resolved'], resolved: ['open', 'closed'], closed: ['open'] };
        modal(t.number, `<div class="record-overview"><div><span class="record-kicker">CUSTOMER REQUEST</span><h2>${e(t.subject)}</h2><p>${e(customerName(t.customer_id))}</p></div>${status(t.status)}</div><div class="record-facts"><span><small>ASSIGNED TO</small><b>${e(people.find(p => p.id === t.assignee_id)?.name || 'Team member')}</b></span><span><small>PRIORITY</small><b>${e(t.priority)}</b></span></div><p class="preformatted">${e(t.description)}</p>${t.resolution ? `<div class="resolution-note"><b>Recorded resolution</b><p>${e(t.resolution)}</p></div>` : ''}<div class="actions"><button class="btn" data-action="record-chat" data-id="ticket:${id}">${nexusIcon('chat')} Open discussion</button>${t.source_message_id ? button('View source message', 'source', t.source_message_id) : ''}</div>${canWrite() && (isRole('admin', 'manager') || [t.created_by, t.assignee_id].includes(state.me.user.user_id)) ? `<form id="productTicketStatus" data-key="${id}" data-revision="${t.revision}"><div class="form-grid">${select('status', 'Next step', transitions[t.status].map(s => [s, s.replaceAll('_', ' ')]))}${area('resolution', 'Resolution / outcome', t.resolution)}</div>${formEnd('Update ticket')}</form><form id="productTicketAssign" data-key="${id}" data-revision="${t.revision}"><div class="form-grid">${select('assignee_id', 'Reassign to', people.filter(p => p.role !== 'viewer').map(p => [p.id, p.name]), t.assignee_id)}</div>${formEnd('Update owner')}</form>` : ''}`, undefined, undefined, true);
    }
    async function appHub() {
        const org = orgId();
        apps = await api('/custom-apps');
        if (!current('Apps', org))
            return;
        selectedApp = null;
        appArchived = false;
        panel().innerHTML = heading('Made for the way you work.', 'Your business is unique. Your tools should fit.', isRole('admin') ? button('Build an app', 'app-builder', '', true) : '') + `<section class="apps-hero"><div><span class="hero-kicker">YOUR BUSINESS TOOLKIT</span><h2>A new process?<br><em>Make it your own.</em></h2><p>Turn the forms, inspections and registers your team uses into connected business records.</p>${isRole('admin') ? button('Create your first form', 'app-builder', '', true) : route('Explore your workspace', 'Tasks')}</div><div class="app-preview-art" aria-hidden="true"><span>${nexusIcon('layers')} YOUR NEXT BUSINESS APP</span><div><i class="tone-teal">✓</i><b>Site inspection</b><small>Connected to your project</small></div><p><span>Inspection location</span><b>Riverside development</b></p><p><span>Outcome</span><b class="good">Ready to move forward</b></p></div></section><div class="section-heading"><div><h2>Your custom apps <span class="count-badge">${apps.length}</span></h2><p>Forms and records configured for your organization.</p></div></div><div class="app-catalog">${apps.map((app, i) => `<article class="card app-tile"><span class="app-tile-icon tone-${['teal', 'blue', 'rose', 'amber'][i % 4]}">${nexusIcon('layers')}</span><span class="app-scope">${app.scope === 'team' ? 'Workspace app' : 'Managers & finance'}</span><h3>${e(app.name)}</h3><p>${e(app.description || 'A custom business application.')}</p><div class="app-tile-meta">${app.fields.length} fields · Version ${app.current_version}</div><div class="actions">${button('Open app', 'open-app', app.id, true)}${isRole('admin') ? button('Edit form', 'app-builder', app.id) : ''}</div></article>`).join('') || blank('Start with a process you know.', 'Create a site inspection, equipment checkout, incident log or any form your team needs.')}</div><div class="section-heading"><div><h2>Built into your platform</h2><p>Extend your operating rhythm with connected tools.</p></div></div><div class="app-catalog">${[['Approval policies', 'Purchasing approval designer', 'Configure spend thresholds and distinct review stages with saved versions and simulation.', 'shield', 'teal'], ['Automations', 'Workflow automation', 'Turn overdue invoices, stock thresholds and contract dates into accountable follow-up.', 'layers', 'violet'], ['Industry apps', 'Industry extensions', 'Project costing and professional-services time recording, connected to project context.', 'briefcase', 'amber'], ['Business Brain', 'Business Brain', 'Find accessible evidence and explore explicit financial scenarios.', 'spark', 'blue']].filter(([page]) => !['Automations', 'Approval policies'].includes(page) || isRole('admin')).map(([page, name, copy, icon, tone]) => `<article class="card app-tile"><span class="app-tile-icon tone-${tone}">${nexusIcon(icon)}</span><h3>${name}</h3><p>${copy}</p>${route('Open ' + name, page, icon)}</article>`).join('')}</div>` + footer();
    }
    NexusProduct.appHub = appHub;
    async function customApp(id) {
        const org = orgId();
        selectedApp = await api('/custom-apps/' + id);
        records = await api('/custom-apps/' + id + '/records' + (appArchived ? '?archived=1' : ''));
        if (!current('Apps', org))
            return;
        const app = selectedApp;
        panel().innerHTML = `<button class="back-link" data-product="apps">← All apps</button>` + heading(app.name, appArchived ? 'Archived records · Restore records to return them to the active register.' : app.description, button(appArchived ? 'Active records' : 'Archived records', 'app-archive-view', id) + (isRole('admin') ? button('Edit form', 'app-builder', id) : '') + (canWrite() && !appArchived ? button('Add record', 'app-record-form', id, true) : '')) + `<div class="record-facts card app-record-summary"><span><small>ACCESSIBLE RECORDS</small><b>${records.length}</b></span><span><small>FORM VERSION</small><b>Version ${app.current_version}</b></span><span><small>ACCESS SCOPE</small><b>${app.scope === 'team' ? 'Workspace members' : 'Managers & finance'}</b></span></div>` + (records.length ? `<div class="card simple-table-wrap"><table class="table"><thead><tr>${app.fields.slice(0, 4).map(f => `<th>${e(f.label.toUpperCase())}</th>`).join('')}<th>CREATED</th><th></th></tr></thead><tbody>${records.map(r => `<tr>${app.fields.slice(0, 4).map(f => `<td>${displayValue(r.payload[f.key], f)}</td>`).join('')}<td>${dt(r.created_at)}</td><td>${button('Open', 'app-record', r.id)}</td></tr>`).join('')}</tbody></table></div>` : blank('Ready for your first record.', 'Your configured form is ready. Every saved record keeps the schema version it was created with.', canWrite() ? button('Add record', 'app-record-form', id, true) : '')) + `<div class="actions">${button('Export records', 'export', 'app', false, `data-app="${id}" data-archived="${appArchived ? '1' : '0'}"`)}</div><p class="section-help">Historical records preserve their original fields and form version. Changing a form does not rewrite saved records.</p>` + footer();
    }
    function displayValue(value, field) {
        if (value === undefined || value === null)
            return '—';
        if (field.type === 'money')
            return e(currency(Number(value)));
        if (field.type === 'boolean')
            return `<span class="boolean-value ${value ? 'good' : ''}">${value ? 'Yes' : 'No'}</span>`;
        if (field.type === 'customer')
            return e(customerName(String(value)));
        return e(value);
    }
    async function appBuilder(id = '') {
        editingApp = id ? await api('/custom-apps/' + id) : null;
        builderFields = editingApp ? structuredClone(editingApp.fields) : [{ key: 'name', label: 'Name', type: 'text', required: true }, { key: 'notes', label: 'Notes', type: 'longtext', required: false }];
        modal(editingApp ? 'Edit app form' : 'Build your business app', `<form id="productAppBuilder"><div class="builder-intro"><span class="app-tile-icon tone-violet">${nexusIcon('layers')}</span><div><h3>A form that fits your process.</h3><p>Choose your fields. Arrange them. Start collecting connected records.</p></div></div><div class="form-grid">${field('name', 'App name', 'text', editingApp?.name || '', { maxlength: 100 })}${select('scope', 'Who can access this app?', [['team', 'Workspace members'], ['managers', 'Administrators, managers & finance']], editingApp?.scope || 'team')}${area('description', 'What is this app for?', editingApp?.description || '')}</div><div class="builder-toolbar"><h3>Form fields <span id="fieldCount"></span></h3><span>Drag to reorder, or use the arrow buttons.</span></div><div id="builderFields"></div>${button('Add field', 'add-field')}<p class="form-note">Field keys connect saved values to a field. Keep a key unchanged when renaming its label. Existing records retain their original schema. App scope is fixed at creation; form revisions cannot expand access.</p>${formEnd(editingApp ? 'Save new form version' : 'Create app')}</form>`, undefined, undefined, true);
        renderBuilder();
        if (editingApp) {
            const name = document.querySelector('#f-name');
            name.readOnly = true;
            document.querySelector('#f-scope').disabled = true;
        }
    }
    function captureFields() {
        document.querySelectorAll('.builder-field').forEach((row, i) => { builderFields[i] = { key: row.querySelector('[data-field-key]').value, label: row.querySelector('[data-field-label]').value, type: row.querySelector('[data-field-type]').value, required: row.querySelector('[data-field-required]').checked, options: row.querySelector('[data-field-options]').value.split(',').map(s => s.trim()).filter(Boolean) }; });
    }
    function renderBuilder() {
        const kinds = [['text', 'Short text'], ['longtext', 'Long text'], ['number', 'Number'], ['money', 'Money'], ['date', 'Date'], ['boolean', 'Yes / no'], ['choice', 'Choice'], ['customer', 'Customer relationship']];
        document.querySelector('#builderFields').innerHTML = builderFields.map((f, i) => `<section class="builder-field" draggable="true" data-field-index="${i}"><div class="field-drag" aria-hidden="true">⠿</div><div class="builder-field-main"><div class="builder-field-row"><div><label for="builder-label-${i}">Field label</label><input id="builder-label-${i}" data-field-label value="${e(f.label)}" required maxlength="80"></div><div><label for="builder-type-${i}">Field type</label><select id="builder-type-${i}" data-field-type>${kinds.map(([value, label]) => `<option value="${value}" ${f.type === value ? 'selected' : ''}>${label}</option>`).join('')}</select></div></div><div class="builder-field-row"><div><label for="builder-key-${i}">Field key</label><input id="builder-key-${i}" data-field-key value="${e(f.key)}" pattern="[a-z][a-z0-9_]{0,39}" required></div><div><label for="builder-options-${i}">Choices (comma separated)</label><input id="builder-options-${i}" data-field-options value="${e(f.options?.join(', ') || '')}" placeholder="Used for Choice fields"></div></div><label class="builder-required"><input data-field-required type="checkbox" ${f.required ? 'checked' : ''}> Required field</label></div><div class="field-tools">${button('↑', 'field-up', String(i), false, 'aria-label="Move field up"')}${button('↓', 'field-down', String(i), false, 'aria-label="Move field down"')}${button('Remove', 'remove-field', String(i))}</div></section>`).join('');
        document.querySelector('#fieldCount').textContent = String(builderFields.length) + '/12';
    }
    async function appRecordForm(id, recordId = '') {
        await refs();
        const app = await api('/custom-apps/' + id);
        selectedApp = app;
        const record = recordId ? await api('/custom-apps/' + id + '/records/' + recordId) : null;
        formFields = record ? app.versions.find(v => v.version === record.schema_version).fields : app.fields;
        modal(record ? 'Edit ' + app.name + ' record' : 'Add ' + app.name + ' record', `<form id="productAppRecord" data-key="${id}" data-record="${recordId}" data-revision="${record?.revision || 1}" data-version="${record?.schema_version || app.current_version}"><div class="form-grid">${record ? '' : projectSelect()}${formFields.map(f => appField(f, record?.payload[f.key])).join('')}</div>${record ? '<p class="form-note">This edit uses the original form version and retains the previous values in history. Access context remains unchanged.</p>' : ''}${formEnd(record ? 'Save record revision' : 'Save record')}</form>`, undefined, undefined, true);
    }
    function appField(f, value = '') {
        const name = 'custom_' + f.key;
        let initial = value === null || value === undefined ? '' : String(value);
        if (f.type === 'boolean')
            return `<div><label for="custom-${f.key}">${e(f.label)}</label><select id="custom-${f.key}" name="${name}" ${f.required ? 'required' : ''}><option value="">Choose…</option><option value="true" ${value === true ? 'selected' : ''}>Yes</option><option value="false" ${value === false ? 'selected' : ''}>No</option></select></div>`;
        if (f.type === 'choice' || f.type === 'customer')
            return select(name, e(f.label), [['', 'Choose…'], ...(f.type === 'customer' ? customers.map(c => [c.id, c.name]) : f.options.map(o => [o, o]))], initial, false).replace('<select ', '<select ' + (f.required ? 'required ' : ''));
        if (f.type === 'longtext')
            return area(name, e(f.label), initial, f.required);
        if (f.type === 'money' && initial !== '')
            initial = (Number(value) / 100).toFixed(2);
        return field(name, e(f.label), f.type === 'money' || f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text', initial, { required: f.required, step: f.type === 'money' ? '.01' : f.type === 'number' ? 'any' : undefined, min: f.type === 'money' ? 0 : undefined, maxlength: 500 });
    }
    async function appRecord(id) {
        const app = selectedApp, record = await api('/custom-apps/' + app.id + '/records/' + id);
        const schema = app.versions?.find(v => v.version === record.schema_version)?.fields || app.fields;
        const writable = canWrite() && (isRole('admin', 'manager') || record.created_by === state.me.user.user_id);
        modal(app.name, `<span class="record-kicker">RECORD · FORM VERSION ${record.schema_version} · REVISION ${record.revision}${record.archived ? ' · ARCHIVED' : ''}</span><div class="custom-record-values">${schema.map(f => `<div><small>${e(f.label)}</small><p>${displayValue(record.payload[f.key], f)}</p></div>`).join('')}</div><p class="form-note">Saved ${dt(record.created_at)}. ${record.project_id ? 'Project permissions apply.' : 'Workspace-level record.'}</p><div class="actions">${writable && !record.archived ? button('Edit record', 'edit-app-record', id, true) : ''}${writable ? button(record.archived ? 'Restore record' : 'Archive record', record.archived ? 'restore-app-record' : 'archive-app-record', id, false, `data-revision="${record.revision}"`) : ''}</div>${record.history?.length ? `<details class="record-history"><summary>View saved revisions (${record.history.length + 1})</summary>${record.history.map(h => `<div><b>Revision ${h.revision} · ${dt(h.created_at)}</b><dl>${schema.map(f => `<dt>${e(f.label)}</dt><dd>${displayValue(h.payload[f.key], f)}</dd>`).join('')}</dl></div>`).join('')}<div><b>Original values · ${dt(record.created_at)}</b><dl>${schema.map(f => `<dt>${e(f.label)}</dt><dd>${displayValue(record.original_payload?.[f.key], f)}</dd>`).join('')}</dl></div></details>` : ''}`, undefined, undefined, true);
    }
    async function brain() {
        const org = orgId();
        brainData = await api('/brain' + (brainQuery ? '?q=' + encodeURIComponent(brainQuery) : ''));
        if (!current('Business Brain', org))
            return;
        const d = brainData;
        panel().innerHTML = heading('Your business has a memory.', 'Find the evidence. Understand the dependencies. Decide with context.') + `<section class="brain-search-card"><span class="brain-symbol">${nexusIcon('spark')}</span><div><h2>Start with what you need to know.</h2><p>Search accessible records, documents and conversations together.</p><form id="productBrainSearch"><label class="sr-only" for="brainQuery">Search business knowledge</label><div class="brain-search-input">${nexusIcon('search')}<input id="brainQuery" name="query" placeholder="Try a customer, project, decision or phrase…" value="${e(brainQuery)}" minlength="2" maxlength="160" required><button class="btn primary" type="submit">Find evidence ${nexusIcon('arrow')}</button></div></form><div class="brain-prompts">${['Riverside', 'procurement', 'safety'].map(q => button(q, 'brain-query', q)).join('')}</div></div></section><div class="brain-evidence-label">${nexusIcon('shield')} Permission-aware search · Saved records and messages · No generated facts</div>${brainQuery ? `<section class="evidence-results"><div class="section-heading"><h2>${d.results.length}${d.truncated ? '+' : ''} accessible results for “${e(brainQuery)}”</h2>${button('Clear search', 'brain-query', '')}</div>${d.results.map(r => `<button class="card evidence-card" data-product="evidence" data-key="${e(r.id)}" data-kind="${r.kind}"><span class="file-icon tone-${r.kind === 'message' ? 'violet' : 'blue'}">${nexusIcon(r.kind === 'message' ? 'chat' : 'file')}</span><span><small>${e(r.kind.toUpperCase())} · ${dt(r.created_at)}</small><h3>${e(r.title)}</h3><p>${e(r.snippet)}</p><b>Open source ${nexusIcon('arrow')}</b></span></button>`).join('') || blank('No matching evidence.', 'Try another term. Results include only information you are allowed to access.')}</section>` : ''}<div class="brain-columns"><section class="card insights-panel"><div class="section-heading"><div><h2>Signals worth a closer look</h2><p>Simple rules. Traceable business records.</p></div></div>${d.signals.map(s => `<button class="signal-link" data-action="navigate" data-id="${s.route}"><span class="metric-icon tone-${s.count ? 'amber' : 'teal'}">${nexusIcon(s.count ? 'alert' : 'checkCircle')}</span><span>${e(s.label)}<small>Open the underlying records</small></span><strong>${s.count}</strong>${nexusIcon('arrow')}</button>`).join('')}</section>${d.finance ? `<section class="card scenario-panel"><span class="record-kicker">CASH TIMING SCENARIO</span><h2>What if collections improve?</h2><p>Explore a simple scenario using recorded cash, overdue invoices and issued purchase commitments.</p><label for="collectionRange">Assumed collection of overdue invoices <b id="collectionPercent">50%</b></label><input type="range" id="collectionRange" min="0" max="100" step="5" value="50"><div class="scenario-result"><small>ILLUSTRATIVE CASH AFTER COMMITMENTS</small><strong id="scenarioResult"></strong></div><p class="form-note">Recorded cash + assumed overdue collections − issued purchase commitments. Purchase commitments may already be settled outside this application. No payment dates, tax, payroll or other expenses are modeled. This is a scenario, not a forecast.</p>${d.finance.evidence.length ? button('Inspect invoice evidence', 'finance-evidence') : route('Open finance', 'Finance', 'wallet')}</section>` : '<section class="card insights-panel"><span class="metric-icon tone-violet">' + nexusIcon('spark') + '</span><h2>Context before conclusions.</h2><p>Finance scenarios are available to authorized finance members. Your knowledge search respects the same record permissions as the rest of your workspace.</p></section>'}</div>` + footer();
        updateScenario();
    }
    NexusProduct.brain = brain;
    function updateScenario() { if (!brainData?.finance)
        return; const value = Number(document.querySelector('#collectionRange')?.value || 50), f = brainData.finance; const result = document.querySelector('#scenarioResult'); if (result)
        result.textContent = currency(Math.round(f.recorded_cash + f.overdue_receivables * value / 100 - f.issued_purchase_commitments)); const label = document.querySelector('#collectionPercent'); if (label)
        label.textContent = value + '%'; }
    async function customerDirectory() {
        const org = orgId();
        customers = await api('/customers');
        if (!current('Customers', org))
            return;
        const stages = ['lead', 'qualified', 'customer', 'inactive'];
        panel().innerHTML = heading('Customers', 'A complete relationship, beyond the contact details.', canWrite() ? '<button class="btn primary" data-action="new-customer">' + nexusIcon('plus') + ' Add customer</button>' : '') + `<div class="customer-stage-strip">${stages.map(s => `<div><span class="stage-dot stage-${s}"></span><small>${e(s === 'customer' ? 'Active customers' : s === 'qualified' ? 'Qualified opportunities' : s === 'lead' ? 'New relationships' : 'Inactive')}</small><strong>${customers.filter(c => c.stage === s).length}</strong></div>`).join('')}</div><div class="directory-toolbar"><label class="filter-search">${nexusIcon('search')}<input id="customerFilter" type="search" aria-label="Find a customer" placeholder="Find a customer, company or contact…"></label><span>${customers.length} relationships</span></div><div class="customer-grid" id="customerCards"></div>` + footer();
        renderCustomers('');
    }
    NexusProduct.customerDirectory = customerDirectory;
    function renderCustomers(query) {
        const rows = customers.filter(c => [c.name, c.company, c.email].join(' ').toLowerCase().includes(query.toLowerCase()));
        const host = document.querySelector('#customerCards');
        if (!host)
            return;
        host.innerHTML = rows.map((c, i) => `<button class="card customer-card" data-product="customer" data-key="${c.id}"><div class="customer-card-top"><span class="customer-avatar tone-${['teal', 'blue', 'violet', 'amber', 'rose'][i % 5]}">${initials(c.name)}</span>${status(c.stage)}</div><h2>${e(c.name)}</h2><p>${e(c.company || 'Individual contact')}</p><div class="customer-contact">${nexusIcon('mail')} ${e(c.email || 'No email recorded')}</div><div class="customer-card-footer">Open relationship ${nexusIcon('arrow')}</div></button>`).join('') || blank('No matching customers.', 'Try another name or company.');
    }
    async function customerDetail(id) {
        await refs();
        const c = customers.find(c => c.id === id);
        if (!c) {
            toast('Customer no longer available.');
            return;
        }
        const [qs, os, ts] = await Promise.all([api('/quotes'), api('/sales-orders'), api('/tickets')]);
        const relatedQuotes = qs.filter(q => q.customer_id === id), relatedOrders = os.filter(o => o.customer_id === id), relatedTickets = ts.filter(t => t.customer_id === id);
        modal(c.name, `<div class="customer-detail-heading"><span class="customer-avatar tone-teal">${initials(c.name)}</span><div><h2>${e(c.name)}</h2><p>${e(c.company || 'Customer relationship')}</p></div>${status(c.stage)}</div><div class="record-facts"><span><small>EMAIL</small><b>${e(c.email || 'Not recorded')}</b></span><span><small>PHONE</small><b>${e(c.phone || 'Not recorded')}</b></span></div>${c.notes ? `<p class="preformatted">${e(c.notes)}</p>` : ''}<div class="actions">${canWrite() ? button('Create quotation', 'customer-quote', id, true) : ''}<button class="btn" data-action="record-chat" data-id="customer:${id}">${nexusIcon('chat')} Customer discussion</button></div>${canWrite() ? `<label class="inline-stage-label">Relationship stage <select data-change="customer-stage" data-id="${id}" aria-label="Customer relationship stage">${['lead', 'qualified', 'customer', 'inactive'].map(s => `<option value="${s}" ${s === c.stage ? 'selected' : ''}>${s}</option>`).join('')}</select></label>` : ''}<div class="customer-related-grid"><section><h3>Quotations <span>${relatedQuotes.length}</span></h3>${relatedQuotes.map(q => `<button data-product="quote" data-key="${q.id}"><span>${e(q.title)}<small>${e(q.number)} · ${e(q.status)}</small></span><b>${currency(q.total)}</b></button>`).join('') || '<p>No quotations yet.</p>'}</section><section><h3>Sales orders <span>${relatedOrders.length}</span></h3>${relatedOrders.map(o => `<button data-product="order" data-key="${o.id}"><span>${e(o.number)}<small>${e(o.status)}</small></span><b>${currency(o.total)}</b></button>`).join('') || '<p>No orders yet.</p>'}</section><section><h3>Service requests <span>${relatedTickets.length}</span></h3>${relatedTickets.map(t => `<button data-product="ticket" data-key="${t.id}"><span>${e(t.subject)}<small>${e(t.number)} · ${e(t.status)}</small></span>${nexusIcon('arrow')}</button>`).join('') || '<p>No service requests yet.</p>'}</section></div>`, undefined, undefined, true);
    }
    async function customerStageSaved(id, value) { const customer = customers.find(c => c.id === id); if (customer)
        customer.stage = value; const badge = document.querySelector('#modal .customer-detail-heading .status'); if (badge) {
        badge.className = 'status status-' + value;
        badge.textContent = value;
    } if (state.page === 'Customers')
        await customerDirectory(); }
    NexusProduct.customerStageSaved = customerStageSaved;
    function operationLinks() { if (!['Operations', 'Procurement', 'Assets', 'Contracts'].includes(state.page))
        return; panel().querySelector('.titlebar')?.insertAdjacentHTML('afterend', `<div class="operation-tabs">${[['Operations', 'Products & suppliers', 'box'], ['Procurement', 'Purchasing', 'cart'], ['Assets', 'Assets', 'asset'], ['Contracts', 'Contracts', 'file']].filter(([page]) => page !== 'Contracts' || isRole('admin', 'manager', 'finance')).map(([page, label, icon]) => `<button data-action="navigate" data-id="${page}" class="${state.page === page ? 'selected' : ''}">${nexusIcon(icon)}${label}</button>`).join('')}</div>`); }
    NexusProduct.operationLinks = operationLinks;
    function settingLinks() { if (state.page !== 'Settings')
        return; panel().querySelector('.titlebar')?.insertAdjacentHTML('afterend', `<div class="settings-shortcuts">${isRole('admin') ? route('Audit trail', 'Audit log', 'shield') + route('Workflow rules', 'Automations', 'layers') + route('Purchasing policies', 'Approval policies', 'shield') : ''}${route('Your business apps', 'Apps', 'layers')}${route('Document library', 'Documents', 'folder')}</div>`); }
    NexusProduct.settingLinks = settingLinks;
    function workspaceLinks() { if (!['Tasks', 'Meetings'].includes(state.page))
        return; panel().querySelector('.titlebar')?.insertAdjacentHTML('afterend', `<div class="operation-tabs">${route('My work & tasks', 'Tasks', 'check')}${route('Meetings & calendar', 'Meetings', 'calendar')}</div>`); }
    NexusProduct.workspaceLinks = workspaceLinks;
    async function analytics() {
        const org = orgId();
        const [dashboard, qs, ts] = await Promise.all([api('/dashboard'), api('/quotes'), api('/tickets')]);
        if (!current('Intelligence', org))
            return;
        const tasks = dashboard.tasks, active = tasks.filter(t => t.status !== 'done'), peopleNames = [...new Set(tasks.map(t => t.assignee_name))];
        panel().innerHTML = heading('Business performance', 'See the shape of your work. Find the next improvement.') + `<div class="commerce-metrics">${moneySummary('Tasks completed', String(tasks.filter(t => t.status === 'done').length), tasks.length + ' tasks in your accessible workspace', 'checkCircle', 'teal')}${moneySummary('Projects needing attention', String(dashboard.projects.filter((p) => p.status === 'at_risk').length), 'Projects explicitly marked at risk', 'alert', 'amber')}${moneySummary('Customer requests resolved', String(ts.filter(t => ['resolved', 'closed'].includes(t.status)).length), ts.length + ' requests recorded', 'shield', 'blue')}</div><div class="analytics-grid"><section class="card analysis-card"><div class="section-heading"><div><h2>Team workload</h2><p>Open tasks by assigned owner</p></div></div>${peopleNames.map(name => { const count = active.filter(t => t.assignee_name === name).length; return `<div class="workload-row"><span class="customer-monogram tone-blue">${initials(name)}</span><div><b>${e(name)}</b><div class="workload-bar"><span style="width:${Math.min(100, count / Math.max(1, ...peopleNames.map(n => active.filter(t => t.assignee_name === n).length)) * 100)}%"></span></div></div><strong>${count}</strong></div>`; }).join('') || '<p>No tasks yet.</p>'}</section><section class="card analysis-card"><div class="section-heading"><div><h2>Commercial pipeline</h2><p>Count and value by quotation stage</p></div></div>${['draft', 'sent', 'accepted', 'converted', 'declined'].map(stage => { const items = qs.filter(q => q.status === stage); return `<div class="pipeline-analysis-row"><span class="stage-dot stage-${stage}"></span><b>${e(stage === 'converted' ? 'Ordered' : stage)}</b><span>${items.length}</span><strong>${currency(items.reduce((a, q) => a + q.total, 0))}</strong></div>`; }).join('')}<p class="form-note">Quoted value is not posted revenue. Open Finance for issued invoices and journal entries.</p></section></div><div class="analytics-next card"><span class="metric-icon tone-violet">${nexusIcon('spark')}</span><div><h2>Numbers are the start. Context is the next step.</h2><p>Explore the records, discussions and assumptions behind your business.</p></div>${route('Open Business Brain', 'Business Brain', 'arrow')}</div>` + footer();
    }
    NexusProduct.analytics = analytics;
    async function search(query) { brainQuery = query; await navigate('Business Brain'); }
    NexusProduct.search = search;
    function tour(step) { const slides = [['One connected business.', 'Start at Home for current projects, requests and tasks. Every card opens a real working area.', 'overview'], ['Relationships that move forward.', 'Customers brings contact details, quotations, orders and service requests together.', 'users'], ['Keep the conversation in context.', 'Discuss customers, quotations, tickets and projects beside their records. Convert messages into reviewed tasks, requisitions or tickets.', 'chat'], ['Make your own way of working.', 'Use Apps to configure business forms and save records. Use Automations to simulate and activate recurring follow-up rules.', 'layers'], ['Evidence before conclusions.', 'Business Brain searches authorized records and conversations. Financial scenarios show their assumptions, separate from recorded facts.', 'spark']]; const [title, copy, icon] = slides[step]; modal('Discover NEXUS', `<div class="tour-slide"><span class="tour-icon tone-violet">${nexusIcon(icon)}</span><span class="record-kicker">${step + 1} OF ${slides.length}</span><h2>${title}</h2><p>${copy}</p><div class="tour-dots">${slides.map((_, i) => `<i class="${i === step ? 'selected' : ''}"></i>`).join('')}</div>${step < slides.length - 1 ? button('Next', 'tour', String(step + 1), true) : button('Start exploring', 'tour-finish', '', true)}</div>`); }
    document.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-product]');
        if (!target || target.disabled)
            return;
        const action = target.dataset.product, id = target.dataset.key || '';
        target.disabled = true;
        try {
            if (action === 'export') {
                const query = new URLSearchParams();
                if (target.dataset.app)
                    query.set('app', target.dataset.app);
                if (target.dataset.archived === '1')
                    query.set('archived', '1');
                const link = document.createElement('a');
                link.href = '/api/exports/' + id + '.csv?' + query;
                link.download = 'nexus-' + id + '.csv';
                document.body.append(link);
                link.click();
                link.remove();
                return;
            }
            if (action === 'customize-home') {
                customizeHome();
                return;
            }
            if (action === 'new-quote') {
                await quoteForm();
                return;
            }
            if (action === 'edit-quote') {
                await quoteForm('', id);
                return;
            }
            if (action === 'customer-quote') {
                await quoteForm(id);
                return;
            }
            if (action === 'add-line') {
                const host = document.querySelector('#quoteLines');
                if (host.children.length >= 50) {
                    toast('A quotation supports at most 50 lines.');
                    return;
                }
                host.insertAdjacentHTML('beforeend', quoteLine(Date.now()));
                return;
            }
            if (action === 'remove-line') {
                if (document.querySelectorAll('[data-line]').length > 1)
                    target.closest('[data-line]').remove();
                else
                    toast('Keep at least one line item.');
                return;
            }
            if (action === 'sales-view') {
                salesView = id;
                await sales();
                return;
            }
            if (action === 'quote') {
                await refs();
                await quoteDetail(id);
                return;
            }
            if (action.startsWith('quote-')) {
                const result = await api('/quotes/' + id + '/' + action.slice(6), 'POST', { revision: Number(target.dataset.revision) });
                toast(action === 'quote-order' ? 'Sales order created.' : 'Quotation updated.');
                await sales();
                if (action === 'quote-order')
                    await orderDetail(result.id);
                else
                    await quoteDetail(id);
                return;
            }
            if (action === 'declined') {
                modal('Declined quotations', quotes.filter(q => q.status === 'declined').map(q => `<div class="member-list"><b>${e(q.title)}</b>${button('Open', 'quote', q.id)}</div>`).join(''));
                return;
            }
            if (action === 'order') {
                await refs();
                await orderDetail(id);
                return;
            }
            if (action === 'order-fulfil' || action === 'order-cancel') {
                await api('/sales-orders/' + id + '/' + (action === 'order-fulfil' ? 'fulfil' : 'cancel'), 'POST');
                await sales();
                await orderDetail(id);
                toast('Order status updated.');
                return;
            }
            if (action === 'invoice-form') {
                modal('Prepare draft invoice', `<form id="productOrderInvoice" data-key="${id}"><div class="form-grid">${field('number', 'Invoice number', 'text', 'INV-' + Date.now().toString().slice(-7), { maxlength: 80 })}${field('due_date', 'Due date', 'date', '', { required: false })}</div><p class="form-note">The order’s customer, description and amount will be copied. This creates a draft; it does not post revenue or record payment.</p>${formEnd('Create draft invoice')}</form>`);
                return;
            }
            if (action === 'new-ticket') {
                await ticketForm();
                return;
            }
            if (action === 'message-ticket') {
                await ticketForm(id);
                return;
            }
            if (action === 'ticket') {
                await refs();
                await ticketDetail(id);
                return;
            }
            if (action === 'ticket-view') {
                ticketView = id;
                await support();
                return;
            }
            if (action === 'source') {
                closeModal();
                await sourceMessage(id);
                return;
            }
            if (action === 'app-builder') {
                await appBuilder(id);
                return;
            }
            if (action === 'apps') {
                await appHub();
                return;
            }
            if (action === 'open-app') {
                await refs();
                await customApp(id);
                return;
            }
            if (action === 'app-record-form') {
                await appRecordForm(id);
                return;
            }
            if (action === 'app-record') {
                await appRecord(id);
                return;
            }
            if (action === 'edit-app-record') {
                await appRecordForm(selectedApp.id, id);
                return;
            }
            if (action === 'app-archive-view') {
                appArchived = !appArchived;
                await customApp(id);
                return;
            }
            if (action === 'archive-app-record' || action === 'restore-app-record') {
                await api('/custom-apps/' + selectedApp.id + '/records/' + id + '/' + (action === 'archive-app-record' ? 'archive' : 'restore'), 'POST', { revision: Number(target.dataset.revision) });
                closeModal();
                await customApp(selectedApp.id);
                toast(action === 'archive-app-record' ? 'Record archived. It can be restored.' : 'Record restored.');
                return;
            }
            if (action === 'add-field') {
                captureFields();
                if (builderFields.length >= 12) {
                    toast('A form supports at most 12 fields.');
                    return;
                }
                let key = 'field_' + (builderFields.length + 1);
                while (builderFields.some(f => f.key === key))
                    key += '_new';
                builderFields.push({ key, label: 'New field', type: 'text', required: false });
                renderBuilder();
                return;
            }
            if (['field-up', 'field-down', 'remove-field'].includes(action)) {
                captureFields();
                const index = Number(id);
                if (action === 'remove-field') {
                    if (builderFields.length > 1)
                        builderFields.splice(index, 1);
                }
                else {
                    const next = index + (action === 'field-up' ? -1 : 1);
                    if (next >= 0 && next < builderFields.length)
                        [builderFields[index], builderFields[next]] = [builderFields[next], builderFields[index]];
                }
                renderBuilder();
                return;
            }
            if (action === 'brain-query') {
                brainQuery = id;
                await brain();
                return;
            }
            if (action === 'evidence') {
                const kind = target.dataset.kind;
                closeModal();
                if (kind === 'custom_record') {
                    const result = brainData?.results.find(r => r.id === id);
                    await navigate('Apps');
                    await customApp(result.app_id);
                    await appRecord(id);
                    return;
                }
                if (kind === 'message') {
                    await sourceMessage(id);
                    return;
                }
                if (kind === 'quote') {
                    await refs();
                    await quoteDetail(id);
                    return;
                }
                if (kind === 'ticket') {
                    await refs();
                    await ticketDetail(id);
                    return;
                }
                if (kind === 'customer') {
                    await customerDetail(id);
                    return;
                }
                if (kind === 'document') {
                    await navigate('Documents');
                    document.querySelector(`[data-action="doc-detail"][data-id="${id}"]`)?.click();
                    return;
                }
                if (kind === 'project') {
                    await navigate('Projects');
                    document.querySelector(`[data-action="project-detail"][data-id="${id}"]`)?.click();
                    return;
                }
                await navigate('Tasks');
                return;
            }
            if (action === 'finance-evidence') {
                const f = brainData.finance;
                modal('Scenario source records', `<div class="record-facts"><span><small>RECORDED CASH</small><b>${currency(f.recorded_cash)}</b></span><span><small>ISSUED PURCHASE COMMITMENTS</small><b>${currency(f.issued_purchase_commitments)}</b></span></div><h3>Overdue issued invoices</h3>${f.evidence.map(i => `<div class="scenario-invoice"><b>${e(i.number)}</b><span>Due ${e(i.due_date)}</span><strong>${currency(i.total)}</strong></div>`).join('')}<p class="form-note">The scenario uses only currently authorized records. Commitments are issued purchase orders; actual payment timing is not tracked.</p>${route('Open finance', 'Finance', 'wallet')}`, undefined, undefined, true);
                return;
            }
            if (action === 'customer') {
                await customerDetail(id);
                return;
            }
            if (action === 'tour') {
                tour(Number(id));
                return;
            }
            if (action === 'tour-finish') {
                closeModal();
                return;
            }
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
        if (!form.id.startsWith('product'))
            return;
        event.preventDefault();
        const values = Object.fromEntries(new FormData(form)), submit = form.querySelector('[type=submit]');
        if (submit)
            submit.disabled = true;
        try {
            if (form.id === 'productHomePreferences') {
                const preferences = {};
                for (const key of Object.keys(homePreferences))
                    preferences[key] = values[key] === 'on';
                homePreferences = await api('/preferences', 'POST', preferences);
                closeModal();
                await home();
                toast('Your home layout has been saved.');
            }
            if (form.id === 'productQuote') {
                const lines = Array.from(form.querySelectorAll('[data-line]')).map(row => ({ description: row.querySelector('[data-line-description]').value, quantity: Number(row.querySelector('[data-line-quantity]').value), unit_price: row.querySelector('[data-line-price]').value }));
                const result = await api('/quotes' + (form.dataset.key ? '/' + form.dataset.key + '/update' : ''), 'POST', { ...values, revision: Number(form.dataset.revision), lines });
                closeModal();
                await sales();
                await quoteDetail(result.id);
                toast('Quotation draft saved.');
            }
            if (form.id === 'productOrderInvoice') {
                await api('/sales-orders/' + form.dataset.key + '/invoice', 'POST', values);
                closeModal();
                await navigate('Finance');
                toast('Draft invoice created. Review it before issue.');
            }
            if (form.id === 'productTicket') {
                const result = await api('/tickets', 'POST', { ...values, source_message_id: form.dataset.source || null });
                closeModal();
                await navigate('Support');
                await ticketDetail(result.id);
                toast('Ticket created and linked.');
            }
            if (form.id === 'productTicketAssign') {
                await api('/tickets/' + form.dataset.key + '/assign', 'POST', { ...values, revision: Number(form.dataset.revision) });
                closeModal();
                await support();
                await ticketDetail(form.dataset.key);
                toast('Ticket owner updated.');
            }
            if (form.id === 'productTicketStatus') {
                await api('/tickets/' + form.dataset.key + '/status', 'POST', { ...values, revision: Number(form.dataset.revision) });
                closeModal();
                await support();
                await ticketDetail(form.dataset.key);
                toast('Ticket updated.');
            }
            if (form.id === 'productAppBuilder') {
                captureFields();
                const result = await api(editingApp ? '/custom-apps/' + editingApp.id + '/versions' : '/custom-apps', 'POST', { ...values, fields: builderFields, expected_version: editingApp?.current_version });
                closeModal();
                await customApp(result.id);
                toast('App form saved.');
            }
            if (form.id === 'productAppRecord') {
                const payload = {};
                formFields.forEach(f => { const value = values['custom_' + f.key]; payload[f.key] = value === '' ? null : f.type === 'boolean' ? value === 'true' : value; });
                await api('/custom-apps/' + form.dataset.key + '/records' + (form.dataset.record ? '/' + form.dataset.record + '/update' : ''), 'POST', { project_id: values.project_id, schema_version: Number(form.dataset.version), revision: Number(form.dataset.revision), payload });
                closeModal();
                await customApp(form.dataset.key);
                toast('Record saved.');
            }
            if (form.id === 'productBrainSearch') {
                brainQuery = String(values.query || '').trim();
                await brain();
            }
        }
        catch (error) {
            const holder = form.querySelector('.form-error');
            if (holder)
                holder.textContent = error.message;
            else
                toast(error.message);
        }
        finally {
            if (submit?.isConnected)
                submit.disabled = false;
        }
    });
    document.addEventListener('input', event => { const target = event.target; if (target.id === 'customerFilter')
        renderCustomers(target.value); if (target.id === 'collectionRange')
        updateScenario(); });
    document.addEventListener('dragstart', event => { const target = event.target.closest('[data-field-index]'); if (!target)
        return; captureFields(); dragField = Number(target.dataset.fieldIndex); event.dataTransfer?.setData('text/plain', String(dragField)); });
    document.addEventListener('dragover', event => { if (event.target.closest('[data-field-index]') && dragField >= 0)
        event.preventDefault(); });
    document.addEventListener('drop', event => { const target = event.target.closest('[data-field-index]'); if (!target || dragField < 0)
        return; event.preventDefault(); const next = Number(target.dataset.fieldIndex), [moved] = builderFields.splice(dragField, 1); builderFields.splice(next, 0, moved); dragField = -1; renderBuilder(); });
    document.addEventListener('dragend', () => { dragField = -1; });
})(NexusProduct || (NexusProduct = {}));
var NexusPurchasing;
(function (NexusPurchasing) {
    let requestRows = [], queue = 'all';
    let policies = null, selectedVersion = -1, draft = null, dragging = null;
    const labels = { manager: 'Manager or administrator', finance: 'Finance or administrator', admin: 'Administrator' };
    const e = (value) => escape(value);
    const button = (label, action, key = '', primary = false, extra = '') => `<button type="button" class="btn ${primary ? 'primary' : ''}" data-purchase="${action}" data-key="${e(key)}" ${extra}>${e(label)}</button>`;
    const templates = {
        simple: { name: 'Independent purchasing review', threshold: 500000, standard_stages: [{ label: 'Independent manager review', reviewer_role: 'manager' }], high_value_stages: [{ label: 'Independent manager review', reviewer_role: 'manager' }] },
        dual: { name: 'Two-person spend control', threshold: 500000, standard_stages: [{ label: 'Manager review', reviewer_role: 'manager' }], high_value_stages: [{ label: 'Procurement manager review', reviewer_role: 'manager' }, { label: 'Finance review', reviewer_role: 'finance' }] },
        governance: { name: 'High-value purchase governance', threshold: 2500000, standard_stages: [{ label: 'Manager review', reviewer_role: 'manager' }, { label: 'Finance review', reviewer_role: 'finance' }], high_value_stages: [{ label: 'Procurement manager review', reviewer_role: 'manager' }, { label: 'Finance review', reviewer_role: 'finance' }, { label: 'Final administrator review', reviewer_role: 'admin' }] }
    };
    async function render() {
        const org = state.me.organization.id;
        const data = await api('/purchasing-policy');
        if (state.page !== 'Approval policies' || state.me.organization.id !== org)
            return;
        policies = data;
        if (!data.versions.some(v => v.version === selectedVersion))
            selectedVersion = data.active_version;
        const selected = data.versions.find(v => v.version === selectedVersion);
        draft = structuredClone(selected.definition);
        document.querySelector('#app').innerHTML = `<button class="back-link" data-action="navigate" data-id="Apps">← Apps & workflows</button>` + heading('Purchasing, with the right checks.', 'Design the review. Keep every decision accountable.', button('Simulate saved version', 'simulate', String(selectedVersion))) + `<div class="policy-status-strip"><span class="metric-icon tone-teal">${nexusIcon('shield')}</span><div><b>${e(data.versions.find(v => v.version === data.active_version).definition.name)}</b><p>${data.active_version === 0 ? 'Default policy' : 'Active version ' + data.active_version} · Applies to new submissions only</p></div>${button('View version history', 'history')}</div><div class="policy-template-row">${[['simple', 'Simple review', 'One independent reviewer.'], ['dual', 'Two-person spend control', 'Finance review above a threshold.'], ['governance', 'High-value governance', 'Three distinct reviewers for larger purchases.']].map(([key, name, copy]) => `<button class="policy-template" data-purchase="template" data-key="${key}"><span class="metric-icon tone-${key === 'dual' ? 'teal' : key === 'governance' ? 'violet' : 'blue'}">${nexusIcon('layers')}</span><span><b>${name}</b><small>${copy}</small></span>${nexusIcon('arrow')}</button>`).join('')}</div><form id="purchasingDesigner"><div class="policy-editor-heading"><div><span class="record-kicker">EDITING ${selectedVersion === 0 ? 'DEFAULT TEMPLATE' : 'SAVED VERSION ' + selectedVersion}</span><h2>Build your approval route.</h2><p>Changes are saved as a new version. The live policy stays unchanged until activation.</p></div></div><div class="form-grid policy-name-grid">${field('policy_name', 'Policy name', 'text', draft.name, { full: true, maxlength: 120 })}</div><div class="policy-trigger card"><span class="metric-icon tone-blue">${nexusIcon('cart')}</span><div><small>WHEN</small><b>A purchase request is submitted</b><p>Use the requested quantity × estimated unit price.</p></div></div><div class="policy-connector" aria-hidden="true">↓</div><div class="policy-condition card"><span class="metric-icon tone-violet">${nexusIcon('layers')}</span><div><small>IF THE ESTIMATED TOTAL EXCEEDS</small><label class="sr-only" for="policyThreshold">Spend threshold</label><div class="policy-money-input"><span>${e(data.currency)}</span><input id="policyThreshold" name="threshold" type="number" min="0" max="1000000000" step=".01" required value="${(draft.threshold / 100).toFixed(2)}"></div></div></div><div class="policy-branch-arrows" aria-hidden="true"><span>↙</span><span>↘</span></div><div class="policy-branches"><section class="policy-branch"><div class="policy-branch-label"><span class="stage-dot stage-draft"></span><h3>At or below threshold</h3></div><p>Follow the standard review route.</p><div id="policy-standard_stages"></div>${button('Add review stage', 'add-stage', 'standard_stages')}</section><section class="policy-branch"><div class="policy-branch-label"><span class="stage-dot stage-accepted"></span><h3>Above threshold</h3></div><p>Apply additional review where it matters.</p><div id="policy-high_value_stages"></div>${button('Add review stage', 'add-stage', 'high_value_stages')}</section></div><div class="policy-guardrail"><span class="metric-icon tone-teal">${nexusIcon('lock')}</span><div><b>Guardrails stay in place.</b><p>The requester cannot review their own request. Each stage needs a different person who already has access to the project and source conversation. Approval never issues an order automatically.</p></div></div><div class="form-error" role="alert"></div><div class="actions form-footer"><button class="btn primary" type="submit">Save as new draft version</button></div></form><section class="card policy-versions" id="policyVersions"><div class="section-heading"><div><h2>Policy history</h2><p>Immutable definitions. Explicit activation. In-flight requests keep their original plan.</p></div></div>${data.versions.map(version => `<div class="policy-version-row"><span class="policy-version-number">${version.version === 0 ? 'D' : 'V' + version.version}</span><div><b>${e(version.definition.name)}</b><small>${version.version === 0 ? 'Built-in default' : dt(version.created_at)} · ${version.definition.standard_stages.length} / ${version.definition.high_value_stages.length} stages${data.active_version === version.version ? ' · Active' : ''}</small></div><div class="actions">${button('Edit', 'edit', String(version.version))}${button('Simulate', 'simulate', String(version.version))}${data.active_version !== version.version ? button(version.version < data.active_version ? 'Roll back' : 'Activate', 'activate', String(version.version), true) : '<span class="status status-accepted">Active</span>'}</div></div>`).join('')}</section>` + footer();
        renderStages();
    }
    NexusPurchasing.render = render;
    function capture() {
        if (!draft)
            return;
        const name = document.querySelector('#f-policy_name'), threshold = document.querySelector('#policyThreshold');
        if (name)
            draft.name = name.value;
        if (threshold)
            draft.threshold = Math.round(Number(threshold.value) * 100);
        for (const branch of ['standard_stages', 'high_value_stages']) {
            draft[branch] = Array.from(document.querySelectorAll('#policy-' + branch + ' .policy-stage')).map(row => ({ label: row.querySelector('[data-stage-label]').value, reviewer_role: row.querySelector('[data-stage-role]').value }));
        }
    }
    function renderStages() {
        for (const branch of ['standard_stages', 'high_value_stages']) {
            document.querySelector('#policy-' + branch).innerHTML = draft[branch].map((stage, index) => `<section class="card policy-stage" draggable="true" data-branch="${branch}" data-index="${index}"><div class="policy-stage-number">${index + 1}</div><div class="policy-stage-body"><label for="${branch}-label-${index}">Stage name</label><input id="${branch}-label-${index}" data-stage-label value="${e(stage.label)}" maxlength="100" required><label for="${branch}-role-${index}">Eligible reviewers</label><select id="${branch}-role-${index}" data-stage-role>${Object.entries(labels).map(([role, label]) => `<option value="${role}" ${stage.reviewer_role === role ? 'selected' : ''}>${label}</option>`).join('')}</select><small>A different person at every stage.</small><div class="policy-stage-tools">${button('↑', 'move-up', String(index), false, `data-branch="${branch}" aria-label="Move review stage up"`)}${button('↓', 'move-down', String(index), false, `data-branch="${branch}" aria-label="Move review stage down"`)}${button('Remove', 'remove-stage', String(index), false, `data-branch="${branch}"`)}</div></div></section>`).join('');
        }
    }
    function simulationForm(version) {
        const definition = policies.versions.find(v => v.version === version).definition;
        modal('Simulate purchasing approval', `<form id="purchasingSimulation" data-version="${version}"><span class="record-kicker">${version === 0 ? 'DEFAULT POLICY' : 'VERSION ' + version} · NO BUSINESS ACTIONS</span><h3 class="inline-title spacer-top">${e(definition.name)}</h3><div class="form-grid">${field('amount', 'Example purchase total', 'number', '7500.00', { min: 0, max: 1000000000, step: '.01' })}</div><div class="form-error" role="alert"></div><div class="actions form-footer"><button type="submit" class="btn primary">Run simulation</button></div></form>`);
    }
    function requestsHTML(rows) { requestRows = rows; return `<div id="purchaseQueue">${requestQueueHTML()}</div>`; }
    NexusPurchasing.requestsHTML = requestsHTML;
    function requestQueueHTML() {
        const pending = requestRows.filter(r => r.status === 'submitted'), mine = requestRows.filter(r => r.approval_plan?.can_review), approved = requestRows.filter(r => r.status === 'approved');
        const rows = requestRows.filter(r => queue === 'review' ? r.approval_plan?.can_review : queue === 'mine' ? r.created_by === state.me.user.user_id : queue === 'approved' ? r.status === 'approved' : true);
        return `<div class="commerce-metrics"><div class="card commerce-metric"><span class="metric-icon tone-amber">${nexusIcon('clock')}</span><div><small>Awaiting a decision</small><strong>${pending.length}</strong><p>Requests moving through saved review routes</p></div></div><div class="card commerce-metric"><span class="metric-icon tone-violet">${nexusIcon('shield')}</span><div><small>Your review queue</small><strong>${mine.length}</strong><p>Current stages you are eligible to review</p></div></div><div class="card commerce-metric"><span class="metric-icon tone-teal">${nexusIcon('cart')}</span><div><small>Approved, awaiting order</small><strong>${currency(approved.reduce((sum, r) => sum + r.quantity * r.unit_price, 0))}</strong><p>${approved.length} fully reviewed requests</p></div></div></div><div class="section-toolbar"><div class="segmented">${[['all', 'All requests'], ['review', 'Needs my review'], ['mine', 'My requests'], ['approved', 'Ready to order']].map(([key, label]) => button(label, 'queue', key, queue === key)).join('')}</div></div>${rows.length ? `<div class="card table-wrap"><table class="table"><thead><tr><th>REQUEST</th><th>REQUESTER</th><th>ESTIMATE</th><th>REVIEW PROGRESS</th><th>ACTION</th></tr></thead><tbody>${rows.map(r => { const plan = r.approval_plan, stage = plan?.pending_stage !== null && plan?.pending_stage !== undefined ? plan.stages[plan.pending_stage] : null; return `<tr data-export-id="${r.id}"><td><button class="record-title" data-action="req-detail" data-id="${r.id}">${e(r.item)}</button><small class="subtext">${e(r.project_name || 'Workspace-wide')}</small></td><td>${e(r.requester_name)}</td><td class="amount-cell">${currency(r.quantity * r.unit_price)}</td><td><span class="status status-${r.status}">${e(r.status)}</span>${r.status === 'submitted' && stage ? `<small class="subtext">Stage ${stage.index + 1}/${plan.stages.length} · ${e(stage.label)}</small>` : ''}</td><td><button class="btn" data-action="req-detail" data-id="${r.id}">Open request</button></td></tr>`; }).join('')}</tbody></table></div>` : `<section class="card product-empty"><span class="empty-illustration">${nexusIcon('checkCircle')}</span><h2>${queue === 'review' ? 'Your review queue is clear.' : 'No requests in this view.'}</h2><p>${queue === 'review' ? 'Requests appear here when the current stage matches your role and record access.' : 'Create a purchase request or choose another queue.'}</p>${canWrite() ? '<button class="btn primary" data-action="new-req">Create purchase request</button>' : ''}</section>`}`;
    }
    function progressHTML(plan) {
        if (!plan)
            return '';
        const historical = ['draft', 'rejected'].includes(plan.request_status);
        return `<section class="request-approval-plan"><div><span class="record-kicker">${historical ? 'PREVIOUS SUBMISSION' : 'SAVED APPROVAL ROUTE'}</span><h3>${e(plan.policy_name)}</h3><p>${plan.policy_version === 0 ? 'Default policy' : 'Version ' + plan.policy_version} · Submission ${plan.cycle || 'before upgrade'} · ${plan.stages.length} distinct reviewer${plan.stages.length === 1 ? '' : 's'}</p></div><ol>${plan.stages.map(stage => { const decision = plan.decisions.find(d => d.stage_index === stage.index); return `<li class="approval-state-${stage.state}"><span>${stage.state === 'approved' ? '✓' : stage.state === 'rejected' ? '×' : stage.index + 1}</span><div><b>${e(stage.label)}</b><small>${e(labels[stage.reviewer_role])}${decision ? ' · ' + e(decision.reviewer_name) + ' · ' + dt(decision.created_at) : ''}</small>${decision?.comment ? `<p>${e(decision.comment)}</p>` : ''}</div><em>${e(stage.state === 'pending' ? 'Current stage' : stage.state)}</em></li>`; }).join('')}</ol>${plan.reviewer_note && !plan.blocked_reason ? `<div class="notice">${e(plan.reviewer_note)}</div>` : ''}${plan.blocked_reason ? `<div class="policy-blocked">${nexusIcon('alert')}<span>${e(plan.blocked_reason)}</span></div>` : ''}${historical ? '<p class="form-note">A new submission uses the currently active policy and starts a fresh review cycle.</p>' : ''}</section>`;
    }
    NexusPurchasing.progressHTML = progressHTML;
    document.addEventListener('click', async (event) => {
        const target = event.target.closest('[data-purchase]');
        if (!target || target.disabled)
            return;
        const action = target.dataset.purchase, key = target.dataset.key || '';
        target.disabled = true;
        try {
            if (action === 'queue') {
                queue = key;
                const host = document.querySelector('#purchaseQueue');
                if (host)
                    host.innerHTML = requestQueueHTML();
                return;
            }
            if (action === 'template') {
                draft = structuredClone(templates[key]);
                document.querySelector('#f-policy_name').value = draft.name;
                document.querySelector('#policyThreshold').value = (draft.threshold / 100).toFixed(2);
                renderStages();
                toast('Template loaded. Save and simulate before activation.');
                return;
            }
            if (action === 'history') {
                document.querySelector('#policyVersions')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                return;
            }
            if (action === 'edit') {
                selectedVersion = Number(key);
                await render();
                document.querySelector('#purchasingDesigner')?.scrollIntoView({ behavior: 'smooth' });
                return;
            }
            if (action === 'simulate') {
                simulationForm(Number(key));
                return;
            }
            if (action === 'activate') {
                await api('/purchasing-policy/activate', 'POST', { version: Number(key), expected_active_version: policies.active_version });
                selectedVersion = Number(key);
                await render();
                toast('Policy activated for new submissions. Existing requests retain their saved plan.');
                return;
            }
            if (action === 'add-stage') {
                capture();
                const branch = key;
                if (draft[branch].length >= 5) {
                    toast('Each branch supports up to five review stages.');
                    return;
                }
                draft[branch].push({ label: 'Additional review', reviewer_role: 'manager' });
                renderStages();
                return;
            }
            if (['move-up', 'move-down', 'remove-stage'].includes(action)) {
                capture();
                const branch = target.dataset.branch, index = Number(key);
                if (action === 'remove-stage') {
                    if (draft[branch].length > 1)
                        draft[branch].splice(index, 1);
                    else
                        toast('Every branch needs at least one independent review.');
                }
                else {
                    const next = index + (action === 'move-up' ? -1 : 1);
                    if (next >= 0 && next < draft[branch].length)
                        [draft[branch][index], draft[branch][next]] = [draft[branch][next], draft[branch][index]];
                }
                renderStages();
                return;
            }
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
        if (!['purchasingDesigner', 'purchasingSimulation'].includes(form.id))
            return;
        event.preventDefault();
        const submit = form.querySelector('[type=submit]');
        submit.disabled = true;
        try {
            if (form.id === 'purchasingDesigner') {
                capture();
                const result = await api('/purchasing-policy/versions', 'POST', { definition: { ...draft, threshold: document.querySelector('#policyThreshold').value } });
                selectedVersion = result.versions[0].version;
                await render();
                toast('Draft version saved. Simulate it, then activate explicitly.');
            }
            else {
                const result = await api('/purchasing-policy/simulate', 'POST', { version: Number(form.dataset.version), amount: new FormData(form).get('amount') });
                modal('Simulation result', `<span class="record-kicker">NO REQUESTS CHANGED · NO APPROVALS CREATED</span><h3 class="inline-title spacer-top">${currency(result.amount)} → ${result.branch === 'high_value_stages' ? 'Above threshold' : 'At or below threshold'}</h3><ol class="policy-simulation-stages">${result.stages.map((stage, i) => `<li><span>${i + 1}</span><div><b>${e(stage.label)}</b><small>${e(labels[stage.reviewer_role])} · ${result.available_by_role[i]} active users match this role</small></div></li>`).join('')}</ol><p class="form-note">${e(result.note)} Every stage requires a different person. The requester is always excluded.</p>`);
            }
        }
        catch (error) {
            const holder = form.querySelector('.form-error');
            if (holder)
                holder.textContent = error.message;
            else
                toast(error.message);
        }
        finally {
            if (submit.isConnected)
                submit.disabled = false;
        }
    });
    document.addEventListener('dragstart', event => { const target = event.target.closest('.policy-stage'); if (!target)
        return; capture(); dragging = { branch: target.dataset.branch, index: Number(target.dataset.index) }; event.dataTransfer?.setData('text/plain', String(dragging.index)); });
    document.addEventListener('dragover', event => { const target = event.target.closest('.policy-stage'); if (target && dragging && target.dataset.branch === dragging.branch)
        event.preventDefault(); });
    document.addEventListener('drop', event => { const target = event.target.closest('.policy-stage'); if (!target || !dragging || target.dataset.branch !== dragging.branch)
        return; event.preventDefault(); const stages = draft[dragging.branch], [stage] = stages.splice(dragging.index, 1); stages.splice(Number(target.dataset.index), 0, stage); dragging = null; renderStages(); });
    document.addEventListener('dragend', () => { dragging = null; });
})(NexusPurchasing || (NexusPurchasing = {}));
