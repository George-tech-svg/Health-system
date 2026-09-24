# _sidebar.py — add collapsible sidebar to all 3 dashboards
import pathlib

# ============================================================
# Common CSS + JS to inject
# ============================================================
SIDEBAR_CSS = '''
/* === Collapsible Sidebar === */
.sidebar { transition: width 0.25s ease; }
.main { transition: margin-left 0.25s ease; }
.sidebar-toggle {
    position: absolute;
    top: 12px;
    right: 10px;
    background: rgba(255,255,255,0.15);
    color: white;
    border: none;
    width: 30px;
    height: 30px;
    border-radius: 8px;
    cursor: pointer;
    font-size: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10;
}
.sidebar-toggle:hover { background: rgba(255,255,255,0.25); }

body.sidebar-collapsed .sidebar { width: 72px !important; padding: 22px 8px !important; }
body.sidebar-collapsed .main { margin-left: 72px !important; }
body.sidebar-collapsed .sidebar .logo,
body.sidebar-collapsed .sidebar .logo-sub,
body.sidebar-collapsed .sidebar .profile-name,
body.sidebar-collapsed .sidebar .profile-role,
body.sidebar-collapsed .sidebar .profile-hospital,
body.sidebar-collapsed .sidebar .nav a span.label {
    display: none !important;
}
body.sidebar-collapsed .sidebar .profile { padding: 8px 4px; }
body.sidebar-collapsed .sidebar .profile-avatar { width: 36px; height: 36px; font-size: 16px; margin: 0 auto; }
body.sidebar-collapsed .sidebar .nav a { text-align: center; padding: 12px 4px; font-size: 18px; }
body.sidebar-collapsed .sidebar .nav a i,
body.sidebar-collapsed .sidebar .nav a .nav-icon { display: inline-block; margin: 0; }
body.sidebar-collapsed .sidebar .nav a .nav-text { display: none; }
'''

SIDEBAR_JS = '''
<script>
(function() {
    var KEY = 'fastafya_sidebar_collapsed';
    if (localStorage.getItem(KEY) === '1') {
        document.body.classList.add('sidebar-collapsed');
    }
    window.toggleSidebar = function() {
        document.body.classList.toggle('sidebar-collapsed');
        var collapsed = document.body.classList.contains('sidebar-collapsed') ? '1' : '0';
        localStorage.setItem(KEY, collapsed);
        // Force map to resize if present
        setTimeout(function() {
            if (window.doctorFloatingMap) window.doctorFloatingMap.invalidateSize();
            if (window.patientFloatingMap) window.patientFloatingMap.invalidateSize();
        }, 300);
    };
})();
</script>
'''

# ============================================================
# 1. SUPER ADMIN DASHBOARD
# ============================================================
sa_path = pathlib.Path("templates/super_admin_dashboard.html")
sa = sa_path.read_text(encoding="utf-8")

# Inject CSS before </style>
if "Collapsible Sidebar" not in sa:
    sa = sa.replace("</style>", SIDEBAR_CSS + "\n</style>", 1)
    print("[1/3] OK - CSS added to super_admin_dashboard.html")

# Add toggle button inside sidebar (right after opening <aside class="sidebar">)
if 'class="sidebar-toggle"' not in sa:
    sa = sa.replace(
        '<aside class="sidebar">',
        '<aside class="sidebar">\n<button class="sidebar-toggle" onclick="toggleSidebar()" title="Toggle menu">☰</button>',
        1
    )
    print("      - toggle button added")

# Wrap nav text in span.label for icon-only collapse
import re
def wrap_nav_labels(html):
    # Match lines like: <li><a ...>EMOJI TEXT</a></li>
    def repl(m):
        pre = m.group(1)   # <li><a ...>
        text = m.group(2).strip()
        # Split emoji from text — emoji is first 1-2 characters
        parts = text.split(" ", 1)
        emoji = parts[0]
        label = parts[1] if len(parts) > 1 else ""
        return f'{pre}<span class="nav-icon">{emoji}</span> <span class="nav-text">{label}</span></a></li>'
    return re.sub(r'(<li><a[^>]*>)([^<]+)</a></li>', repl, html)

sa = wrap_nav_labels(sa)

# Add JS before </body>
if "window.toggleSidebar" not in sa:
    sa = sa.replace("</body>", SIDEBAR_JS + "\n</body>", 1)
    print("      - JS added")

sa_path.write_text(sa, encoding="utf-8")

# ============================================================
# 2. DEPARTMENT DASHBOARD
# ============================================================
dept_path = pathlib.Path("templates/department_dashboard.html")
dept = dept_path.read_text(encoding="utf-8")

if "Collapsible Sidebar" not in dept:
    dept = dept.replace("</style>", SIDEBAR_CSS + "\n</style>", 1)
    print("[2/3] OK - CSS added to department_dashboard.html")

if 'class="sidebar-toggle"' not in dept:
    dept = dept.replace(
        '<aside class="sidebar">',
        '<aside class="sidebar">\n<button class="sidebar-toggle" onclick="toggleSidebar()" title="Toggle menu">☰</button>',
        1
    )
    print("      - toggle button added")

dept = wrap_nav_labels(dept)

if "window.toggleSidebar" not in dept:
    dept = dept.replace("</body>", SIDEBAR_JS + "\n</body>", 1)
    print("      - JS added")

dept_path.write_text(dept, encoding="utf-8")

# ============================================================
# 3. PATIENT DASHBOARD
# ============================================================
pat_path = pathlib.Path("templates/patient_dashboard.html")
pat = pat_path.read_text(encoding="utf-8")

if "Collapsible Sidebar" not in pat:
    pat = pat.replace("</style>", SIDEBAR_CSS + "\n</style>", 1)
    print("[3/3] OK - CSS added to patient_dashboard.html")

if 'class="sidebar-toggle"' not in pat:
    pat = pat.replace(
        '<div class="sidebar">',
        '<div class="sidebar">\n<button class="sidebar-toggle" onclick="toggleSidebar()" title="Toggle menu">☰</button>',
        1
    )
    # also try aside in case it was structured differently
    if 'class="sidebar-toggle"' not in pat:
        pat = pat.replace(
            '<aside class="sidebar">',
            '<aside class="sidebar">\n<button class="sidebar-toggle" onclick="toggleSidebar()" title="Toggle menu">☰</button>',
            1
        )
    print("      - toggle button added")

pat = wrap_nav_labels(pat)

if "window.toggleSidebar" not in pat:
    pat = pat.replace("</body>", SIDEBAR_JS + "\n</body>", 1)
    print("      - JS added")

pat_path.write_text(pat, encoding="utf-8")

print("")
print("DONE")