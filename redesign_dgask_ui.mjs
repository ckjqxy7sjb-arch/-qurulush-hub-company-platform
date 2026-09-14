import { readFile, writeFile } from 'node:fs/promises';

const files = [
  {
    path: '/Users/maxai/Desktop/01_Инспектор.html',
    role: 'inspector',
    accent: '#0f766e',
    accent2: '#0ea5a4',
    title: 'Инспектор'
  },
  {
    path: '/Users/maxai/Desktop/02_Региональный_отдел.html',
    role: 'regional',
    accent: '#7c3aed',
    accent2: '#a855f7',
    title: 'Региональный отдел'
  },
  {
    path: '/Users/maxai/Desktop/03_Министерство.html',
    role: 'ministry',
    accent: '#003070',
    accent2: '#0055b3',
    title: 'Министерство'
  }
];

const START = '<!-- DGASK_UI_REFRESH_START -->';
const END = '<!-- DGASK_UI_REFRESH_END -->';

function css({ accent, accent2, role }) {
  return `${START}
<style>
:root{
  --ux-bg:#eef2f7;
  --ux-panel:#ffffff;
  --ux-panel-2:#f8fafc;
  --ux-text:#102033;
  --ux-muted:#64748b;
  --ux-faint:#94a3b8;
  --ux-line:#d7e0ea;
  --ux-line-2:#e7edf4;
  --ux-navy:#0b2f66;
  --ux-gold:#d4a017;
  --ux-red:#cc2222;
  --ux-green:#1a7a3c;
  --ux-orange:#d4700a;
  --ux-accent:${accent};
  --ux-accent-2:${accent2};
  --navy:var(--ux-navy);
  --navy2:#082653;
  --blue:var(--ux-accent-2);
  --gold:var(--ux-gold);
  --gold2:#f2c94c;
  --bg:var(--ux-bg);
  --border:var(--ux-line);
  --t1:var(--ux-text);
  --t2:#334155;
  --t3:var(--ux-muted);
  --t4:var(--ux-faint);
  --m-navy:var(--ux-navy);
  --m-navy2:#082653;
  --m-blue:var(--ux-accent-2);
  --m-gold:var(--ux-gold);
  --m-gold2:#f2c94c;
  --m-bg:var(--ux-bg);
  --m-border:var(--ux-line);
  --m-t1:var(--ux-text);
  --m-t2:#334155;
  --m-t3:var(--ux-muted);
  --m-t4:var(--ux-faint);
}
html{background:var(--ux-bg)}
body{
  font-family:Inter,'Segoe UI',Arial,sans-serif!important;
  background:
    linear-gradient(180deg,#f8fafc 0,#eef2f7 260px,#e9eff6 100%)!important;
  color:var(--ux-text)!important;
  letter-spacing:0!important;
}
#flag,#flag-stripe{
  height:3px!important;
  background:linear-gradient(90deg,#cc2222 0 30%,#f8fafc 30% 60%,#003070 60% 100%)!important;
}
#topbar,#header{
  min-height:68px!important;
  background:rgba(255,255,255,.94)!important;
  color:var(--ux-text)!important;
  border-bottom:1px solid var(--ux-line)!important;
  box-shadow:0 8px 24px rgba(15,35,70,.08)!important;
  backdrop-filter:blur(14px);
}
.logo-text,.hd-divider,.tb-divider{border-color:var(--ux-line)!important;background:var(--ux-line)!important}
.logo-ministry,.platform-title,.hd-title,.inspector-name{color:var(--ux-text)!important}
.logo-platform,.platform-sub,.hd-sub,.inspector-dept{color:var(--ux-muted)!important}
.tb-role,.hd-badge,.tb-region{
  background:color-mix(in srgb,var(--ux-accent) 10%,#fff)!important;
  border:1px solid color-mix(in srgb,var(--ux-accent) 24%,#d8e2ef)!important;
  color:var(--ux-accent)!important;
  border-radius:999px!important;
  font-weight:700!important;
}
.tb-avatar,.hd-avatar{
  background:linear-gradient(135deg,var(--ux-accent),var(--ux-accent-2))!important;
  color:#fff!important;
  border-radius:10px!important;
  box-shadow:0 8px 18px color-mix(in srgb,var(--ux-accent) 25%,transparent)!important;
}
.tb-bell,.hd-bell{color:var(--ux-muted)!important}
#layout{background:transparent!important}
#sidebar{
  width:252px!important;
  background:#0f2d5c!important;
  border-right:0!important;
  padding:18px 10px!important;
  box-shadow:8px 0 26px rgba(15,45,92,.12)!important;
}
.nav-section{
  color:rgba(255,255,255,.46)!important;
  padding:12px 14px 8px!important;
  letter-spacing:.08em!important;
}
.nav-item{
  border-radius:8px!important;
  border-left:0!important;
  margin-bottom:4px!important;
  padding:10px 12px!important;
  color:rgba(255,255,255,.76)!important;
}
.nav-item:hover{background:rgba(255,255,255,.10)!important;color:#fff!important}
.nav-item.active{
  background:#fff!important;
  color:#0f2d5c!important;
  box-shadow:0 8px 20px rgba(0,0,0,.18)!important;
  font-weight:800!important;
}
.nav-item.active .nav-icon{filter:none}
.nav-badge,.tb-badge,.bell-cnt,.tb-bell-cnt{
  background:var(--ux-red)!important;
  color:#fff!important;
  box-shadow:0 0 0 2px rgba(255,255,255,.9)!important;
}
.sidebar-footer{
  background:rgba(255,255,255,.08)!important;
  border:1px solid rgba(255,255,255,.10)!important;
  border-radius:8px!important;
}
#main,#content{
  padding:28px!important;
  background:transparent!important;
}
#content{max-width:1260px!important}
#tabbar{
  background:#fff!important;
  border-bottom:1px solid var(--ux-line)!important;
  padding:0 24px!important;
  gap:4px!important;
  overflow-x:auto!important;
}
.tb{
  color:var(--ux-muted)!important;
  border-bottom:3px solid transparent!important;
  padding:14px 14px 12px!important;
  white-space:nowrap!important;
}
.tb:hover{background:#f3f7fb!important;color:var(--ux-text)!important}
.tb.active{
  color:var(--ux-accent)!important;
  border-bottom-color:var(--ux-accent)!important;
  background:#fff!important;
}
.page-head{
  align-items:center!important;
  gap:16px!important;
  margin-bottom:20px!important;
}
.page-title{
  font-size:24px!important;
  line-height:1.15!important;
  color:var(--ux-text)!important;
  letter-spacing:0!important;
}
.page-sub{color:var(--ux-muted)!important;font-size:12.5px!important}
.card,.kpi,.form-catalog-card,.notif-item,.visit-card,.rep-sec,.rep-meta,.modal,.modal-box,.login-box{
  background:var(--ux-panel)!important;
  border:1px solid var(--ux-line)!important;
  border-radius:8px!important;
  box-shadow:0 10px 28px rgba(16,32,51,.07)!important;
}
.card:hover,.kpi:hover,.form-catalog-card:hover{
  border-color:color-mix(in srgb,var(--ux-accent) 28%,var(--ux-line))!important;
  box-shadow:0 14px 34px rgba(16,32,51,.10)!important;
}
.card-blue{
  background:linear-gradient(135deg,#12366d,var(--ux-accent))!important;
  color:#fff!important;
}
.kpi,.form-catalog-card,.visit-card,.rep-meta{
  border-left:4px solid var(--ux-accent)!important;
}
.kpi-label,.kpi-lbl,.sec-title,.form-label,.fg label,.rep-meta-label,.rep-sec-title{
  color:var(--ux-muted)!important;
  letter-spacing:.06em!important;
}
.kpi-val{color:var(--ux-accent)!important}
.kpi-sub{color:var(--ux-faint)!important}
.btn,.btn-green,.btn-red,.btn-orange,.btn-gold{
  border-radius:8px!important;
  border:0!important;
  box-shadow:0 8px 18px rgba(15,35,70,.10)!important;
  min-height:36px!important;
}
.btn{
  background:var(--ux-accent)!important;
  color:#fff!important;
}
.btn:hover{background:var(--ux-accent-2)!important}
.btn-green{background:var(--ux-green)!important;color:#fff!important}
.btn-red{background:var(--ux-red)!important;color:#fff!important}
.btn-orange{background:var(--ux-orange)!important;color:#fff!important}
.btn-gold{background:var(--ux-gold)!important;color:#102033!important}
.btn-ghost{
  border:1px solid var(--ux-line)!important;
  background:#fff!important;
  color:var(--ux-text)!important;
  border-radius:8px!important;
  min-height:36px!important;
}
.btn-ghost:hover{
  border-color:var(--ux-accent)!important;
  color:var(--ux-accent)!important;
  background:#f8fbff!important;
}
.inp,.sel,.textarea,input[type="text"],input[type="number"],input[type="date"],select,textarea{
  border-radius:8px!important;
  border:1px solid var(--ux-line)!important;
  background:#fff!important;
  color:var(--ux-text)!important;
  box-shadow:none!important;
}
.inp:focus,.sel:focus,.textarea:focus,input:focus,select:focus,textarea:focus{
  border-color:var(--ux-accent)!important;
  box-shadow:0 0 0 3px color-mix(in srgb,var(--ux-accent) 14%,transparent)!important;
  outline:none!important;
}
.tbl{
  border-collapse:separate!important;
  border-spacing:0!important;
  overflow:hidden!important;
}
.tbl thead th,.tbl th{
  background:#f4f7fb!important;
  color:var(--ux-muted)!important;
  border-bottom:1px solid var(--ux-line)!important;
}
.tbl tbody td,.tbl td{
  border-bottom:1px solid var(--ux-line-2)!important;
}
.tbl tbody tr:hover td,.tbl tr:hover td{
  background:color-mix(in srgb,var(--ux-accent) 7%,#fff)!important;
}
.badge,.st{
  border-radius:999px!important;
  border:1px solid transparent!important;
  letter-spacing:0!important;
}
.prog{background:#e2e8f0!important;height:8px!important}
.prog-fill{background:var(--ux-accent)!important}
.modal-hd,.modal-head,.dr-head,.fd-head,.fp-head{
  background:#102b5b!important;
  border-bottom:3px solid var(--ux-accent)!important;
  border-radius:8px 8px 0 0!important;
}
#drawer,#form-drawer,#form-preview-box{
  border-radius:0!important;
  box-shadow:-18px 0 44px rgba(15,35,70,.22)!important;
}
.dr-body,.fd-body{background:#f7fafc!important}
#login-screen{
  background:
    radial-gradient(circle at 50% 0,color-mix(in srgb,var(--ux-accent) 22%,transparent),transparent 38%),
    linear-gradient(180deg,#f8fafc,#e7eef7)!important;
}
.login-box{
  max-width:440px!important;
  padding:34px!important;
}
.login-title{color:var(--ux-text)!important}
.login-sub{color:var(--ux-muted)!important}
.chip{
  border-radius:999px!important;
  border:1px solid var(--ux-line)!important;
  background:#fff!important;
  color:var(--ux-text)!important;
}
.chip.sel{
  background:var(--ux-accent)!important;
  color:#fff!important;
  border-color:var(--ux-accent)!important;
}
#ksk-live-card{
  background:linear-gradient(135deg,#102b5b 0%,#173f7a 58%,var(--ux-accent) 100%)!important;
  color:#fff!important;
  border:0!important;
  box-shadow:0 18px 44px rgba(15,35,70,.18)!important;
}
#ksk-live-card .sec-title,
#ksk-live-card [style*="rgba(255,255,255"],
#ksk-live-card div{
  color:inherit;
}
#ksk-live-grid > div{
  background:rgba(255,255,255,.12)!important;
  border:1px solid rgba(255,255,255,.18)!important;
  border-radius:8px!important;
  padding:12px!important;
}
#ksk-live-grid [style*="font-size:22px"]{
  color:#fff!important;
}
.g2,.g3,.g4,.kpi-grid{align-items:stretch!important}
${role === 'inspector' ? `
#header{position:sticky!important;top:0!important;z-index:80!important}
#content{padding-top:30px!important}
` : `
#topbar{position:sticky!important;top:0!important;z-index:80!important}
`}
@media (max-width: 980px){
  body{height:auto!important;min-height:100vh!important;overflow:auto!important}
  #layout{display:block!important;overflow:visible!important}
  #sidebar{
    width:100%!important;
    display:flex!important;
    flex-direction:row!important;
    overflow-x:auto!important;
    padding:10px!important;
    gap:6px!important;
  }
  .nav-section,.nav-sep,.sidebar-footer{display:none!important}
  .nav-item{width:auto!important;white-space:nowrap!important;flex:0 0 auto!important}
  #main,#content{padding:18px!important}
  .g2,.g3,.g4,.kpi-grid{grid-template-columns:1fr!important}
  .page-head{align-items:flex-start!important;flex-direction:column!important}
  #topbar,#header{min-height:auto!important;padding:12px 14px!important;gap:10px!important;flex-wrap:wrap!important}
  .logo-ministry{max-width:220px!important}
  #tabbar{padding:0 12px!important}
}
@media (max-width: 680px){
  .tb-right,.hd-right{width:100%!important;justify-content:flex-start!important;flex-wrap:wrap!important}
  .emblem{width:44px!important;height:44px!important}
  .page-title{font-size:21px!important}
  .card,.kpi{padding:14px!important}
  .tbl{font-size:12px!important}
}
</style>
${END}`;
}

function inject(html, block) {
  const escapedStart = START.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const escapedEnd = END.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const markerRe = new RegExp(`${escapedStart}[\\s\\S]*?${escapedEnd}\\s*`, 'g');
  const clean = html.replace(markerRe, '');
  if (!clean.includes('</head>')) {
    throw new Error('No </head> tag found');
  }
  return clean.replace('</head>', `${block}\n</head>`);
}

for (const item of files) {
  const original = await readFile(item.path, 'utf8');
  const updated = inject(original, css(item));
  await writeFile(item.path, updated, 'utf8');
  console.log(`Updated ${item.title}: ${item.path}`);
}
