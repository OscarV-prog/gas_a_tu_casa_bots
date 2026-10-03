/**
 * Petroil Admin Backoffice - Single Page Application JS
 * Handles Live Metrics, Orders, Products CRUD, Drivers CRUD, Customers & Modals
 */

const API_BASE = '/api/admin';
let currentTab = 'dashboard';
let allVehiclesCache = [];
let allDriversCache = [];
let allProductsCache = [];
let allOrdersCache = [];
let allCustomersCache = [];
let allAgendaCache = [];
let currentAgendaFilter = 'all';
let agendaSearchQuery = '';

// -----------------------------------------------------------------------------
// Initialization
// -----------------------------------------------------------------------------

// -----------------------------------------------------------------------------
// Theme Management (Light / Dark Mode)
// -----------------------------------------------------------------------------

function initTheme() {
    const savedTheme = localStorage.getItem('petroil_admin_theme') || 'dark';
    applyTheme(savedTheme, false);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme, true);
    localStorage.setItem('petroil_admin_theme', newTheme);
}

function applyTheme(theme, showNotification = false) {
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);
    
    const themeIcons = document.querySelectorAll('.theme-icon');
    const themeTexts = document.querySelectorAll('.theme-text');
    
    if (theme === 'light') {
        themeIcons.forEach(el => el.textContent = '☀️');
        themeTexts.forEach(el => el.textContent = 'Modo Claro');
    } else {
        themeIcons.forEach(el => el.textContent = '🌙');
        themeTexts.forEach(el => el.textContent = 'Modo Oscuro');
    }

    if (showNotification && typeof showToast === 'function') {
        showToast(`Modo ${theme === 'dark' ? 'Oscuro 🌙' : 'Claro ☀️'} activado`, 'info');
    }
}

// -----------------------------------------------------------------------------
// Mobile & Tablet Sidebar Navigation
// -----------------------------------------------------------------------------

function initMobileSidebar() {
    const toggleBtn = document.getElementById('sidebar-toggle');
    const closeBtn = document.getElementById('sidebar-close');
    const backdrop = document.getElementById('sidebar-backdrop');
    const sidebar = document.querySelector('.sidebar');
    
    function openSidebar() {
        if (sidebar) sidebar.classList.add('open');
        if (backdrop) backdrop.classList.add('open');
        document.body.classList.add('sidebar-open');
    }
    
    function closeSidebar() {
        if (sidebar) sidebar.classList.remove('open');
        if (backdrop) backdrop.classList.remove('open');
        document.body.classList.remove('sidebar-open');
    }
    
    if (toggleBtn) toggleBtn.addEventListener('click', openSidebar);
    if (closeBtn) closeBtn.addEventListener('click', closeSidebar);
    if (backdrop) backdrop.addEventListener('click', closeSidebar);
    
    // Auto-close on nav item click when in mobile/tablet mode
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            if (window.innerWidth <= 1024) {
                closeSidebar();
            }
        });
    });

    // Close on ESC key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar && sidebar.classList.contains('open')) {
            closeSidebar();
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initMobileSidebar();
    initNavigation();
    initModals();
    loadDashboardMetrics();
    loadDashboardShifts();
    loadAgenda();
    loadOrders();
    loadRejections();
    loadProducts();
    loadVehicles();
    loadDrivers();
    loadCustomers();

    // Auto-refresh metrics, orders, rejections and drivers continually in near-real-time (2.5s)
    setInterval(() => {
        loadDashboardMetrics();
        loadDrivers(); // Keep fleet status always fresh in background
        if (currentTab === 'dashboard') {
            loadAgenda();
            loadOrders();
            loadDashboardShifts();
        } else if (currentTab === 'agenda') {
            loadAgenda();
        } else if (currentTab === 'orders') {
            loadOrders();
        } else if (currentTab === 'rejections') {
            loadRejections();
        } else if (currentTab === 'vehicles') {
            loadVehicles();
        }
    }, 2500);

    // Instant refresh whenever window regains focus or tab becomes visible
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            loadDashboardMetrics();
            loadDrivers();
            if (currentTab === 'dashboard' || currentTab === 'orders') loadOrders();
            if (currentTab === 'agenda' || currentTab === 'dashboard') loadAgenda();
        }
    });
    window.addEventListener('focus', () => {
        loadDashboardMetrics();
        loadDrivers();
        if (currentTab === 'dashboard' || currentTab === 'orders') loadOrders();
    });
});

// -----------------------------------------------------------------------------
// Navigation Tabs
// -----------------------------------------------------------------------------

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const targetTab = item.getAttribute('data-tab');
            switchTab(targetTab);
        });
    });
}

function switchTab(tabId) {
    currentTab = tabId;

    // Update nav links
    document.querySelectorAll('.nav-item').forEach(item => {
        if (item.getAttribute('data-tab') === tabId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });

    // Update section views
    document.querySelectorAll('.tab-section').forEach(sec => {
        if (sec.id === `tab-${tabId}`) {
            sec.classList.add('active');
        } else {
            sec.classList.remove('active');
        }
    });

    // Refresh tab data
    if (tabId === 'dashboard') {
        loadDashboardMetrics();
        loadDashboardShifts();
        loadAgenda();
        loadOrders();
    } else if (tabId === 'agenda') {
        loadAgenda();
    } else if (tabId === 'orders') {
        loadOrders();
    } else if (tabId === 'rejections') {
        loadRejections();
    } else if (tabId === 'products') {
        loadProducts();
    } else if (tabId === 'drivers') {
        loadDrivers();
    } else if (tabId === 'vehicles') {
        loadVehicles();
    } else if (tabId === 'customers') {
        loadCustomers();
    } else if (tabId === 'reports') {
        // Reports tab activated
    }
}

// -----------------------------------------------------------------------------
// Toast Notifications
// -----------------------------------------------------------------------------

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icon = type === 'success' ? '✅' : (type === 'error' ? '❌' : 'ℹ️');
    toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;
    
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function formatDateTime(dateStr) {
    if (!dateStr) return '';
    try {
        const cleanStr = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T');
        const d = new Date(cleanStr);
        if (isNaN(d.getTime())) return dateStr;

        const day = String(d.getDate()).padStart(2, '0');
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const year = d.getFullYear();
        let hours = d.getHours();
        const mins = String(d.getMinutes()).padStart(2, '0');
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12 || 12;
        const hStr = String(hours).padStart(2, '0');
        return `${day}/${month}/${year} ${hStr}:${mins} ${ampm}`;
    } catch {
        return dateStr;
    }
}

// -----------------------------------------------------------------------------
// 1. Dashboard & KPI Metrics
// -----------------------------------------------------------------------------

async function loadDashboardMetrics() {
    try {
        const res = await fetch(`${API_BASE}/metrics`);
        if (!res.ok) throw new Error('Error cargando métricas');
        const data = await res.json();

        // Update cards
        document.getElementById('kpi-active-orders').innerText = data.active_orders;
        if (document.getElementById('kpi-unresolved-rejections')) {
            document.getElementById('kpi-unresolved-rejections').innerText = data.unresolved_rejections || 0;
        }
        if (document.getElementById('kpi-drivers-available')) {
            document.getElementById('kpi-drivers-available').innerText = data.available_drivers || 0;
            document.getElementById('kpi-drivers-busy').innerText = data.en_entrega_drivers || 0;
            document.getElementById('kpi-drivers-off').innerText = data.fuera_servicio_drivers || 0;
        }
        document.getElementById('kpi-delivered-orders').innerText = data.delivered_orders;
        document.getElementById('kpi-total-revenue').innerText = `$${data.total_revenue.toLocaleString('es-MX', { minimumFractionDigits: 2 })}`;
        document.getElementById('kpi-cash-revenue').innerText = `$${data.revenue_cash.toLocaleString('es-MX', { minimumFractionDigits: 2 })}`;
        document.getElementById('kpi-card-revenue').innerText = `$${data.revenue_card.toLocaleString('es-MX', { minimumFractionDigits: 2 })}`;
        if (document.getElementById('kpi-csat-rating')) {
            const csat = (data.avg_satisfaction !== undefined && data.avg_satisfaction !== null) ? Number(data.avg_satisfaction).toFixed(1) : '5.0';
            const count = data.total_ratings || 0;
            document.getElementById('kpi-csat-rating').innerText = `${csat} ⭐`;
            document.getElementById('kpi-csat-count').innerText = count;
        }
        
        // Update badge in sidebar
        document.getElementById('badge-active-orders').innerText = data.active_orders;
        const rejBadge = document.getElementById('badge-rejections');
        if (rejBadge) {
            const rejs = data.unresolved_rejections || 0;
            rejBadge.innerText = rejs;
            rejBadge.style.display = rejs > 0 ? 'inline-block' : 'none';
        }
    } catch (err) {
        console.error('Error metrics:', err);
    }
}

async function loadDashboardShifts() {
    const tbody = document.getElementById('dashboard-shifts-table-body');
    if (!tbody) return;

    try {
        const res = await fetch(`${API_BASE}/shifts?limit=25`);
        if (!res.ok) throw new Error('Error al cargar turnos');
        const shifts = await res.json();

        if (!shifts || shifts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-muted); padding: 25px;">No hay registros de turnos o asistencia hoy aún.</td></tr>`;
            return;
        }

        tbody.innerHTML = shifts.map(s => {
            const isActive = s.status === 'active';
            const badge = isActive 
                ? `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); font-weight: 700;">🟢 EN TURNO</span>` 
                : `<span class="badge" style="background: rgba(255, 255, 255, 0.06); color: var(--text-muted);">⚪ FINALIZADO</span>`;

            const hIn = s.check_in_at ? (s.check_in_at.includes(' ') ? s.check_in_at.split(' ')[1].substring(0, 5) : s.check_in_at) : 'N/A';
            const hOut = s.check_out_at ? (s.check_out_at.includes(' ') ? s.check_out_at.split(' ')[1].substring(0, 5) : s.check_out_at) : '<span style="color: var(--accent-cyan); font-weight: 600;">⚡ En curso...</span>';

            let durText = '<span style="color: var(--accent-cyan); font-weight: 600;">⚡ En curso</span>';
            if (!isActive && s.duration_minutes !== null && s.duration_minutes !== undefined) {
                const mins = s.duration_minutes;
                const h = Math.floor(mins / 60);
                const m = mins % 60;
                durText = h > 0 ? `${h}h ${m}m` : `${m} min`;
            }

            const iniGas = s.initial_reading ? `<strong style="color: var(--accent-emerald);">${s.initial_reading}</strong>` : `<span style="color: var(--text-muted);">-</span>`;
            const finGas = s.final_reading ? `<strong style="color: var(--accent-rose);">${s.final_reading}</strong>` : `<span style="color: var(--text-muted);">-</span>`;

            return `
                <tr>
                    <td>
                        <div style="font-weight: 600; color: var(--text-heading);">${escapeQuote(s.driver_name || 'Chofer')}</div>
                        <div style="font-size: 0.76rem; color: var(--text-secondary);">${s.driver_phone || ''}</div>
                    </td>
                    <td><code>[${escapeQuote(s.vehicle_plate || 'S/P')}]</code></td>
                    <td>${badge}</td>
                    <td style="font-weight: 600; color: var(--accent-emerald);">🟢 ${hIn}</td>
                    <td style="font-weight: 600;">${hOut}</td>
                    <td style="font-weight: 700;">${durText}</td>
                    <td>${iniGas}</td>
                    <td>${finGas}</td>
                    <td>
                        <button class="btn btn-secondary btn-sm" onclick="openDriverTankReadingsModal('${s.driver_id}', '${escapeQuote(s.driver_name || '')}', '${escapeQuote(s.vehicle_plate || '')}')" title="Ver Historial y Lecturas">⏱️ Ver Detalle</button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Error dashboard shifts:', err);
    }
}

// -----------------------------------------------------------------------------
// 1.5. Scheduled Orders Agenda (Dashboard)
// -----------------------------------------------------------------------------

function formatMinutesToHours(minutes) {
    if (minutes <= 0) return '0 min';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h > 0 && m > 0) return `${h}h ${m}m`;
    if (h > 0) return `${h}h`;
    return `${m}m`;
}

function filterAgendaSearch() {
    const input = document.getElementById('agenda-search-input');
    agendaSearchQuery = input ? input.value.trim().toLowerCase() : '';
    renderAgendaTable();
}

async function loadAgenda() {
    try {
        const res = await fetch(`${API_BASE}/agenda`);
        if (!res.ok) throw new Error('Error al cargar agenda');
        const agenda = await res.json();
        allAgendaCache = agenda;

        const waitingCount = agenda.filter(x => !x.is_activated).length;
        const activeCount = agenda.filter(x => x.is_activated).length;
        const assignedCount = agenda.filter(x => x.driver_id).length;

        // Counters (Dashboard)
        const badgeCount = document.getElementById('agenda-badge-count');
        const countWaiting = document.getElementById('agenda-count-waiting');
        const countActive = document.getElementById('agenda-count-active');
        const countAssigned = document.getElementById('agenda-count-assigned');

        if (badgeCount) badgeCount.innerText = `${agenda.length} en agenda`;
        if (countWaiting) countWaiting.innerText = waitingCount;
        if (countActive) countActive.innerText = activeCount;
        if (countAssigned) countAssigned.innerText = assignedCount;

        // Counters (Dedicated Agenda Tab)
        const tabBadgeCount = document.getElementById('agenda-tab-badge-count');
        const tabCountWaiting = document.getElementById('agenda-tab-count-waiting');
        const tabCountActive = document.getElementById('agenda-tab-count-active');
        const tabCountAssigned = document.getElementById('agenda-tab-count-assigned');
        const tabCountTotal = document.getElementById('agenda-tab-count-total');

        if (tabBadgeCount) tabBadgeCount.innerText = `${agenda.length} en agenda`;
        if (tabCountWaiting) tabCountWaiting.innerText = waitingCount;
        if (tabCountActive) tabCountActive.innerText = activeCount;
        if (tabCountAssigned) tabCountAssigned.innerText = assignedCount;
        if (tabCountTotal) tabCountTotal.innerText = agenda.length;

        // Sidebar Navigation Badge
        const navBadge = document.getElementById('badge-agenda-orders');
        if (navBadge) {
            navBadge.innerText = agenda.length;
            navBadge.style.display = agenda.length > 0 ? 'inline-block' : 'none';
        }

        renderAgendaTable();
    } catch (err) {
        console.error('Error loadAgenda:', err);
    }
}

function filterAgenda(filterType) {
    currentAgendaFilter = filterType;

    // Update filter buttons on Dashboard card
    const btnAll = document.getElementById('agenda-filter-btn-all');
    const btnToday = document.getElementById('agenda-filter-btn-today');
    const btnTomorrow = document.getElementById('agenda-filter-btn-tomorrow');

    if (btnAll) btnAll.className = filterType === 'all' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
    if (btnToday) btnToday.className = filterType === 'today' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
    if (btnTomorrow) btnTomorrow.className = filterType === 'tomorrow' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';

    // Update filter buttons on Dedicated Tab
    const tabBtnAll = document.getElementById('agenda-tab-filter-btn-all');
    const tabBtnToday = document.getElementById('agenda-tab-filter-btn-today');
    const tabBtnTomorrow = document.getElementById('agenda-tab-filter-btn-tomorrow');

    if (tabBtnAll) tabBtnAll.className = filterType === 'all' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
    if (tabBtnToday) tabBtnToday.className = filterType === 'today' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';
    if (tabBtnTomorrow) tabBtnTomorrow.className = filterType === 'tomorrow' ? 'btn btn-sm btn-primary' : 'btn btn-sm btn-secondary';

    renderAgendaTable();
}

function renderAgendaTable() {
    const dashTbody = document.getElementById('dashboard-agenda-table-body');
    const fullTbody = document.getElementById('agenda-table-body');

    if (!dashTbody && !fullTbody) return;

    // Ordenar pedidos programados por hora pactada de entrega / deadline ascendente (más temprano primero)
    let items = [...allAgendaCache].sort((a, b) => {
        const timeA = a.scheduled_for ? new Date(a.scheduled_for).getTime() : 9999999999999;
        const timeB = b.scheduled_for ? new Date(b.scheduled_for).getTime() : 9999999999999;
        if (timeA !== timeB) return timeA - timeB;

        const getOrderNum = (item) => {
            const val = String(item.id || '');
            const digits = val.match(/\d+/g);
            return digits ? parseInt(digits[digits.length - 1], 10) : 0;
        };
        return getOrderNum(a) - getOrderNum(b);
    });
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const todayLocalStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;

    const tom = new Date(now);
    tom.setDate(tom.getDate() + 1);
    const tomLocalStr = `${tom.getFullYear()}-${pad(tom.getMonth() + 1)}-${pad(tom.getDate())}`;

    if (currentAgendaFilter === 'today') {
        items = items.filter(x => {
            if (x.deadline_display && x.deadline_display.toLowerCase().includes('hoy')) return true;
            if (x.scheduled_for) {
                const sDate = x.scheduled_for.slice(0, 10);
                if (sDate === todayLocalStr) return true;
                const d = new Date(x.scheduled_for);
                if (!isNaN(d.getTime())) {
                    const dStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                    if (dStr === todayLocalStr) return true;
                }
            }
            return false;
        });
    } else if (currentAgendaFilter === 'tomorrow') {
        items = items.filter(x => {
            if (x.deadline_display && x.deadline_display.toLowerCase().includes('mañana')) return true;
            if (x.scheduled_for) {
                const sDate = x.scheduled_for.slice(0, 10);
                if (sDate === tomLocalStr) return true;
                const d = new Date(x.scheduled_for);
                if (!isNaN(d.getTime())) {
                    const dStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
                    if (dStr === tomLocalStr) return true;
                }
            }
            return false;
        });
    }

    if (agendaSearchQuery) {
        items = items.filter(x =>
            String(x.id).includes(agendaSearchQuery) ||
            (x.customer_name && x.customer_name.toLowerCase().includes(agendaSearchQuery)) ||
            (x.customer_phone && x.customer_phone.toLowerCase().includes(agendaSearchQuery)) ||
            (x.delivery_address && x.delivery_address.toLowerCase().includes(agendaSearchQuery)) ||
            (x.delivery_schedule && x.delivery_schedule.toLowerCase().includes(agendaSearchQuery)) ||
            (x.driver_name && x.driver_name.toLowerCase().includes(agendaSearchQuery)) ||
            (x.notes && x.notes.toLowerCase().includes(agendaSearchQuery))
        );
    }

    let emptyFilterText = currentAgendaFilter === 'today' ? 'para hoy' : (currentAgendaFilter === 'tomorrow' ? 'para mañana' : '');
    if (agendaSearchQuery) emptyFilterText += ` con el término "${agendaSearchQuery}"`;

    if (!items || items.length === 0) {
        const emptyHtml = `
            <tr>
                <td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">
                    <div style="font-size: 1.6rem; margin-bottom: 6px;">🗓️</div>
                    No hay pedidos programados en la agenda ${emptyFilterText}.
                </td>
            </tr>
        `;
        if (dashTbody) dashTbody.innerHTML = emptyHtml;
        if (fullTbody) fullTbody.innerHTML = emptyHtml;
        return;
    }

    const rowsHtml = items.map(item => {
        const itemsSummary = (item.items || []).map(it => `${it.quantity}x ${it.product_name}`).join(', ');
        const payIcon = (item.payment_method || '').toLowerCase().includes('efectivo') ? '💵 Efectivo' : '💳 Terminal';

        // Countdown / timing badge
        let timeBadge = '';
        if (item.minutes_until_deadline > 0) {
            timeBadge = `<div style="font-size: 0.72rem; color: #60a5fa; font-weight: 600; margin-top: 3px;">🕒 Faltan ${formatMinutesToHours(item.minutes_until_deadline)}</div>`;
        } else {
            timeBadge = `<div style="font-size: 0.72rem; color: var(--accent-rose); font-weight: 700; margin-top: 3px;">⚠️ Horario en curso / cumplido</div>`;
        }

        // Activation badge (30-minute threshold)
        let activationHtml = '';
        if (item.is_activated) {
            activationHtml = `
                <span class="badge" style="background: rgba(16, 185, 129, 0.15); color: var(--accent-emerald); font-weight: 700;">🟢 ACTIVO EN TABLERO</span>
                <div style="font-size: 0.72rem; color: var(--text-secondary); margin-top: 2px;">En mesa de despacho activa</div>
            `;
        } else {
            const waitTime = item.minutes_until_activation > 0 ? `en ${formatMinutesToHours(item.minutes_until_activation)}` : 'en breve';
            activationHtml = `
                <span class="badge" style="background: rgba(59, 130, 246, 0.15); color: #60a5fa; font-weight: 600;">⏳ EN ESPERA</span>
                <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;" title="Se activa automáticamente 30 min antes">Llega al tablero ${waitTime} (${item.activation_display ? (item.activation_display.split(' a las ')[1] || '') : ''})</div>
            `;
        }

        // Driver / Vehicle
        let driverHtml = '';
        if (item.driver_name) {
            driverHtml = `
                <div style="font-weight: 600; color: var(--text-heading);">🛻 ${escapeQuote(item.driver_name)}</div>
                <div style="font-size: 0.74rem; color: var(--text-muted);">${item.driver_vehicle || ''} (${item.driver_phone || ''})</div>
            `;
        } else {
            driverHtml = `
                <button class="btn btn-secondary btn-sm" onclick="openReassignModal('${item.id}', '${escapeQuote(item.customer_name)}', null, '${item.status}')" title="Asignar chofer con anticipación">
                    🛻 Pre-asignar Chofer
                </button>
            `;
        }

        // Action buttons
        const advanceBtn = !item.is_activated ? `
            <button class="btn btn-sm btn-primary" onclick="activateScheduledOrderNow('${item.id}')" title="Pasar ahora a la mesa de pedidos activos sin esperar los 30 minutos">
                ⚡ Pasar a Pedidos Ya
            </button>
        ` : '';

        return `
            <tr>
                <td>
                    <div style="font-weight: 700; color: var(--text-heading); font-size: 0.92rem;">📅 ${item.deadline_display}</div>
                    ${timeBadge}
                </td>
                <td>${activationHtml}</td>
                <td>
                    <div style="font-weight: 700; color: var(--text-heading);">#${item.id} - ${escapeQuote(item.customer_name)}</div>
                    <div style="font-size: 0.76rem; color: var(--text-secondary);">${item.customer_phone}</div>
                </td>
                <td>
                    <div style="max-width: 220px; font-size: 0.82rem; line-height: 1.3;">${escapeQuote(item.delivery_address)}</div>
                    ${item.notes ? `<div style="font-size: 0.72rem; color: var(--accent-cyan); margin-top: 2px;">📝 ${escapeQuote(item.notes)}</div>` : ''}
                </td>
                <td>
                    <div style="font-size: 0.82rem; font-weight: 500;">${itemsSummary || 'Cilindro Gas LP'}</div>
                </td>
                <td>
                    <div style="font-weight: 700; color: var(--text-heading);">$${item.total_amount.toFixed(2)}</div>
                    <div style="font-size: 0.72rem; color: var(--text-secondary);">${payIcon}</div>
                </td>
                <td>${driverHtml}</td>
                <td>
                    <div style="display: flex; gap: 6px; align-items: center;">
                        ${advanceBtn}
                        <button class="btn btn-secondary btn-sm" onclick="openOrderDetailsModal('${item.id}')" title="Ver detalle completo">📋</button>
                        <button class="btn btn-secondary btn-sm" onclick="openRescheduleModal('${item.id}', '${escapeQuote(item.delivery_schedule || '')}', '${item.scheduled_for || ''}', '${escapeQuote(item.customer_name)}')" title="Reprogramar horario">✏️</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');

    if (dashTbody) dashTbody.innerHTML = rowsHtml;
    if (fullTbody) fullTbody.innerHTML = rowsHtml;
}

async function activateScheduledOrderNow(orderId) {
    if (!confirm(`¿Deseas activar y transferir de inmediato el pedido #${orderId} a la mesa de pedidos activos sin esperar los 30 minutos previos?`)) {
        return;
    }

    try {
        const res = await fetch(`${API_BASE}/orders/${orderId}/activate-now`, { method: 'POST' });
        if (!res.ok) throw new Error('Error al activar pedido');
        showToast(`Pedido #${orderId} activado y transferido a pedidos activos`, 'success');
        loadAgenda();
        loadOrders();
        loadDashboardMetrics();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

function openRescheduleModal(orderId, currentSchedule, currentDateTimeIso, customerName) {
    const modal = document.getElementById('modal-reschedule');
    if (!modal) return;

    document.getElementById('modal-reschedule-order-id').value = orderId;
    document.getElementById('modal-reschedule-info').innerHTML = `Modificando horario de entrega para pedido <strong>#${orderId}</strong> (${escapeQuote(customerName)}):`;
    
    // Set default datetime in picker
    const dtInput = document.getElementById('modal-reschedule-datetime');
    if (dtInput) {
        if (currentDateTimeIso && currentDateTimeIso.length >= 16) {
            dtInput.value = currentDateTimeIso.substring(0, 16);
        } else {
            const d = new Date();
            d.setHours(d.getHours() + 2);
            d.setMinutes(0);
            const pad = n => String(n).padStart(2, '0');
            dtInput.value = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        }
    }

    const textInput = document.getElementById('modal-reschedule-schedule-text');
    if (textInput) textInput.value = currentSchedule || '';

    modal.classList.add('open');
}

async function submitRescheduleOrder() {
    const orderId = document.getElementById('modal-reschedule-order-id').value;
    const dtValue = document.getElementById('modal-reschedule-datetime').value;
    let scheduleText = document.getElementById('modal-reschedule-schedule-text').value.trim();

    if (!dtValue) {
        showToast('Debes seleccionar la fecha y hora pactada', 'error');
        return;
    }

    if (!scheduleText) {
        scheduleText = dtValue.replace('T', ' ');
    }

    try {
        const res = await fetch(`${API_BASE}/orders/${orderId}/reschedule`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                delivery_schedule: scheduleText,
                scheduled_for: dtValue
            })
        });

        if (!res.ok) throw new Error('Error al reprogramar pedido');
        showToast(`Pedido #${orderId} reprogramado con éxito`, 'success');
        closeModals();
        loadAgenda();
        loadOrders();
        loadDashboardMetrics();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// -----------------------------------------------------------------------------
// Manual Order Creation (Torre de Control)
// -----------------------------------------------------------------------------

let createOrderItems = []; // Array de partidas: [{ product_id, quantity, unit_price }]

async function openCreateOrderModal() {
    const modal = document.getElementById('modal-create-order');
    if (!modal) return;

    // Resetear formulario
    const form = document.getElementById('form-create-order');
    if (form) form.reset();

    const schedType = document.getElementById('create-order-schedule-type');
    if (schedType) schedType.value = 'now';

    const dispMode = document.getElementById('create-order-dispatch-mode');
    if (dispMode) dispMode.value = 'none';

    toggleCreateOrderSchedule();
    toggleCreateOrderDispatch();

    // Poblar selector de choferes
    populateCreateOrderDrivers();

    // Asegurar que el catálogo de productos esté cargado
    if (!allProductsCache || allProductsCache.length === 0) {
        try {
            const res = await fetch(`${API_BASE}/products`);
            if (res.ok) {
                allProductsCache = await res.json();
            }
        } catch (e) {
            console.error('Error cargando catálogo para modal de pedido:', e);
        }
    }

    // Inicializar con 1 partida por defecto
    createOrderItems = [];
    addCreateOrderItemRow();

    modal.classList.add('open');
}

function populateCreateOrderDrivers() {
    const select = document.getElementById('create-order-driver-select');
    if (!select) return;

    if (!allDriversCache || allDriversCache.length === 0) {
        select.innerHTML = '<option value="">No hay choferes cargados aún</option>';
        return;
    }

    select.innerHTML = allDriversCache.map(d => {
        let opIcon = '🟢';
        let opLabel = 'Disponible';
        if (d.operational_status === 'en_entrega') {
            opIcon = '🟡';
            opLabel = `En Entrega (#${d.active_order_id || ''})`;
        } else if (d.operational_status === 'fuera_servicio') {
            opIcon = '🔴';
            opLabel = 'Fuera de Turno';
        }
        return `<option value="${d.id}">${opIcon} ${d.name} [${opLabel}] - ${d.vehicle_type} (${d.phone})</option>`;
    }).join('');
}

function addCreateOrderItemRow() {
    const defaultProduct = (allProductsCache && allProductsCache.length > 0) ? allProductsCache[0] : null;
    const defaultId = defaultProduct ? defaultProduct.id : 'cilindro-30kg';
    const defaultPrice = defaultProduct ? defaultProduct.price : 670.0;

    createOrderItems.push({
        product_id: defaultId,
        quantity: 1,
        unit_price: defaultPrice
    });

    renderCreateOrderItems();
}

function removeCreateOrderItemRow(index) {
    if (createOrderItems.length <= 1) {
        showToast('El pedido debe tener al menos un producto', 'warning');
        return;
    }
    createOrderItems.splice(index, 1);
    renderCreateOrderItems();
}

function renderCreateOrderItems() {
    const container = document.getElementById('create-order-items-list');
    if (!container) return;

    if (!allProductsCache || allProductsCache.length === 0) {
        container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.85rem; padding: 10px;">Cargando catálogo de productos...</div>';
        return;
    }

    container.innerHTML = createOrderItems.map((item, idx) => {
        const prodOptions = allProductsCache.map(p => {
            const isSel = p.id === item.product_id ? 'selected' : '';
            return `<option value="${p.id}" ${isSel}>${p.name} - $${p.price.toFixed(2)} ${p.currency}</option>`;
        }).join('');

        const subtotal = (item.quantity * item.unit_price).toFixed(2);
        const canDelete = createOrderItems.length > 1;

        return `
            <div style="display: grid; grid-template-columns: 2fr 1fr 1fr auto; gap: 10px; align-items: center; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); padding: 10px 12px; border-radius: var(--radius-sm);">
                <div>
                    <label style="font-size: 0.72rem; color: var(--text-muted); display: block; margin-bottom: 2px;">Producto / Presentación</label>
                    <select class="form-control" style="font-size: 0.85rem; padding: 6px 10px;" onchange="onItemProductChange(${idx}, this.value)">
                        ${prodOptions}
                    </select>
                </div>
                <div>
                    <label style="font-size: 0.72rem; color: var(--text-muted); display: block; margin-bottom: 2px;">Cantidad (Pzas/L)</label>
                    <input type="number" min="0.1" step="any" value="${item.quantity}" class="form-control" style="font-size: 0.85rem; padding: 6px 10px;" oninput="onItemQuantityChange(${idx}, this.value)">
                </div>
                <div style="text-align: right;">
                    <label style="font-size: 0.72rem; color: var(--text-muted); display: block; margin-bottom: 2px;">Subtotal</label>
                    <div style="font-weight: 700; color: var(--accent-emerald); font-size: 0.95rem; padding-top: 4px;">$${subtotal}</div>
                </div>
                <div>
                    <label style="font-size: 0.72rem; visibility: hidden; display: block; margin-bottom: 2px;">X</label>
                    <button type="button" class="btn btn-secondary btn-sm" style="padding: 6px 10px; color: ${canDelete ? 'var(--accent-rose)' : 'var(--text-muted)'};" onclick="removeCreateOrderItemRow(${idx})" ${canDelete ? '' : 'disabled'} title="Eliminar partida">
                        🗑️
                    </button>
                </div>
            </div>
        `;
    }).join('');

    updateCreateOrderTotal();
}

function onItemProductChange(index, productId) {
    const prod = (allProductsCache || []).find(p => p.id === productId);
    if (prod && createOrderItems[index]) {
        createOrderItems[index].product_id = prod.id;
        createOrderItems[index].unit_price = prod.price;
        renderCreateOrderItems();
    }
}

function onItemQuantityChange(index, qtyStr) {
    const qty = parseFloat(qtyStr);
    if (!isNaN(qty) && qty > 0 && createOrderItems[index]) {
        createOrderItems[index].quantity = qty;
        updateCreateOrderTotal();
        const container = document.getElementById('create-order-items-list');
        if (container && container.children[index]) {
            const subtotalDiv = container.children[index].querySelector('div:nth-child(3) div');
            if (subtotalDiv) {
                subtotalDiv.innerText = `$${(qty * createOrderItems[index].unit_price).toFixed(2)}`;
            }
        }
    }
}

function updateCreateOrderTotal() {
    let total = 0;
    createOrderItems.forEach(it => {
        total += (it.quantity || 0) * (it.unit_price || 0);
    });
    const display = document.getElementById('create-order-total-display');
    if (display) {
        display.innerText = `$${total.toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} MXN`;
    }
}

function toggleCreateOrderSchedule() {
    const type = document.getElementById('create-order-schedule-type')?.value;
    const schedGroup = document.getElementById('create-order-scheduled-group');
    const dtInput = document.getElementById('create-order-scheduled-for');
    if (schedGroup) {
        if (type === 'scheduled') {
            schedGroup.style.display = 'block';
            if (dtInput && !dtInput.value) {
                const d = new Date();
                d.setHours(d.getHours() + 2);
                d.setMinutes(0);
                const pad = n => String(n).padStart(2, '0');
                dtInput.value = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
            }
        } else {
            schedGroup.style.display = 'none';
        }
    }
}

function toggleCreateOrderDispatch() {
    const mode = document.getElementById('create-order-dispatch-mode')?.value;
    const driverGroup = document.getElementById('create-order-driver-group');
    if (driverGroup) {
        driverGroup.style.display = mode === 'driver' ? 'block' : 'none';
    }
}

async function submitCreateOrderForm() {
    const name = document.getElementById('create-order-customer-name')?.value?.trim();
    const phone = document.getElementById('create-order-customer-phone')?.value?.trim();
    const address = document.getElementById('create-order-address')?.value?.trim();
    const notes = document.getElementById('create-order-notes')?.value?.trim() || '';
    const scheduleType = document.getElementById('create-order-schedule-type')?.value;
    const paymentMethod = document.getElementById('create-order-payment-method')?.value || 'Efectivo';
    const dispatchMode = document.getElementById('create-order-dispatch-mode')?.value || 'none';
    const driverSelect = document.getElementById('create-order-driver-select');
    const rawDriverVal = (dispatchMode === 'driver' && driverSelect) ? driverSelect.value?.trim() : null;
    const driverId = rawDriverVal ? ((!isNaN(rawDriverVal) && !rawDriverVal.includes('-')) ? parseInt(rawDriverVal, 10) : rawDriverVal) : null;

    if (!name || !phone || !address) {
        showToast('Nombre, teléfono y dirección son obligatorios', 'error');
        return;
    }

    if (!createOrderItems || createOrderItems.length === 0) {
        showToast('Debes agregar al menos un producto al pedido', 'error');
        return;
    }

    let deliverySchedule = 'Lo antes posible';
    let scheduledFor = null;
    if (scheduleType === 'scheduled') {
        scheduledFor = document.getElementById('create-order-scheduled-for')?.value;
        const schedText = document.getElementById('create-order-schedule-text')?.value?.trim();
        if (!scheduledFor) {
            showToast('Selecciona la fecha y hora programada', 'error');
            return;
        }
        deliverySchedule = schedText || scheduledFor.replace('T', ' ');
    }

    if (dispatchMode === 'driver' && !driverId) {
        showToast('Selecciona un chofer válido de la lista', 'error');
        return;
    }

    const payload = {
        customer_name: name,
        customer_phone: phone,
        delivery_address: address,
        delivery_schedule: deliverySchedule,
        scheduled_for: scheduledFor,
        payment_method: paymentMethod,
        notes: notes,
        dispatch_mode: dispatchMode,
        driver_id: driverId,
        items: createOrderItems.map(it => {
            const prod = (allProductsCache || []).find(p => p.id === it.product_id);
            return {
                product_id: it.product_id,
                product_name: prod ? prod.name : it.product_id,
                quantity: it.quantity,
                unit_price: it.unit_price,
            };
        }),
    };

    const submitBtn = document.getElementById('btn-submit-create-order');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerText = '⏳ Creando y despachando...';
    }

    try {
        const res = await fetch(`${API_BASE}/orders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({ detail: 'Error al crear pedido' }));
            throw new Error(errData.detail || 'Error en el servidor');
        }

        const data = await res.json();
        const createdOrder = data.order || {};
        showToast(`🎉 ¡Pedido #${createdOrder.id} creado con éxito! ($${(createdOrder.total_amount || 0).toFixed(2)})`, 'success');

        closeModals();
        loadDashboardMetrics();
        loadOrders();
        loadAgenda();
        loadCustomers();
    } catch (err) {
        showToast(`Error al levantar pedido: ${err.message}`, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerText = '🚀 Levantar y Crear Pedido';
        }
    }
}

// -----------------------------------------------------------------------------
// 2. Orders Management
// -----------------------------------------------------------------------------

async function loadOrders() {
    const statusFilter = document.getElementById('orders-filter-status')?.value || 'all';
    const searchQuery = document.getElementById('orders-search-input')?.value || '';

    try {
        const url = new URL(`${window.location.origin}${API_BASE}/orders`);
        if (statusFilter && statusFilter !== 'all') url.searchParams.append('status', statusFilter);
        if (searchQuery) url.searchParams.append('search', searchQuery);

        const res = await fetch(url.toString());
        if (!res.ok) throw new Error('Error al obtener pedidos');
        const orders = await res.json();
        allOrdersCache = orders;

        renderOrdersTable(orders, 'orders-table-body');
        renderOrdersTable(orders.slice(0, 6), 'dashboard-recent-orders-body');
    } catch (err) {
        console.error('Error orders:', err);
    }
}

function renderOrdersTable(orders, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    if (orders.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">No se encontraron pedidos.</td></tr>`;
        return;
    }

    tbody.innerHTML = orders.map(ord => {
        const itemsSummary = (ord.items || []).map(it => `${it.quantity}x ${it.product_name}`).join(', ');
        const payIcon = (ord.payment_method || '').toLowerCase().includes('efectivo') ? '💵 Efectivo' : '💳 Terminal';
        
        const rawStatus = String(ord.status || 'confirmed').toLowerCase().trim();
        const normStatus = (rawStatus === 'en_ruta' || rawStatus === 'en_reparto' || rawStatus === 'en_camino' || rawStatus === 'in_route') ? 'in_route' 
            : (rawStatus === 'entregado' || rawStatus === 'delivered' ? 'delivered' 
            : (rawStatus === 'cancelado' || rawStatus === 'cancelled' ? 'cancelled' 
            : (rawStatus === 'asignado' || rawStatus === 'assigned' ? 'assigned' 
            : (rawStatus === 'programado' || rawStatus === 'scheduled' ? 'scheduled' 
            : (rawStatus === 'rejected_by_driver' || rawStatus === 'rechazado' ? 'rejected_by_driver'
            : (rawStatus === 'pendiente' || rawStatus === 'pending' || rawStatus === 'confirmado' ? 'confirmed' : rawStatus))))));

        let statusBadge = `<span class="badge badge-${normStatus}">${getStatusLabel(ord.status)}</span>`;
        if (normStatus === 'rejected_by_driver' && ord.rejection_reason) {
            statusBadge += `<div class="rejection-reason-tag">⚠️ ${escapeQuote(ord.rejection_reason)}</div>`;
        }

        let driverDisplay = '';
        if (normStatus === 'cancelled') {
            driverDisplay = `<span style="color: var(--text-muted); font-size: 0.82rem; font-style: italic;">⛔ Cancelado</span>`;
        } else if (normStatus === 'delivered') {
            const ratingHtml = ord.driver_rating ? `
                <div style="color: var(--accent-amber); font-size: 0.76rem; font-weight: 700; margin-top: 3px;" title="${ord.rating_comment ? escapeQuote(ord.rating_comment) : ''}">
                    ⭐ ${ord.driver_rating}/5 ${ord.rating_tag ? `• ${ord.rating_tag}` : ''}
                </div>
            ` : '';
            driverDisplay = ord.driver_name ? `
                <div style="font-weight: 600;">🛻 ${escapeQuote(ord.driver_name)}</div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">${ord.driver_vehicle || ''} (${ord.driver_phone || ''})</div>
                ${ratingHtml}
            ` : `<span style="color: var(--accent-emerald); font-size: 0.82rem;">✅ Entregado</span>`;
        } else if (ord.driver_id && ord.driver_name) {
            const isDelivering = normStatus === 'in_route';
            const tripTag = isDelivering ? `<span style="color: var(--accent-amber); font-size: 0.74rem; font-weight: 700;">🚚 En Reparto</span>` : '';
            driverDisplay = `
                <div style="font-weight: 600;">🛻 ${escapeQuote(ord.driver_name)}</div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">${ord.driver_vehicle || ''} (${ord.driver_phone || ''})</div>
                ${tripTag}
            `;
        } else {
            const btnColor = normStatus === 'rejected_by_driver' ? 'btn-danger' : 'btn-primary';
            const btnText = normStatus === 'rejected_by_driver' ? '🔄 Reasignar' : '🛻 Asignar Chofer';
            driverDisplay = `
                <button class="btn ${btnColor} btn-sm" onclick="openReassignModal('${ord.id}', '${escapeQuote(ord.customer_name)}', null, '${normStatus}')">
                    ${btnText}
                </button>
            `;
        }

        let gmapsBtn = '';
        if (ord.delivery_lat && ord.delivery_lng) {
            gmapsBtn = `<a href="https://www.google.com/maps/dir/?api=1&destination=${ord.delivery_lat},${ord.delivery_lng}" target="_blank" class="btn btn-secondary btn-sm" title="Ver en Google Maps">🗺️</a>`;
        } else if (ord.delivery_address) {
            const clean = encodeURIComponent(ord.delivery_address + ', Mazatlán, Sinaloa');
            gmapsBtn = `<a href="https://www.google.com/maps/dir/?api=1&destination=${clean}" target="_blank" class="btn btn-secondary btn-sm" title="Ver en Google Maps">🗺️</a>`;
        }

        let reassignActionBtn = '';
        if (normStatus !== 'cancelled' && normStatus !== 'delivered') {
            reassignActionBtn = `
                <button class="btn btn-secondary btn-sm" onclick="openReassignModal('${ord.id}', '${escapeQuote(ord.customer_name)}', ${ord.driver_id ? `'${ord.driver_id}'` : 'null'}, '${normStatus}')" title="Asignar / Reasignar chofer">🛻</button>
            `;
        }

        return `
            <tr>
                <td>
                    <div style="font-weight: 700; font-size: 0.95rem; color: var(--text-heading);">#${ord.id}</div>
                    <div style="font-size: 0.72rem; color: var(--accent-cyan); margin-top: 3px; white-space: nowrap; font-weight: 500;" title="Fecha y hora de registro del pedido">
                        📅 ${formatDateTime(ord.created_at)}
                    </div>
                </td>
                <td>
                    <div style="font-weight: 600; color: var(--text-heading);">${escapeQuote(ord.customer_name)}</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">${ord.customer_phone || ''}</div>
                </td>
                <td>
                    <div style="max-width: 240px; font-size: 0.82rem; line-height: 1.3;">${escapeQuote(ord.delivery_address)}</div>
                    ${ord.notes ? `<div style="font-size: 0.72rem; color: var(--accent-cyan); margin-top: 2px;">📝 ${escapeQuote(ord.notes)}</div>` : ''}
                </td>
                <td>
                    <div style="font-size: 0.82rem; font-weight: 500;">${itemsSummary || 'Cilindro Gas LP'}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">🕒 ${ord.delivery_schedule}</div>
                </td>
                <td>
                    <div style="font-weight: 700; color: var(--text-heading);">$${(Number(ord.total_amount) || 0).toFixed(2)}</div>
                    <div style="font-size: 0.72rem; color: var(--text-secondary);">${payIcon}</div>
                </td>
                <td>${driverDisplay}</td>
                <td>${statusBadge}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-secondary btn-sm" onclick="openOrderDetailsModal('${ord.id}')" title="Ver detalle completo">📋</button>
                        ${gmapsBtn}
                        ${reassignActionBtn}
                        <button class="btn btn-secondary btn-sm" onclick="openStatusModal('${ord.id}', '${normStatus}', '${escapeQuote(ord.customer_name)}')" title="Cambiar estado">⚙️</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function getStatusLabel(status) {
    if (!status) return '🔵 Por Asignar';
    const s = String(status).toLowerCase().trim().replace(/ /g, '_');
    const map = {
        'confirmed': '🔵 Por Asignar',
        'pending': '🔵 Por Asignar',
        'pendiente': '🔵 Por Asignar',
        'confirmado': '🔵 Por Asignar',
        'assigned': '🟣 Asignado',
        'asignado': '🟣 Asignado',
        'in_route': '🚚 En Reparto',
        'en_ruta': '🚚 En Reparto',
        'en_reparto': '🚚 En Reparto',
        'en_camino': '🚚 En Reparto',
        'delivered': '🟢 Entregado',
        'entregado': '🟢 Entregado',
        'cancelled': '🔴 Cancelado',
        'cancelado': '🔴 Cancelado',
        'scheduled': '🔷 Programado',
        'programado': '🔷 Programado',
        'rejected_by_driver': '⚠️ Rechazado por Chofer',
        'rechazado': '⚠️ Rechazado por Chofer'
    };
    return map[s] || status;
}

function escapeQuote(str) {
    if (!str) return '';
    return str.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// -----------------------------------------------------------------------------
// 2b. Rejections & Incidents Management
// -----------------------------------------------------------------------------

async function loadRejections() {
    try {
        const res = await fetch(`${API_BASE}/rejections`);
        if (!res.ok) throw new Error('Error al obtener incidencias');
        const rejections = await res.json();
        renderRejectionsTable(rejections);
    } catch (err) {
        console.error('Error rejections:', err);
    }
}

function renderRejectionsTable(rejections) {
    const tbody = document.getElementById('rejections-table-body');
    if (!tbody) return;

    if (rejections.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 36px;">✨ No hay incidencias ni pedidos rechazados registrados. ¡Todo en orden!</td></tr>`;
        return;
    }

    tbody.innerHTML = rejections.map(r => {
        const dateStr = r.created_at ? new Date(r.created_at).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' }) : 'Reciente';
        const statusBadge = r.is_resolved 
            ? `<span class="badge badge-delivered">🟢 Resuelto / Reasignado</span>` 
            : `<span class="badge badge-rejected_by_driver">🔴 Pendiente de Reasignar</span>`;

        const reassignBtn = `<button class="btn btn-primary btn-sm" onclick="openReassignModal(${r.order_id}, '${escapeQuote(r.customer_name || '')}', null)" title="Reasignar a otro chofer">🔄 Reasignar Chofer</button>`;

        return `
            <tr>
                <td><strong>#${r.order_id}</strong></td>
                <td>
                    <div style="font-weight: 600; color: var(--text-heading);">${r.customer_name || 'Cliente'}</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">${r.customer_phone || ''}</div>
                </td>
                <td>
                    <div style="max-width: 220px; font-size: 0.82rem;">${r.delivery_address || 'Sin dirección'}</div>
                </td>
                <td>
                    <div style="font-weight: 600; color: var(--accent-rose);">🛻 ${r.driver_name}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${r.driver_vehicle_plate ? `Unidad [${r.driver_vehicle_plate}]` : ''} (${r.driver_phone || ''})</div>
                </td>
                <td>
                    <div class="rejection-reason-tag">
                        ⚠️ <strong>${r.reason}</strong>
                    </div>
                </td>
                <td>
                    <div style="font-size: 0.8rem; color: var(--text-secondary);">🕒 ${dateStr}</div>
                </td>
                <td>${statusBadge}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        ${reassignBtn}
                        <button class="btn btn-secondary btn-sm" onclick="openOrderDetailsModal('${r.order_id}')" title="Ver pedido">📋</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function openOrderDetailsModal(orderId) {
    const ord = allOrdersCache.find(o => String(o.id) === String(orderId));
    if (!ord) return;

    document.getElementById('modal-details-title').innerText = `📋 Detalle del Pedido #${ord.id}`;
    
    const itemsHtml = ord.items && ord.items.length > 0 
        ? ord.items.map(it => `
            <tr>
                <td style="padding: 6px 10px;">${it.product_name}</td>
                <td style="padding: 6px 10px; text-align: center;">${it.quantity}</td>
                <td style="padding: 6px 10px; text-align: right;">$${it.unit_price.toFixed(2)}</td>
                <td style="padding: 6px 10px; text-align: right; font-weight: 700;">$${it.subtotal.toFixed(2)}</td>
            </tr>
        `).join('')
        : `<tr><td colspan="4" style="padding: 8px; text-align: center;">Sin desglose de items</td></tr>`;

    let mapsLinks = '';
    if (ord.delivery_lat && ord.delivery_lng) {
        mapsLinks = `
            <a href="https://www.google.com/maps/dir/?api=1&destination=${ord.delivery_lat},${ord.delivery_lng}" target="_blank" class="btn btn-secondary btn-sm" style="margin-right: 8px;">🗺️ Google Maps</a>
            <a href="https://waze.com/ul?ll=${ord.delivery_lat},${ord.delivery_lng}&navigate=yes" target="_blank" class="btn btn-secondary btn-sm">🚗 Waze</a>
        `;
    } else {
        const clean = encodeURIComponent(ord.delivery_address + ', Mazatlán, Sinaloa');
        mapsLinks = `
            <a href="https://www.google.com/maps/dir/?api=1&destination=${clean}" target="_blank" class="btn btn-secondary btn-sm" style="margin-right: 8px;">🗺️ Google Maps</a>
            <a href="https://waze.com/ul?q=${clean}&navigate=yes" target="_blank" class="btn btn-secondary btn-sm">🚗 Waze</a>
        `;
    }

    document.getElementById('modal-details-content').innerHTML = `
        <div style="background: rgba(14, 23, 42, 0.6); padding: 14px; border-radius: var(--radius-md); margin-bottom: 16px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-size: 1.1rem; font-weight: 700; color: var(--text-heading);">👤 ${ord.customer_name}</span>
                <span class="badge badge-${ord.status}">${getStatusLabel(ord.status)}</span>
            </div>
            <div><strong>📅 Fecha y Hora de Pedido:</strong> <span style="color: var(--accent-cyan); font-weight: 600;">${formatDateTime(ord.created_at)}</span></div>
            ${ord.delivered_at ? `<div><strong>🏁 Fecha y Hora de Entrega:</strong> <span style="color: var(--accent-emerald); font-weight: 600;">${formatDateTime(ord.delivered_at)}</span></div>` : ''}
            <div><strong>📞 Teléfono:</strong> ${ord.customer_phone}</div>
            <div><strong>📍 Dirección:</strong> ${ord.delivery_address}</div>
            ${ord.notes ? `<div><strong>📝 Referencias:</strong> ${ord.notes}</div>` : ''}
            <div><strong>🕒 Horario de Entrega:</strong> ${ord.delivery_schedule}</div>
            <div><strong>💳 Forma de Pago:</strong> ${ord.payment_method}</div>
            <div><strong>📱 Canal:</strong> ${ord.channel || 'Telegram'}</div>
        </div>

        <div style="margin-bottom: 16px;">
            <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 8px;">📦 Productos del Pedido:</h4>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.85rem; background: var(--bg-card); border-radius: var(--radius-sm); overflow: hidden;">
                <thead>
                    <tr style="background: rgba(255,255,255,0.05); text-align: left;">
                        <th style="padding: 6px 10px;">Producto</th>
                        <th style="padding: 6px 10px; text-align: center;">Cant.</th>
                        <th style="padding: 6px 10px; text-align: right;">Unitario</th>
                        <th style="padding: 6px 10px; text-align: right;">Subtotal</th>
                    </tr>
                </thead>
                <tbody>
                    ${itemsHtml}
                </tbody>
                <tfoot>
                    <tr style="border-top: 1px solid var(--border-color);">
                        <td colspan="3" style="padding: 8px 10px; text-align: right; font-weight: 700;">TOTAL:</td>
                        <td style="padding: 8px 10px; text-align: right; font-weight: 800; color: var(--accent-emerald); font-size: 1.1rem;">$${ord.total_amount.toFixed(2)} MXN</td>
                    </tr>
                </tfoot>
            </table>
        </div>

        <div style="background: rgba(14, 23, 42, 0.6); padding: 14px; border-radius: var(--radius-md); margin-bottom: 16px;">
            <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 6px;">🛻 Chofer Asignado:</h4>
            ${ord.status === 'cancelled' ? `
                <div style="color: var(--accent-rose); font-style: italic; display: flex; align-items: center; gap: 6px;">
                    <span>⛔</span> <strong>Pedido cancelado</strong> (no requiere asignación de chofer).
                </div>
            ` : ord.driver_name ? `
                <div><strong>Nombre:</strong> ${ord.driver_name}</div>
                <div><strong>Unidad:</strong> ${ord.driver_vehicle || 'Camioneta'} (${ord.driver_phone || ''})</div>
                ${ord.assigned_at ? `<div><strong>Asignado el:</strong> ${new Date(ord.assigned_at).toLocaleString()}</div>` : ''}
            ` : `<div style="color: var(--accent-amber); font-style: italic;">No hay chofer asignado aún a este pedido.</div>`}
        </div>

        <div>
            <h4 style="font-size: 0.95rem; font-weight: 700; margin-bottom: 8px;">🚀 Navegación y Rutas:</h4>
            ${mapsLinks}
        </div>
    `;

    document.getElementById('modal-details').classList.add('open');
}

// -----------------------------------------------------------------------------
// 3. Products Catalog Management (CRUD)
// -----------------------------------------------------------------------------

async function loadProducts() {
    try {
        const res = await fetch(`${API_BASE}/products`);
        if (!res.ok) throw new Error('Error al cargar productos');
        const products = await res.json();
        allProductsCache = products;
        renderProductsGrid(products);
    } catch (err) {
        console.error('Error products:', err);
    }
}

function renderProductsGrid(products) {
    const container = document.getElementById('products-grid-container');
    if (!container) return;

    if (products.length === 0) {
        container.innerHTML = `<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); padding: 40px;">No hay productos en el catálogo.</div>`;
        return;
    }

    container.innerHTML = products.map(p => {
        const stockBadge = p.in_stock 
            ? `<span class="badge badge-available">Disponible</span>` 
            : `<span class="badge badge-cancelled">Agotado</span>`;
        const promoBadge = p.is_promoted 
            ? `<span class="badge badge-scheduled">🌟 Destacado</span>` 
            : '';

        return `
            <div class="kpi-card" style="display: flex; flex-direction: column; justify-content: space-between;">
                <div>
                    <div class="kpi-header">
                        <span class="kpi-title">${p.category || 'Gas LP'}</span>
                        <div style="display: flex; gap: 4px;">${stockBadge} ${promoBadge}</div>
                    </div>
                    <h3 style="font-size: 1.15rem; font-weight: 700; color: var(--text-heading); margin: 10px 0 6px 0;">${p.name}</h3>
                    <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 16px; min-height: 38px;">${p.description || 'Sin descripción'}</p>
                    <div style="font-size: 1.6rem; font-weight: 800; color: var(--accent-emerald);">$${p.price.toFixed(2)} <span style="font-size: 0.85rem; color: var(--text-muted);">${p.currency}</span></div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">Código: <code>${p.id}</code></div>
                </div>
                <div style="display: flex; gap: 8px; margin-top: 20px; border-top: 1px solid var(--border-color); padding-top: 14px;">
                    <button class="btn btn-secondary btn-sm" style="flex: 1;" onclick="openEditProductModal('${p.id}')">✏️ Editar</button>
                    <button class="btn btn-danger btn-sm" onclick="confirmDeleteProduct('${p.id}', '${p.name}')">🗑️</button>
                </div>
            </div>
        `;
    }).join('');
}

function openAddProductModal() {
    document.getElementById('modal-product-title').innerText = '➕ Nuevo Producto';
    document.getElementById('form-product-id').value = '';
    document.getElementById('form-product-id').disabled = false;
    document.getElementById('form-product-name').value = '';
    document.getElementById('form-product-description').value = '';
    document.getElementById('form-product-price').value = '';
    document.getElementById('form-product-category').value = 'Cilindros';
    document.getElementById('form-product-stock').checked = true;
    document.getElementById('form-product-promoted').checked = false;

    document.getElementById('modal-product').classList.add('open');
}

async function openEditProductModal(productId) {
    try {
        const res = await fetch(`${API_BASE}/products`);
        const products = await res.json();
        const p = products.find(x => x.id === productId);
        if (!p) return;

        document.getElementById('modal-product-title').innerText = `✏️ Editar Producto: ${p.name}`;
        document.getElementById('form-product-id').value = p.id;
        document.getElementById('form-product-id').disabled = true;
        document.getElementById('form-product-name').value = p.name;
        document.getElementById('form-product-description').value = p.description || '';
        document.getElementById('form-product-price').value = p.price;
        document.getElementById('form-product-category').value = p.category || 'Cilindros';
        document.getElementById('form-product-stock').checked = p.in_stock;
        document.getElementById('form-product-promoted').checked = p.is_promoted;

        document.getElementById('modal-product').classList.add('open');
    } catch (err) {
        showToast('Error al cargar datos del producto', 'error');
    }
}

async function saveProductForm() {
    const isEdit = document.getElementById('form-product-id').disabled;
    const pid = document.getElementById('form-product-id').value.trim();
    const name = document.getElementById('form-product-name').value.trim();
    const price = parseFloat(document.getElementById('form-product-price').value);
    const description = document.getElementById('form-product-description').value.trim();
    const category = document.getElementById('form-product-category').value;
    const inStock = document.getElementById('form-product-stock').checked;
    const isPromoted = document.getElementById('form-product-promoted').checked;

    if (!pid || !name || isNaN(price)) {
        showToast('Por favor completa los campos requeridos (ID, Nombre, Precio)', 'error');
        return;
    }

    try {
        let res;
        if (isEdit) {
            res = await fetch(`${API_BASE}/products/${pid}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, description, price, category, in_stock: inStock, is_promoted: isPromoted })
            });
        } else {
            res = await fetch(`${API_BASE}/products`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: pid, name, description, price, category, in_stock: inStock, is_promoted: isPromoted })
            });
        }

        if (!res.ok) {
            const errData = await res.json();
            throw new Error(errData.detail || 'Error al guardar');
        }

        showToast(isEdit ? 'Producto actualizado con éxito' : 'Producto agregado al catálogo', 'success');
        closeModals();
        loadProducts();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function confirmDeleteProduct(id, name) {
    if (!confirm(`¿Estás seguro de que deseas eliminar el producto "${name}" del catálogo?`)) return;

    try {
        const res = await fetch(`${API_BASE}/products/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Error al eliminar');
        showToast(`Producto "${name}" eliminado`, 'success');
        loadProducts();
    } catch (err) {
        showToast('Error al eliminar producto', 'error');
    }
}

// -----------------------------------------------------------------------------
// 4. Drivers / Fleet Management (CRUD)
// -----------------------------------------------------------------------------

async function loadDrivers() {
    try {
        const res = await fetch(`${API_BASE}/drivers`);
        if (!res.ok) throw new Error('Error al cargar choferes');
        const drivers = await res.json();
        allDriversCache = drivers;
        renderDriversTable(drivers);
    } catch (err) {
        console.error('Error drivers:', err);
    }
}

function renderDriversTable(drivers) {
    const tbody = document.getElementById('drivers-table-body');
    if (!tbody) return;

    if (drivers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--text-muted); padding: 30px;">No hay choferes registrados.</td></tr>`;
        return;
    }

    tbody.innerHTML = drivers.map(d => {
        let opBadge = '';
        if (d.operational_status === 'en_entrega') {
            opBadge = `
                <span class="badge badge-op-en_entrega">🟡 EN ENTREGA</span>
                <div style="margin-top: 3px;">
                    <a href="javascript:void(0)" onclick="switchTab('orders'); filterOrderById(${d.active_order_id})" style="font-size: 0.78rem; color: var(--accent-cyan); font-weight: 600;">
                        Pedido #${d.active_order_id} ↗
                    </a>
                </div>
                <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeQuote(d.active_customer_name || '')}</div>
            `;
        } else if (d.operational_status === 'disponible') {
            opBadge = `<span class="badge badge-op-disponible">🟢 DISPONIBLE</span>`;
        } else {
            opBadge = `<span class="badge badge-op-fuera_servicio">🔴 FUERA DE SERVICIO</span>`;
        }

        let shiftTimeBadge = '';
        if (d.shift_check_in_at) {
            const h = d.shift_check_in_at.includes(' ') ? d.shift_check_in_at.split(' ')[1].substring(0, 5) : d.shift_check_in_at;
            shiftTimeBadge = `<div style="font-size: 0.74rem; color: var(--accent-emerald); margin-top: 4px; font-weight: 600;">⏰ Entrada: ${h}</div>`;
        } else if (d.last_check_out_at) {
            const h = d.last_check_out_at.includes(' ') ? d.last_check_out_at.split(' ')[1].substring(0, 5) : d.last_check_out_at;
            shiftTimeBadge = `<div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 4px;">🏁 Últ. Salida: ${h}</div>`;
        }

        const toggleBtn = d.is_available 
            ? `<button class="btn btn-secondary btn-sm" onclick="toggleDriverAvailability(${d.id}, true)" title="Poner fuera de servicio">🛑 Desconectar</button>` 
            : `<button class="btn btn-secondary btn-sm" style="color: var(--accent-emerald);" onclick="toggleDriverAvailability(${d.id}, false)" title="Poner disponible">🟢 Conectar</button>`;

        let vehicleIcon = '🛻';
        if (d.vehicle_type === 'estacionario') vehicleIcon = '🚛 Pipa';
        else if (d.vehicle_type === 'cilindros') vehicleIcon = '🛻 Camioneta';
        else vehicleIcon = '🚚 Mixta';

        let gpsStr = (d.current_lat && d.current_lng) 
            ? `<a href="https://www.google.com/maps?q=${d.current_lat},${d.current_lng}" target="_blank" style="color: var(--accent-cyan); text-decoration: none;">📍 (${d.current_lat.toFixed(4)}, ${d.current_lng.toFixed(4)})</a>`
            : `<span style="color: var(--text-muted);">Sin GPS</span>`;

        const ratingVal = (d.avg_rating !== undefined && d.avg_rating !== null) ? Number(d.avg_rating).toFixed(1) : '5.0';
        const ratingCount = d.total_ratings || 0;
        const ratingBadge = `
            <div style="cursor: pointer; display: inline-block;" onclick="openDriverRatingsModal(${d.id}, '${escapeQuote(d.name)}')" title="Ver detalle de encuestas y reseñas">
                <span style="color: var(--accent-amber); font-weight: 700; font-size: 0.92rem;">⭐ ${ratingVal}</span>
                <div style="font-size: 0.72rem; color: var(--accent-cyan); font-weight: 500;">${ratingCount} reseña(s) ↗</div>
            </div>
        `;

        const vehUnit = d.vehicle_unit_identifier || '';
        const vehModel = d.vehicle_model || '';
        let vehicleCell = '';
        if (vehUnit) {
            vehicleCell = `
                <div style="font-weight: 700; color: var(--text-heading); display: flex; align-items: center; gap: 6px;">
                    <span>${vehicleIcon}</span>
                    <span class="badge" style="background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.4); font-size: 0.76rem;">${vehUnit}</span>
                </div>
                <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 2px;">${vehModel} <code>[${d.vehicle_plate || ''}]</code></div>
            `;
        } else {
            vehicleCell = `<div>${vehicleIcon} ${d.vehicle_plate ? `<code>[${d.vehicle_plate}]</code>` : '<span style="color: var(--text-muted); font-size: 0.8rem;">Sin unidad</span>'}</div>`;
        }

        return `
            <tr>
                <td><strong>#${d.id}</strong></td>
                <td>
                    <div style="font-weight: 600; color: var(--text-heading);">${d.name}</div>
                    <div style="font-size: 0.78rem; color: var(--text-secondary);">${d.phone}</div>
                </td>
                <td>${vehicleCell}</td>
                <td><span style="font-size: 0.85rem;">${d.zone || 'General'}</span></td>
                <td>${ratingBadge}</td>
                <td>
                    ${opBadge}
                    ${shiftTimeBadge}
                </td>
                <td>${gpsStr}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        ${toggleBtn}
                        <button class="btn btn-secondary btn-sm" onclick="openDriverRatingsModal(${d.id}, '${escapeQuote(d.name)}')" title="Ver Calificaciones y Encuestas">⭐</button>
                        <button class="btn btn-secondary btn-sm" onclick="openDriverTankReadingsModal(${d.id}, '${escapeQuote(d.name)}', '${escapeQuote(d.vehicle_plate || '')}')" title="Ver Horas de Entrada/Salida y Cargas de Tanque">⏱️</button>
                        <button class="btn btn-secondary btn-sm" onclick="openEditDriverModal(${d.id})" title="Editar datos">✏️</button>
                        <button class="btn btn-danger btn-sm" onclick="confirmDeleteDriver(${d.id}, '${escapeQuote(d.name)}')" title="Eliminar chofer">🗑️</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

async function toggleDriverAvailability(driverId, currentIsAvailable) {
    try {
        const res = await fetch(`${API_BASE}/drivers/${driverId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_available: !currentIsAvailable })
        });
        if (!res.ok) throw new Error('Error al cambiar disponibilidad');
        showToast(`Disponibilidad del chofer #${driverId} actualizada`, 'success');
        loadDrivers();
        loadDashboardMetrics();
    } catch (err) {
        showToast('Error al actualizar disponibilidad', 'error');
    }
}

function populateDriverVehicleSelect(selectedVehicleId) {
    const sel = document.getElementById('form-driver-vehicle-id');
    if (!sel) return;

    sel.innerHTML = '<option value="">-- Sin unidad asignada (O asignar después) --</option>';
    allVehiclesCache.forEach(v => {
        const typeIcon = v.vehicle_type === 'pipa' ? '🚛 Pipa' : '🛻 Camioneta';
        let cap = '';
        if (v.vehicle_type === 'pipa' && v.pipa_capacity_liters) {
            cap = ` | ${Number(v.pipa_capacity_liters).toLocaleString()} L`;
        } else if (v.cylinder_capacity_count) {
            cap = ` | ${v.cylinder_capacity_count} Cilindros`;
        }

        let assignedNotice = '';
        if (v.assigned_driver_id && (!selectedVehicleId || v.id !== selectedVehicleId)) {
            assignedNotice = ` (Ocupada por ${v.assigned_driver_name || 'otro chofer'})`;
        }

        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = `${v.unit_identifier} - ${v.model} [${v.plate}] (${typeIcon}${cap})${assignedNotice}`;
        if (selectedVehicleId && v.id === selectedVehicleId) {
            opt.selected = true;
        }
        sel.appendChild(opt);
    });

    onDriverVehicleSelected();
}

function onDriverVehicleSelected() {
    const sel = document.getElementById('form-driver-vehicle-id');
    const previewBox = document.getElementById('driver-vehicle-details-preview');
    const previewText = document.getElementById('driver-vehicle-preview-text');
    const vtypeInput = document.getElementById('form-driver-vtype');
    const plateInput = document.getElementById('form-driver-plate');

    if (!sel) return;
    const vid = parseInt(sel.value, 10);
    const veh = allVehiclesCache.find(v => v.id === vid);

    if (veh) {
        if (previewBox) previewBox.style.display = 'block';
        const typeLabel = veh.vehicle_type === 'pipa' ? '🚛 Pipa de Gas Estacionario' : '🛻 Camioneta de Cilindros';
        let capStr = veh.vehicle_type === 'pipa' 
            ? `${Number(veh.pipa_capacity_liters || 0).toLocaleString()} Litros` 
            : `${veh.cylinder_capacity_count || 0} Cilindros`;

        if (previewText) {
            previewText.innerHTML = `<strong>${veh.unit_identifier}</strong> — ${veh.model} &bull; Placas: <code>${veh.plate}</code><br>Tipo: ${typeLabel} &bull; Capacidad: <strong>${capStr}</strong>`;
        }
        if (vtypeInput) vtypeInput.value = (veh.vehicle_type === 'pipa' ? 'estacionario' : 'cilindros');
        if (plateInput) plateInput.value = `${veh.unit_identifier} (${veh.plate})`;
    } else {
        if (previewBox) previewBox.style.display = 'none';
        if (previewText) previewText.innerHTML = '';
        if (vtypeInput) vtypeInput.value = 'cilindros';
        if (plateInput) plateInput.value = '';
    }
}

async function openAddDriverModal() {
    document.getElementById('modal-driver-title').innerText = '➕ Registrar Chofer';
    document.getElementById('form-driver-id').value = '';
    document.getElementById('form-driver-name').value = '';
    document.getElementById('form-driver-phone').value = '';
    document.getElementById('form-driver-zone').value = 'Mazatlán Centro';
    document.getElementById('form-driver-tgid').value = '';

    if (allVehiclesCache.length === 0) {
        await loadVehicles();
    }
    populateDriverVehicleSelect(null);

    document.getElementById('modal-driver').classList.add('open');
}

async function openEditDriverModal(driverId) {
    const d = allDriversCache.find(x => String(x.id).toLowerCase() === String(driverId).toLowerCase());
    if (!d) return;

    document.getElementById('modal-driver-title').innerText = `✏️ Editar Chofer: ${d.name}`;
    document.getElementById('form-driver-id').value = d.id;
    document.getElementById('form-driver-name').value = d.name;
    document.getElementById('form-driver-phone').value = d.phone;
    document.getElementById('form-driver-zone').value = d.zone || 'General';
    document.getElementById('form-driver-tgid').value = d.telegram_user_id || '';

    if (allVehiclesCache.length === 0) {
        await loadVehicles();
    }
    populateDriverVehicleSelect(d.vehicle_id || null);

    document.getElementById('modal-driver').classList.add('open');
}

async function saveDriverForm() {
    const did = document.getElementById('form-driver-id').value;
    const name = document.getElementById('form-driver-name').value.trim();
    const phone = document.getElementById('form-driver-phone').value.trim();
    const vehicleIdVal = document.getElementById('form-driver-vehicle-id').value;
    const vehicleId = vehicleIdVal ? parseInt(vehicleIdVal, 10) : null;
    const vehicleType = document.getElementById('form-driver-vtype').value;
    const vehiclePlate = document.getElementById('form-driver-plate').value.trim();
    const zone = document.getElementById('form-driver-zone').value.trim();
    const telegramUserId = document.getElementById('form-driver-tgid').value.trim();

    if (!name || !phone) {
        showToast('Nombre y teléfono son obligatorios', 'error');
        return;
    }

    const payload = {
        name,
        phone,
        vehicle_id: vehicleId,
        vehicle_type: vehicleType,
        vehicle_plate: vehiclePlate,
        zone,
        telegram_user_id: telegramUserId
    };

    try {
        let res;
        if (did) {
            res = await fetch(`${API_BASE}/drivers/${did}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        } else {
            res = await fetch(`${API_BASE}/drivers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
        }

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Error al guardar chofer');
        }

        showToast(did ? 'Chofer actualizado con éxito' : 'Chofer registrado con éxito', 'success');
        closeModals();
        loadDrivers();
        loadVehicles(); // refresh vehicles to update assigned driver name
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// -----------------------------------------------------------------------------
// Vehicles Management (Unidades Vehiculares / Flota)
// -----------------------------------------------------------------------------

async function loadVehicles() {
    try {
        const res = await fetch(`${API_BASE}/vehicles`);
        if (!res.ok) throw new Error('Error al cargar unidades');
        allVehiclesCache = await res.json();
        renderVehiclesTable(allVehiclesCache);
    } catch (err) {
        console.error('Error cargando unidades:', err);
    }
}

function renderVehiclesTable(vehicles) {
    const tbody = document.getElementById('vehicles-table-body');
    if (!tbody) return;

    if (!vehicles || vehicles.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" style="text-align: center; color: var(--text-muted); padding: 32px;">
                    🚛 No hay unidades vehiculares registradas. Haz clic en <strong>➕ Registrar Nueva Unidad</strong> para dar de alta una pipa o camioneta.
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = vehicles.map(v => {
        const isPipa = v.vehicle_type === 'pipa';
        const typeBadge = isPipa 
            ? `<span class="badge" style="background: rgba(14, 165, 233, 0.15); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.35); font-weight: 600;">🚛 Pipa Gas Estacionario</span>`
            : `<span class="badge" style="background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); font-weight: 600;">🛻 Camioneta de Cilindros</span>`;

        let capBadge = '';
        if (isPipa && v.pipa_capacity_liters) {
            capBadge = `<span style="font-weight: 700; color: var(--accent-cyan); font-size: 0.95rem;">${Number(v.pipa_capacity_liters).toLocaleString()} L</span>`;
        } else if (v.cylinder_capacity_count) {
            capBadge = `<span style="font-weight: 700; color: var(--accent-amber); font-size: 0.95rem;">${v.cylinder_capacity_count} Cilindros</span>`;
        } else {
            capBadge = `<span style="color: var(--text-muted); font-size: 0.8rem;">No especificada</span>`;
        }

        let driverInfo = '';
        if (v.assigned_driver_name) {
            driverInfo = `
                <div style="font-weight: 600; color: var(--text-heading);">👤 ${v.assigned_driver_name}</div>
                ${v.assigned_driver_phone ? `<div style="font-size: 0.75rem; color: var(--text-secondary);">${v.assigned_driver_phone}</div>` : ''}
            `;
        } else {
            driverInfo = `<span style="color: var(--text-muted); font-size: 0.82rem; font-style: italic;">Sin chofer asignado</span>`;
        }

        let statusBadge = '';
        if (v.status === 'active') {
            statusBadge = `<span class="badge badge-active">🟢 Activa</span>`;
        } else if (v.status === 'maintenance') {
            statusBadge = `<span class="badge badge-scheduled" style="background: rgba(234, 179, 8, 0.15); color: #facc15;">🟡 En Taller</span>`;
        } else {
            statusBadge = `<span class="badge badge-cancelled">🔴 Inactiva</span>`;
        }

        return `
            <tr>
                <td>
                    <div style="font-weight: 800; font-size: 1.05rem; color: var(--text-heading); letter-spacing: 0.5px;">${v.unit_identifier}</div>
                    ${v.notes ? `<div style="font-size: 0.72rem; color: var(--text-muted);">${v.notes}</div>` : ''}
                </td>
                <td>
                    <div style="font-weight: 600; color: var(--text-primary);">${v.model}</div>
                    <div style="font-size: 0.78rem; font-family: monospace; color: var(--accent-cyan);"><code>${v.plate}</code></div>
                </td>
                <td>${typeBadge}</td>
                <td>${capBadge}</td>
                <td>${driverInfo}</td>
                <td>${statusBadge}</td>
                <td>
                    <div style="display: flex; gap: 6px;">
                        <button class="btn btn-secondary btn-sm" onclick="openEditVehicleModal(${v.id})" title="Editar unidad">✏️</button>
                        <button class="btn btn-danger btn-sm" onclick="confirmDeleteVehicle(${v.id}, '${escapeQuote(v.unit_identifier)}')" title="Eliminar unidad">🗑️</button>
                    </div>
                </td>
            </tr>
        `;
    }).join('');
}

function toggleVehicleCapacityFields() {
    const type = document.getElementById('form-vehicle-type').value;
    const pipaGroup = document.getElementById('group-vehicle-pipa-cap');
    const cylGroup = document.getElementById('group-vehicle-cyl-cap');

    if (type === 'pipa') {
        if (pipaGroup) pipaGroup.style.display = 'block';
        if (cylGroup) cylGroup.style.display = 'none';
    } else {
        if (pipaGroup) pipaGroup.style.display = 'none';
        if (cylGroup) cylGroup.style.display = 'block';
    }
}

function openAddVehicleModal() {
    document.getElementById('modal-vehicle-title').innerText = '➕ Registrar Nueva Unidad';
    document.getElementById('form-vehicle-id').value = '';
    document.getElementById('form-vehicle-identifier').value = '';
    document.getElementById('form-vehicle-plate').value = '';
    document.getElementById('form-vehicle-model').value = '';
    document.getElementById('form-vehicle-type').value = 'camioneta';
    document.getElementById('form-vehicle-pipa-cap').value = '';
    document.getElementById('form-vehicle-cyl-cap').value = '40';
    document.getElementById('form-vehicle-status').value = 'active';
    document.getElementById('form-vehicle-notes').value = '';

    toggleVehicleCapacityFields();
    document.getElementById('modal-vehicle').classList.add('open');
}

function openEditVehicleModal(vehicleId) {
    const v = allVehiclesCache.find(x => x.id === vehicleId);
    if (!v) return;

    document.getElementById('modal-vehicle-title').innerText = `✏️ Editar Unidad: ${v.unit_identifier}`;
    document.getElementById('form-vehicle-id').value = v.id;
    document.getElementById('form-vehicle-identifier').value = v.unit_identifier;
    document.getElementById('form-vehicle-plate').value = v.plate;
    document.getElementById('form-vehicle-model').value = v.model;
    document.getElementById('form-vehicle-type').value = v.vehicle_type || 'camioneta';
    document.getElementById('form-vehicle-pipa-cap').value = v.pipa_capacity_liters || '';
    document.getElementById('form-vehicle-cyl-cap').value = v.cylinder_capacity_count || '';
    document.getElementById('form-vehicle-status').value = v.status || 'active';
    document.getElementById('form-vehicle-notes').value = v.notes || '';

    toggleVehicleCapacityFields();
    document.getElementById('modal-vehicle').classList.add('open');
}

async function saveVehicleForm() {
    const vid = document.getElementById('form-vehicle-id').value;
    const unitIdentifier = document.getElementById('form-vehicle-identifier').value.trim().toUpperCase();
    const plate = document.getElementById('form-vehicle-plate').value.trim().toUpperCase();
    const model = document.getElementById('form-vehicle-model').value.trim();
    const vehicleType = document.getElementById('form-vehicle-type').value;
    const pipaCapVal = document.getElementById('form-vehicle-pipa-cap').value;
    const cylCapVal = document.getElementById('form-vehicle-cyl-cap').value;
    const status = document.getElementById('form-vehicle-status').value;
    const notes = document.getElementById('form-vehicle-notes').value.trim();

    if (!unitIdentifier || !plate || !model) {
        showToast('Identificador, placas y modelo son obligatorios', 'error');
        return;
    }

    const payload = {
        unit_identifier: unitIdentifier,
        plate: plate,
        model: model,
        vehicle_type: vehicleType,
        pipa_capacity_liters: vehicleType === 'pipa' && pipaCapVal ? parseFloat(pipaCapVal) : null,
        cylinder_capacity_count: vehicleType === 'camioneta' && cylCapVal ? parseInt(cylCapVal, 10) : null,
        status: status,
        notes: notes,
    };

    try {
        let res;
        if (vid) {
            res = await fetch(`${API_BASE}/vehicles/${vid}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        } else {
            res = await fetch(`${API_BASE}/vehicles`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        }

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Error al guardar unidad');
        }

        showToast(vid ? 'Unidad actualizada correctamente' : 'Unidad registrada con éxito', 'success');
        closeModals();
        loadVehicles();
        loadDrivers(); // refresh drivers in case vehicle info changed
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function confirmDeleteVehicle(id, identifier) {
    if (!confirm(`¿Eliminar la unidad "${identifier}" de la flota? Se desvinculará de cualquier chofer asignado.`)) return;

    try {
        const res = await fetch(`${API_BASE}/vehicles/${id}`, {
            method: 'DELETE',
        });
        if (!res.ok) throw new Error('Error al eliminar unidad');
        showToast(`Unidad "${identifier}" eliminada`, 'success');
        loadVehicles();
        loadDrivers();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

async function confirmDeleteDriver(id, name) {
    if (!confirm(`¿Eliminar al chofer "${name}" de la flota?`)) return;

    try {
        const res = await fetch(`${API_BASE}/drivers/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Error al eliminar');
        showToast(`Chofer "${name}" eliminado`, 'success');
        loadDrivers();
    } catch (err) {
        showToast('Error al eliminar chofer', 'error');
    }
}

function switchDriverAuditTab(tab) {
    const btnShifts = document.getElementById('tab-btn-shifts');
    const btnReadings = document.getElementById('tab-btn-readings');
    const panelShifts = document.getElementById('driver-audit-shifts-panel');
    const panelReadings = document.getElementById('driver-audit-readings-panel');

    if (tab === 'shifts') {
        if (btnShifts) btnShifts.className = 'btn btn-sm btn-primary';
        if (btnReadings) btnReadings.className = 'btn btn-sm btn-secondary';
        if (panelShifts) panelShifts.style.display = 'block';
        if (panelReadings) panelReadings.style.display = 'none';
    } else {
        if (btnReadings) btnReadings.className = 'btn btn-sm btn-primary';
        if (btnShifts) btnShifts.className = 'btn btn-sm btn-secondary';
        if (panelReadings) panelReadings.style.display = 'block';
        if (panelShifts) panelShifts.style.display = 'none';
    }
}

async function openDriverTankReadingsModal(driverId, driverName, vehiclePlate) {
    const modal = document.getElementById('modal-tank-readings');
    const title = document.getElementById('modal-tank-readings-title');
    const subtitle = document.getElementById('modal-tank-readings-subtitle');
    const panelShifts = document.getElementById('driver-audit-shifts-panel');
    const panelReadings = document.getElementById('driver-audit-readings-panel');
    if (!modal || !panelShifts || !panelReadings) return;

    title.innerHTML = `⏱️ Asistencia y Cargas: ${escapeQuote(driverName)}`;
    subtitle.innerHTML = `Unidad: <strong>${escapeQuote(vehiclePlate || 'Sin placas')}</strong> | ID Chofer: #${driverId}`;
    panelShifts.innerHTML = `<div style="text-align: center; padding: 25px; color: var(--text-muted);">⏳ Cargando registro de asistencia y turnos...</div>`;
    panelReadings.innerHTML = `<div style="text-align: center; padding: 25px; color: var(--text-muted);">⏳ Cargando lecturas de tanque...</div>`;

    // Por defecto mostrar pestaña de asistencia/turnos
    switchDriverAuditTab('shifts');
    modal.classList.add('open');

    try {
        const [resShifts, resReadings] = await Promise.all([
            fetch(`${API_BASE}/drivers/${driverId}/shifts`),
            fetch(`${API_BASE}/drivers/${driverId}/tank-readings`)
        ]);

        const shifts = resShifts.ok ? await resShifts.json() : [];
        const readings = resReadings.ok ? await resReadings.json() : [];

        // 1. Renderizar Panel de Turnos y Asistencia (Entrada y Salida)
        if (!shifts || shifts.length === 0) {
            panelShifts.innerHTML = `
                <div style="text-align: center; padding: 30px; color: var(--text-muted);">
                    <div style="font-size: 2rem; margin-bottom: 8px;">⏰</div>
                    Este chofer no tiene registros de asistencia ni turnos iniciados aún.
                </div>
            `;
        } else {
            panelShifts.innerHTML = `
                <div style="display: flex; flex-direction: column; gap: 12px;">
                    ${shifts.map(s => {
                        const isActive = s.status === 'active';
                        const badgeColor = isActive ? 'var(--accent-emerald)' : 'var(--text-muted)';
                        const badgeBg = isActive ? 'rgba(16, 185, 129, 0.15)' : 'rgba(255, 255, 255, 0.06)';
                        const badgeText = isActive ? '🟢 EN TURNO ACTIVO' : '⚪ JORNADA FINALIZADA';

                        const hIn = s.check_in_at ? (s.check_in_at.includes(' ') ? s.check_in_at.split(' ')[1].substring(0, 5) : s.check_in_at) : 'N/A';
                        const hOut = s.check_out_at ? (s.check_out_at.includes(' ') ? s.check_out_at.split(' ')[1].substring(0, 5) : s.check_out_at) : (isActive ? '⚡ En curso...' : 'N/A');

                        let durText = 'En curso';
                        if (!isActive && s.duration_minutes !== null && s.duration_minutes !== undefined) {
                            const mins = s.duration_minutes;
                            const h = Math.floor(mins / 60);
                            const m = mins % 60;
                            durText = h > 0 ? `${h} hrs ${m} mins` : `${m} mins`;
                        }

                        const gasLecturas = (s.initial_reading || s.final_reading) 
                            ? `<div style="margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.08); font-size: 0.8rem; color: var(--text-secondary); display: flex; gap: 16px;">
                                 ${s.initial_reading ? `<span>⛽ Carga Inicial: <strong style="color: var(--accent-emerald);">${s.initial_reading}</strong></span>` : ''}
                                 ${s.final_reading ? `<span>🏁 Carga Final: <strong style="color: var(--accent-rose);">${s.final_reading}</strong></span>` : ''}
                               </div>`
                            : '';

                        return `
                            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: var(--radius-md); padding: 14px 16px;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                                    <span style="font-weight: 700; font-size: 0.8rem; color: ${badgeColor}; background: ${badgeBg}; padding: 3px 10px; border-radius: var(--radius-full);">
                                        ${badgeText}
                                    </span>
                                    <span style="font-size: 0.8rem; color: var(--text-muted);">
                                        📅 Fecha: <strong>${s.shift_date}</strong>
                                    </span>
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; background: rgba(0,0,0,0.2); padding: 10px 14px; border-radius: var(--radius-sm);">
                                    <div>
                                        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Hora de Entrada</div>
                                        <div style="font-size: 1.15rem; font-weight: 700; color: var(--accent-emerald);">🟢 ${hIn}</div>
                                    </div>
                                    <div>
                                        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Hora de Salida</div>
                                        <div style="font-size: 1.15rem; font-weight: 700; color: ${isActive ? 'var(--accent-cyan)' : 'var(--accent-rose)'};">🔴 ${hOut}</div>
                                    </div>
                                    <div>
                                        <div style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Tiempo Laborado</div>
                                        <div style="font-size: 1.05rem; font-weight: 700; color: var(--text-heading);">⏱️ ${durText}</div>
                                    </div>
                                </div>
                                ${gasLecturas}
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        }

        // 2. Renderizar Panel de Lecturas de Tanque
        if (!readings || readings.length === 0) {
            panelReadings.innerHTML = `
                <div style="text-align: center; padding: 30px; color: var(--text-muted);">
                    <div style="font-size: 2rem; margin-bottom: 8px;">🛢️</div>
                    Este chofer no ha registrado lecturas de carga para esta unidad aún.
                </div>
            `;
        } else {
            const tipoLabels = {
                'initial': { text: '🟢 Carga Inicial', color: 'var(--accent-emerald)', bg: 'rgba(16, 185, 129, 0.12)' },
                'final': { text: '🔴 Carga Final', color: 'var(--accent-rose)', bg: 'rgba(244, 63, 94, 0.12)' },
                'refill': { text: '🔵 Recarga en Planta', color: 'var(--accent-cyan)', bg: 'rgba(6, 182, 212, 0.12)' },
            };

            panelReadings.innerHTML = `
                <div style="display: flex; flex-direction: column; gap: 12px;">
                    ${readings.map(r => {
                        const info = tipoLabels[r.reading_type] || { text: r.reading_type, color: '#fff', bg: 'rgba(255,255,255,0.08)' };
                        const photoHtml = r.photo_path 
                            ? `
                                <div style="margin-top: 10px;">
                                    <a href="/${r.photo_path}" target="_blank" style="display: inline-flex; align-items: center; gap: 8px; text-decoration: none; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); padding: 6px 12px; border-radius: var(--radius-sm); font-size: 0.8rem; color: var(--accent-cyan);">
                                        <span>📸 Ver Fotografía del Medidor en Grande ↗</span>
                                    </a>
                                    <div style="margin-top: 6px;">
                                        <a href="/${r.photo_path}" target="_blank">
                                            <img src="/${r.photo_path}" alt="Medidor" style="max-width: 140px; max-height: 100px; border-radius: var(--radius-sm); border: 1px solid rgba(255,255,255,0.15); object-fit: cover;" loading="lazy">
                                        </a>
                                    </div>
                                </div>
                              ` 
                            : `<div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 4px;">✍️ Capturado manualmente por mensaje de texto</div>`;

                        return `
                            <div style="background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: var(--radius-md); padding: 14px 16px;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                    <span style="font-weight: 700; font-size: 0.85rem; color: ${info.color}; background: ${info.bg}; padding: 3px 10px; border-radius: var(--radius-full);">
                                        ${info.text}
                                    </span>
                                    <span style="font-size: 0.78rem; color: var(--text-muted);">
                                        📅 ${r.created_at || r.shift_date}
                                    </span>
                                </div>
                                <div style="display: flex; align-items: baseline; gap: 10px;">
                                    <span style="font-size: 1.25rem; font-weight: 800; color: var(--text-heading);">
                                        ${r.reading_value}
                                    </span>
                                    ${r.notes ? `<span style="font-size: 0.8rem; color: var(--text-secondary);">(${escapeQuote(r.notes)})</span>` : ''}
                                </div>
                                ${photoHtml}
                            </div>
                        `;
                    }).join('')}
                </div>
            `;
        }

    } catch (err) {
        console.error('Error al cargar datos de auditoría del chofer:', err);
        panelShifts.innerHTML = `<div style="color: var(--accent-rose); padding: 20px; text-align: center;">Error al obtener turnos.</div>`;
        panelReadings.innerHTML = `<div style="color: var(--accent-rose); padding: 20px; text-align: center;">Error al obtener lecturas.</div>`;
    }
}

// -----------------------------------------------------------------------------
// 5. Customers Directory
// -----------------------------------------------------------------------------

async function loadCustomers() {
    try {
        const res = await fetch(`${API_BASE}/customers`);
        if (!res.ok) throw new Error('Error al cargar clientes');
        const customers = await res.json();
        allCustomersCache = customers;
        renderCustomersTable(customers);
    } catch (err) {
        console.error('Error customers:', err);
    }
}

function filterCustomersTable() {
    const q = (document.getElementById('customers-search-input')?.value || '').toLowerCase().trim();
    if (!q) {
        renderCustomersTable(allCustomersCache);
        return;
    }

    const filtered = allCustomersCache.filter(c => {
        const name = (c.name || '').toLowerCase();
        const phone = (c.phone || '').toLowerCase();
        const addrs = (c.addresses || []).map(a => a.address.toLowerCase()).join(' ');
        return name.includes(q) || phone.includes(q) || addrs.includes(q);
    });

    renderCustomersTable(filtered);
}

function renderCustomersTable(customers) {
    const tbody = document.getElementById('customers-table-body');
    if (!tbody) return;

    if (customers.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 30px;">No hay clientes registrados.</td></tr>`;
        return;
    }

    tbody.innerHTML = customers.map(c => {
        let addrsList = c.addresses.map((a, i) => `<div>${i+1}. 📍 ${a.address}</div>`).join('');
        if (!addrsList && c.address) addrsList = `<div>📍 ${c.address}</div>`;

        return `
            <tr>
                <td><strong>#${c.id}</strong></td>
                <td>
                    <div style="font-weight: 600; color: var(--text-heading);">${c.name}</div>
                    <div style="font-size: 0.78rem; color: var(--text-muted);">Canal: ${c.channel} (${c.channel_user_id || ''})</div>
                </td>
                <td><strong style="color: var(--accent-cyan);">${c.phone || 'Sin teléfono'}</strong></td>
                <td>
                    <div style="max-width: 320px; font-size: 0.8rem; line-height: 1.4;">${addrsList || '<span style="color: var(--text-muted);">Sin direcciones guardadas</span>'}</div>
                </td>
                <td>
                    <span class="badge badge-scheduled">${c.order_count} entregados</span>
                </td>
                <td>
                    <strong style="color: var(--accent-emerald);">$${c.total_spent.toFixed(2)}</strong>
                </td>
            </tr>
        `;
    }).join('');
}

// -----------------------------------------------------------------------------
// 6. Action Modals (Reassign & Status)
// -----------------------------------------------------------------------------

async function openReassignModal(orderId, customerName, currentDriverId, orderStatus = null) {
    if (orderStatus === 'cancelled') {
        showToast('⚠️ Este pedido se encuentra cancelado. No es posible asignarle un chofer.', 'error');
        return;
    }

    document.getElementById('modal-reassign-order-id').value = orderId;
    document.getElementById('modal-reassign-title').innerText = currentDriverId ? `🔄 Reasignar Pedido #${orderId}` : `🛻 Asignar Chofer: Pedido #${orderId}`;
    document.getElementById('modal-reassign-info').innerText = `Cliente: ${customerName}`;

    const select = document.getElementById('modal-reassign-driver-select');

    function renderOptions(drivers) {
        select.innerHTML = drivers.map(d => {
            const isSelected = String(d.id).toLowerCase() === String(currentDriverId).toLowerCase() ? 'selected' : '';
            let icon = '🟢';
            let opLabel = 'Disponible';
            if (d.operational_status === 'en_entrega') {
                icon = '🟡';
                opLabel = `En Entrega (#${d.active_order_id})`;
            } else if (d.operational_status === 'fuera_servicio') {
                icon = '🔴';
                opLabel = 'Fuera de Turno';
            }
            return `<option value="${d.id}" ${isSelected}>${icon} ${d.name} [${opLabel}] - ${d.vehicle_type} (${d.phone})</option>`;
        }).join('');
    }

    // 1. Mostrar de inmediato con caché
    if (allDriversCache && allDriversCache.length > 0) {
        renderOptions(allDriversCache);
    } else {
        select.innerHTML = '<option value="">⏳ Consultando disponibilidad de flota...</option>';
    }

    document.getElementById('modal-reassign').classList.add('open');

    // 2. Consultar al vuelo el estatus más reciente de la flota
    try {
        const res = await fetch(`${API_BASE}/drivers`);
        if (res.ok) {
            const freshDrivers = await res.json();
            allDriversCache = freshDrivers;
            renderOptions(freshDrivers);
        }
    } catch (e) {
        console.warn('Error refrescando choferes en modal:', e);
    }
}

function filterActiveOrders() {
    switchTab('orders');
    const select = document.getElementById('orders-filter-status');
    if (select) {
        select.value = 'active';
        loadOrders();
    }
}

async function submitReassignOrder() {
    const orderId = document.getElementById('modal-reassign-order-id').value;
    const selectElem = document.getElementById('modal-reassign-driver-select');
    const rawVal = selectElem ? selectElem.value?.trim() : '';

    if (!rawVal) {
        showToast('⚠️ Por favor selecciona un chofer de la lista.', 'warning');
        return;
    }

    const driverId = (!isNaN(rawVal) && !rawVal.includes('-')) ? parseInt(rawVal, 10) : rawVal;

    // Instant close modal so the user feels immediate responsiveness
    closeModals();
    showToast(`⏳ Asignando pedido #${orderId}...`, 'info');

    try {
        const res = await fetch(`${API_BASE}/orders/${orderId}/reassign`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ driver_id: driverId })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Error al asignar o reasignar');
        }
        const data = await res.json();
        const dName = data.driver_name || `Chofer ${driverId}`;
        
        if (data.reassigned) {
            showToast(`✅ Pedido #${orderId} reasignado a ${dName}. Se notificó a la unidad y al cliente por Telegram.`, 'success');
        } else {
            showToast(`✅ Pedido #${orderId} asignado a ${dName}. Notificaciones enviadas al chofer y cliente.`, 'success');
        }
        
        // Parallel refresh
        await Promise.all([
            loadOrders(),
            loadRejections(),
            loadDrivers(),
            loadDashboardMetrics()
        ]);
    } catch (err) {
        showToast(`❌ Error al asignar pedido: ${err.message}`, 'error');
        loadOrders();
    }
}

function filterOrderById(orderId) {
    const searchInput = document.getElementById('orders-search-input');
    if (searchInput) {
        searchInput.value = orderId;
        loadOrders();
    }
}

function openStatusModal(orderId, currentStatus, customerName) {
    document.getElementById('modal-status-order-id').value = orderId;
    document.getElementById('modal-status-title').innerText = `⚙️ Cambiar Estado: Pedido #${orderId}`;
    document.getElementById('modal-status-info').innerText = `Cliente: ${customerName} (Estado actual: ${getStatusLabel(currentStatus)})`;
    const select = document.getElementById('modal-status-select');
    select.value = currentStatus;

    const reasonGroup = document.getElementById('modal-status-reason-group');
    const reasonInput = document.getElementById('modal-status-reason');
    if (reasonInput) reasonInput.value = '';

    const checkReasonVisibility = () => {
        if (reasonGroup) {
            reasonGroup.style.display = select.value === 'cancelled' ? 'block' : 'none';
        }
    };
    select.onchange = checkReasonVisibility;
    checkReasonVisibility();

    document.getElementById('modal-status').classList.add('open');
}

async function submitStatusChange() {
    const orderId = document.getElementById('modal-status-order-id').value;
    const newStatus = document.getElementById('modal-status-select').value;
    const reason = document.getElementById('modal-status-reason')?.value?.trim() || '';

    try {
        const res = await fetch(`${API_BASE}/orders/${orderId}/status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus, reason: reason })
        });
        if (!res.ok) throw new Error('Error al cambiar estado');
        if (newStatus === 'cancelled') {
            showToast(`⚠️ Pedido #${orderId} cancelado. Se envió notificación con explicación y disculpa al cliente.`, 'warning');
        } else {
            showToast(`Pedido #${orderId} actualizado a [${getStatusLabel(newStatus)}]`, 'success');
        }
        closeModals();
        loadOrders();
        loadDashboardMetrics();
    } catch (err) {
        showToast(`Error: ${err.message}`, 'error');
    }
}

// -----------------------------------------------------------------------------
// Modal Utilities
// -----------------------------------------------------------------------------

function initModals() {
    document.querySelectorAll('.modal-close, .btn-close-modal').forEach(btn => {
        btn.addEventListener('click', closeModals);
    });

    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) closeModals();
        });
    });
}

function openModal(modalId) {
    const m = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
    if (m) m.classList.add('open');
}

function closeModals() {
    document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('open'));
}

// -----------------------------------------------------------------------------
// 9. Excel Reports & Exports
// -----------------------------------------------------------------------------

function exportOrdersExcel() {
    const filterSelect = document.getElementById('orders-filter-status');
    const status = filterSelect ? filterSelect.value : '';
    let url = `${API_BASE}/reports/excel/orders`;
    if (status && status !== 'all') {
        url += `?status=${encodeURIComponent(status)}`;
    }
    showToast('Generando reporte Excel de pedidos...', 'info');
    window.location.href = url;
}

function exportFilteredOrdersExcel() {
    const select = document.getElementById('report-order-status');
    const status = select ? select.value : '';
    let url = `${API_BASE}/reports/excel/orders`;
    if (status) {
        url += `?status=${encodeURIComponent(status)}`;
    }
    showToast('Generando reporte Excel de pedidos...', 'info');
    window.location.href = url;
}

// -----------------------------------------------------------------------------
// 10. Driver Ratings & Survey Modal
// -----------------------------------------------------------------------------

async function openDriverRatingsModal(driverId, driverName) {
    const modal = document.getElementById('modal-driver-ratings');
    if (!modal) return;

    document.getElementById('modal-driver-ratings-title').innerText = `⭐ Calificaciones: ${driverName}`;
    document.getElementById('modal-driver-ratings-subtitle').innerText = `Historial de encuestas de satisfacción para el chofer #${driverId}`;
    
    const panel = document.getElementById('driver-ratings-content');
    panel.innerHTML = `<div style="text-align: center; padding: 25px; color: var(--text-muted);">Cargando calificaciones...</div>`;
    modal.classList.add('open');

    try {
        const res = await fetch(`${API_BASE}/drivers/${driverId}/ratings`);
        if (!res.ok) throw new Error('Error al cargar calificaciones del chofer');
        const data = await res.json();
        
        const stats = data.stats || { average: 5.0, count: 0, breakdown: { 5: 0, 4: 0, 3: 0, 2: 0, 1: 0 } };
        const ratings = data.ratings || [];

        const roundedAvg = stats.count > 0 ? Math.round(stats.average || 0) : 0;
        const avgStars = stats.count > 0 
            ? ('⭐'.repeat(Math.max(0, Math.min(5, roundedAvg))) + '☆'.repeat(Math.max(0, 5 - Math.max(0, Math.min(5, roundedAvg)))))
            : '☆☆☆☆☆';

        let summaryHtml = `
            <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255,255,255,0.08); border-radius: 8px; padding: 14px; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-around;">
                <div style="text-align: center;">
                    <div style="font-size: 2.2rem; font-weight: 800; color: var(--accent-amber);">${stats.average.toFixed(1)}</div>
                    <div style="color: var(--accent-amber); font-size: 1.1rem; margin-top: -4px;">${avgStars}</div>
                    <div style="font-size: 0.78rem; color: var(--text-muted); margin-top: 4px;">Basado en ${stats.count} encuestas</div>
                </div>
                <div style="font-size: 0.8rem; line-height: 1.6; color: var(--text-secondary);">
                    <div>5 estrellas: <strong>${stats.breakdown[5] || 0}</strong></div>
                    <div>4 estrellas: <strong>${stats.breakdown[4] || 0}</strong></div>
                    <div>3 estrellas: <strong>${stats.breakdown[3] || 0}</strong></div>
                    <div>2 estrellas: <strong>${stats.breakdown[2] || 0}</strong></div>
                    <div>1 estrella: <strong>${stats.breakdown[1] || 0}</strong></div>
                </div>
            </div>
        `;

        if (ratings.length === 0) {
            panel.innerHTML = summaryHtml + `
                <div style="text-align: center; padding: 30px; color: var(--text-muted); font-size: 0.9rem;">
                    El chofer aún no cuenta con encuestas o calificaciones registradas en este período.
                </div>
            `;
            return;
        }

        let listHtml = ratings.map(r => {
            const starsText = '⭐'.repeat(r.rating) + '☆'.repeat(5 - r.rating);
            const tagBadge = r.feedback_tag ? `<span class="badge" style="background: rgba(6, 182, 212, 0.15); color: var(--accent-cyan); border: 1px solid rgba(6, 182, 212, 0.3);">${escapeQuote(r.feedback_tag)}</span>` : '';
            const commentText = r.comment ? `<div style="margin-top: 6px; font-size: 0.85rem; color: var(--text-heading); font-style: italic; background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 6px; border-left: 3px solid var(--accent-amber);">"${escapeQuote(r.comment)}"</div>` : '';
            const dt = formatDateTime(r.created_at);

            return `
                <div style="background: rgba(30, 41, 59, 0.5); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 12px 16px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: baseline;">
                        <div>
                            <span style="color: var(--accent-amber); font-weight: 700; font-size: 1.05rem;">${starsText}</span>
                            <span style="font-size: 0.82rem; color: var(--text-muted); margin-left: 6px;">(${r.rating}/5)</span>
                        </div>
                        <span style="font-size: 0.75rem; color: var(--text-muted);">${dt}</span>
                    </div>
                    <div style="margin-top: 6px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                        <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-heading);">Pedido #${r.order_id}</span>
                        <span style="font-size: 0.78rem; color: var(--text-secondary);">• Cliente: ${escapeQuote(r.customer_name || 'Cliente')}</span>
                        ${tagBadge}
                    </div>
                    ${commentText}
                </div>
            `;
        }).join('');

        panel.innerHTML = summaryHtml + `<div style="margin-top: 12px;"><h4 style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 8px; text-transform: uppercase;">Opiniones Recientes</h4>${listHtml}</div>`;
    } catch (err) {
        panel.innerHTML = `<div style="color: var(--accent-rose); padding: 20px; text-align: center;">Error al cargar calificaciones: ${err.message}</div>`;
    }
}

// -----------------------------------------------------------------------------
// 11. Manual Order Creation (Levantar Pedido desde el Dashboard)
// -----------------------------------------------------------------------------

async function openCreateOrderModal() {
    const modal = document.getElementById('modal-create-order');
    if (!modal) return;

    // Reset Form
    const form = document.getElementById('form-create-order');
    if (form) form.reset();

    // Ensure products and drivers cache is loaded
    if (!allProductsCache || allProductsCache.length === 0) {
        await loadProducts();
    }
    if (!allDriversCache || allDriversCache.length === 0) {
        await loadDrivers();
    }

    // Reset items list container and add 1 initial row
    const itemsList = document.getElementById('create-order-items-list');
    if (itemsList) {
        itemsList.innerHTML = '';
        addCreateOrderItemRow();
    }

    // Reset schedule & dispatch defaults
    const scheduleType = document.getElementById('create-order-schedule-type');
    if (scheduleType) scheduleType.value = 'now';
    toggleCreateOrderSchedule();

    const dispatchMode = document.getElementById('create-order-dispatch-mode');
    if (dispatchMode) dispatchMode.value = 'auto';
    toggleCreateOrderDispatch();

    // Populate drivers select
    populateCreateOrderDriversSelect();

    // Calculate initial totals
    updateCreateOrderTotals();

    // Open modal
    modal.classList.add('open');
}

function populateCreateOrderDriversSelect() {
    const select = document.getElementById('create-order-driver-select');
    if (!select) return;

    if (!allDriversCache || allDriversCache.length === 0) {
        select.innerHTML = `<option value="">No hay choferes registrados</option>`;
        return;
    }

    select.innerHTML = allDriversCache.map(d => {
        const vIcon = d.vehicle_type === 'estacionario' ? '🚛 Pipa' : '🛻 Camioneta';
        const vPlate = d.vehicle_plate ? `[${d.vehicle_plate}]` : '';
        const vUnit = d.vehicle_unit_identifier ? `${d.vehicle_unit_identifier} ` : '';
        const opStatus = d.operational_status === 'disponible' ? '🟢 Disp.' : (d.operational_status === 'en_entrega' ? '🟡 En entrega' : '🔴 Fuera');
        return `<option value="${d.id}">${d.name} (${vUnit}${vIcon} ${vPlate}) - ${opStatus}</option>`;
    }).join('');
}

function addCreateOrderItemRow() {
    const container = document.getElementById('create-order-items-list');
    if (!container) return;

    const rowId = 'order-item-row-' + Date.now() + '-' + Math.floor(Math.random() * 1000);
    const row = document.createElement('div');
    row.id = rowId;
    row.className = 'create-order-item-row';
    row.style.cssText = 'display: flex; gap: 10px; align-items: center; background: rgba(15, 23, 42, 0.4); padding: 10px 12px; border: 1px solid rgba(255,255,255,0.06); border-radius: var(--radius-sm);';

    let productOptions = '';
    if (allProductsCache && allProductsCache.length > 0) {
        productOptions = allProductsCache.map(p => {
            return `<option value="${p.id}" data-price="${p.price}" data-name="${escapeQuote(p.name)}">${p.name} - $${p.price.toFixed(2)} MXN</option>`;
        }).join('');
    } else {
        productOptions = `<option value="cilindro-30kg" data-price="670.0" data-name="Gas LP Cilindro 30kg">Gas LP Cilindro 30kg - $670.00 MXN</option>`;
    }

    row.innerHTML = `
        <div style="flex: 2;">
            <select class="form-control item-product-select" onchange="updateCreateOrderTotals()" style="padding: 8px 10px; font-size: 0.85rem;">
                ${productOptions}
            </select>
        </div>
        <div style="flex: 1; max-width: 100px;">
            <input type="number" class="form-control item-quantity-input" value="1" min="1" step="any" oninput="updateCreateOrderTotals()" style="padding: 8px 10px; font-size: 0.85rem;" placeholder="Cant.">
        </div>
        <div style="min-width: 90px; text-align: right; font-weight: 700; color: var(--accent-emerald); font-size: 0.95rem;" class="item-subtotal-display">
            $0.00
        </div>
        <div>
            <button type="button" class="btn btn-danger btn-sm" onclick="removeCreateOrderItemRow('${rowId}')" title="Quitar producto" style="padding: 6px 10px;">
                🗑️
            </button>
        </div>
    `;

    container.appendChild(row);
    updateCreateOrderTotals();
}

function removeCreateOrderItemRow(rowId) {
    const container = document.getElementById('create-order-items-list');
    if (!container) return;

    const rows = container.querySelectorAll('.create-order-item-row');
    if (rows.length <= 1) {
        showToast('El pedido debe incluir al menos un producto.', 'warning');
        return;
    }

    const targetRow = document.getElementById(rowId);
    if (targetRow) {
        targetRow.remove();
        updateCreateOrderTotals();
    }
}

function updateCreateOrderTotals() {
    const container = document.getElementById('create-order-items-list');
    if (!container) return;

    let total = 0;
    const rows = container.querySelectorAll('.create-order-item-row');

    rows.forEach(row => {
        const select = row.querySelector('.item-product-select');
        const qtyInput = row.querySelector('.item-quantity-input');
        const subtotalDisplay = row.querySelector('.item-subtotal-display');

        let price = 0;
        if (select && select.selectedIndex >= 0) {
            const opt = select.options[select.selectedIndex];
            price = parseFloat(opt.getAttribute('data-price')) || 0;
        }

        const qty = parseFloat(qtyInput ? qtyInput.value : 1) || 0;
        const subtotal = price * qty;
        total += subtotal;

        if (subtotalDisplay) {
            subtotalDisplay.innerText = `$${subtotal.toFixed(2)}`;
        }
    });

    const totalDisplay = document.getElementById('create-order-total-display');
    if (totalDisplay) {
        totalDisplay.innerText = `$${total.toFixed(2)} MXN`;
    }
}

function toggleCreateOrderSchedule() {
    const typeSelect = document.getElementById('create-order-schedule-type');
    const group = document.getElementById('create-order-scheduled-group');
    if (!typeSelect || !group) return;

    const isScheduled = typeSelect.value === 'scheduled';
    group.style.display = isScheduled ? 'block' : 'none';

    if (isScheduled) {
        const scheduledInput = document.getElementById('create-order-scheduled-for');
        if (scheduledInput && !scheduledInput.value) {
            // Default to 2 hours from now
            const now = new Date();
            now.setHours(now.getHours() + 2);
            now.setMinutes(0);
            now.setSeconds(0);
            const tzOffset = now.getTimezoneOffset() * 60000;
            const localISOTime = (new Date(now.getTime() - tzOffset)).toISOString().slice(0, 16);
            scheduledInput.value = localISOTime;
        }
    }
}

function toggleCreateOrderDispatch() {
    const modeSelect = document.getElementById('create-order-dispatch-mode');
    const group = document.getElementById('create-order-driver-group');
    if (!modeSelect || !group) return;

    group.style.display = modeSelect.value === 'driver' ? 'block' : 'none';
}

async function submitCreateOrderForm() {
    const customerName = document.getElementById('create-order-customer-name')?.value?.trim();
    const customerPhone = document.getElementById('create-order-customer-phone')?.value?.trim();
    const address = document.getElementById('create-order-address')?.value?.trim();
    const notes = document.getElementById('create-order-notes')?.value?.trim() || '';
    const paymentMethod = document.getElementById('create-order-payment-method')?.value || 'Efectivo';
    const scheduleType = document.getElementById('create-order-schedule-type')?.value || 'now';
    const scheduledFor = document.getElementById('create-order-scheduled-for')?.value || null;
    const scheduleText = document.getElementById('create-order-schedule-text')?.value?.trim() || '';
    const dispatchMode = document.getElementById('create-order-dispatch-mode')?.value || 'auto';
    const driverSelect = document.getElementById('create-order-driver-select');
    const rawDriverVal = (dispatchMode === 'driver' && driverSelect && driverSelect.value) ? driverSelect.value.trim() : null;
    const driverId = rawDriverVal ? ((!isNaN(rawDriverVal) && !rawDriverVal.includes('-')) ? parseInt(rawDriverVal, 10) : rawDriverVal) : null;

    if (!customerName || !customerPhone || !address) {
        showToast('Por favor completa los campos obligatorios: Nombre, Teléfono y Dirección.', 'error');
        return;
    }

    // Collect items
    const rows = document.querySelectorAll('#create-order-items-list .create-order-item-row');
    if (rows.length === 0) {
        showToast('Debes agregar al menos un producto al pedido.', 'error');
        return;
    }

    const items = [];
    rows.forEach(row => {
        const select = row.querySelector('.item-product-select');
        const qtyInput = row.querySelector('.item-quantity-input');
        if (select && select.selectedIndex >= 0) {
            const opt = select.options[select.selectedIndex];
            const pId = opt.value;
            const pName = opt.getAttribute('data-name') || pId;
            const pPrice = parseFloat(opt.getAttribute('data-price')) || 0;
            const qty = parseFloat(qtyInput ? qtyInput.value : 1) || 1;
            items.push({
                product_id: pId,
                product_name: pName,
                quantity: qty,
                unit_price: pPrice
            });
        }
    });

    if (items.length === 0) {
        showToast('No se detectaron productos válidos en el pedido.', 'error');
        return;
    }

    let deliverySchedule = 'Lo antes posible';
    let finalScheduledFor = null;

    if (scheduleType === 'scheduled') {
        if (scheduledFor) {
            finalScheduledFor = scheduledFor;
            const d = new Date(scheduledFor);
            const timeStr = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            deliverySchedule = scheduleText || `Programado: ${d.toLocaleDateString()} ${timeStr}`;
        } else {
            deliverySchedule = scheduleText || 'Programado';
        }
    }

    const payload = {
        customer_name: customerName,
        customer_phone: customerPhone,
        delivery_address: address,
        items: items,
        delivery_schedule: deliverySchedule,
        scheduled_for: finalScheduledFor,
        payment_method: paymentMethod,
        notes: notes,
        dispatch_mode: dispatchMode,
        driver_id: driverId
    };

    const submitBtn = document.getElementById('btn-submit-create-order');
    if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '⏳ Creando y despachando...';
    }

    try {
        const res = await fetch(`${API_BASE}/orders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) {
            throw new Error(data.detail || data.message || 'Error al crear el pedido');
        }

        const newOrderId = data.order ? data.order.id : '';
        showToast(`🎉 ¡Pedido #${newOrderId} levantado con éxito!`, 'success');

        closeModals();

        // Refresh views
        loadDashboardMetrics();
        loadDashboardShifts();
        loadAgenda();
        loadOrders();
        loadDrivers();
    } catch (err) {
        showToast(`❌ Error: ${err.message}`, 'error');
    } finally {
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '🚀 Levantar y Crear Pedido';
        }
    }
}

